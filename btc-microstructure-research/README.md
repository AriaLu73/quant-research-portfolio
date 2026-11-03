<div align="center">

# BTC Microstructure Research

**Independent experiments on short-horizon returns and order book signals.**

![Focus: Market Microstructure](https://img.shields.io/badge/Focus-Market_Microstructure-2563EB?style=flat-square)
![Market: Crypto](https://img.shields.io/badge/Market-Crypto-F0B90B?style=flat-square)

[Experiments](#experiments) · [Organization](#organization) · [Research Principles](#research-principles)

</div>

---

## Overview

I use this repository to investigate short-horizon predictability in BTC markets. Each experiment has its own research question, methodology, analysis, and conclusions.

## Experiments

| Experiment | Research Question |
| :--- | :--- |
| [001 · BTC Short-Horizon Predictability](experiments/001-btc-ar1/README.md) | Can recent returns predict the next 100 ms return, and does order book imbalance add predictive value? |

## Organization

Each study lives in its own directory under `experiments/`. I use numbered, descriptive names such as `001-btc-ar1` and add new studies to the index above.

Within each experiment, I keep the README alongside its code and notebooks. As outputs are produced, I place figures and findings in an experiment-specific `results/` directory. Large datasets remain outside Git.

## Research Principles

- Define the question and hypotheses before evaluating results.
- Preserve chronological ordering and prevent look-ahead bias.
- Compare models against simple baselines on unseen data.
- Record data sources, assumptions, and reproducibility details.
- Report negative findings and distinguish predictability from trading profitability.
