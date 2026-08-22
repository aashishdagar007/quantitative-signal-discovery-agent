"""
AI Trading System — Dual-Market Execution Engine
Event-driven, ultra-low-latency engine integrating:
  • Binance Spot & Futures via WebSockets (aiohttp ws_connect)
  • MetaTrader 5 Forex bridge (polling-based, Windows sidecar)
  • PulseHyperHybrid EUR/USD bot
  • Deterministic order routing with HMAC-signed Binance REST calls
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
import urllib.parse
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

import aiohttp
from dotenv import load_dotenv

from security.python_security_profiler import profiler as _security_profiler

# Load environment
for _p in ["infrastructure/.env", ".env", "../infrastructure/.env"]:
    if os.path.exists(_p):
        load_dotenv(_p)
        break

logger = logging.getLogger(__name__)

BINANCE_WS_URL   = os.environ.get("BINANCE_WS_URL",   "wss://fstream.binance.com/ws")
BINANCE_REST_URL = os.environ.get("BINANCE_REST_URL",  "https://fapi.binance.com")
BINANCE_API_KEY  = os.environ.get("BINANCE_API_KEY",   "")
BINANCE_SECRET   = os.environ.get("BINANCE_API_SECRET","")

MAX_ORDER_NOTIONAL   = float(os.environ.get("MAX_ORDER_NOTIONAL", "10000.0"))
MAX_DAILY_LOSS       = float(os.environ.get("MAX_DAILY_LOSS", "5000.0"))
DEFAULT_TRADING_MODE = os.environ.get("TRADING_MODE", "PAPER").upper()


class RiskLimitExceeded(Exception):
    """Raised when an order breaches risk controls (max notional or max daily loss)."""
    pass


# ══════════════════════════════════════════════════════════════════════════════
#  Binance WebSocket Adapter
# ══════════════════════════════════════════════════════════════════════════════

class BinanceAdapter:
    """
    Binance Spot & Futures WebSocket adapter.
    Uses aiohttp.ClientSession.ws_connect() for true WebSocket connections.
    """

    def __init__(
        self,
        base_ws_url: str = BINANCE_WS_URL,
        symbols: Optional[List[str]] = None,
    ) -> None:
        self.base_ws_url = base_ws_url
        self.symbols     = symbols or ["BTCUSDT", "ETHUSDT"]
        self._callbacks: Dict[str, List[Callable]] = {}
        self._session: Optional[aiohttp.ClientSession] = None
        self._running = False

    async def start(self) -> None:
        """Open WebSocket connections for all symbols concurrently."""
        self._running = True
        self._session = aiohttp.ClientSession()
        tasks = [asyncio.create_task(self._subscribe(sym)) for sym in self.symbols]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def stop(self) -> None:
        self._running = False
        if self._session:
            await self._session.close()

    async def _subscribe(self, symbol: str) -> None:
        """Subscribe to 1-minute kline stream via proper WebSocket handshake."""
        stream_name = f"{symbol.lower()}@kline_1m"
        url = f"{self.base_ws_url}/{stream_name}"

        reconnect_delay = 1.0
        while self._running:
            try:
                async with self._session.ws_connect(url, heartbeat=20.0) as ws:
                    logger.info("[Binance WS] Connected: %s", stream_name)
                    reconnect_delay = 1.0  # reset on successful connection
                    async for msg in ws:
                        if not self._running:
                            break
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            await self._handle_message(symbol, msg.data)
                        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            logger.warning("[Binance WS] %s disconnected, reconnecting…", symbol)
                            break
            except Exception as exc:
                logger.error("[Binance WS] %s error: %s", symbol, exc)

            if self._running:
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 30.0)  # exponential backoff

    async def _handle_message(self, symbol: str, raw: str) -> None:
        try:
            data = json.loads(raw)
            if "k" not in data:
                return
            kline = data["k"]
            ohlcv = {
                "timestamp": kline["t"],
                "open":      float(kline["o"]),
                "high":      float(kline["h"]),
                "low":       float(kline["l"]),
                "close":     float(kline["c"]),
                "volume":    float(kline["v"]),
                "closed":    kline["x"],
            }
            await self._emit("kline", symbol, ohlcv)
            if kline["x"]:  # candle closed
                await self._emit("kline_closed", symbol, ohlcv)
        except (json.JSONDecodeError, KeyError) as exc:
            logger.debug("[Binance WS] Parse error: %s", exc)

    def on(self, event: str, callback: Callable) -> None:
        self._callbacks.setdefault(event, []).append(callback)

    async def _emit(self, event: str, *args: Any) -> None:
        for cb in self._callbacks.get(event, []):
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(*args)
                else:
                    cb(*args)
            except Exception as exc:
                logger.error("[Binance WS] Callback error: %s", exc)

    # ── REST order execution with HMAC-SHA256 signing ─────────────────────────

    async def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "MARKET",
        price: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Place a signed order via Binance REST API."""
        if not BINANCE_API_KEY or not BINANCE_SECRET:
            logger.warning("[Binance] No API credentials — order skipped (paper mode)")
            return {"status": "PAPER", "symbol": symbol, "side": side, "qty": quantity}

        endpoint = f"{BINANCE_REST_URL}/fapi/v1/order"
        params: Dict[str, Any] = {
            "symbol":    symbol,
            "side":      side.upper(),
            "type":      order_type,
            "quantity":  quantity,
            "timestamp": int(time.time() * 1000),
        }
        if order_type == "LIMIT" and price:
            params["price"]      = price
            params["timeInForce"] = "GTC"

        # HMAC-SHA256 signature
        query_string = urllib.parse.urlencode(params)
        signature = hmac.new(
            BINANCE_SECRET.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        params["signature"] = signature

        headers = {"X-MBX-APIKEY": BINANCE_API_KEY}
        async with self._session.post(endpoint, params=params, headers=headers) as resp:
            return await resp.json()


# ══════════════════════════════════════════════════════════════════════════════
#  MetaTrader 5 Forex Bridge (Windows sidecar / polling-based)
# ══════════════════════════════════════════════════════════════════════════════

class ForexMT5Bridge:
    """
    MetaTrader 5 bridge for EUR/USD and other forex pairs.
    Uses mt5.copy_ticks_from() polling loop (no unsupported callback API).
    Only functional on Windows with MetaTrader5 package installed.
    """

    def __init__(
        self,
        mt5_path: str = "",
        login: int = 0,
        password: str = "",
        server: str = "",
        symbols: Optional[List[str]] = None,
    ) -> None:
        self.mt5_path  = mt5_path or os.environ.get("MT5_PATH", "")
        self.login     = login    or int(os.environ.get("MT5_LOGIN", 0) or 0)
        self.password  = password or os.environ.get("MT5_PASSWORD", "")
        self.server    = server   or os.environ.get("MT5_SERVER",   "")
        self.symbols   = symbols  or os.environ.get("MT5_SYMBOLS", "EURUSD").split(",")
        self.connected = False
        self._callbacks: Dict[str, List[Callable]] = {}
        self._mt5_available = False
        self._running  = False

    def connect(self) -> bool:
        """Connect to MetaTrader 5 terminal (Windows only)."""
        try:
            import MetaTrader5 as mt5
            self._mt5 = mt5
        except ImportError:
            logger.warning("[MT5] MetaTrader5 package not available. Forex bridge in simulation mode.")
            self._mt5_available = False
            return False

        kwargs: Dict[str, Any] = {}
        if self.mt5_path:
            kwargs["path"] = self.mt5_path
        if not self._mt5.initialize(**kwargs):
            logger.error("[MT5] Initialize failed: %s", self._mt5.last_error())
            return False

        if self.login:
            if not self._mt5.login(self.login, self.password, self.server):
                logger.error("[MT5] Login failed: %s", self._mt5.last_error())
                return False

        for sym in self.symbols:
            self._mt5.symbol_select(sym, True)

        self.connected = True
        self._mt5_available = True
        logger.info("[MT5] Connected successfully. Symbols: %s", self.symbols)
        return True

    async def start_polling(self, interval_ms: float = 100.0) -> None:
        """Poll MT5 tick data in an async loop (non-blocking via asyncio.sleep)."""
        self._running = True
        import datetime as _dt

        last_ticks: Dict[str, Any] = {}

        while self._running:
            if self._mt5_available and self.connected:
                for sym in self.symbols:
                    try:
                        ticks = self._mt5.copy_ticks_from(
                            sym,
                            _dt.datetime.utcnow() - _dt.timedelta(seconds=1),
                            10,
                            self._mt5.COPY_TICKS_ALL,
                        )
                        if ticks is not None and len(ticks) > 0:
                            latest = ticks[-1]
                            tick_data = {
                                "bid":       float(latest.bid),
                                "ask":       float(latest.ask),
                                "last":      float(latest.last),
                                "timestamp": int(latest.time),
                            }
                            if last_ticks.get(sym) != tick_data.get("bid"):
                                last_ticks[sym] = tick_data["bid"]
                                await self._emit("tick", sym, tick_data)
                    except Exception as exc:
                        logger.debug("[MT5] Poll error for %s: %s", sym, exc)
            else:
                # Simulation mode: generate synthetic tick
                import random
                for sym in self.symbols:
                    base = {"EURUSD": 1.0845, "GBPUSD": 1.2650, "USDJPY": 149.50}.get(sym, 1.0)
                    spread = 0.00020
                    bid = base + random.gauss(0, 0.0002)
                    tick_data = {
                        "bid":       round(bid, 5),
                        "ask":       round(bid + spread, 5),
                        "last":      round(bid, 5),
                        "timestamp": int(time.time()),
                    }
                    await self._emit("tick", sym, tick_data)

            await asyncio.sleep(interval_ms / 1000.0)

    def stop(self) -> None:
        self._running = False
        if self._mt5_available and self.connected:
            self._mt5.shutdown()
            self.connected = False

    def on(self, event: str, callback: Callable) -> None:
        self._callbacks.setdefault(event, []).append(callback)

    async def _emit(self, event: str, *args: Any) -> None:
        for cb in self._callbacks.get(event, []):
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(*args)
                else:
                    cb(*args)
            except Exception as exc:
                logger.error("[MT5] Callback error: %s", exc)

    def place_order(
        self,
        symbol: str,
        side: str,
        volume: float,
        price: float = 0.0,
        comment: str = "PulseHyperHybrid",
    ) -> Dict[str, Any]:
        """Place a market order via MT5."""
        if not self._mt5_available or not self.connected:
            logger.warning("[MT5] Not connected — order skipped (paper mode)")
            return {"retcode": -1, "status": "PAPER", "symbol": symbol, "side": side, "volume": volume}

        mt5 = self._mt5
        side_map = {"buy": mt5.ORDER_TYPE_BUY, "sell": mt5.ORDER_TYPE_SELL}
        tick = mt5.symbol_info_tick(symbol)

        request = {
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       symbol,
            "volume":       volume,
            "type":         side_map.get(side.lower(), mt5.ORDER_TYPE_BUY),
            "price":        tick.ask if side.lower() == "buy" else tick.bid,
            "deviation":    20,
            "magic":        202600,
            "comment":      comment,
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_FOK,
        }

        result = mt5.order_send(request)
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error("[MT5] Order failed: retcode=%d", result.retcode)
        else:
            logger.info("[MT5] Order filled: %s %s %.2f @ %.5f", side, symbol, volume, result.price)

        return {
            "retcode":       result.retcode,
            "order_id":      result.order,
            "price":         result.price,
            "volume":        result.volume,
            "symbol":        symbol,
            "side":          side,
        }


# ══════════════════════════════════════════════════════════════════════════════
#  Dual-Market Event-Driven Engine
# ══════════════════════════════════════════════════════════════════════════════

class DualMarketEngine:
    """
    Core event loop synchronizing crypto OHLCV and forex tick streams
    without blocking. Provides a unified execute_order() interface.
    """

    def __init__(self) -> None:
        self.binance: Optional[BinanceAdapter] = None
        self.forex:   Optional[ForexMT5Bridge] = None
        self._data: Dict[str, Dict] = {}
        self._order_log: List[Dict] = []
        self._running = False
        self._on_data_callbacks: List[Callable] = []
        self.mode: str = DEFAULT_TRADING_MODE
        self.max_order_notional: float = MAX_ORDER_NOTIONAL
        self.max_daily_loss: float = MAX_DAILY_LOSS
        self.daily_loss: float = 0.0
        self.profiler = _security_profiler

    def initialize(
        self,
        binance_symbols: Optional[List[str]] = None,
        mt5_config: Optional[Dict] = None,
    ) -> None:
        cfg = mt5_config or {}
        self.binance = BinanceAdapter(symbols=binance_symbols or ["BTCUSDT", "ETHUSDT"])
        self.binance.on("kline_closed", self._on_binance_kline)

        self.forex = ForexMT5Bridge(
            mt5_path =cfg.get("path",     ""),
            login    =cfg.get("login",    0),
            password =cfg.get("password", ""),
            server   =cfg.get("server",   ""),
            symbols  =cfg.get("symbols",  ["EURUSD"]),
        )
        self.forex.on("tick", self._on_forex_tick)

    async def start(self) -> None:
        """Start both market data streams concurrently."""
        self._running = True
        self.forex.connect()
        await asyncio.gather(
            self.binance.start(),
            self.forex.start_polling(interval_ms=200),
            return_exceptions=True,
        )

    def stop(self) -> None:
        self._running = False
        if self.forex:
            self.forex.stop()

    def on_data(self, callback: Callable) -> None:
        """Register a callback triggered on every incoming market event."""
        self._on_data_callbacks.append(callback)

    async def _on_binance_kline(self, symbol: str, ohlcv: Dict) -> None:
        self._data.setdefault(symbol, {"ohlcv": [], "type": "crypto"})
        buf = self._data[symbol]["ohlcv"]
        buf.append(ohlcv)
        if len(buf) > 500:
            buf[:] = buf[-500:]
        logger.debug("[Engine] Binance kline %s close=%.2f", symbol, ohlcv["close"])
        for cb in self._on_data_callbacks:
            if asyncio.iscoroutinefunction(cb):
                await cb({"market": "crypto", "symbol": symbol, "data": ohlcv})
            else:
                cb({"market": "crypto", "symbol": symbol, "data": ohlcv})

    async def _on_forex_tick(self, symbol: str, tick: Dict) -> None:
        self._data.setdefault(symbol, {"ticks": [], "type": "forex"})
        buf = self._data[symbol]["ticks"]
        buf.append(tick)
        if len(buf) > 5000:
            buf[:] = buf[-5000:]
        logger.debug("[Engine] MT5 tick %s bid=%.5f", symbol, tick["bid"])
        for cb in self._on_data_callbacks:
            if asyncio.iscoroutinefunction(cb):
                await cb({"market": "forex", "symbol": symbol, "data": tick})
            else:
                cb({"market": "forex", "symbol": symbol, "data": tick})

    def _estimate_price(self, symbol: str, override_price: Optional[float] = None) -> float:
        """Estimate current asset price from buffers or reference defaults."""
        if override_price is not None and override_price > 0:
            return float(override_price)
        prices = self.get_prices(symbol)
        if prices:
            return float(prices[-1])
        defaults = {"BTCUSDT": 65000.0, "ETHUSDT": 3500.0, "EURUSD": 1.0845, "GBPUSD": 1.2650}
        return defaults.get(symbol, 100.0)

    async def execute_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "market",
        price: Optional[float] = None,
        mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Route and execute an order.
        In PAPER mode: orders simulate execution without sending to live venue.
        In LIVE mode: risk guards (max notional cap, daily loss limit) are enforced,
        and orders are submitted to Binance / MT5 with HFT timing & profiler observation.
        """
        active_mode = (mode or self.mode).upper()
        order_id = f"ord_{int(time.time()*1000)}_{symbol}"
        est_price = self._estimate_price(symbol, price)

        # ── PAPER MODE ──────────────────────────────────────────────────────────
        if active_mode == "PAPER":
            with self.profiler.hft_timer(f"paper_order_{symbol}"):
                self.profiler.monitor_execution(
                    order_id=order_id,
                    executed_price=est_price,
                    expected_price=est_price,
                    deviation_pct=0.0,
                )
            order = {
                "id":        order_id,
                "symbol":    symbol,
                "side":      side,
                "quantity":  quantity,
                "price":     est_price,
                "type":      order_type,
                "status":    "PAPER",
                "exchange":  "paper_sim",
                "mode":      "PAPER",
                "timestamp": datetime.utcnow().isoformat(),
            }
            self._order_log.append(order)
            logger.info("[Engine] [PAPER] Order %s: %s %s %.4f @ %.4f", order_id, side, symbol, quantity, est_price)
            return order

        # ── LIVE MODE: Risk Guards ─────────────────────────────────────────────
        notional = quantity * est_price
        if notional > self.max_order_notional:
            raise RiskLimitExceeded(
                f"Order notional ${notional:.2f} exceeds maximum allowed cap of ${self.max_order_notional:.2f}"
            )

        if self.daily_loss >= self.max_daily_loss:
            raise RiskLimitExceeded(
                f"Daily loss ${self.daily_loss:.2f} reached circuit breaker limit of ${self.max_daily_loss:.2f}"
            )

        # ── LIVE MODE: Order Execution with Security Profiling ─────────────────
        order: Dict[str, Any] = {
            "id":        order_id,
            "symbol":    symbol,
            "side":      side,
            "quantity":  quantity,
            "type":      order_type,
            "mode":      "LIVE",
            "status":    "pending",
            "timestamp": datetime.utcnow().isoformat(),
        }

        crypto_symbols = {"BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"}
        with self.profiler.hft_timer(f"live_order_{symbol}"):
            if symbol in crypto_symbols:
                if self.binance is None:
                    result = {"status": "error", "message": "Binance adapter not initialized"}
                else:
                    result = await self.binance.place_order(symbol, side, quantity, order_type.upper(), price=price)
                order.update({"exchange": "binance", "status": result.get("status", "UNKNOWN"), **result})
            else:
                if self.forex is None:
                    result = {"retcode": -1, "status": "error", "message": "Forex MT5 bridge not initialized"}
                else:
                    result = self.forex.place_order(symbol, side, quantity, price=price or 0.0)
                order.update({"exchange": "mt5", "status": "filled" if result.get("retcode") == 0 else "error", **result})

        exec_price = float(order.get("price") or est_price)
        dev_pct = abs(exec_price - est_price) / max(est_price, 1e-6) * 100.0
        self.profiler.monitor_execution(
            order_id=order_id,
            executed_price=exec_price,
            expected_price=est_price,
            deviation_pct=dev_pct,
        )

        self._order_log.append(order)
        logger.info("[Engine] [LIVE] Order %s: %s %s %.4f → %s", order_id, side, symbol, quantity, order.get("status"))
        return order

    def get_prices(self, symbol: str) -> List[float]:
        """Return recent close prices for a symbol."""
        sym_data = self._data.get(symbol, {})
        if "ohlcv" in sym_data:
            return [c["close"] for c in sym_data["ohlcv"]]
        elif "ticks" in sym_data:
            return [t["bid"] for t in sym_data["ticks"]]
        return []


# ══════════════════════════════════════════════════════════════════════════════
#  PulseHyperHybrid — EUR/USD Scalping Bot
# ══════════════════════════════════════════════════════════════════════════════

class PulseHyperHybrid:
    """
    Configurable EUR/USD scalping bot using dual-market signals.
    Targets the EUR/USD pair. Integrates with AI Desk consensus.
    """

    def __init__(
        self,
        engine: DualMarketEngine,
        symbol: str = "EURUSD",
        signal_threshold: float = 0.0003,   # 3 pips
        volume: float = 0.01,
        ema_period: int = 14,
    ) -> None:
        self.engine           = engine
        self.symbol           = symbol
        self.signal_threshold = signal_threshold
        self.volume           = volume
        self.ema_period       = ema_period
        self._position        = 0       # 1 = long, -1 = short, 0 = flat
        self._ema: Optional[float] = None
        self._tick_count = 0

    def _update_ema(self, price: float) -> float:
        k = 2.0 / (self.ema_period + 1)
        if self._ema is None:
            self._ema = price
        else:
            self._ema = k * price + (1 - k) * self._ema
        return self._ema

    async def on_tick(self, symbol: str, tick: Dict) -> None:
        """Called on each MT5 tick for EUR/USD."""
        if symbol != self.symbol:
            return

        self._tick_count += 1
        bid = tick["bid"]
        ask = tick["ask"]
        mid = (bid + ask) / 2.0

        ema = self._update_ema(mid)

        # Signal: price crosses EMA by more than threshold
        diff = mid - ema
        if abs(diff) < self.signal_threshold:
            return

        desired_position = 1 if diff > 0 else -1

        # Only trade on position change
        if desired_position == self._position:
            return

        # Close existing
        if self._position != 0:
            close_side = "sell" if self._position == 1 else "buy"
            await self.engine.execute_order(self.symbol, close_side, self.volume)

        # Open new
        open_side = "buy" if desired_position == 1 else "sell"
        await self.engine.execute_order(self.symbol, open_side, self.volume)
        self._position = desired_position
        logger.info(
            "[PulseHyperHybrid] %s %s @ bid=%.5f ema=%.5f diff=%.5f",
            open_side, self.symbol, bid, ema, diff,
        )

    async def run(self) -> None:
        """Register the tick handler and let the engine drive us."""
        self.engine.forex.on("tick", self.on_tick)
        logger.info("[PulseHyperHybrid] Bot active on %s (threshold=%.5f)", self.symbol, self.signal_threshold)
        while True:
            await asyncio.sleep(60)   # heartbeat; actual work is event-driven


# ══════════════════════════════════════════════════════════════════════════════
#  Entry point
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    engine = DualMarketEngine()
    engine.initialize(
        binance_symbols=["BTCUSDT", "ETHUSDT"],
        mt5_config={"symbols": ["EURUSD"]},
    )

    bot = PulseHyperHybrid(engine, symbol="EURUSD")

    async def _main():
        await asyncio.gather(engine.start(), bot.run())

    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        engine.stop()
        print("[Engine] Shutdown complete.")
