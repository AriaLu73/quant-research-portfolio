import sys
sys.path.insert(0, 'scripts/research'); import policy_sim as ps
ps.PRESETS.clear()
b = dict(imb_post=0.3, imb_pull=-0.3, reduce_ungated=False, hold_max_s=120, vanish_cancel=True, q_pull=0.25, grace_ms=500, max_clips=2)
ps.PRESETS.update({
    "grow_025_06": dict(b, join_lo=0.25, join_hi=0.6, grow_thr=-0.3),
    "grow_025_1": dict(b, join_lo=0.25, join_hi=1.0, grow_thr=-0.3),
    "grow_01_06": dict(b, join_lo=0.1, join_hi=0.6, grow_thr=-0.3),
    "grow_025_06_thr05": dict(b, join_lo=0.25, join_hi=0.6, grow_thr=-0.5),
    "grow_025_06_thr0": dict(b, join_lo=0.25, join_hi=0.6, grow_thr=0.0),
    "grow_025_06_vol_ofi": dict(b, join_lo=0.25, join_hi=0.6, grow_thr=-0.3, vol_max=1.0, ofi_pull=-1.5),
    "grow_025_1_vol_ofi": dict(b, join_lo=0.25, join_hi=1.0, grow_thr=-0.3, vol_max=1.0, ofi_pull=-1.5),
    "grow_025_06_qp06": dict(b, join_lo=0.25, join_hi=0.6, grow_thr=-0.3, q_pull=0.6),
    "grow_025_06_h300": dict(b, join_lo=0.25, join_hi=0.6, grow_thr=-0.3, hold_max_s=300),
    "grow_025_06_c1": dict(b, join_lo=0.25, join_hi=0.6, grow_thr=-0.3, max_clips=1),
})
sys.argv = ['x', '--days', '20251001,20260101,20260401', '--grid', '--out', 'docs/research/policy_grid11.md']
ps.main()
