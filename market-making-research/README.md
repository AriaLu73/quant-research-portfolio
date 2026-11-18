# Market-making research on crypto perpetual futures

Research logs, reports and scripts from five research lines run between September and November 2026.
Most reports are written in Chinese. Market data is not included.

| Folder | What it is | Period | Recorded verdict |
|---|---|---|---|
| `01-btc-perp-maker-research-log` | Research log 1: a two-sided maker on a BTC perpetual; GLFT / Avellaneda–Stoikov baseline against several variants | Sep 2026 | No strategy passed the 5 × 1 h out-of-sample test |
| `02-hedged-quoting-l3-price-model` | Hedged quoting line, studies on self-recorded order-by-order (L3) data, a price model, and an audit of the L3 evaluation | 1–3 Oct 2026 | Hedged line stopped after a small live test; QMM-2, PX-2, PX-3 and PX-5 not passed; the audit found three evaluation errors |
| `03-lead-venue-maker-families-as-rebuild` | Lead-venue analysis, maker-family profiles from the public L3 feed, Avellaneda–Stoikov / GLFT rebuilt from scratch | 1–8 Oct 2026 | L-1 and L-4 killed, L-3 fragile; MM-XVL archived; ASM-1 failed its gate |
| `04-staged-as-glft-framework` | A staged Avellaneda–Stoikov / GLFT framework with pre-registered thresholds | 7–17 Oct 2026 | Stages 0 and 1 passed; stages 2–7 failed and were not merged |
| `05-paper-reproduction-adaptive-mm` | Reproduction of Chávez-Casillas et al. (2024) and Guilbaud–Pham (2011) with exact queue positions | 6–9 Nov 2026 | Reported per contract; no overall pass or fail |

Each folder keeps the original layout: `docs/` for logs and reports, `scripts/` for code
(folder 05 keeps its own `repro/` and `loss_diagnosis/` trees).

## What is not here

- Market data, result tables (`.csv`, `.json`, `.npz`), logs and figures.
- Paper PDFs and text extracted from papers.

## Redactions

The files were redacted by script before upload.

| Removed | Replaced with |
|---|---|
| Fee and rebate rates, fee tier | `我方费率` / `OUR_FEE` |
| IP addresses, data-centre details | `我方IP` / `OUR_IP`, `我方机房` / `OUR_DATACENTER` |
| Money amounts: capital, live and simulated P&L, traded value | `[金额已抹]` / `[amount removed]` |
| Account and order identifiers | `[ID已抹]` / `[id removed]` |
| Names of people and entities | `我方` / `ME` |
| Local absolute paths | shortened to relative paths |

Results expressed in basis points, ticks, IC and t-statistics are kept. Strategy parameters are kept.

The scripts keep their logic but do not run as they are: fee constants are placeholders and the data they read is not included.
