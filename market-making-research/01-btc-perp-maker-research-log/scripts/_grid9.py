import sys
sys.path.insert(0, 'scripts/research'); import policy_sim as ps
ps.PRESETS.clear()
b = dict(imb_post=0.3, imb_pull=-0.3, join_max=0.1, q_pull=0.25, grace_ms=500, reduce_ungated=False, hold_max_s=120, vanish_cancel=True)
ps.PRESETS.update({
    "j_base": dict(b),
    "j_c1": dict(b, max_clips=1),
    "j_c2": dict(b, max_clips=2),
    "j_c1_h60": dict(b, max_clips=1, hold_max_s=60),
    "j_c1_h300": dict(b, max_clips=1, hold_max_s=300),
    "j_c2_h300": dict(b, max_clips=2, hold_max_s=300),
    "j_c1_clip01": dict(b, max_clips=1, clip=0.10),
    "j_c1_imb05": dict(b, max_clips=1, imb_post=0.5, imb_pull=0.0),
    "j_c1_imb02": dict(b, max_clips=1, imb_post=0.2, imb_pull=-0.5),
    "j_c1_rpost0": dict(b, max_clips=1, reduce_post=0.0, reduce_pull=-0.6),
    "j_c2_rpost0_h300": dict(b, max_clips=2, reduce_post=0.0, reduce_pull=-0.6, hold_max_s=300),
    "j_c1_ofi": dict(b, max_clips=1, ofi_pull=-1.5),
    "j_c1_vol": dict(b, max_clips=1, vol_max=1.0),
    "j_c1_g200": dict(b, max_clips=1, grace_ms=200),
})
sys.argv = ['x', '--days', '20251001,20260101,20260401', '--grid', '--out', 'docs/research/policy_grid9.md']
ps.main()
