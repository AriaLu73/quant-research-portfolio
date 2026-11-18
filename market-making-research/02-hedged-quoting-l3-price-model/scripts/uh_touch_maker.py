"""research3 H-T2: can we quote at the BTC-USDC touch, pulling the quote when the reference makes it stale?
Own recording (data/research5/usdc_pairs), exchange timestamps, paired prints removed by order id. Stated before computing:

  quote     we join the public touch: for a real taker SELL our bid is the best public bid just before it (BUY: best ask).
  rule      the quote is kept only while its margin to fair value is at least theta bp
            (margin = distance of the quote from F on the profitable side; F = USDT mid x (1 + 60 s median basis)).
            When the reference moves and the margin drops below theta, we cancel; the cancel takes effect tau later.
  fill      a real taker order fills us if, at its time t, the quote is valid (margin >= theta), or it became invalid
            less than tau before t (we could not get out in time). Quotes that were never valid since the touch moved to
            that price are not ours (we would not have posted there). Queue front, full taker size: optimistic.
  result    per fill, bp of notional: e = g x (F(t + h) - px) / px, plus fees
              passive hedge: e(5 s) + 1.2 + 0.7          taker hedge: e(50 ms) + 1.2 - 1.8 - USDT half spread
  grid      theta in {-1, 0, 0.5, 1.0} bp (-1 = always quote the touch), tau in {0, 6, 26, 50} ms
            (6 / 26 ms = median / p90 of the reaction time measured live on 2026-10-02).
  verdict   worth building only if, at tau = 26 ms, the size-weighted mean with the passive hedge is above zero by more than
            two standard errors AND the taker-hedged mean is not below -1 bp (the passive figure assumes a hedge at mid).
One day of one regime, already looked at in aggregate: an indication, not a validation.
usage: Python314/python.exe scripts/research3/uh_touch_maker.py <day> [coin=BTC] [first_hour=0]"""
import io, contextlib, math, runpy, sys
import numpy as np

day = sys.argv[1]; coin = sys.argv[2] if len(sys.argv) > 2 else "BTC"; h0 = int(sys.argv[3]) if len(sys.argv) > 3 else 0
sys.argv = ["x", day, coin]
with contextlib.redirect_stdout(io.StringIO()):
    ns = runpy.run_path(__file__.replace("uh_touch_maker.py", "uh_flow_now.py"))
Q, H, o, g, basis, at = ns["Q"], ns["H"], ns["o"], ns["g"], ns["basis"], ns["at"]
qt = Q.t.to_numpy(np.int64); qbb = Q.bb.to_numpy(); qba = Q.ba.to_numpy()
ht = H.t.to_numpy(np.int64); hb = H.bb.to_numpy(); ha = H.ba.to_numpy(); hmid = (hb + ha) / 2
real = o[(~o.pair) & (o.hour >= h0)].sort_values("t")
hours = real.hour.nunique()
THETAS, TAUS = (-1.0, 0.0, 0.5, 1.0), (0, 6, 26, 50)
REB_Q, REB_H, FEE_H = OUR_FEE, 0.7, 1.8
res = {(th, tau): [] for th in THETAS for tau in TAUS}        # rows: (usd, e5, e005, hs, kind)
n_touch = 0
for t, sgn, usd, hour in zip(real.t.to_numpy(), real.sgn.to_numpy(), real.usd.to_numpy(), real.hour.to_numpy()):
    i = np.searchsorted(qt, t, side="left") - 1                # book strictly before the order
    if i < 0:
        continue
    gm = -sgn                                                  # maker side: +1 we buy (taker sold)
    px = qbb[i] if gm > 0 else qba[i]
    # when did the touch arrive at this price?
    j = i
    arr = qbb if gm > 0 else qba
    while j > 0 and arr[j - 1] == px and qt[i] - qt[j - 1] < 1000:
        j -= 1
    t_post = max(qt[j], t - 1000)
    b = basis[np.clip(np.searchsorted(g, t, side="right") - 1, 0, len(g) - 1)]
    if not np.isfinite(b):
        continue
    n_touch += 1
    k1 = np.searchsorted(ht, t, side="right")                  # reference states up to t
    k0 = max(np.searchsorted(ht, t_post, side="right") - 1, 0)
    F = hmid[k0:k1] * (1 + b)
    tt = np.maximum(ht[k0:k1], t_post)
    margin = gm * (F - px) / px * 1e4
    F5 = at(ht, hmid, t + 5000) * (1 + b); F005 = at(ht, hmid, t + 50) * (1 + b)
    e5 = gm * (F5 - px) / px * 1e4; e005 = gm * (F005 - px) / px * 1e4
    hs = (ha[k1 - 1] - hb[k1 - 1]) / 2 / hmid[k1 - 1] * 1e4
    for th in THETAS:
        if th < 0:
            for tau in TAUS:
                res[(th, tau)].append((usd, e5, e005, hs, 0))
            continue
        ok = margin >= th
        if ok[-1]:
            for tau in TAUS:
                res[(th, tau)].append((usd, e5, e005, hs, 0))  # valid quote: a fill we wanted
            continue
        if not ok.any():
            continue                                           # never valid at this price: not our quote
        last_ok = np.nonzero(ok)[0][-1]
        t_stale = tt[last_ok + 1]                              # first reference state with the margin below theta
        age = t - t_stale
        for tau in TAUS:
            if age < tau:
                res[(th, tau)].append((usd, e5, e005, hs, 1))  # stale, cancel not yet effective: picked off


def wstat(v, w):
    v, w = np.asarray(v, float), np.asarray(w, float)
    m = (v * w).sum() / w.sum()
    neff = w.sum() ** 2 / (w * w).sum()
    return m, math.sqrt(((w * (v - m) ** 2).sum() / w.sum()) / max(neff - 1, 1)), neff


print("%s-USDC %s from hour %02d: %d hours, real taker orders at the touch %d ($%.0f)" % (coin, day, h0, hours, n_touch, real.usd.sum()))
print("theta bp | tau ms | fills/h   $/h   picked-off share | net passive-hedged bp (se)  $/h | net taker-hedged bp  $/h")
for th in THETAS:
    for tau in TAUS:
        r = res[(th, tau)]
        if th < 0 and tau != TAUS[0]:
            continue
        if len(r) < 5:
            print("  %5s | %4s | too few fills (%d)" % ("always" if th < 0 else "%.1f" % th, "-" if th < 0 else tau, len(r))); continue
        a = np.array(r)
        w = a[:, 0]
        mp, sp, _ = wstat(a[:, 1] + REB_Q + REB_H, w)
        mt, _, _ = wstat(a[:, 2] + REB_Q - FEE_H - a[:, 3], w)
        print("  %6s | %4s | %6.1f %7.0f   %5.1f%%          | %+6.2f (%.2f)  %+7.2f        | %+6.2f  %+7.2f" % (
            "always" if th < 0 else "%.1f" % th, "-" if th < 0 else tau, len(r) / hours, w.sum() / hours, 100 * a[:, 4].mean(),
            mp, sp, mp * w.sum() / hours / 1e4, mt, mt * w.sum() / hours / 1e4))

# ---- robustness (added after the first table was read; the verdict rule above is unchanged) ----
# Our quote has a size: a fill is min(order $, S). Income per hour and how it is spread over the hours, at theta = 0, tau = 26 ms.
hr_all = np.sort(real.hour.unique())
for S in (7500.0, 375.0):
    for th, tau in ((0.0, 26), (0.5, 26), (-1.0, 0)):
        r = res[(th, tau)]
        if len(r) < 5:
            continue
        a = np.array(r)
        w = np.minimum(a[:, 0], S)
        pas = (a[:, 1] + REB_Q + REB_H) * w / 1e4
        tak = (a[:, 2] + REB_Q - FEE_H - a[:, 3]) * w / 1e4
        mp, sp, neff = wstat(a[:, 1] + REB_Q + REB_H, w)
        mt, st_, _ = wstat(a[:, 2] + REB_Q - FEE_H - a[:, 3], w)
        print("size cap $%-5.0f theta %-6s tau %2d ms: filled $%.0f/h | passive-hedged %+5.2f bp (se %.2f, n_eff %.0f) = $%+.2f/h | taker-hedged %+5.2f bp (se %.2f) = $%+.2f/h | best 3 fills give %.0f%% of the passive income" % (
            S, "always" if th < 0 else "%.1f" % th, tau, w.sum() / hours, mp, sp, neff, pas.sum() / hours, mt, st_, tak.sum() / hours,
            100 * np.sort(pas)[-3:].sum() / pas.sum() if pas.sum() > 0 else float("nan")))
