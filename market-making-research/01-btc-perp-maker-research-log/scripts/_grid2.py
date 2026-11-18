
import sys, json, os
sys.path.insert(0,'scripts/research'); import policy_sim as ps
keep=['baseline','imb03_partial','imb03_full','imb03_redgate_loose','imb03_redgate_loose_h60','imb03_redgate_loose_h20','imb03_redgate_same_h60','imb03_redgate_same_h300','imb03_redgate_same','imb05_redgate_same_h60','imb03_redgate_same_h60_c1','imb03_redgate_same_h60_skew']
for k in list(ps.PRESETS):
    if k not in keep: ps.PRESETS.pop(k)
sys.argv=['x','--days','20251001,20260101,20260401','--grid','--out','docs/research/policy_grid2.md']
ps.main()
