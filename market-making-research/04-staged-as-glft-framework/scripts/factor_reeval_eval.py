#!/usr/bin/env python3
"""已有因子重评 —— 第二步:在我们自己的真实成交 / 持仓上评(用户 10-15:"你先重评再看需不需要新的因子")。

样本(都只取 12–18 时 UTC,盘口网格只有这六小时)
  回测十天  第三轮交给 RD 的实盘组回测成交(RDAgent_Factor/Inventory/第三轮_实盘组持仓路径/fills.parquet;BTC 实验 E、ETH 实验 C + 15 张上限)
  实盘 10-14 两个实盘实例(MmAsBtc-bc24ee34、MmAsEth-1be9e2b6)的成交(data/research7/live_orders_20261014.jsonl.gz)
因子值  data/factors/reeval/<日>.npz(factor_reeval_calc.py 算的)+ data/factors/tox1(毒性一轮)+ 这里按策略原式算的 rv_ewm_10s、RV1。
        取值时刻:严格早于 t − 延迟 的最后一个 10 毫秒网格行(网格行 t_r 含 t_r 及以前的更新,严格早于避免把打到我们的那笔成交算进去)。
三个角色
  A 成交后毒性  每笔挂单成交。M_τ = s·(m_{t+τ} − P)/P·1e4(bp,s = +1 买 / −1 卖)。
                侧别因子(_ask/_bid):买单成交用 _bid、卖单成交用 _ask;方向因子乘 s;库存对(_long/_short):买用 _long、卖用 _short。
  B 出货        有仓位的时刻(每 1 秒一个点)。H_τ = s·(m_{t+τ} − m_t)/m_t·1e4,s = 仓位方向。取号同 A(多仓看 _bid / _long)。
  C 波动        全部时刻每 1 秒一个点。RV_τ = (t, t+τ] 内 10 毫秒对数中间价变动的平方和(bp²)。非方向因子原样用,侧别因子用两侧之和。
指标
  IC          秩相关,逐天算再平均(t = 均值 / 逐天标准差 × √天数);另报合并全部样本的秩相关
  曲线 / 半衰期  τ 从 10 毫秒到 60 秒;峰值 = |IC| 最大的 τ;半衰期 = 峰值之后 |IC| 第一次降到峰值一半的 τ(对数插值)
  A 的经济量   按因子"预期方向"去掉最毒的 20% 成交(侧别毒性因子:值高 = 毒;方向因子 × s 与库存对:值低 = 毒),
               留下的每笔 M_0.1 / M_1 / M_3 比全部好多少 bp,去掉了几成成交额;另报延迟 20 / 50 毫秒的 IC、负控(因子取 10 分钟前)
  B           五分组最高 − 最低的 H_1 / H_10(bp);基线 obi_l1 × s
  C           逐天 IC 与合并 IC;对 rv_ewm_10s 的增量(两者秩次回归后的残差秩相关);前一可用日常数 σ 只有合并 IC(同一天内是常数)
输出   data/factors/reeval/评估_<样本>.txt、.csv
用法   Python314/python.exe scripts/research7/factor_reeval_eval.py
"""
import glob
import gzip
import json
import os
import sys

import numpy as np
import pandas as pd

np.seterr(all="ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GRID = os.path.join(ROOT, "data", "factors", "grid")
RE = os.path.join(ROOT, "data", "factors", "reeval")
TOX1 = os.path.join(ROOT, "data", "factors", "tox1")
STEP = 10_000_000
SYMS = {"BTC": ("XBTUSDTM", 0), "ETH": ("ETHUSDTM", 1)}
TAU_A = (0.01, 0.02, 0.05, 0.1, 0.2, 0.3, 0.5, 1, 2, 3, 5, 10, 20, 30, 60)
TAU_B = (0.1, 0.3, 1, 3, 10, 30, 60)
TAU_C = (0.1, 0.3, 1, 3, 10)
BT_DAYS = ("20260827", "20260828", "20260829", "20260830", "20260831", "20260901", "20260917", "20260918", "20260923", "20260924")
LIVE_INST = {"MmAsBtc-bc24ee34": "BTC", "MmAsEth-1be9e2b6": "ETH"}
SEEN = {"20260918": "找因子用过的日子(用户 10-14)"}


def rank(x):
    return pd.Series(x).rank().to_numpy()


def sic(x, y, nmin=30):
    m = np.isfinite(x) & np.isfinite(y)
    if m.sum() < nmin or np.nanstd(x[m]) == 0 or np.nanstd(y[m]) == 0:
        return np.nan
    return float(np.corrcoef(rank(x[m]), rank(y[m]))[0, 1])


# ---------------------------------------------------------------------------------------------------
# 数据
# ---------------------------------------------------------------------------------------------------
def grid_mid(day, nat):
    z = np.load(os.path.join(GRID, "%s_%s.npz" % (nat, day)))
    ok = z["ok"] & (z["ap"] > z["bp"])
    m = pd.Series(np.where(ok, (z["bp"].astype(float) + z["ap"]) / 2.0 * float(z["tick"]), np.nan)).ffill().to_numpy()
    return int(z["t0"]), m


def rv_feats(mid):
    """策略第 8 步原式:r = 10 毫秒对数变动(bp);RV1 = 最近 100 个 r² 之和开方;rv_ewm_10s = RV1 的指数平均(半衰期 1000 格)。"""
    r = np.zeros(len(mid))
    r[1:] = 1e4 * np.diff(np.log(mid))
    r = np.nan_to_num(r)
    cs = np.cumsum(r * r)
    rs = cs.copy()
    rs[100:] = cs[100:] - cs[:-100]
    rv1 = np.sqrt(np.maximum(rs, 0))
    from scipy.signal import lfilter
    d = 0.5 ** (1 / 1000)
    ew = lfilter([1 - d], [1, -d], rv1, zi=[d * rv1[0]])[0]
    ew[:1000] = np.nan
    return rv1, ew, cs


def bt_fills():
    f = pd.read_parquet(os.path.join(ROOT, "RDAgent_Factor", "Inventory", "第三轮_实盘组持仓路径", "fills.parquet"))
    f = f.assign(s=np.where(f["side"] == "buy", 1.0, -1.0), day=f["day"].astype(str))
    return f[["symbol", "day", "hour", "ts_ns", "s", "qty", "px", "pos_after"]].assign(maker=True)


def live_fills():
    cache = os.path.join(RE, "live_fills_20261014.parquet")
    if os.path.exists(cache):
        return pd.read_parquet(cache)
    oid, rows = {}, []
    with gzip.open(os.path.join(ROOT, "data", "research7", "live_orders_20261014.jsonl.gz"), "rt", encoding="utf-8") as fh:
        for l in fh:
            if '"Order"' not in l[:200] and '"Fill"' not in l[:200]:
                continue
            r = json.loads(l)
            o = r["obj"]
            if r["msg_type"] == "Order" and o.get("strategy_id") in LIVE_INST:
                oid[o["order_id"]] = LIVE_INST[o["strategy_id"]]
            elif r["msg_type"] == "Fill" and o["symbol"] in ("BTC-USDT", "ETH-USDT"):
                sym = o["symbol"][:3]
                if o["order_id"] in oid or not o.get("is_maker"):   # 策略单 + 手动平仓(非挂单)都算进持仓;只有策略挂单进 A 的样本
                    rows.append((sym, "20261014", int(o["ts_ns"]), 1.0 if o["side"] == "buy" else -1.0, float(o["quantity"]), float(o["price"]),
                                 bool(o.get("is_maker")) and o["order_id"] in oid))
    f = pd.DataFrame(rows, columns=["symbol", "day", "ts_ns", "s", "qty", "px", "maker"]).sort_values("ts_ns")
    f["pos_after"] = f.groupby("symbol")["s"].transform(lambda s: 0) + (f["s"] * f["qty"]).groupby(f["symbol"]).cumsum()
    f["hour"] = (f["ts_ns"] // 3_600_000_000_000) % 24
    os.makedirs(RE, exist_ok=True)
    f.to_parquet(cache)
    return f


def factor_names(day):
    z = np.load(os.path.join(RE, "%s.npz" % day))
    names = list(z.files)
    t = np.load(os.path.join(TOX1, "%s.npz" % day))
    names += [n for n in t.files if n.startswith(("tox_bnpush_", "tox_bnunmatched_", "tox_deepecho_"))]
    p6 = os.path.join(RE, "%s_inv6.npz" % day)                     # 库存一轮补算的 6 个(pandas 3 只读数组问题)
    if os.path.exists(p6):
        names += list(np.load(p6).files)
    return sorted(set(names))


def load_factor(day, name):
    p = os.path.join(RE, "%s.npz" % day)
    z = np.load(p)
    if name in z.files:
        return z[name]
    p6 = os.path.join(RE, "%s_inv6.npz" % day)
    if os.path.exists(p6) and name in np.load(p6).files:
        return np.load(p6)[name]
    return np.load(os.path.join(TOX1, "%s.npz" % day))[name]


def groups(names):
    """把因子名归成 (显示名, 种类, 部件):种类 side = 侧别对(_ask/_bid);pos = 库存对(_long/_short);dir = 方向因子;flat = 非方向。"""
    out, seen = [], set()
    for n in names:
        if n.endswith(("_ask", "_bid")):
            b = n[:-4]
            if b not in seen:
                seen.add(b)
                out.append((b, "side", (b + "_ask", b + "_bid")))
        elif n.endswith(("_long", "_short")):
            b = n.rsplit("_", 1)[0]
            if b not in seen:
                seen.add(b)
                out.append((b, "pos", (b + "_long", b + "_short")))
        elif n == "wid_depletion_jump":
            out.append((n, "flat", (n,)))
        else:
            out.append((n, "dir", (n,)))
    return out


def pick(kind, parts, vals, s):
    """按成交 / 仓位方向 s 取因子值。vals = {部件名: 数组}。"""
    if kind == "side":                                             # 买单成交 / 多仓 → 怕买盘被扫 → _bid
        return np.where(s > 0, vals[parts[1]], vals[parts[0]])
    if kind == "pos":
        return np.where(s > 0, vals[parts[0]], vals[parts[1]])
    if kind == "dir":
        return s * vals[parts[0]]
    return vals[parts[0]]


def toxic_high(kind):
    return kind in ("side", "flat")                                # 侧别毒性与非方向:值高 = 毒;方向 × s、库存对:值低 = 毒


# ---------------------------------------------------------------------------------------------------
# B2 挂单出货(用户 10-15:"成交后用因子决定平仓单挂多近,全都用挂单,不用吃单")
#   有仓位的时刻 t,在减仓方向挂一张平仓单:多仓 = 卖单挂在 卖一 + d 跳,空仓 = 买单挂在 买一 − d 跳(d = 0 即跟最优价同价)。
#   成交判定(保守,只用 L2 + 逐笔):t 之后同方向的吃单打到比挂价更深的价位,或在挂价上成交的量超过 t 时刻该价位已有的量
#   (假设排在该价位队尾、前面的单不撤)。最多看 10 秒。
#   报两样:成交要等多久(第一次满足条件的时刻 u − t);成交质量 = 平仓价相对 u + 1 秒中间价(按平仓方向,bp)+ 返佣 我方费率
#   ——正 = 卖出后价格回落(多仓)/ 买回后价格回升(空仓);负 = 平仓之后价格继续往原仓位有利的方向走。
#   (10-16 改:原先拿"挂平仓单"和"继续拿着"比,但继续拿着的仓位将来也要平,这笔成本没算,比较偏向"不挂近"。)
# ---------------------------------------------------------------------------------------------------
EXIT_D = (0, 1, 2, 3, 5, 10)
EXIT_TMAX = 10.0
REBATE_BP = OUR_FEE


def _sparse_max(a):
    t = [a]
    k = 1
    while (1 << k) <= len(a):
        p = t[-1]
        h = 1 << (k - 1)
        t.append(np.maximum(p[:-h], p[h:]))
        k += 1
    return t


def _first_above(tab, key, i0, thr):
    """从 i0 起第一个 key > thr 的下标(没有则 len)。tab = key 的稀疏最大值表。"""
    n = len(key)
    pos = i0.copy()
    for k in range(len(tab) - 1, -1, -1):
        step = 1 << k
        ok = pos + step <= n
        cand = np.where(ok, pos, 0)
        can = ok & (tab[k][np.minimum(cand, len(tab[k]) - 1)] <= thr)
        pos = np.where(can, pos + step, pos)
    return pos


def exit_sim(day, nat, t0, z, rB, sB, mid):
    """返回 {("wait", d): 等待秒数(10 秒内没成交 = nan), ("qual", d): 成交质量 bp}。z = 网格(单位:跳 / 张)。"""
    ev = np.load(os.path.join(ROOT, "data", "research7", "l2", "%s_%s.npz" % (nat, day)))
    tr = ev["kind"] == 0
    tts, tsd, ttk, tsz = ev["ts"][tr], ev["side"][tr], ev["tick"][tr].astype(np.int64), ev["size"][tr].astype(float)
    tick = float(z["tick"])
    n = len(mid)
    t_s = t0 + rB.astype(np.int64) * STEP
    out = {}
    for d in EXIT_D:
        out[("wait", d)] = np.full(len(rB), np.nan)
        out[("qual", d)] = np.full(len(rB), np.nan)
    BIG = np.iinfo(np.int64).max
    for sign, side_hit in ((1.0, 1), (-1.0, 0)):                  # 多仓:主动买打卖盘(side = 1);空仓:主动卖打买盘(side = 0)
        sel = np.flatnonzero(sB == sign)
        if len(sel) == 0:
            continue
        m = tsd == side_hit
        ts_, tk_, sz_ = tts[m], ttk[m], tsz[m]
        if len(ts_) == 0:
            continue
        key = (tk_ if sign > 0 else -tk_).astype(float)           # 统一成"找更大的 key"
        tab = _sparse_max(key)
        rr = rB[sel]
        tt = t_s[sel]
        best = z["ap"][rr].astype(np.int64) if sign > 0 else z["bp"][rr].astype(np.int64)
        offs = z["ao"][rr] if sign > 0 else z["bo"][rr]
        sizes = z["as_"][rr] if sign > 0 else z["bs"][rr]
        i0 = np.searchsorted(ts_, tt, side="right")
        order = np.lexsort((ts_, tk_))
        tk_s, ts_s, cs = tk_[order], ts_[order], np.cumsum(sz_[order])
        for d in EXIT_D:
            L = best + d if sign > 0 else best - d
            Q = np.zeros(len(rr))
            for k in range(offs.shape[1]):
                hit = offs[:, k] == d
                Q[hit] = sizes[hit, k]
            jj = _first_above(tab, key, i0, (L if sign > 0 else -L).astype(float))
            u_thr = np.where(jj < len(ts_), ts_[np.minimum(jj, len(ts_) - 1)], BIG)
            lo = np.searchsorted(tk_s, L, side="left")
            hi = np.searchsorted(tk_s, L, side="right")
            u_vol = np.full(len(rr), BIG)
            for i in np.flatnonzero(hi > lo):
                a = lo[i] + np.searchsorted(ts_s[lo[i]:hi[i]], tt[i], side="right")
                cprev = cs[a - 1] if a > 0 else 0.0
                b = np.searchsorted(cs[a:hi[i]], cprev + Q[i], side="right") + a     # 累计量第一次超过 Q 的那一笔
                if b < hi[i]:
                    u_vol[i] = ts_s[b]
            u = np.minimum(u_thr, u_vol)
            ok = u <= tt + int(EXIT_TMAX * 1e9)
            wait = np.where(ok, (np.where(ok, u, tt) - tt) / 1e9, np.nan)
            k1 = np.minimum(((np.where(ok, u, tt) + 10**9 - t0) // STEP).astype(np.int64), n - 1)
            qual = np.where(ok, sign * (L * tick - mid[k1]) / mid[k1] * 1e4 + REBATE_BP, np.nan)
            out[("wait", d)][sel] = wait
            out[("qual", d)][sel] = qual
    return out

def build(sample, fills):
    A, B, C = [], [], []
    for day in sorted(fills["day"].unique()):
        names = factor_names(day)
        G = groups(names)
        for sym, (nat, j) in SYMS.items():
            t0, mid = grid_mid(day, nat)
            n = len(mid)
            rv1, rvew, cs = rv_feats(mid)
            fall = fills[(fills["symbol"] == sym) & (fills["day"] == day)].sort_values("ts_ns")      # 持仓路径用全天成交(实盘持仓跨 12 时)
            f = fall[(fall["ts_ns"] >= t0 + 5 * 10**9) & (fall["ts_ns"] < t0 + n * STEP)]
            # ---- A:挂单成交 ----
            fa = f[f["maker"]]
            t = fa["ts_ns"].to_numpy()
            s = fa["s"].to_numpy()
            P = fa["px"].to_numpy()
            rows_at = lambda tt, lag_ns: np.ceil((tt - lag_ns - t0) / STEP).astype(np.int64) - 1
            r0 = rows_at(t, 0)
            dA = {"day": day, "sym": sym, "s": s, "notional": fa["qty"].to_numpy() * P}
            for tau in TAU_A:
                k = ((t + int(tau * 1e9) - t0) // STEP).astype(np.int64)
                dA["M_%g" % tau] = np.where(k < n, s * (mid[np.minimum(k, n - 1)] - P) / P * 1e4, np.nan)
            ok_r = lambda r: (r >= 0) & (r < n)
            for lag in (0, 20, 50):
                r = rows_at(t, lag * 1_000_000)
                dA["rv_ewm_10s|%d" % lag] = np.where(ok_r(r), rvew[np.clip(r, 0, n - 1)], np.nan)
                dA["RV1|%d" % lag] = np.where(ok_r(r), rv1[np.clip(r, 0, n - 1)], np.nan)
            # ---- B:持仓时刻(每 1 秒)----
            grid_t = t0 + np.arange(5 * 100, n, 100, dtype=np.int64) * STEP     # 每 1 秒一个点(网格行时刻)
            ft, pa = fall["ts_ns"].to_numpy(), fall["pos_after"].to_numpy()
            fh = fall["hour"].to_numpy()
            idx = np.searchsorted(ft, grid_t, side="right") - 1
            pos = np.where(idx >= 0, pa[np.clip(idx, 0, None)], 0.0)
            if sample == "bt":                                     # 回测每个整点从空仓开始
                same_h = (idx >= 0) & (fh[np.clip(idx, 0, None)] == (grid_t // 3_600_000_000_000) % 24)
                pos = np.where(same_h, pos, 0.0)
            hold = np.abs(pos) > 1e-12
            gB = grid_t[hold]
            sB = np.sign(pos[hold])
            rB = ((gB - t0) // STEP).astype(np.int64)
            dB = {"day": day, "sym": sym, "s": sB}
            for tau in TAU_B:
                k = rB + int(round(tau * 100))
                dB["H_%g" % tau] = np.where(k < n, sB * (mid[np.minimum(k, n - 1)] - mid[rB]) / mid[rB] * 1e4, np.nan)
            dB["rv_ewm_10s|0"] = rvew[rB - 1]
            zg = np.load(os.path.join(GRID, "%s_%s.npz" % (nat, day)))
            ex = exit_sim(day, nat, t0, zg, rB, sB, mid)
            for (kind_, dd), v in ex.items():
                dB["EX%s_%d" % ("W" if kind_ == "wait" else "Q", dd)] = v
            # ---- C:全部时刻(每 1 秒)----
            rC = ((grid_t - t0) // STEP).astype(np.int64)
            dC = {"day": day, "sym": sym}
            for tau in TAU_C:
                k = rC + int(round(tau * 100))
                dC["RV_%g" % tau] = np.where(k < n, cs[np.minimum(k, n - 1)] - cs[rC], np.nan)
            dC["rv_ewm_10s"] = rvew[rC - 1]
            dC["RV1"] = rv1[rC - 1]
            # ---- 因子 ----
            for gname, kind, parts in G:
                vals = {}
                for p in parts:
                    try:
                        vals[p] = load_factor(day, p)[:, j].astype(float)
                    except KeyError:
                        vals = None
                        break
                if vals is None:
                    continue
                for lag in (0, 20, 50):
                    r = rows_at(t, lag * 1_000_000)
                    v = {p: np.where(ok_r(r), a[np.clip(r, 0, n - 1)], np.nan) for p, a in vals.items()}
                    dA["%s|%d" % (gname, lag)] = pick(kind, parts, v, s)
                rn = r0 - 60_000                                   # 负控:10 分钟前的因子值
                v = {p: np.where(ok_r(rn), a[np.clip(rn, 0, n - 1)], np.nan) for p, a in vals.items()}
                dA["%s|neg" % gname] = pick(kind, parts, v, s)
                v = {p: a[rB - 1] for p, a in vals.items()}
                dB["%s|0" % gname] = pick(kind, parts, v, sB)
                v = {p: a[rC - 1] for p, a in vals.items()}
                dC[gname] = sum(v.values()) if kind == "side" else (np.abs(v[parts[0]]) if kind in ("dir", "pos") else v[parts[0]])   # 库存对 short = −long,取绝对值
            A.append(pd.DataFrame(dA))
            B.append(pd.DataFrame(dB))
            C.append(pd.DataFrame(dC))
            print("  %s %s %s:挂单成交 %d 笔,持仓取样 %d 个,全部取样 %d 个" % (sample, day, sym, len(fa), len(gB), len(rC)), flush=True)
    return pd.concat(A, ignore_index=True), pd.concat(B, ignore_index=True), pd.concat(C, ignore_index=True), G


# ---------------------------------------------------------------------------------------------------
# 指标
# ---------------------------------------------------------------------------------------------------
def by_day_ic(df, x, y):
    v = [sic(g[x].to_numpy(), g[y].to_numpy()) for _, g in df.groupby("day")]
    v = np.array([a for a in v if np.isfinite(a)])
    if len(v) == 0:
        return np.nan, np.nan, 0
    t = v.mean() / v.std(ddof=1) * np.sqrt(len(v)) if len(v) > 1 and v.std(ddof=1) > 0 else np.nan
    return float(v.mean()), float(t), len(v)


def half_life(taus, ics):
    a = np.abs(np.asarray(ics, float))
    if not np.isfinite(a).any():
        return np.nan, np.nan, np.nan
    k = int(np.nanargmax(a))
    pk = a[k]
    for i in range(k + 1, len(taus)):
        if a[i] <= pk / 2:
            x0, x1 = np.log(taus[i - 1]), np.log(taus[i])
            w = (a[i - 1] - pk / 2) / (a[i - 1] - a[i]) if a[i - 1] != a[i] else 0
            return taus[k], float(np.sign(ics[k]) * pk), float(np.exp(x0 + w * (x1 - x0)))
    return taus[k], float(np.sign(ics[k]) * pk), np.inf


def eval_A(A, G, dir_from=None):
    """dir_from:{(sym, 因子): +1 / −1} = 值高的成交更好(+1)还是更坏(−1);给了就直接用(实盘用回测定的方向),
    没给就两折:一半天上按 M_1 的逐天 IC(延迟 20 毫秒)定方向,另一半天上去掉最坏的 20% 评改善。"""
    out = []
    feats = [("rv_ewm_10s", "flat"), ("RV1", "flat")] + [(g, k) for g, k, _ in G]
    for sym, d in A.groupby("sym"):
        d = d.reset_index(drop=True)
        days = sorted(d["day"].unique())
        folds = [days[0::2], days[1::2]]
        for name, kind in feats:
            c0, c20 = "%s|0" % name, "%s|20" % name
            if c0 not in d:
                continue
            ics = [by_day_ic(d, c0, "M_%g" % tau)[0] for tau in TAU_A]
            pk_tau, pk, hl = half_life(TAU_A, ics)
            ics20 = [by_day_ic(d, c20, "M_%g" % tau)[0] for tau in TAU_A]
            pk20_tau, pk20, hl20 = half_life(TAU_A, ics20)
            ic1, t1, nd = by_day_ic(d, c0, "M_1")
            ic20, t20, _ = by_day_ic(d, c20, "M_1")
            row = dict(sym=sym, factor=name, kind=kind, n=int(d[c0].notna().sum()), days=nd, ic_1s=ic1, t_1s=t1, ic20_1s=ic20, t20_1s=t20,
                       ic20_0_1=by_day_ic(d, c20, "M_0.1")[0], ic20_3=by_day_ic(d, c20, "M_3")[0],
                       ic_1s_lag50=by_day_ic(d, "%s|50" % name, "M_1")[0],
                       ic_neg=by_day_ic(d, "%s|neg" % name, "M_1")[0] if "%s|neg" % name in d else np.nan,
                       peak_tau=pk_tau, peak_ic=pk, half_life=hl, peak20_tau=pk20_tau, peak20_ic=pk20, half_life20=hl20,
                       dir_all=float(np.sign(ic20)) if np.isfinite(ic20) else np.nan)
            x = d[c20].to_numpy()
            m = np.isfinite(x)
            w = d["notional"].to_numpy()
            if m.sum() < 50:
                out.append(row)
                continue
            plans = []
            if dir_from is not None:
                sg = dir_from.get((sym, name), np.nan)
                if np.isfinite(sg) and sg != 0:
                    plans.append((sg, np.ones(len(d), bool)))
            else:
                for k in range(2):
                    tr_ = d["day"].isin(folds[k])
                    ic_tr = by_day_ic(d[tr_], c20, "M_1")[0]
                    if np.isfinite(ic_tr) and ic_tr != 0:
                        plans.append((np.sign(ic_tr), d["day"].isin(folds[1 - k]).to_numpy()))
            gains = {0.1: [], 1: [], 3: []}
            removed, signs = [], []
            for sg, te in plans:
                bad = np.zeros(len(d), bool)
                for _, g in d[m & te].groupby("day"):
                    xv = g[c20].to_numpy()
                    sel = (xv <= np.nanquantile(xv, 0.2)) if sg > 0 else (xv >= np.nanquantile(xv, 0.8))
                    bad[g.index[sel]] = True
                use = m & te
                keep = use & ~bad
                for tau in gains:
                    y = d["M_%g" % tau].to_numpy()
                    ok = np.isfinite(y)
                    if w[keep & ok].sum() > 0 and w[use & ok].sum() > 0:
                        gains[tau].append(np.average(y[keep & ok], weights=w[keep & ok]) - np.average(y[use & ok], weights=w[use & ok]))
                removed.append(w[bad].sum() / max(w[use].sum(), 1e-9))
                signs.append(sg)
            for tau, v in gains.items():
                row["gain_%g" % tau] = float(np.mean(v)) if v else np.nan
            row["vol_removed"] = float(np.mean(removed)) if removed else np.nan
            row["dir"] = "/".join("高好" if sg > 0 else "高坏" for sg in signs)
            out.append(row)
    return pd.DataFrame(out)

def eval_B(B, G):
    out = []
    feats = [("rv_ewm_10s", "flat")] + [(g, k) for g, k, _ in G]
    for sym, d in B.groupby("sym"):
        for name, kind in feats:
            c0 = "%s|0" % name
            if c0 not in d:
                continue
            ics = [by_day_ic(d, c0, "H_%g" % tau)[0] for tau in TAU_B]
            pk_tau, pk, hl = half_life(TAU_B, ics)
            ic1, t1, nd = by_day_ic(d, c0, "H_1")
            row = dict(sym=sym, factor=name, kind=kind, n=int(d[c0].notna().sum()), days=nd, ic_1s=ic1, t_1s=t1,
                       peak_tau=pk_tau, peak_ic=pk, half_life=hl)
            for tau in TAU_B:
                row["ic_%g" % tau] = ics[TAU_B.index(tau)]
            for tau in (1, 10):                                     # 五分组:逐天分组,最高组 − 最低组
                sp = []
                for _, g in d.groupby("day"):
                    x, y = g[c0].to_numpy(), g["H_%g" % tau].to_numpy()
                    m = np.isfinite(x) & np.isfinite(y)
                    if m.sum() < 100:
                        continue
                    q = pd.qcut(pd.Series(x[m]).rank(method="first").to_numpy(), 5, labels=False)
                    sp.append(y[m][q == 4].mean() - y[m][q == 0].mean())
                row["q5_q1_%g" % tau] = float(np.mean(sp)) if sp else np.nan
            out.append(row)
    return pd.DataFrame(out)


def eval_B2(B, G):
    """基准:不看因子,各个 d 的 1 / 3 / 10 秒内成交率、等待中位数、成交质量。
    因子:逐天五分组,比较最高组和最低组在 d = 0 和 d = 2 的 3 秒成交率与成交质量;再报"按组选 d"——两折:一半天上每组选
    3 秒得分(3 秒内成交算成交质量、没成交算 0)最大的 d,另一半天上评,和所有组都用同一个 d 比。"""
    rows, base = [], []
    feats = [("rv_ewm_10s", "flat")] + [(g, k) for g, k, _ in G]
    for sym, d in B.groupby("sym"):
        d = d.reset_index(drop=True)
        days = sorted(d["day"].unique())
        for dd in EXIT_D:
            wt, q = d["EXW_%d" % dd].to_numpy(), d["EXQ_%d" % dd].to_numpy()
            base.append(dict(sym=sym, d=dd, fill1=np.mean(wt <= 1), fill3=np.mean(wt <= 3), fill10=np.mean(np.isfinite(wt)),
                             wait_med=np.nanmedian(wt), qual=np.nanmean(q), score3=np.nanmean(np.where(wt <= 3, q, 0.0))))
        S = np.column_stack([np.where(d["EXW_%d" % dd].to_numpy() <= 3, d["EXQ_%d" % dd].to_numpy(), 0.0) for dd in EXIT_D])
        folds = [days[0::2], days[1::2]]
        for name, kind in feats:
            c0 = "%s|0" % name
            if c0 not in d or d[c0].notna().sum() < 1000:
                continue
            q = np.full(len(d), -1)
            for _, g in d.groupby("day"):
                x = g[c0].to_numpy()
                mm = np.isfinite(x)
                if mm.sum() >= 100:
                    q[g.index[mm]] = pd.qcut(pd.Series(x[mm]).rank(method="first").to_numpy(), 5, labels=False)
            row = dict(sym=sym, factor=name, kind=kind)
            for dd in (0, 2):
                wt, qq = d["EXW_%d" % dd].to_numpy(), d["EXQ_%d" % dd].to_numpy()
                for gq, tag in ((0, "lo"), (4, "hi")):
                    sel = q == gq
                    row["fill3_d%d_%s" % (dd, tag)] = np.mean(wt[sel] <= 3) if sel.any() else np.nan
                    row["qual_d%d_%s" % (dd, tag)] = np.nanmean(qq[sel]) if sel.any() else np.nan
            gains, picks = [], []
            if len(days) >= 2:
                for k in range(2):
                    tr_ = d["day"].isin(folds[k]).to_numpy() & (q >= 0)
                    te = d["day"].isin(folds[1 - k]).to_numpy() & (q >= 0)
                    if tr_.sum() == 0 or te.sum() == 0:
                        continue
                    fixed = int(np.argmax(S[tr_].mean(axis=0)))
                    best_q = np.array([int(np.argmax(S[tr_ & (q == g)].mean(axis=0))) for g in range(5)])
                    ti = np.flatnonzero(te)
                    gains.append(S[ti, best_q[q[ti]]].mean() - S[te, fixed].mean())
                    picks.append("/".join(str(EXIT_D[b]) for b in best_q) + "(统一 %d)" % EXIT_D[fixed])
            row["gain"] = float(np.mean(gains)) if gains else np.nan
            row["picks"] = " | ".join(picks)
            rows.append(row)
    return pd.DataFrame(base), pd.DataFrame(rows)

def eval_C(C, G, prev_sigma):
    out = []
    feats = ["rv_ewm_10s", "RV1"] + [g for g, _, _ in G]
    for sym, d in C.groupby("sym"):
        d = d.copy()
        d["sigma_prev"] = d["day"].map(lambda x: prev_sigma.get((sym, x), np.nan))
        base = d["rv_ewm_10s"].to_numpy()
        for name in feats + ["sigma_prev"]:
            if name not in d:
                continue
            ics = [by_day_ic(d, name, "RV_%g" % tau)[0] for tau in TAU_C]
            pk_tau, pk, hl = half_life(TAU_C, ics)
            row = dict(sym=sym, factor=name, n=int(d[name].notna().sum()), peak_tau=pk_tau, peak_ic=pk, half_life=hl)
            for tau in TAU_C:
                row["ic_%g" % tau] = ics[TAU_C.index(tau)]
                row["pooled_%g" % tau] = sic(d[name].to_numpy(), d["RV_%g" % tau].to_numpy())
            # 对 rv_ewm_10s 的增量:逐天,两者秩次线性回归后的残差秩相关(1 秒)
            inc = []
            for _, g in d.groupby("day"):
                x, b, y = g[name].to_numpy(), g["rv_ewm_10s"].to_numpy(), g["RV_1"].to_numpy()
                m = np.isfinite(x) & np.isfinite(b) & np.isfinite(y)
                if m.sum() < 500 or name in ("rv_ewm_10s",):
                    continue
                rx, rb, ry = rank(x[m]), rank(b[m]), rank(y[m])
                ex = rx - np.polyval(np.polyfit(rb, rx, 1), rb)
                ey = ry - np.polyval(np.polyfit(rb, ry, 1), rb)
                if ex.std() > 0:
                    inc.append(np.corrcoef(ex, ey)[0, 1])
            row["incr_over_rvewm_1s"] = float(np.mean(inc)) if inc else np.nan
            out.append(row)
    return pd.DataFrame(out)


def prev_sigma_map(days):
    allg = sorted({f[-12:-4] for f in os.listdir(GRID) if f.startswith("XBTUSDTM_")})
    res = {}
    for sym, (nat, _) in SYMS.items():
        for d in days:
            prev = [x for x in allg if x < d and x != "20260401"]
            if not prev:
                continue
            t0, m = grid_mid(prev[-1], nat)
            r = 1e4 * np.diff(np.log(m[::100]))
            res[(sym, d)] = float(np.sqrt(np.nanmean(r * r)))       # 前一可用日 12–18 时 1 秒对数变动的均方根(bp/√秒)
    return res


def write(tag, A, B, C, G, dir_from=None):
    ea, eb = eval_A(A, G, dir_from), eval_B(B, G)
    write.last_dir = {(r["sym"], r["factor"]): r["dir_all"] for r in ea.to_dict("records")}
    ec = eval_C(C, G, prev_sigma_map(sorted(C["day"].unique())))
    for nm, df in (("A", ea), ("B", eb), ("C", ec)):
        df.to_csv(os.path.join(RE, "评估_%s_%s.csv" % (tag, nm)), index=False, encoding="utf-8-sig")
    L = []
    P = L.append
    P("样本 %s;A 挂单成交 %s;B 持仓取样 %s;C 全部取样 %s(12–18 时 UTC)" % (tag, dict(A.groupby("sym").size()), dict(B.groupby("sym").size()), dict(C.groupby("sym").size())))
    P("\n== A 成交后毒性 / 躲坏单。IC = 因子 vs 成交后 τ 秒的走势 M_τ(逐天平均;正 = 值高的成交更好)。躲单要来得及撤,主看延迟 20 毫秒的 IC。")
    P("   改善 = 按方向去掉最坏 20% 成交后,留下的每笔(按成交额加权)多挣 bp;方向两折定(一半天定、另一半天评),回测以外的样本用回测定的方向")
    for sym, g in ea.groupby("sym"):
        P("\n[%s]" % sym)
        P("%-34s %5s %7s %6s | %8s %6s %8s %8s %7s %7s | %6s %7s | %6s %6s %6s %5s %s" % ("因子", "种类", "IC1s", "t", "延20IC1s", "t", "延20_0.1s", "延20_3s", "延50ms", "负控",
                                                                                     "峰值τ", "半衰期", "改0.1s", "改1s", "改3s", "去量", "方向"))
        for a in g.reindex(g["ic20_1s"].abs().sort_values(ascending=False).index).to_dict("records"):
            P("%-34s %5s %+7.3f %6.1f | %+8.3f %6.1f %+8.3f %+8.3f %+7.3f %+7.3f | %6g %7.3g | %+6.2f %+6.2f %+6.2f %4.0f%% %s" % (
                a["factor"], a["kind"], a["ic_1s"], a["t_1s"], a["ic20_1s"], a["t20_1s"], a["ic20_0_1"], a["ic20_3"], a["ic_1s_lag50"], a["ic_neg"],
                a["peak20_tau"], a["half_life20"], a.get("gain_0.1", np.nan), a.get("gain_1", np.nan), a.get("gain_3", np.nan),
                100 * a.get("vol_removed", np.nan), a.get("dir", "") if isinstance(a.get("dir", ""), str) else ""))
    P("\n== B 出货(IC = 因子 vs H_τ,逐天平均;正 = 值高时仓位方向接下来更顺。q5−q1 = 五分组最高 − 最低,bp)")
    for sym, g in eb.groupby("sym"):
        P("\n[%s]" % sym)
        P("%-38s %5s %7s %7s %6s %7s %7s | %6s %8s %7s | %8s %7s" % ("因子", "种类", "IC0.1s", "IC1s", "t", "IC10s", "IC60s", "峰值τ", "峰值IC", "半衰期", "q5−q1 1s", "10s"))
        for a in g.reindex(g["ic_1s"].abs().sort_values(ascending=False).index).to_dict("records"):
            P("%-38s %5s %+7.3f %+7.3f %6.1f %+7.3f %+7.3f | %6g %+8.3f %7.3g | %+8.2f %+7.2f" % (
                a["factor"], a["kind"], a["ic_0.1"], a["ic_1s"], a["t_1s"], a["ic_10"], a["ic_60"], a["peak_tau"], a["peak_ic"], a["half_life"], a["q5_q1_1"], a["q5_q1_10"]))
    P("\n== C 波动(IC = 因子 vs 之后 τ 的已实现方差 RV_τ,逐天平均;合并 = 全部天合在一起;增量 = 对 rv_ewm_10s 的残差秩相关,1 秒)")
    for sym, g in ec.groupby("sym"):
        P("\n[%s]" % sym)
        P("%-38s %7s %7s %7s %7s | %7s | %6s %7s %7s" % ("因子", "IC0.1s", "IC1s", "IC10s", "合并1s", "增量1s", "峰值τ", "峰值IC", "半衰期"))
        for a in g.reindex(g["ic_1"].abs().sort_values(ascending=False).index).to_dict("records"):
            P("%-38s %+7.3f %+7.3f %+7.3f %+7.3f | %+7.3f | %6g %+7.3f %7.3g" % (
                a["factor"], a["ic_0.1"], a["ic_1"], a["ic_10"], a["pooled_1"], a["incr_over_rvewm_1s"], a["peak_tau"], a["peak_ic"], a["half_life"]))
    b2base, b2 = eval_B2(B, G)
    b2base.to_csv(os.path.join(RE, "评估_%s_B2基准.csv" % tag), index=False, encoding="utf-8-sig")
    b2.to_csv(os.path.join(RE, "评估_%s_B2.csv" % tag), index=False, encoding="utf-8-sig")
    P("\n== B2 挂单出货(全用挂单)。平仓单挂在最优价后 d 跳:成交率、等待中位数(秒)、成交质量(平仓价相对成交后 1 秒中间价 + 返佣,bp;正 = 平得好)、")
    P("   3 秒得分 = 3 秒内成交才算、成交算成交质量、没成交算 0 的期望(bp / 持仓时刻)")
    for sym, g in b2base.groupby("sym"):
        P("\n[%s]  %4s %7s %7s %7s %8s %8s %8s" % (sym, "d", "1秒成交", "3秒成交", "10秒成交", "等待中位", "成交质量", "3秒得分"))
        for a in g.to_dict("records"):
            P("       %4d %6.0f%% %6.0f%% %6.0f%% %8.2f %+8.2f %+8.3f" % (a["d"], 100 * a["fill1"], 100 * a["fill3"], 100 * a["fill10"], a["wait_med"], a["qual"], a["score3"]))
    P("\n   因子五分组:最低组 / 最高组在 d = 0 的 3 秒成交率与成交质量;按组选 d(两折样本外)相对统一 d 的 3 秒得分改善(bp / 持仓时刻)")
    for sym, g in b2.groupby("sym"):
        P("\n[%s]" % sym)
        P("%-34s %5s | %8s %8s %8s %8s | %8s %8s | %8s  %s" % ("因子", "种类", "低组成交", "高组成交", "低组质量", "高组质量", "d2低质量", "d2高质量", "按组选d", "各组选的 d(因子从低到高)"))
        for a in g.reindex(g["gain"].sort_values(ascending=False).index).to_dict("records"):
            P("%-34s %5s | %7.0f%% %7.0f%% %+8.2f %+8.2f | %+8.2f %+8.2f | %+8.3f  %s" % (a["factor"], a["kind"], 100 * a["fill3_d0_lo"], 100 * a["fill3_d0_hi"],
                                                                                 a["qual_d0_lo"], a["qual_d0_hi"], a["qual_d2_lo"], a["qual_d2_hi"], a["gain"], a["picks"]))
    open(os.path.join(RE, "评估_%s.txt" % tag), "w", encoding="utf-8").write("\n".join(L))
    print("\n".join(L), flush=True)


if __name__ == "__main__":
    done = {os.path.basename(f)[:8] for f in glob.glob(os.path.join(RE, "2026????.npz"))}
    bt = bt_fills()
    bt = bt[bt["day"].isin(done)]
    if len(bt):
        A, B, C, G = build("bt", bt)
        write("回测十天", A, B, C, G)
    if "20261014" in done:
        lv = live_fills()
        A, B, C, G = build("live", lv)
        write("实盘1014", A, B, C, G, getattr(write, "last_dir", None))
    print("REEVAL_EVAL_DONE", flush=True)
