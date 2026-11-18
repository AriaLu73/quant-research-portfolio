import sys
sys.path.insert(0, 'scripts/research'); import policy_sim as ps
ps.PRESETS.clear()
g = dict(imb_post=0.3, imb_pull=-0.3)
ps.PRESETS.update({
    "base": {},
    "gate": dict(g),
    "x_pull05": dict(x_pull=-0.5),
    "x_pull03": dict(x_pull=-0.3),
    "x_post0_pull05": dict(x_post=0.0, x_pull=-0.5),
    "gate_x_pull05": dict(g, x_pull=-0.5),
    "gate_x_post0_pull05": dict(g, x_post=0.0, x_pull=-0.5),
    "gate_x_post03_pull03": dict(g, x_post=0.3, x_pull=-0.3),
    "gate_x_post0_pull05_rg": dict(g, x_post=0.0, x_pull=-0.5, reduce_ungated=False),
    "gate_x_post0_pull05_qp01": dict(g, x_post=0.0, x_pull=-0.5, q_pull=0.1),
})
sys.argv = ['x', '--days', '20260401', '--grid', '--out', 'docs/research/policy_grid5_xlead.md']
ps.main()
