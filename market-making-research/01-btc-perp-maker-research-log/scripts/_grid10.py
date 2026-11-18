import sys
sys.path.insert(0, 'scripts/research'); import policy_sim as ps
ps.PRESETS.clear()
b = dict(imb_post=0.3, imb_pull=-0.3, join_max=0.1, q_pull=0.25, grace_ms=500, reduce_ungated=False, hold_max_s=120, vanish_cancel=True)
ps.PRESETS.update({
    "j_c3_vol": dict(b, vol_max=1.0),
    "j_c3_ofi": dict(b, ofi_pull=-1.5),
    "j_c3_vol_ofi": dict(b, vol_max=1.0, ofi_pull=-1.5),
    "j_c2_vol": dict(b, max_clips=2, vol_max=1.0),
    "j_c2_vol_ofi": dict(b, max_clips=2, vol_max=1.0, ofi_pull=-1.5),
    "j_c2_vol07_ofi": dict(b, max_clips=2, vol_max=0.7, ofi_pull=-1.5),
    "j_c2_vol15_ofi": dict(b, max_clips=2, vol_max=1.5, ofi_pull=-1.5),
    "j_c2_vol_ofi_tint": dict(b, max_clips=2, vol_max=1.0, ofi_pull=-1.5, tint_max=6),
    "j_c2_vol_ofi_h300": dict(b, max_clips=2, vol_max=1.0, ofi_pull=-1.5, hold_max_s=300),
    "j_c2_vol_ofi_qp04": dict(b, max_clips=2, vol_max=1.0, ofi_pull=-1.5, q_pull=0.4),
    "j_c2_vol_ofi_j02": dict(b, max_clips=2, vol_max=1.0, ofi_pull=-1.5, join_max=0.2),
})
sys.argv = ['x', '--days', '20251001,20260101,20260401', '--grid', '--out', 'docs/research/policy_grid10.md']
ps.main()
