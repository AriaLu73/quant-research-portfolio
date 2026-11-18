# 策略模拟面板(快速模拟器,训练日)

天:20251001, 20260101, 20260401;单量 0.15 BTC;库存上限 3 手;返费 OUR_FEE;队列估计 ESTIMATED

| policy | fills | vol $ | spread pnl $ (bp) | rebate $ | net $ (bp) | net by day | max DD $ | pos mean/max BTC | fill rate | mk5s bp | hours>0 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| scan_base | 20,297 | [amount removed] | [amount removed] (-0.477) | [amount removed] | [amount removed] (+0.223) | [amount removed] | [amount removed] | 0.078 / 0.45 | 0.19 | -0.415 | 66/72 (min [amount removed]) |
| latency_ms=10 | 20,310 | [amount removed] | [amount removed] (-0.513) | [amount removed] | [amount removed] (+0.187) | [amount removed] | [amount removed] | 0.081 / 0.45 | 0.19 | -0.438 | 65/72 (min [amount removed]) |
| latency_ms=25 | 19,954 | [amount removed] | [amount removed] (-0.567) | [amount removed] | [amount removed] (+0.133) | [amount removed] | [amount removed] | 0.082 / 0.45 | 0.19 | -0.484 | 59/72 (min [amount removed]) |
| latency_ms=50 | 19,698 | [amount removed] | [amount removed] (-0.606) | [amount removed] | [amount removed] (+0.094) | [amount removed] | [amount removed] | 0.083 / 0.45 | 0.19 | -0.511 | 57/72 (min [amount removed]) |
| latency_ms=100 | 19,445 | [amount removed] | [amount removed] (-0.656) | [amount removed] | [amount removed] (+0.044) | [amount removed] | [amount removed] | 0.086 / 0.45 | 0.19 | -0.554 | 50/72 (min [amount removed]) |
| imb_post=0.1 | 22,371 | [amount removed] | [amount removed] (-0.492) | [amount removed] | [amount removed] (+0.208) | [amount removed] | [amount removed] | 0.091 / 0.45 | 0.20 | -0.427 | 65/72 (min [amount removed]) |
| imb_post=0.2 | 21,351 | [amount removed] | [amount removed] (-0.479) | [amount removed] | [amount removed] (+0.221) | [amount removed] | [amount removed] | 0.083 / 0.45 | 0.19 | -0.416 | 66/72 (min [amount removed]) |
| imb_post=0.5 | 17,557 | [amount removed] | [amount removed] (-0.463) | [amount removed] | [amount removed] (+0.237) | [amount removed] | [amount removed] | 0.062 / 0.45 | 0.17 | -0.401 | 67/72 (min [amount removed]) |
| imb_post=0.7 | 13,850 | [amount removed] | [amount removed] (-0.451) | [amount removed] | [amount removed] (+0.249) | [amount removed] | [amount removed] | 0.045 / 0.45 | 0.14 | -0.386 | 64/72 (min [amount removed]) |
| imb_pull=-0.6 | 22,935 | [amount removed] | [amount removed] (-0.510) | [amount removed] | [amount removed] (+0.190) | [amount removed] | [amount removed] | 0.091 / 0.45 | 0.22 | -0.441 | 65/72 (min [amount removed]) |
| imb_pull=-0.1 | 18,383 | [amount removed] | [amount removed] (-0.452) | [amount removed] | [amount removed] (+0.248) | [amount removed] | [amount removed] | 0.069 / 0.45 | 0.16 | -0.402 | 66/72 (min [amount removed]) |
| imb_pull=0.0 | 17,305 | [amount removed] | [amount removed] (-0.446) | [amount removed] | [amount removed] (+0.254) | [amount removed] | [amount removed] | 0.063 / 0.45 | 0.15 | -0.398 | 67/72 (min [amount removed]) |
| imb_pull=0.2 | 14,849 | [amount removed] | [amount removed] (-0.415) | [amount removed] | [amount removed] (+0.285) | [amount removed] | [amount removed] | 0.050 / 0.45 | 0.11 | -0.371 | 66/72 (min [amount removed]) |
| max_clips=1 | 15,771 | [amount removed] | [amount removed] (-0.434) | [amount removed] | [amount removed] (+0.266) | [amount removed] | [amount removed] | 0.045 / 0.15 | 0.17 | -0.377 | 70/72 (min [amount removed]) |
| max_clips=2 | 19,016 | [amount removed] | [amount removed] (-0.466) | [amount removed] | [amount removed] (+0.234) | [amount removed] | [amount removed] | 0.065 / 0.30 | 0.18 | -0.404 | 67/72 (min [amount removed]) |
| max_clips=5 | 21,351 | [amount removed] | [amount removed] (-0.471) | [amount removed] | [amount removed] (+0.229) | [amount removed] | [amount removed] | 0.095 / 0.75 | 0.20 | -0.416 | 66/72 (min [amount removed]) |
| skew=0.2 | 18,510 | [amount removed] | [amount removed] (-0.470) | [amount removed] | [amount removed] (+0.230) | [amount removed] | [amount removed] | 0.065 / 0.45 | 0.17 | -0.402 | 65/72 (min [amount removed]) |
| skew=0.5 | 16,509 | [amount removed] | [amount removed] (-0.443) | [amount removed] | [amount removed] (+0.257) | [amount removed] | [amount removed] | 0.050 / 0.30 | 0.16 | -0.385 | 67/72 (min [amount removed]) |
| reduce_ungated=False | 8,150 | [amount removed] | [amount removed] (+0.244) | [amount removed] | [amount removed] (+0.944) | [amount removed] | [amount removed] | 0.323 / 0.45 | 0.10 | -0.038 | 58/72 (min [amount removed]) |
| clip=0.05 | 24,571 | [amount removed] | [amount removed] (-0.421) | [amount removed] | [amount removed] (+0.279) | [amount removed] | [amount removed] | 0.027 / 0.15 | 0.21 | -0.365 | 69/72 (min [amount removed]) |
| clip=0.3 | 16,176 | [amount removed] | [amount removed] (-0.543) | [amount removed] | [amount removed] (+0.157) | [amount removed] | [amount removed] | 0.140 / 0.90 | 0.16 | -0.472 | 57/72 (min [amount removed]) |
