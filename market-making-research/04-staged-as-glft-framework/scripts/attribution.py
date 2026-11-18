#!/usr/bin/env python3
"""research7 markout 与 P&L 归因。

用途      把策略的每笔成交按提示词 <markout与P&L归因> 的恒等式拆成三项,再加手续费 / 返佣:
              ε·V·(m_T − P) = ε·V·(m_0 − P) + ε·V·(m_h − m_0) + ε·V·(m_T − m_h)
                               价差收益         markout(h)         库存持有
          直接从成交记录和中间价序列计算,不依赖任何模型。
所属阶段  阶段 0(研究基础设施);所有阶段的评估都用它。不属于某个研究模块。
对应公式  不替换报价公式的任何一项;它度量各研究模块的效果(研究一、三 → markout;研究二 → 价差收益与成交量;研究四 → 库存持有)。
变量与 <符号表> 的对应
          eps = ε(买入 +1,卖出 −1);qty = V(BTC);px = P;m0 = m_0;mh[h] = m_h;mT = m_T
m_T 的取法(提示词符号表):这笔成交形成的库存被平掉时刻的中间价;评估截止时仍未平掉的,取截止时刻的中间价。
          "被平掉"按先进先出(FIFO)配对:一笔成交先用来平掉最早的反向库存,剩下的部分才形成新库存。
          平仓的那部分成交自己不形成库存,它的 m_T = 它自己的 m_0(于是它的"库存持有"项 = −markout,两项相消,
          只留下价差收益;全部成交加总后恒等于 已实现盈亏 + 期末持仓按中间价计的浮动盈亏)。
          FIFO 是会计配对约定,不是模型;换成别的配对,三项各自的分摊会变,总和不变。
依据      分解的出处(有效价差 = 已实现价差 + 价格冲击)待文献台账核对后在方法依据记录登记;恒等式本身是代数恒等式。
"""
import collections

import numpy as np

HORIZONS_S = (0.1, 1.0, 10.0, 60.0)   # markout 时间窗(秒)。来源:提示词 <markout与P&L归因>("例如 100 ms、1 s、10 s、60 s")
NS = 1_000_000_000                    # 纳秒 / 秒


def mid_before(bbo_t, bbo_mid, t):
    """t 之前(严格早于 t)最后一次买一卖一变化时的中间价。用作 m_0:吃单到达之前的中间价,不含这笔成交自己造成的变化。
    bbo_t 升序纳秒;bbo_mid 美元;t 纳秒(标量或数组)。只用 t 以前的数据。"""
    i = np.searchsorted(bbo_t, t, side="left") - 1
    return np.where(i >= 0, bbo_mid[np.clip(i, 0, len(bbo_mid) - 1)], np.nan)


def mid_at(bbo_t, bbo_mid, t):
    """t 时刻(含 t)最后一次买一卖一变化时的中间价。用作 m_h、m_T。只用 t 以前(含)的数据。"""
    i = np.searchsorted(bbo_t, t, side="right") - 1
    return np.where(i >= 0, bbo_mid[np.clip(i, 0, len(bbo_mid) - 1)], np.nan)


def fifo_lots(ts, eps, qty):
    """按先进先出把成交拆成"片":每一片要么平掉此前的库存(closing),要么形成新库存(opening)。

    输入  ts[n] 纳秒升序;eps[n] ±1;qty[n] BTC(> 0)。
    输出  list[(成交下标, 片的数量 BTC, 是否形成新库存, 被平掉的时间纳秒或 None)]
          形成新库存的片:被平掉的时间 = 把它平完的那笔反向成交的时间(一片被多笔反向成交分几次平掉时,再拆成多片);
          平仓的片:被平掉的时间 = 它自己的成交时间。
    """
    open_lots = collections.deque()          # [成交下标, 剩余数量]
    pos_sign = 0
    out = []
    pending = {}                             # 成交下标 → 已登记的开仓片在 out 里的位置列表(平掉时回填时间)
    for i in range(len(ts)):
        left = float(qty[i])
        e = int(eps[i])
        # 先平掉反向库存(最早的先平)
        while left > 1e-12 and open_lots and pos_sign == -e:
            j, rem = open_lots[0]
            x = min(rem, left)
            out.append((j, x, True, int(ts[i])))        # 开仓成交 j 的这一片,在 ts[i] 被平掉
            out.append((i, x, False, int(ts[i])))       # 平仓成交 i 的这一片
            left -= x
            if rem - x <= 1e-12:
                open_lots.popleft()
            else:
                open_lots[0][1] = rem - x
        if not open_lots:
            pos_sign = 0
        # 剩下的形成新库存
        if left > 1e-12:
            open_lots.append([i, left])
            pos_sign = e
    for j, rem in open_lots:
        out.append((j, rem, True, None))                # 评估截止时仍未平掉
    return out


def attribute(ts, eps, px, qty, bbo_t, bbo_mid, t_end, fee_bp, horizons_s=HORIZONS_S):
    """逐片归因。

    输入  ts[n] 成交时间(纳秒,升序);eps[n] ±1;px[n] 成交价(美元);qty[n] 数量(BTC);
          bbo_t / bbo_mid 中间价序列(纳秒升序 / 美元);t_end 评估截止时间(纳秒);
          fee_bp 手续费率(bp,成本为正;挂单返佣 我方费率 → 传 −0.7)。
    输出  dict of 数组,每片一行:
          i 成交下标;q 片的数量(BTC);opening 是否形成新库存;
          spread / markout_<h> / hold_<h> / fee / total:美元。恒等式:total = spread + markout_h + hold_h(对每个 h 都成立),
          fee 单列(net = total − fee);notional 美元。
    依赖的假设  中间价序列覆盖 [ts.min, t_end];缺失处结果为 NaN(调用方统计 NaN 的比例)。
    """
    ts, eps, px, qty = (np.asarray(a) for a in (ts, eps, px, qty))
    lots = fifo_lots(ts, eps, qty)
    if not lots:
        return None
    i = np.array([l[0] for l in lots])
    q = np.array([l[1] for l in lots], float)
    opening = np.array([l[2] for l in lots], bool)
    # 被平掉的时间:未平掉的取评估截止时间
    t_close = np.array([t_end if l[3] is None else l[3] for l in lots], np.int64)
    e, p, t = eps[i].astype(float), px[i].astype(float), ts[i].astype(np.int64)
    m0 = mid_before(bbo_t, bbo_mid, t)
    # m_T:开仓片 = 平掉它的那笔成交到达之前的中间价(与那笔平仓成交自己的 m_0 是同一个数,保证加总恒等);
    #      未平掉的 = 截止时刻中间价;平仓片 = 自己的 m_0
    mT = np.where(opening, np.where(t_close >= t_end, mid_at(bbo_t, bbo_mid, t_close), mid_before(bbo_t, bbo_mid, t_close)), m0)
    out = dict(i=i, q=q, opening=opening, t=t, t_close=t_close, eps=e, m0=m0, mT=mT,
               notional=q * p,
               spread=e * q * (m0 - p),
               total=e * q * (mT - p),
               fee=q * p * fee_bp / 1e4)
    for h in horizons_s:
        mh = mid_at(bbo_t, bbo_mid, t + int(h * NS))
        out[f"markout_{h:g}"] = e * q * (mh - m0)
        out[f"hold_{h:g}"] = e * q * (mT - mh)
    return out


def summarize(a, horizons_s=HORIZONS_S, mask=None):
    """把逐片结果汇总成一行:成交额(美元)、各项金额(美元)与各项相对成交额的 bp。mask: 只汇总这些片(布尔数组)。"""
    m = np.ones(len(a["q"]), bool) if mask is None else mask
    nv = float(np.nansum(a["notional"][m]))
    bp = (lambda x: float(np.nansum(x[m])) / nv * 1e4) if nv > 0 else (lambda x: float("nan"))
    row = dict(notional=nv, n_lots=int(m.sum()), spread_usd=float(np.nansum(a["spread"][m])), fee_usd=float(np.nansum(a["fee"][m])),
               total_usd=float(np.nansum(a["total"][m])), spread_bp=bp(a["spread"]), fee_bp=bp(a["fee"]), total_bp=bp(a["total"]))
    row["net_usd"] = row["total_usd"] - row["fee_usd"]
    row["net_bp"] = row["total_bp"] - row["fee_bp"] if nv > 0 else float("nan")
    for h in horizons_s:
        row[f"markout_{h:g}_bp"] = bp(a[f"markout_{h:g}"])
        row[f"hold_{h:g}_bp"] = bp(a[f"hold_{h:g}"])
    return row
