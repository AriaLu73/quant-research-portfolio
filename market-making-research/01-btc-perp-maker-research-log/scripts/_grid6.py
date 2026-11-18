import sys
sys.path.insert(0, 'scripts/research'); import policy_sim as ps
ps.DEFAULT["x_sample_ms"] = 0            # 0401 OKX 原始 20ms 粒度(上界)
ps.PRESETS.clear()
g = dict(imb_post=0.3, imb_pull=-0.3)
ps.PRESETS.update({
    "gate": dict(g),
    "x_pull05": dict(x_pull=-0.5),
    "x_post0_pull05": dict(x_post=0.0, x_pull=-0.5),
    "x_post03_pull03": dict(x_post=0.3, x_pull=-0.3),
    "x_post05_pull0": dict(x_post=0.5, x_pull=0.0),
    "gate_x_post0_pull05": dict(g, x_post=0.0, x_pull=-0.5),
    "gate_x_post03_pull03": dict(g, x_post=0.3, x_pull=-0.3),
    "gate_x_post05_pull0": dict(g, x_post=0.5, x_pull=0.0),
    "gate_x_post05_pull0_rg": dict(g, x_post=0.5, x_pull=0.0, reduce_ungated=False),
    "gate_x_post05_pull0_rg_h120": dict(g, x_post=0.5, x_pull=0.0, reduce_ungated=False, hold_max_s=120),
    "x_post05_pull0_rg_h120": dict(x_post=0.5, x_pull=0.0, reduce_ungated=False, hold_max_s=120),
})
sys.argv = ['x', '--days', '20260401', '--grid', '--out', 'docs/research/policy_grid6_xlead20ms.md']
ps.main()
