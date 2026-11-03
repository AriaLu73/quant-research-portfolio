# ES data notes

- Instrument: ESU6 (E-mini S&P 500 futures)
- Source: Databento MBO CSV
- Original local file size: ~1.4 GB
- Price series: reconstructed best-bid / best-ask midprice
- Sampling: 1 second
- Transformation: price differences
- Usable exploratory sample from interrupted run: ~15,542 seconds (~4h20m)
- Main result: ACF(1) visually ~ -0.14
- PACF(1) visually ~ -0.14; PACF(2) ~ -0.04

## Known limitation

The original return construction may have concatenated distinct continuous time segments. A production-grade rerun should preserve segment boundaries and calculate returns only inside continuous intervals.

The raw MBO data is not included in this portfolio package.
