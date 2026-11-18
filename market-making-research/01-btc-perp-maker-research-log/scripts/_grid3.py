import sys
sys.path.insert(0, 'scripts/research'); import policy_sim as ps
ps.PRESETS.clear()
base = dict(imb_post=0.3, imb_pull=-0.3, reduce_ungated=False, hold_max_s=60)
ps.PRESETS.update({
    "rg_h60": dict(base),
    "rg_h60_qp005": dict(base, q_pull=0.05),
    "rg_h60_qp01": dict(base, q_pull=0.1),
    "rg_h60_qp02": dict(base, q_pull=0.2),
    "rg_h60_qp04": dict(base, q_pull=0.4),
    "rg_h60_qp01_open": dict(base, q_pull=0.1, q_pull_reduce=False),
    "rg_h300_qp01": dict(base, q_pull=0.1, hold_max_s=300),
    "rg_none_qp01": dict(base, q_pull=0.1, hold_max_s=None),
    "ung_qp01": dict(imb_post=0.3, imb_pull=-0.3, q_pull=0.1),
    "ung_qp02": dict(imb_post=0.3, imb_pull=-0.3, q_pull=0.2),
    "base_qp01_nogate": dict(q_pull=0.1),
})
sys.argv = ['x', '--days', '20251001,20260101,20260401', '--grid', '--out', 'docs/research/policy_grid3.md']
ps.main()
