# BTC data notes

- Instrument: BTCUSDT spot
- Venue/source: Binance public historical data
- Date used: 2026-10-20
- Frequency: 1-second klines
- Price field used: close
- Return definition: `diff(log(close))`
- Main result: ACF(1) visually ~ +0.15
- Split-sample ACF(1): first 12h +0.1620, last 12h +0.1492

The original R workflow downloaded a daily ZIP, extracted the CSV to disk, then loaded it with `read.csv`. Extracting first avoids the `seek not enabled for this connection` issue encountered when attempting to read directly from a compressed connection.
