r"""Step 1 单测:合成 ladder 数据上检查 (1) 到达指标是"有无"不是笔数;(2) MO 归入正确区间、五个 Δt 下笔数守恒;
(3) 边界盘口取的是 ts < t_k 的最后状态(无前视);(4) L2 快照整簿替换;(5) L2 同毫秒成交排在盘口更新前。
运行  .venv\Scripts\python.exe -m pytest tests -q   或直接 python tests/test_step01.py
写法  on_time(now, levels_fn) 模拟引擎 _advance:在应用时间戳 now 的消息之前调用,levels_fn 给的是应用前的盘口。
"""
import os
import sys

import numpy as np

REPRO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPRO, "a"))
sys.path.insert(0, os.path.join(REPRO, "data"))
import events as EV            # noqa: E402
import ladder_store as LS      # noqa: E402
from stream import EVENT, Book # noqa: E402

NS = 1_000_000_000
MS = 1_000_000


def synth_ladder():
    """两秒数据:边界 50 ms 网格;t=0.30 s 有两笔买 MO(13、7 张),t=1.20 s 一笔卖 MO;t=0.9 s 盘口中价变化。"""
    w = LS.LadderWriter("test", "T")
    lv0 = lambda side, n: [(100, 5), (99, 5)][:n] if side == 0 else [(102, 5), (103, 5)][:n]
    lv1 = lambda side, n: [(101, 5), (100, 5)][:n] if side == 0 else [(103, 5), (104, 5)][:n]
    t = 0
    w.on_time(t, lv0)
    for t_ms in range(1, 2001):
        t = t_ms * MS
        w.on_time(t, lv1 if t > 900 * MS else lv0)        # 900 ms 那条消息把盘口改成 lv1:应用前仍是 lv0
        if t_ms == 300:
            w.on_sweep(t, 0, 13, 1, 102, 102, lv0(1, 20))
            w.on_sweep(t + 1, 0, 7, 1, 102, 102, lv0(1, 20))
        if t_ms == 1200:
            w.on_sweep(t, 1, 4, 1, 101, 101, lv1(0, 20))
    d = dict(bnd_ts=np.asarray(w.bnd_ts), bnd_mid2=np.asarray(w.bnd_mid2), sw_ts=np.asarray([s[0] for s in w.sw]),
             sw_side=np.asarray([s[1] for s in w.sw], np.int8), sw_vol=np.asarray([s[2] for s in w.sw]), meta={})
    return d


def test_indicator_and_conservation():
    d = synth_ladder()
    fr = EV.build([d], 1000, t_start=0, t_end=2 * NS)
    assert len(fr) == 2
    assert fr.ind_plus.tolist() == [True, False] and fr.ind_minus.tolist() == [False, True]
    assert fr.n_plus.tolist() == [2, 0] and fr.vol_plus.tolist() == [20, 0]        # 指标是有无;笔数 / 量另记
    tot = {dt: int(EV.build([d], dt, 0, 2 * NS).n_plus.sum() + EV.build([d], dt, 0, 2 * NS).n_minus.sum()) for dt in (100, 250, 500, 1000, 2000)}
    assert set(tot.values()) == {3}
    fr100 = EV.build([d], 100, 0, 2 * NS)
    assert fr100.ind_plus[3] and fr100.n_plus[3] == 2 and fr100.ind_minus[12]        # 0.30 s → 区间 3;1.20 s → 区间 12


def test_boundary_uses_pre_state():
    d = synth_ladder()
    fr = EV.build([d], 100, 0, 2 * NS)
    # 盘口在 t=0.9 s 的消息上变化:边界 0.9 s 的记录应是变化前的状态(mid2 = 100+102 = 202),0.95 s 起才是 101+103 = 204
    k9 = int(np.where(fr.t0 == 900 * MS)[0][0])
    assert fr.mid2[k9] == 202 and fr.mid2[k9 + 1] == 204


def test_l2_snapshot_and_order():
    ev = np.array([(1000 * MS, 0, 0, 100, 5, -1), (1000 * MS, 0, 1, 102, 5, -1),
                   (2000 * MS, 2, -1, 0, 0, -1), (2000 * MS, 0, 0, 99, 7, -1), (2000 * MS, 0, 1, 103, 7, -1)], dtype=EVENT)
    b = Book()
    for e in ev:
        b.apply(e)
    assert b.best(0) == 99 and b.best(1) == 103 and 100 not in b.lv[0]        # 快照清空了旧档
    kinds = np.array([2, 1, 0]); ts = np.array([5, 5, 5])
    order = np.lexsort((-kinds, ts))
    assert kinds[order].tolist() == [2, 1, 0]                                 # 同 ts:快照 → 成交 → 盘口更新


if __name__ == "__main__":
    for f in (test_indicator_and_conservation, test_boundary_uses_pre_state, test_l2_snapshot_and_order):
        f()
        print("ok", f.__name__)
