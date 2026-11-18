# 策略模拟面板(快速模拟器,训练日)

天:20251001, 20260101, 20260401;单量 0.15 BTC;库存上限 3 手;返费 OUR_FEE;队列估计 ESTIMATED

| policy | fills | vol $ | spread pnl $ (bp) | rebate $ | net $ (bp) | net by day | max DD $ | pos mean/max BTC | fill rate | mk5s bp | hours>0 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| baseline | 74,561 | [amount removed] | [amount removed] (-2.261) | [amount removed] | [amount removed] (-1.561) | [amount removed] | [amount removed] | 0.212 / 0.45 | 1.32 | -2.029 | 0/72 (min [amount removed]) |
| imb03_partial | 14,081 | [amount removed] | [amount removed] (-1.571) | [amount removed] | [amount removed] (-0.871) | [amount removed] | [amount removed] | 0.028 / 0.45 | 0.15 | -1.472 | 6/72 (min [amount removed]) |
| imb03_full | 20,297 | [amount removed] | [amount removed] (-0.477) | [amount removed] | [amount removed] (+0.223) | [amount removed] | [amount removed] | 0.078 / 0.45 | 0.19 | -0.415 | 66/72 (min [amount removed]) |
| imb03_redgate_loose | 4,584 | [amount removed] | [amount removed] (-0.836) | [amount removed] | [amount removed] (-0.136) | [amount removed] | [amount removed] | 0.161 / 0.45 | 0.06 | -0.543 | 37/72 (min [amount removed]) |
| imb03_redgate_loose_h60 | 10,792 | [amount removed] | [amount removed] (-1.394) | [amount removed] | [amount removed] (-0.694) | [amount removed] | [amount removed] | 0.044 / 0.45 | 0.12 | -1.395 | 17/72 (min [amount removed]) |
| imb03_redgate_loose_h20 | 12,344 | [amount removed] | [amount removed] (-1.476) | [amount removed] | [amount removed] (-0.776) | [amount removed] | [amount removed] | 0.035 / 0.45 | 0.13 | -1.438 | 10/72 (min [amount removed]) |
| imb03_redgate_same_h60 | 10,877 | [amount removed] | [amount removed] (-1.337) | [amount removed] | [amount removed] (-0.637) | [amount removed] | [amount removed] | 0.045 / 0.45 | 0.12 | -1.427 | 17/72 (min [amount removed]) |
| imb03_redgate_same_h300 | 7,049 | [amount removed] | [amount removed] (-1.050) | [amount removed] | [amount removed] (-0.350) | [amount removed] | [amount removed] | 0.086 / 0.45 | 0.09 | -1.284 | 32/72 (min [amount removed]) |
| imb03_redgate_same | 2,995 | [amount removed] | [amount removed] (-0.911) | [amount removed] | [amount removed] (-0.211) | [amount removed] | [amount removed] | 0.215 / 0.45 | 0.04 | -0.474 | 33/72 (min [amount removed]) |
| imb05_redgate_same_h60 | 8,093 | [amount removed] | [amount removed] (-1.465) | [amount removed] | [amount removed] (-0.765) | [amount removed] | [amount removed] | 0.034 / 0.45 | 0.09 | -1.438 | 21/72 (min [amount removed]) |
| imb03_redgate_same_h60_c1 | 6,168 | [amount removed] | [amount removed] (-1.234) | [amount removed] | [amount removed] (-0.534) | [amount removed] | [amount removed] | 0.025 / 0.15 | 0.08 | -1.333 | 22/72 (min [amount removed]) |
| imb03_redgate_same_h60_skew | 9,542 | [amount removed] | [amount removed] (-1.308) | [amount removed] | [amount removed] (-0.608) | [amount removed] | [amount removed] | 0.037 / 0.43 | 0.10 | -1.293 | 20/72 (min [amount removed]) |
