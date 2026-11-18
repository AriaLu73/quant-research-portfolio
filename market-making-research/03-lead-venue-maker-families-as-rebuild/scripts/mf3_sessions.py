#!/usr/bin/env python3
"""research5 MF-3: the sessions behind the profitable sender pattern "#01|20" - who of them earns, and how do they quote?

Input: data/research5/maker_families/orders__01_20_<day>_<hh>.npz (mf_family_orders.py). Mid: research3 l3mid (read-only).
Per session (first 11 characters of the clientOid = "0" + unix start time of the program):
  activity   orders per hour, share that ever rested, buy / sell split, median size, median resting time;
  placement  distance of the order price from the mid at the moment it rested (bp, + = behind the mid on its own side);
  fills      maker notional, distance of the fill from the mid just before (m0), markouts at 1 / 10 / 60 s, net = m10 + rebate,
             hours with a positive result; inventory range if only this contract is counted.
Usage: Python314/python.exe scripts/research5/mf3_sessions.py 20261001 20261002
"""
import glob, os, sys
import numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "data", "research5", "maker_families")
MID = os.path.join(ROOT, "data", "research3", "px", "l3mid")
MULT, REBATE = OUR_FEE, 0.7
OC = "sess num recv ot open side tick size end reason filled".split()
FC = "ts sess side tick size self".split()


class Mid:
    def __init__(self, day):
        z = np.load(os.path.join(MID, f"mid_{day}.npz"))
        self.t, self.m = z["t"], z["m"]

    def at(self, t):
        i = np.searchsorted(self.t, np.asarray(t, np.int64), side="right") - 1
        return np.where(i >= 0, self.m[np.clip(i, 0, len(self.m) - 1)], np.nan)


def load(days, tag="_01_20"):
    Rs, Fs, hours = [], [], 0
    for day in days:
        mid = Mid(day)
        for p in sorted(glob.glob(os.path.join(OUT, f"orders_{tag}_{day}_??.npz"))):
            z = np.load(p)
            R = pd.DataFrame(z["orders"], columns=OC)
            F = pd.DataFrame(z["fills"], columns=FC)
            R["hour"] = F["hour"] = day + os.path.basename(p)[-6:-4]
            rest = R.open > 0
            px = R.tick / 10.0
            m = mid.at(R.open.to_numpy())
            R["dist"] = np.where(rest, np.where(R.side == 0, m - px, px - m) / m * 1e4, np.nan)     # + = behind the mid
            R["life"] = np.where(rest & (R.end > 0), (R.end - R.open) / 1e6, np.nan)
            fpx = F.tick / 10.0
            sg = np.where(F.side == 0, 1.0, -1.0)
            F["notional"] = F["size"] * MULT * fpx
            F["m0"] = sg * (mid.at(F.ts.to_numpy() - 1) - fpx) / fpx * 1e4
            for h in (1, 10, 60):
                F["m%d" % h] = sg * (mid.at(F.ts.to_numpy() + h * 10**9) - fpx) / fpx * 1e4
            F["q"] = sg * F["size"] * MULT
            Rs.append(R); Fs.append(F); hours += 1
    return pd.concat(Rs, ignore_index=True), pd.concat(Fs, ignore_index=True), hours


def wavg(g, c):
    ok = np.isfinite(g[c])
    return np.average(g[c][ok], weights=g.notional[ok]) if ok.any() and g.notional[ok].sum() > 0 else np.nan


def main():
    days = sys.argv[1:] or ["20261001", "20261002"]
    R, F, hours = load(days)
    F = F[F.self == 0]
    print(f"{hours} hours; orders {len(R):,}, rested {int((R.open > 0).sum()):,}; maker fills {len(F):,}, ${F.notional.sum() / 1e6:.1f}M; sessions {R.sess.nunique()}")
    rows = []
    for s, g in R.groupby("sess"):
        r = g[g.open > 0]
        f = F[F.sess == s]
        hv = f.groupby("hour").apply(lambda x: wavg(x, "m10") + REBATE) if len(f) else pd.Series(dtype=float)
        inv = f.sort_values("ts").q.cumsum() if len(f) else pd.Series([0.0])
        rows.append(dict(
            session=s, started=pd.to_datetime(s, unit="s").strftime("%m-%d %H:%M"), hours=g.hour.nunique(),
            orders_h=len(g) / max(g.hour.nunique(), 1), rested=len(r) / len(g), buy=(r.side == 0).mean() if len(r) else np.nan,
            size=r["size"].median() if len(r) else np.nan, life_ms=r.life.median() if len(r) else np.nan,
            d10=r.dist.quantile(0.1) if len(r) else np.nan, d50=r.dist.median() if len(r) else np.nan, d90=r.dist.quantile(0.9) if len(r) else np.nan,
            fills=len(f), usd_m=f.notional.sum() / 1e6, m0=wavg(f, "m0") if len(f) else np.nan, m1=wavg(f, "m1") if len(f) else np.nan,
            m10=wavg(f, "m10") if len(f) else np.nan, m60=wavg(f, "m60") if len(f) else np.nan,
            net10=(wavg(f, "m10") + REBATE) if len(f) else np.nan, hrs_pos=(hv > 0).mean() if len(hv) else np.nan, n_hrs=len(hv),
            usd10=((f.m10 + REBATE) * f.notional).sum() / 1e4 if len(f) else 0.0, inv_min=inv.min(), inv_max=inv.max(),
            # round-trip result on this contract only: cash from its maker fills + the remaining inventory at the last fill's price
            pnl_usd=(-(f.q * f.tick / 10.0).sum() + f.q.sum() * (f.sort_values("ts").tick.iloc[-1] / 10.0)) if len(f) else 0.0,
            rebate_usd=f.notional.sum() * REBATE / 1e4))
    T = pd.DataFrame(rows).sort_values("usd_m", ascending=False)
    pd.set_option("display.width", 300); pd.set_option("display.max_rows", 200)
    print(T.round(dict(orders_h=0, rested=3, buy=2, size=0, life_ms=0, d10=2, d50=2, d90=2, usd_m=2, m0=2, m1=2, m10=2, m60=2, net10=2, hrs_pos=2, usd10=0, inv_min=2, inv_max=2, pnl_usd=0, rebate_usd=0)).to_string(index=False))
    T.to_csv(os.path.join(OUT, "mf3_sessions.csv"), index=False)
    tot = T.usd10.sum()
    print(f"\nall sessions: ${T.usd_m.sum():.1f}M maker notional, $ at 10 s with rebate {tot:,.0f}; top session's share of that {T.usd10.max() / tot:.0%}")


if __name__ == "__main__":
    main()
