import sys
sys.path.insert(0, 'scripts/research'); import policy_sim as ps
ps.PRESETS.clear()
g = dict(imb_post=0.3, imb_pull=-0.3)
v = dict(vanish_cancel=True)
ps.PRESETS.update({
    "gate_v": dict(g, **v),
    "gate_v_rg": dict(g, reduce_ungated=False, **v),
    "gate_v_rg_h120": dict(g, reduce_ungated=False, hold_max_s=120, **v),
    "join01_qp025_v": dict(join_max=0.1, q_pull=0.25, **v),
    "join01_qp025_gate_v": dict(g, join_max=0.1, q_pull=0.25, **v),
    "join01_qp06_gate_v": dict(g, join_max=0.1, q_pull=0.6, **v),
    "join01_qp025_gate_v_rg": dict(g, join_max=0.1, q_pull=0.25, reduce_ungated=False, **v),
    "join01_qp025_gate_v_rg_h120": dict(g, join_max=0.1, q_pull=0.25, reduce_ungated=False, hold_max_s=120, **v),
    "join01_qp06_gate_v_rg_h120": dict(g, join_max=0.1, q_pull=0.6, reduce_ungated=False, hold_max_s=120, **v),
    "join02_qp04_gate_v_rg_h120": dict(g, join_max=0.2, q_pull=0.4, reduce_ungated=False, hold_max_s=120, **v),
    "qp025_gate_v_rg_h120": dict(g, q_pull=0.25, reduce_ungated=False, hold_max_s=120, **v),
    "qp06_gate_v_rg_h120": dict(g, q_pull=0.6, reduce_ungated=False, hold_max_s=120, **v),
    "qp06_v_rg_h120": dict(q_pull=0.6, reduce_ungated=False, hold_max_s=120, **v),
})
sys.argv = ['x', '--days', '20251001,20260101,20260401', '--grid', '--out', 'docs/research/policy_grid7.md']
ps.main()
