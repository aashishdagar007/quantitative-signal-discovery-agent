import asyncio
import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
import aiohttp

from nautilus_trader.app import NautilusTrader
from nautilus_trader.model.currencies import Currencies
from nautilus_trader.model.enums import OrderSide, OrderType, OrderStatus
from nautilus_trader.model.objects import Symbol, Instrument, InstrumentType
from nautilus_trader.trading import SimTrading

logger = logging.getLogger(__name__)


class BinanceAdapter:
    """Binance Spot & Futures WebSocket adapter for Nautilus Trader"""
    
    def __init__(self, base_url: str = "wss://fstream.binance.com/ws", 
                 symbols: List[str] = None):
        self.base_url = base_url
        self.symbols = symbols or ["BTCUSDT", "ETHUSDT"]
        self.callbacks = {}
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def start(self):
        """Start WebSocket connections for all symbols"""
        self.session = aiohttp.ClientSession()
        tasks = []
        for symbol in self.symbols:
            task = asyncio.create_task(self._subscribe(symbol))
            tasks.append(task)
        await asyncio.gather(*tasks)
    
    async def _subscribe(self, symbol: str):
        """Subscribe to kline and trade data for a symbol"""
        stream = f"{symbol.lower()}@kline_1m"
        url = f"{self.base_url}/{stream}"
        async with self.session.get(url) as resp:
            async for line in resp.content:
                if line:
                    data = json.loads(line)
                    if data.get("k", {}).get("x"):  # kline closed
                        kline = data["k"]
                        ohlcv = {
                            "timestamp": kline["t"],
                            "open": float(kline["o"]),
                            "high": float(kline["h"]),
                            "low": float(kline["l"]),
                            "close": float(kline["c"]),
                            "volume": float(kline["v"])
                        }
                        self._emit("kline", symbol, ohlcv)
    
    def on(self, event: str, callback):
        """Register callback for events"""
        if event not in self.callbacks:
            self.callbacks[event] = []
        self.callbacks[event].append(callback)
    
    def _emit(self, event: str, *args):
        """Emit event to registered callbacks"""
        for cb in self.callbacks.get(event, []):
            cb(*args)


class ForexMT5Bridge:
    """MetaTrader 5/FIX Bridge for EUR/USD and other forex pairs"""
    
    def __init__(self, mt5_path: str, login: int, password: str):
        self.mt5_path = mt5_path
        self.login = login
        self.password = password
        self.connected = False
        self.tick_callbacks = []
    
    def connect(self):
        """Connect to MetaTrader 5 terminal"""
        import mt5
        if not mt5.initialize(path=self.mt5_path):
            logger.error("MT5 initialize failed")
            return False
        if not mt5.login(self.login, self.password):
            logger.error("MT5 login failed")
            return False
        self.connected = True
        logger.info("MT5 connected successfully")
        
        # Subscribe to tick data for EURUSD
        symbol = mt5.symbols_get("EURUSD")[0]
        mt5.symbol_select(symbol.name, True)
        
        # Set up tick handler
        mt5.set_tick_callback(self._on_tick)
        return True
    
    def _on_tick(self, symbol, tick):
        """Handle incoming tick data from MT5"""
        tick_data = {
            "bid": tick.bid,
            "ask": tick.ask,
            "last": tick.last,
            "timestamp": tick.time
        }
        self._emit("tick", "EURUSD", tick_data)
    
    def on(self, event: str, callback):
        """Register callback for events"""
        if event not in self.tick_callbacks:
            self.tick_callbacks.append(callback)
    
    def _emit(self, event: str, *args):
        """Emit event to registered callbacks"""
        for cb in self.tick_callbacks:
            cb(*args)


class DualMarketEngine:
    """Event-driven core engine synchronizing crypto and forex data streams"""
    
    def __init__(self):
        self.binance_adapter = None
        self.forex_bridge = None
        self.event_loop = asyncio.get_event_loop()
        self.positions: Dict[str, Dict] = {}
        self.active_orders: Dict[str, Dict] = {}
        self.running = False
    
    def initialize(self, binance_symbols: List[str] = None,
                   mt5_config: Dict = None):
        """Initialize both market adapters"""
        self.binance_adapter = BinanceAdapter(symbols=binance_symbols or ["BTCUSDT", "ETHUSDT"])
        self.binance_adapter.on("kline", self._handle_binance_kline)
        
        mt5_config = mt5_config or {}
        self.forex_bridge = ForexMT5Bridge(
            mt5_path=mt5_config.get("path", "C:\\Program Files\\MetaTrader 5\\terminal64.exe"),
            login=mt5_config.get("login", 0),
            password=mt5_config.get("password", "")
        )
        self.forex_bridge.on("tick", self._handle_forex_tick)
    
    async def start(self):
        """Start both market data streams"""
        self.running = True
        await self.binance_adapter.start()
        self.forex_bridge.connect()
    
    def _handle_binance_kline(self, symbol: str, ohlcv: Dict):
        """Process Binance kline data"""
        logger.info(f"Binance kline {symbol}: {ohlcv['close']:.2f}")
        # Sync data for Kronos forecasting
        if symbol not in self.positions:
            self.positions[symbol] = {"ohlcv": []}
        self.positions[symbol]["ohlcv"].append(ohlcv)
        # Keep only last 100 entries
        if len(self.positions[symbol]["ohlcv"]) > 100:
            self.positions[symbol]["ohlcv"] = self.positions[symbol]["ohlcv"][-100:]
    
    def _handle_forex_tick(self, symbol: str, tick_data: Dict):
        """Process Forex tick data from MT5"""
        logger.info(f"Forex tick {symbol}: bid={tick_data['bid']:.5f}")
        # Sync data for Kronos forecasting
        if symbol not in self.positions:
            self.positions[symbol] = {"ticks": []}
        self.positions[symbol]["ticks"].append(tick_data)
        if len(self.positions[symbol]["ticks"]) > 100:
            self.positions[symbol]["ticks"] = self.positions[symbol]["ticks"][-100:]
    
    async def execute_order(self, symbol: str, side: str, 
                          quantity: float, order_type: str = "market"):
        """Execute order across supported markets"""
        order_id = f"order_{datetime.utcnow().timestamp()}"
        order = {
            "id": order_id,
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "type": order_type,
            "status": "pending",
            "timestamp": datetime.utcnow().isoformat()
        }
        self.active_orders[order_id] = order
        
        # Determine market and execute
        if symbol in ["BTCUSDT", "ETHUSDT"]:
            await self._execute_binance_order(order)
        else:
            self._execute_mt5_order(order)
        
        return order
    
    async def _execute_binance_order(self, order: Dict):
        """Execute order via Binance API"""
        logger.info(f"Executing Binance order: {order['side']} {order['quantity']} {order['symbol']}")
        # In production, would call Binance API
        order["status"] = "filled"
        order["execution_price"] = order["quantity"] * 0.5  # placeholder
    
    def _execute_mt5_order(self, order: Dict):
        """Execute order via MetaTrader 5"""
        import mt5
        side_map = {"buy": mt5.ORDER_TYPE_BUY, "sell": mt5.ORDER_TYPE_SELL}
        order_type = mt5.ORDER_TYPE_MARKET
        
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": order["symbol"],
            "volume": order["quantity"],
            "price": 0,
            "type": order_type,
            "side": side_map.get("buy", mt5.ORDER_TYPE_BUY),
            "deviation": 20,
            "magic": 0,
            "comment": "Nautilus execution",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_FOK,
        }
        
        result = mt5.order_send(request)
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(f"MT5 order failed: {result.retcode}")
        else:
            order["status"] = "filled"
            order["execution_price"] = result.price


# PulseHyperHybrid bot targeting EUR/USD
class PulseHyperHybrid:
    """Scalping bot for EUR/USD pair using dual-market signals"""
    
    def __init__(self, engine: DualMarketEngine):
        self.engine = engine
        self.position = 0
        self.signal_threshold = 0.001
    
    async def run(self):
        """Main bot loop"""
        while True:
            # Wait for synchronized signals
            await asyncio.sleep(0.1)
            
            # Check for EURUSD tick data
            if "EURUSD" in self.engine.positions:
                ticks = self.engine.positions["EURUSD"].get("ticks", [])
                if ticks:
                    latest = ticks[-1]
                    # Simple signal logic
                    price_change = latest["bid"] - latest.get("prev_bid", latest["bid"])
                    
                    if abs(price_change) > self.signal_threshold:
                        side = "buy" if price_change > 0 else "sell"
                        await self.engine.execute_order(
                            symbol="EURUSD",
                            side=side,
                            quantity=0.01
                        )
                        latest["prev_bid"] = latest["bid"]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    
    engine = DualMarketEngine()
    
    # Initialize with EURUSD and major crypto pairs
    engine.initialize(
        binance_symbols=["BTCUSDT", "ETHUSDT"],
        mt5_config={"login": 12345678, "password": "demo"}
    )
    
    # Start market data streams
    asyncio.get_event_loop().create_task(engine.start())
    
    # Start PulseHyperHybrid bot
    bot = PulseHyperHybrid(engine)
    asyncio.get_event_loop().create_task(bot.run())
    
    print("Dual-market execution engine started")
    import signal
    signal.pause()