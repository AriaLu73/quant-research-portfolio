import sys
sys.path.insert(0, 'scripts/research'); import policy_sim as ps
ps.PRESETS.clear()
g = dict(imb_post=0.3, imb_pull=-0.3)
v = dict(vanish_cancel=True)
ps.PRESETS.update({
    "j01_qp025_g200_v": dict(join_max=0.1, q_pull=0.25, grace_ms=200, **v),
    "j01_qp025_g500_gate_v": dict(g, join_max=0.1, q_pull=0.25, grace_ms=500, **v),
    "j01_qp025_g200_gate_v": dict(g, join_max=0.1, q_pull=0.25, grace_ms=200, **v),
    "j01_qp06_g500_gate_v": dict(g, join_max=0.1, q_pull=0.6, grace_ms=500, **v),
    "j01_qp06_g1000_gate_v": dict(g, join_max=0.1, q_pull=0.6, grace_ms=1000, **v),
    "j01_qp06_g500_gate_v_rg_h120": dict(g, join_max=0.1, q_pull=0.6, grace_ms=500, reduce_ungated=False, hold_max_s=120, **v),
    "j01_qp025_g500_gate_v_rg_h120": dict(g, join_max=0.1, q_pull=0.25, grace_ms=500, reduce_ungated=False, hold_max_s=120, **v),
    "j02_qp06_g500_gate_v_rg_h120": dict(g, join_max=0.2, q_pull=0.6, grace_ms=500, reduce_ungated=False, hold_max_s=120, **v),
    "j005_qp06_g500_gate_v_rg_h120": dict(g, join_max=0.05, q_pull=0.6, grace_ms=500, reduce_ungated=False, hold_max_s=120, **v),
    "j01_qp1_g500_gate_v_rg_h120": dict(g, join_max=0.1, q_pull=1.0, grace_ms=500, reduce_ungated=False, hold_max_s=120, **v),
    "j01_qp06_g500_gate_v_rg": dict(g, join_max=0.1, q_pull=0.6, grace_ms=500, reduce_ungated=False, **v),
})
sys.argv = ['x', '--days', '20251001,20260101,20260401', '--grid', '--out', 'docs/research/policy_grid8.md']
ps.main()
