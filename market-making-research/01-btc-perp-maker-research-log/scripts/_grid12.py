import sys, json
sys.path.insert(0, 'scripts/research'); import policy_sim as ps
C = json.load(open('data/research/thin_level_logit_reduced.json')); pct = C["score_pct"]
ps.PRESETS.clear()
b = dict(join_max=0.1, q_pull=0.25, grace_ms=500, reduce_ungated=False, hold_max_s=120, vanish_cancel=True)
g = dict(imb_post=0.3, imb_pull=-0.3)
ps.PRESETS.update({
    "v4_ref": dict(b, **g),
    "s80": dict(b, score_min=pct["80"]),
    "s85": dict(b, score_min=pct["85"]),
    "s90": dict(b, score_min=pct["90"]),
    "s95": dict(b, score_min=pct["95"]),
    "s85_gate": dict(b, score_min=pct["85"], **g),
    "s90_gate": dict(b, score_min=pct["90"], **g),
    "s85_pull0": dict(b, score_min=pct["85"], imb_pull=-0.3),
    "s85_redung": dict(b, score_min=pct["85"], reduce_ungated=True),
    "s85_nored": dict(b, score_min=pct["85"], score_reduce=False),
    "s85_h300": dict(b, score_min=pct["85"], hold_max_s=300),
    "s85_c2": dict(b, score_min=pct["85"], max_clips=2),
    "s85_j02": dict(b, score_min=pct["85"], join_max=0.2),
    "s85_nojoin": dict(b, score_min=pct["85"], join_max=None),
    "s85_qp06": dict(b, score_min=pct["85"], q_pull=0.6),
})
sys.argv = ['x', '--days', '20251001,20260101,20260401', '--grid', '--out', 'docs/research/policy_grid12_score.md']
ps.main()
