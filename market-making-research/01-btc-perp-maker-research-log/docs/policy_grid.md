# 策略模拟面板(快速模拟器,训练日)

天:20251001, 20260101, 20260401;单量 0.15 BTC;库存上限 3 手;返费 OUR_FEE;队列估计 ESTIMATED

| policy | fills | vol $ | spread pnl $ (bp) | rebate $ | net $ (bp) | net by day | max DD $ | pos mean/max BTC | fill rate | mk5s bp |
|---|---|---|---|---|---|---|---|---|---|---|
| baseline | 49,941 | [amount removed] | [amount removed] (-1.109) | [amount removed] | [amount removed] (-0.409) | [amount removed] | [amount removed] | 0.327 / 0.45 | 0.47 | -0.876 |
| imb_gate_03 | 20,167 | [amount removed] | [amount removed] (-0.471) | [amount removed] | [amount removed] (+0.229) | [amount removed] | [amount removed] | 0.077 / 0.45 | 0.19 | -0.409 |
| imb_gate_05 | 16,653 | [amount removed] | [amount removed] (-0.442) | [amount removed] | [amount removed] (+0.258) | [amount removed] | [amount removed] | 0.058 / 0.45 | 0.16 | -0.383 |
| ofi_gate | 38,047 | [amount removed] | [amount removed] (-0.822) | [amount removed] | [amount removed] (-0.122) | [amount removed] | [amount removed] | 0.256 / 0.45 | 0.34 | -0.615 |
| calm | 24,127 | [amount removed] | [amount removed] (-0.959) | [amount removed] | [amount removed] (-0.259) | [amount removed] | [amount removed] | 0.220 / 0.45 | 0.46 | -0.736 |
| qwin | 41,607 | [amount removed] | [amount removed] (-0.883) | [amount removed] | [amount removed] (-0.183) | [amount removed] | [amount removed] | 0.243 / 0.45 | 0.43 | -0.715 |
| calm_qwin | 17,703 | [amount removed] | [amount removed] (-0.794) | [amount removed] | [amount removed] (-0.094) | [amount removed] | [amount removed] | 0.156 / 0.45 | 0.41 | -0.616 |
| calm_qwin_ofi | 13,912 | [amount removed] | [amount removed] (-0.693) | [amount removed] | [amount removed] (+0.007) | [amount removed] | [amount removed] | 0.130 / 0.45 | 0.34 | -0.455 |
| calm_qwin_imb | 7,771 | [amount removed] | [amount removed] (-0.398) | [amount removed] | [amount removed] (+0.302) | [amount removed] | [amount removed] | 0.049 / 0.45 | 0.28 | -0.347 |
| all_gates | 6,358 | [amount removed] | [amount removed] (-0.351) | [amount removed] | [amount removed] (+0.349) | [amount removed] | [amount removed] | 0.039 / 0.45 | 0.25 | -0.322 |
| all_gates_skew | 5,766 | [amount removed] | [amount removed] (-0.324) | [amount removed] | [amount removed] (+0.376) | [amount removed] | [amount removed] | 0.031 / 0.45 | 0.24 | -0.314 |
| all_gates_redgated | 2,760 | [amount removed] | [amount removed] (+0.277) | [amount removed] | [amount removed] (+0.977) | [amount removed] | [amount removed] | 0.297 / 0.45 | 0.15 | +0.021 |
