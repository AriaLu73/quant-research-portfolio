import sys
sys.path.insert(0, 'scripts/research'); import policy_sim as ps
ps.PRESETS.clear()
g = dict(imb_post=0.3, imb_pull=-0.3)
ps.PRESETS.update({
    "join01": dict(join_max=0.1),
    "join01_gate": dict(g, join_max=0.1),
    "join01_behind05": dict(join_max=0.1, behind_min=0.5, grace_ms=500),
    "join01_gate_behind05": dict(g, join_max=0.1, behind_min=0.5, grace_ms=500),
    "join01_gate_behind1": dict(g, join_max=0.1, behind_min=1.0, grace_ms=1000),
    "join005_gate_behind05": dict(g, join_max=0.05, behind_min=0.5, grace_ms=500),
    "join03_gate_behind05": dict(g, join_max=0.3, behind_min=0.5, grace_ms=500),
    "join01_gate_behind05_rg": dict(g, join_max=0.1, behind_min=0.5, grace_ms=500, reduce_ungated=False),
    "join01_gate_behind05_rg_h120": dict(g, join_max=0.1, behind_min=0.5, grace_ms=500, reduce_ungated=False, hold_max_s=120),
    "behind05_only": dict(behind_min=0.5, grace_ms=500),
    "gate_behind05": dict(g, behind_min=0.5, grace_ms=500),
})
sys.argv = ['x', '--days', '20251001,20260101,20260401', '--grid', '--out', 'docs/research/policy_grid4.md']
ps.main()
