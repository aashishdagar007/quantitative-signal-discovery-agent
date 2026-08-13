# SPDX-FileCopyrightText: Copyright (c) 2023-2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.  # noqa
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Disclaimer:
# Each user is responsible for checking the content of datasets and the
# applicable licenses and determining if suitable for the intended use.

"""
Download Binance crypto price-volume data.

Fetches Open, Close, High, Low, and Volume data for a curated Binance
crypto ticker universe and saves each field as a separate CSV file compatible
with the signal discovery workflow.

Usage:
    python -m signal_discovery_workflow.download_data
    python -m signal_discovery_workflow.download_data --start 2023-01-01 --end 2025-12-31
    python -m signal_discovery_workflow.download_data --output /path/to/output
"""

import argparse
import logging
from pathlib import Path

import pandas as pd
from binance.client import Client

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT_DIR = Path(__file__).parent / "data" / "binance"
DATA_FIELDS = ["Open", "Close", "High", "Low", "Volume"]


BINANCE_TICKERS = [
    'BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'ADAUSDT', 'SolanaUSDT', 'XRPUSDT', 'DOGEUSDT', 'DOTUSDT',
    'LINKUSDT', 'MATICUSDT', 'SOLUSDT', 'AVAXUSDT', 'DOTUSDT', 'PolkadotUSDT',
]


def get_binance_tickers() -> list[str]:
    """Return the configured Binance crypto ticker universe."""
    logger.info(f"Using {len(BINANCE_TICKERS)} Binance tickers")
    return BINANCE_TICKERS


def download_binance_data(
    start: str = "2023-01-01",
    end: str = "2025-12-31",
    output_dir: str | Path | None = None,
) -> dict[str, pd.DataFrame]:
    """
    Download Binance crypto price-volume data and save as CSV files.

    Args:
        start: Start date in YYYY-MM-DD format.
        end: End date in YYYY-MM-DD format.
        output_dir: Directory to save CSV files. Defaults to data/binance/.

    Returns:
        Dictionary mapping field names to DataFrames.
    """
    output_path = Path(output_dir) if output_dir else DEFAULT_OUTPUT_DIR
    output_path.mkdir(parents=True, exist_ok=True)

    tickers = get_binance_tickers()

    logger.info(f"Downloading data from {start} to {end} for {len(tickers)} tickers...")
    # Initialize Binance client (public market data doesn't require API keys)
    client = Client()

    results = {}
    for field in DATA_FIELDS:
        # Fetch klines (candlestick) data from Binance for each ticker
        all_dfs = {}
        for ticker in tickers:
            try:
                klines = client.get_klines(
                    symbol=ticker,
                    interval=Client.KLINE_INTERVAL_1DAY,
                    start_str=start,
                    end_str=end,
                )
                # Process kline data into DataFrame
                df = pd.DataFrame(klines, columns=[
                    'Open time', 'Open', 'High', 'Low', 'Close', 'Volume', 'Close time',
                    'Quote asset volume', 'Number of trades', 'Taker buy base asset volume',
                    'Taker buy quote asset volume', 'Ignore'
                ])
                df['Ticker'] = ticker
                df['Date'] = pd.to_datetime(df['Open time'], unit='ms')
                df.set_index('Date', inplace=True)
                # Select only the field we're saving
                field_map = {'Open': 'Open', 'Close': 'Close', 'High': 'High', 'Low': 'Low', 'Volume': 'Volume'}
                if field in field_map:
                    all_dfs[ticker] = df[field_map[field]]
            except Exception as e:
                logger.warning(f"Failed to fetch {ticker} data: {e}")

        # Combine all ticker data into a single DataFrame
        if all_dfs:
            combined = pd.concat(all_dfs, axis=1)
            combined = combined.dropna(axis=1, how="all")
            csv_path = output_path / f"{field}.csv"
            combined.to_csv(csv_path)
            results[field] = combined
            logger.info(f"Saved {field}.csv with shape {combined.shape}")


def main():
    parser = argparse.ArgumentParser(
        description="Download Binance crypto price-volume data for signal discovery."
    )
    parser.add_argument(
        "--start", default="2023-01-01", help="Start date (YYYY-MM-DD). Default: 2023-01-01"
    )
    parser.add_argument(
        "--end", default="2025-12-31", help="End date (YYYY-MM-DD). Default: 2025-12-31"
    )
    parser.add_argument(
        "--output", default=None, help="Output directory. Default: data/binance/"
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    download_binance_data(start=args.start, end=args.end, output_dir=args.output)


if __name__ == "__main__":
    main()
