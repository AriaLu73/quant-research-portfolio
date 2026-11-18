# 文献研读:多资产做市闭式解、信号/逆向选择入价、最优执行、波动率估计、Epps 效应、策略评估统计、RL 做市与 LVR(2026-10-01)

原文全部用 pymupdf(Python314\python.exe)逐页提取,PDF 存于 `docs/research3/papers/`。
标注约定:**[原文]** = 论文原话/原式(附式号与页码);**[paper result]** = 作者报告的数字;**[推导]** = 本文对我方情形的推断/计算,非论文结论。
我方条件(全文统一):KuCoin USDT/USDC 永续;maker 返佣 我方费率(USDC 我方费率),taker 我方费率;REST 下单往返 1.9 ms(单程 ≈1 ms),行情单程 ≈2.2 ms;回测按排队最前撮合;Tardis L2 增量 + 成交(无订单 ID);腰部币 tick ≥ 1 bp、点差 1–2 tick;BTC tick ≈ 0.01 bp。

---

## 0. 八条最具决策相关性的发现(速览)

1. **多资产偏斜是协方差驱动、且是"半平方根"形式,不是简单按 Σ 线性偏斜**(A)。Bergault et al. 式(17)–(20):skew_i = −√γ·qᵀΓe_i,Γ = D₊^{-1/2}(D₊^{1/2}ΣD₊^{1/2})^{1/2}D₊^{-1/2},价差半宽 = ½√γ z_i e_iᵀΓe_i + 1/k_i。等流动性下 Γ ∝ Σ^{1/2}/√d;[推导] ρ=0.8 时"别的币库存对本币报价的偏斜"是自身偏斜的 0.50 倍,ρ=0.9 时 0.63 倍。这直接给出 U15 多品种(ETH/SOL/SUI/XRP)库存偏斜的归一化公式与在线标定量(σ_i, ρ_ij, A_i, k_i)。
2. **闭式近似与真最优在 PnL 上几乎无差别**(A,paper result):两资产例子里,真最优 88 600€ ± 86 900,闭式近似 89 000€ ± 87 500(4000 次 MC,p.33)。→ 不需要求解 HJB,闭式 + 在线估计即可;差异只在大库存处。
3. **信号(price reading)和逆向选择进入报价的方式是"一个全局项 + 一个分层项",而且方向相反**(B)。Barzykin et al. 2025 式(12)–(13):全局项 ∝ D±f̂(q) = −(Σ₊^{1,0}/F₊^{2,1})(±q + Δ_k/2)(零库存时**扩价差**,有库存时**加偏斜**);分层项 ∝ ∓q·w·J′/(Δ_k Λ′)(**减偏斜**以少泄露库存)。逆向选择项的符号取决于 β−κ(markout 随报价距离的斜率 vs 强度衰减斜率):慢信号(β<κ)→ 对无毒流反而**收窄**价差;快信号(β>κ,几 bp、速度优势)→ 全面防御。我方对手主要是后者(几 bp 的速度优势型),论文结论是"扩价差 + 防御性偏斜",与"跟单毒单在任何延迟都不赚"的既有结论一致。
4. **标定指引明确:Λ 用条件成交强度曲线,ζ 用"成交后 markout 对报价距离的条件曲线",J′/w 用"偏斜敏感度 / 后续成交方向 / 报价后 markout 恶化"**(B, p.3 原话)。这正是我方缺失的两条曲线:ζ(δ) 与 Λ(δ) 的斜率对比决定报价方向。
5. **对冲/去库存的正确尺度是 Almgren–Chriss 半衰期 θ = 1/κ, κ = √(λσ²/η)**(C, 式(19) p.15),与总时限 T 无关;含漂移时目标持仓 x̄ = α/(2λσ²)(式(25) p.26)。[推导] 我方 hedge_wait_ms/hedge_max_ms 应改成按 θ 归一化(需在线估计临时冲击 η:一次吃单成本随下单速率的斜率),而不是固定毫秒。
6. **波动率估计器:HAR-RV 三尺度回归、双幂变差去跳、GARCH(1,1) 三者的公式与作者数字均已核对**(D)。BNS:μ₁^{-2}Σ|y_j||y_{j+1}| →∫σ²(μ₁ = √(2/π)),RV − BPV → 跳跃平方和;跳跃检验统计量式(26) p.32,美元/马克 5 分钟数据在 5% 水平 21.5% 的天数拒绝"无跳"(Table 4 p.33)。HAR 系数(USD/CHF)β_d=0.352, β_w=0.323, β_m=0.235(Table 2 p.187)。[推导] 我方 vol_ms=500 的 amove 是"含跳的 RV";报价缓冲应分开用 BPV(连续部分)与 RV−BPV(跳跃部分,对应逆向选择/撤单风险)。
7. **在 ~30 个小时观测上比较 ~5 个参数变体,统计上几乎不可能分出优劣**(F)。Lo 式(9):SE(SR_h) = √((1+SR²/2)/T),T=30 时 SE≈0.18(小时 SR 单位);DSR 的 5 次独立试验期望最大值 ≈1.19σ_trials;[推导] 若各变体 SR 的离散 σ=0.1,则 SR₀≈0.12,要 DSR≥0.95 需要小时 SR ≥0.44,或在 SR=0.2 时需 T≥432 小时(18 天)。PBO/CSCV 对 N=5 太粗(论文 p.22 要求 N≫10)。**唯一可行的做法是配对差分 + 事先注册的选择规则 + 更长样本**,不是多跑变体。
8. **RL 做市的可用经验只有两条:奖励里的库存项必须非对称阻尼(η≈0.1 起策略从"持仓投机"切换到"近零库存"),市场状态变量直接进状态空间会发散**(G)。Spooner Table 6:合并代理 HSBA.L 15.43±13.01(归一化日 PnL ×10⁴)vs 固定价差 2.80±10.30,均绝对仓位 104 vs 2678。LVR(Milionis):ℓ = σ²P²|x*′(P)|/2,CPMM 每天损失 σ²/8(日波动 5% → 3.125 bp/天),99.991% 的 LP PnL 方差是 β;→ 对我方的意义只是"逆向选择损失 ∝ 方差 × 边际流动性",与 Budish 的 sniping 同源。

---

## 0.1 获取情况

| 编号 | 论文 | 来源 | 文件 | 全文 |
|---|---|---|---|---|
| A | Bergault, Evangelista, Guéant, Vieira (2021) *Closed-form approximations in multi-asset market making*, Applied Math. Finance 28(2):101–142 | arXiv:1810.04383v5 | bergault_evangelista_gueant_vieira2021_multiasset_mm.pdf(36 页) | 是 |
| B | Barzykin, Bergault, Guéant, Lemmel (2025) *Optimal quoting under adverse selection and price reading*(Risk Cutting Edge 2026 缩版) | arXiv:2508.20225v6 | barzykin_bergault_gueant_lemmel2025_adverse_selection_price_reading.pdf(23 页) | 是 |
| C | Almgren & Chriss (2000) *Optimal execution of portfolio transactions*, J. Risk 3:5–39 | smallake.kr 镜像的作者 2000-12 稿(optliq.pdf) | almgren_chriss2000_optimal_execution.pdf(42 页) | 是 |
| D1 | Corsi (2009) *A simple approximate long-memory model of realized volatility*, J. Financial Econometrics 7(2):174–196 | statmath.wu.ac.at 课程镜像(期刊版) | corsi2009_har_rv.pdf(23 页) | 是 |
| D2 | Barndorff-Nielsen & Shephard (2004) *Power and bipower variation with stochastic volatility and jumps*, J. Financial Econometrics 2(1):1–37 | nuff.ox.ac.uk 2003-11-02 工作稿(eric.pdf);期刊版付费 | barndorff_nielsen_shephard2004_bipower.pdf(39 页) | 是(工作稿) |
| D3 | Bollerslev (1986) *Generalized autoregressive conditional heteroskedasticity*, J. Econometrics 31:307–327 | public.econ.duke.edu/~boller(作者主页) | bollerslev1986_garch.pdf(21 页) | 是 |
| E | Epps (1979) *Comovements in stock prices in the very short run*, JASA 74(366):291–298 | **JSTOR/T&F 付费,未获得原文**;用两篇公开研究替代:Tóth & Kertész (2009) *The Epps effect revisited*, Quant. Finance 9(7):793–802, arXiv:0704.1099;Münnix, Schäfer, Guhr (2010) *Statistical causes for the Epps effect in microstructure noise*, arXiv:1009.6157 | toth_kertesz2009_epps_revisited.pdf;munnix_etal2010_epps_microstructure_noise.pdf | 原文否;替代文献是 |
| F1 | Lo (2002) *The statistics of Sharpe ratios*, FAJ 58(4):36–52 | traders.studentorg.berkeley.edu 镜像(期刊版) | lo2002_statistics_sharpe_ratios.pdf(17 页) | 是 |
| F2 | Bailey & López de Prado (2014) *The deflated Sharpe ratio*, J. Portfolio Mgmt 40(5):94–107 | davidhbailey.com(SSRN 2460551 稿) | bailey_lopezdeprado2014_deflated_sharpe.pdf(22 页);公式页另渲染为图核对 | 是 |
| F3 | Bailey, Borwein, López de Prado, Zhu (2017) *The probability of backtest overfitting*, J. Computational Finance 20(4):39–69 | davidhbailey.com(2015-02 修订稿) | bailey_borwein_lopezdeprado_zhu2017_pbo.pdf(34 页) | 是 |
| F4 | Bergstra & Bengio (2012) *Random search for hyper-parameter optimization*, JMLR 13:281–305 | jmlr.org | bergstra_bengio2012_random_search.pdf(25 页) | 是 |
| G1 | Spooner, Fearnley, Savani, Koukorinis (2018) *Market making via reinforcement learning*, AAMAS 2018 | arXiv:1804.04216 | spooner_etal2018_mm_rl.pdf(10 页) | 是 |
| G2 | Milionis, Moallemi, Roughgarden, Zhang (2022) *Automated market making and loss-versus-rebalancing* | arXiv:2208.06046v6 | milionis_etal2022_lvr.pdf(65 页) | 是 |

已有笔记(research2/normalization_checklist.md、lit_hedging.md、lit_misc.md)覆盖的 Guéant 2017、GLFT、BBG 2106.06974/2112.02269/2404.15478、Budish 2015、Foucault 2017、Aquilina 2022、Moallemi-Sağlam 2013 不重做。

---

## 1. A. Bergault, Evangelista, Guéant, Vieira (2021) — 多资产做市闭式近似

### 1.1 数据/市场背景
纯理论 + 数值。目标市场是**报价驱动的 OTC**(公司债 RFQ、FX RFQ/RFS,p.2)。作者明确说对"点差/tick 比低的订单驱动市场"应使用建模 LOB 的另一类模型(Guilbaud-Pham 等,p.2)。数值例子:两资产,S=100€,μ=(0.1, −0.1)€/day,σ=(1.2, 0.6)€/√day,ρ=0.5,T=7 天,γ=8e−6 €⁻¹,logistic 强度 Λ(δ)=λ_RFQ/(1+e^{α_Λ+β_Λδ}),λ_RFQ=30/day,α_Λ=0.7,β_Λ=30€⁻¹,Gamma 分布请求量(均值 10 000 股≈1M€),风险限额 Q¹=75 000、Q²=300 000(p.25–26)。

### 1.2 机制
Avellaneda–Stoikov 多资产扩展(Guéant 2017)的 HJ 方程 (5) p.6 中 Hamiltonian 项 H^{i,b}(p)+H^{i,a}(−p) 是 U 形,用二次函数替换后 HJ 方程变成 Riccati 型,可闭式求解(Prop.1–2 p.9–10),T→∞ 极限给出仿射于库存的报价(Prop.3 p.12,式(17)–(20) p.15)。再用一阶摄动给出修正项(§4)。§5 扩展到漂移、分层、分布式请求量、固定成本。

### 1.3 核心公式 [原文]
- 模型 A(CARA)/模型 B(风险调整期望)的 HJ 方程 **式(5) p.6**:
  `0 = ∂_tθ(t,q) − ½γ qᵀΣq + Σ_i 1{q_i+z_i≤Q_i} z_i H^{i,b}_ξ((θ(t,q)−θ(t,q+z_i e_i))/z_i) + Σ_i 1{q_i−z_i≥−Q_i} z_i H^{i,a}_ξ((θ(t,q)−θ(t,q−z_i e_i))/z_i)`,θ(T,q)=0;ξ=γ(A)或 0(B)。
  `H^{i,b}_ξ(p) = sup_δ Λ^{i,b}(δ)/(ξz_i)·(1−exp(−ξz_i(δ−p)))`(ξ>0),`= sup_δ Λ^{i,b}(δ)(δ−p)`(ξ=0)【式(3)–(4) p.6】。
- 最优报价 **Thm 1–2 p.6–7**:`δ^{i,b*}_t = δ̃^{i,b*}_ξ((θ(t,q)−θ(t,q+z_i e_i))/z_i)`,`δ̃^{i,b*}_0(p) = (Λ^{i,b})^{-1}(−H^{i,b}_0′(p))`。
- 二次近似 **式(9) p.8**:Ȟ^{i,b}(p)=α₀+α₁p+½α₂p²(Taylor 于 p=0,Remark 1);解 `θ̌(t,q) = −qᵀA(t)q − qᵀB(t) − C(t)`,A 满足 Riccati `A′ = 2A(D₊^{b}_{2,1}+D₊^{a}_{2,1})A − ½γΣ`【式(11) p.9】,闭式 **式(13) p.10**:
  `A(t) = ½ D₊^{-1/2} Â (e^{Â(T−t)} − e^{−Â(T−t)})(e^{Â(T−t)} + e^{−Â(T−t)})^{-1} D₊^{-1/2}`,`Â = √γ (D₊^{1/2} Σ D₊^{1/2})^{1/2}`,`D₊ = D^b_{2,1}+D^a_{2,1}`。
- 渐近 **Prop.3 p.12**:`A(0) → ½√γ Γ`,`Γ = D₊^{-1/2}(D₊^{1/2}ΣD₊^{1/2})^{1/2}D₊^{-1/2}`。
- 渐近报价(对称强度)**式(19)–(20) p.15**:
  `δ̆^{i,b}_t = δ̃^{i,b*}_ξ(√γ qᵀ_{t−}Γe_i + ½√γ z_i e_iᵀΓe_i)`,`δ̆^{i,a}_t = δ̃^{i,a*}_ξ(−√γ qᵀ_{t−}Γe_i + ½√γ z_i e_iᵀΓe_i)`。
- 指数强度 Λ^i(δ)=A_i e^{−k_iδ} 时 **p.16**:
  模型 B:`δ̆^{i,b} = √γ(qᵀΓe_i + ½z_i e_iᵀΓe_i) + 1/k_i`;模型 A:1/k_i 换成 `(1/(γz_i)) log(1+γz_i/k_i)`;`D₊ = diag(2A_i C^i_ξ k_i z_i)`,C^i_0 = e^{-1}。
  **半价差** = `½√γ z_i e_iᵀΓe_i + 1/k_i`(常数);**偏斜** `(δ̆^a−δ̆^b)/2 = −√γ qᵀΓe_i`(线性于库存)。
- 含漂移 μ、分层 n、请求量 z、固定成本 c **§5.4.2 p.25**:
  `δ̆^{i,n,b}_t(z) = √γ( qᵀΓe_i + ½ z_i e_iᵀΓe_i − (1/γ) e_iᵀ D₊^{-1/2} Â⁺ D₊^{1/2} μ ) + c^{i,n,b}/z + 1/k_{i,n}`(模型 B;模型 A 把 1/k 换成 (1/(γz))log(1+γz/k_{i,n})),`D₊ = diag(2Σ_n A^{i,n}k^{i,n}∫C^{i,n}_ξ(z) z ν^{i,n}(dz))`。
  **注意(页面渲染核对)**:p.25 印刷的 ask 行为 `√γ( qᵀΓe_i − ½ z_i e_iᵀΓe_i + (1/γ) e_iᵀD₊^{-1/2}Â⁺D₊^{1/2}μ ) + c^{i,n,a}/z + 1/k_{i,n}`,与论文自己的式(18)/(20) 及 p.16 的 ask(`−√γ(qᵀΓe_i − ½z_i e_iᵀΓe_i) + …`)符号不一致,疑为印刷漏号。[推导] 按式(18) 的结构,ask 应为 `−√γ qᵀΓe_i + ½√γ z_i e_iᵀΓe_i + (1/√γ) e_iᵀD₊^{-1/2}Â⁺D₊^{1/2}μ + c/z + 1/k`(库存项与 μ 项相对 bid 反号,价差项同号)。实现时以式(17)–(18) 为准,不照抄 p.25 的 ask 行。
  含义:**漂移(alpha)μ 以 D₊^{-1/2}Â⁺D₊^{1/2} 加权、线性平移 bid/ask(一边靠近一边远离);该项 = (1/√γ)·…,而 Â ∝ √γ,故整体 ∝ 1/γ——风险厌恶越小,同样的 alpha 平移越大**。
- 单资产、单位量时式(19)–(20) 与 GLFT(Guéant-Lehalle-Fernandez-Tapia 2013)的近似一致(p.16)。

### 1.4 作者数字 [paper result]
- 两资产例子:真最优 PnL [金额已抹] 600€,σ 86 900€;闭式近似 89 000€,σ 87 500€(4000 次 MC,p.33)。
- 图 8–11:闭式与真最优在库存接近 0 附近几乎重合,库存接近限额 Q 时偏差明显(p.31–34)。

### 1.5 局限
- 无 LOB、无排队、无 tick 离散(p.2 作者自述);强度只依赖自家报价距离,不依赖他人报价。
- 近似在大库存处失效(作者 p.34)。
- Σ、A_i、k_i 全部视为已知常数;没有给标定方法(GLFT/Guéant 2017 里有 A、k 的极大似然)。
- 对我方:USDC 线流动性仅 USDT 的 ~1%,k_i 估计噪声大,Γ 里 D₊ 依赖 A_i k_i,需收缩。

### 1.6 对 KuCoin 做市的含义 [推导]
- U15 多品种(ETH/SOL/SUI/XRP,USDC 本位)的库存偏斜应用 `skew_i = −√γ Σ_j Γ_ij q_j`,而不是每品种独立的 inv_skew_bp。等流动性近似 Γ ≈ Σ^{1/2}/√(2A k z e^{-1}),ρ=0.8 时交叉偏斜/自身偏斜 = 0.50,ρ=0.9 时 0.63(本文计算)。加密腰部币与 BTC/ETH 的分钟级 ρ 常在 0.7–0.9(需用我方数据核,注意 Epps 效应:秒级 ρ 会被低估,见 §5)。
- 半价差 = 风险缓冲 ½√γ z e_iᵀΓe_i + 1/k_i:1/k_i 是"成交频率 vs 每笔利润"的权衡,我方现行 h_min_bp=2、vol_k×amove 应替换为该式(k 在线估计,已在清单 #5)。
- 漂移项给了 alpha 信号进入报价的**线性**方式:每单位 μ 平移 (1/γ) e_iᵀD₊^{-1/2}Â⁺D₊^{1/2}μ;这也是 signal.rs/RS1 的 max_alpha_shift 应当如何标定的理论依据(信号尺度 → μ → 报价平移,而不是 1 tick 固定)。

### 1.7 假设卡
- **Strategy hypothesis (what is the edge?)**:多品种同时做市时,用协方差矩阵驱动的联合偏斜(Γ 矩阵)比逐品种独立偏斜更少承担价格风险、更少被迫对冲,从而在同样成交量下 PnL 方差更低、净 PnL 更高。
- **Economic mechanism (why should this edge exist?)**:相关品种的库存可以互相对冲;联合偏斜把"总风险 qᵀΣq"而不是"各自 q_i²"当作要管理的量,偏斜方向让相关品种的成交自然把组合风险拉回零。
- **Required data (L1 / L2 / L3 / trades / order events)**:L2(top-of-book 中价用于 σ_i、ρ_ij,5 档用于成交强度 Λ(δ) 的 A、k 标定)、trades(成交聚合,按吃单聚合)。不需要 L3。
- **Holding horizon (1ms / 10ms / 100ms / …)**:库存周期 10 s–数分钟(θ 由 √γ Γ 与 k 决定);报价更新 100 ms 级。
- **Expected signal (what observable predicts the edge?)**:各品种库存向量 q 与 Γ;观测上 "q_j≠0 的品种 j 与 i 的相关 ρ_ij" 预测 i 的最优偏斜方向。
- **Execution dependency (queue / latency / fill probability)**:fill probability 曲线 Λ_i(δ) 的 A_i、k_i(排队位置影响 A);延迟只通过 σ√τ 进入风险缓冲。
- **Failure modes (why might it disappear?)**:ρ 在秒级被 Epps 效应低估 → 偏斜不足;ρ 在行情冲击时突变(相关性崩塌);USDC 线 k 估计噪声大;大库存处近似失效;品种间 tick 差异使偏斜量化到 tick 时丢失。
- **Evidence (paper + empirical result, with numbers)**:闭式近似 vs 真最优 PnL [金额已抹] 000 vs 88 600(σ 87 500 vs 86 900)(p.33)。无实盘证据。
- **Test (the exact experiment we should run on KuCoin Futures data: contract type, data needed, statistic, pass/fail threshold)**:KuCoin USDC 永续 ETH/SOL/SUI/XRP(+BTC 作对冲腿),9 月购买数据(训练日 = 9 月前 20 天,考卷 09-02 起 9 天不动)。两组策略同一撮合器:(a) 现行逐品种 inv_skew_bp;(b) 式(19)–(20) 联合偏斜,γ 与 A_i、k_i、Σ 按训练日估计(Σ 用 1 分钟收益,BPV 去跳)。统计:每日净 PnL(bp of 成交名义)与库存 qᵀΣq 的日均值,配对差分。通过标准:9 个考卷日中 (b) 的日均 qᵀΣq 下降 ≥30% 且净 PnL 配对差 ≥0 于 ≥6/9 天,且成交量不低于 (a) 的 90%;任一不满足即不采纳。

---

## 2. B. Barzykin, Bergault, Guéant, Lemmel (2025) — 逆向选择与 price reading 下的最优报价

### 2.1 数据/市场背景
HSBC FX 研究计划资助的理论 + 仿真论文(p.21),设定是**dealer 向 N 个客户层级(tier)流式报价**的 OTC 市场。数值例子(§5.2 p.14):档位 (1,2,5,10,20,50) M 名义;两层合计基线强度 (2000,800,600,400,120,80)/day;κ=3 bp⁻¹;top-of-book 点差 ≈我方费率;日波动 100 bp;γ=1e−4 bp⁻¹M⁻¹;MC 10⁵ 条路径,T=10⁴ s;一阶公式取 ε=1,报价距离下限 0。无实盘数据。

### 2.2 机制
参考价 **式(1) p.2**:
`dS_t = σdB_t − Σ_{n,k}[ ζ̃^{n,k}(S_{t−}−S^{n,k,b}_t) dN^{n,k,b}_t − ζ̃^{n,k}(S^{n,k,a}_t−S_{t−}) dN^{n,k,a}_t ] + Σ_n J̃^n( Σ_k w^{n,k}(S^{n,k,a}_t − 2S_{t−} + S^{n,k,b}_t) ) dt`
- **逆向选择**:成交后价格朝对我方不利方向跳 ζ̃^{n,k}(δ),ζ̃ 非减 —— 在更保守的报价上仍被成交,说明对方信息更强(p.3)。常数 ζ̃ 是 BBG 2023 的特例。
- **Price reading(skew sniffing)**:报价偏斜 S^a−2S+S^b 被读出后,价格以 J̃^n(·) 漂移(p.3)。附录给出有界的"竞争力分数"版本 s(δ)=1/(1+exp((δ−δ̄)/τ))(p.20–21)。
- 目标 **式(5) p.5**(无限期折现):`E∫e^{−ρt}( Σ_n b^n(q,δ^{n,·,b},δ^{n,·,a}) − ½γσ²q² )dt`,
  `b^n = q J̃^n(Σ_k w^{n,k}(δ^{n,k,a}−δ^{n,k,b})) + Σ_k[ Δ_kΛ^{n,k,b}(δ^{n,k,b})(δ^{n,k,b} − ((q+Δ_k)/Δ_k)ζ̃^{n,k}(δ^{n,k,b})) + Δ_kΛ^{n,k,a}(δ^{n,k,a})(δ^{n,k,a} + ((q−Δ_k)/Δ_k)ζ̃^{n,k}(δ^{n,k,a})) ]`。
- 标定指引 **[原文] p.3**:"the functions Λ^{n,k,b/a} are intensity curves estimated from RFQ and execution data conditional on tier, size and side. The adverse-selection functions ζ̃^{n,k} summarise post-fill markouts of the reference price, conditional on execution at a given offset. The price-reading loadings w^{n,k} and response functions J̃^n … may be proxied by tier-level analysis such as skew sensitivity, subsequent trading direction, or observed deterioration in post-quote markouts."

### 2.3 核心公式 [原文]
- 一阶摄动 J̃=εJ、ζ̃=εζ,值函数 ϑ = θ + εf,f 满足线性方程 **式(7) p.7**,Feynman–Kac 解释:f = 若维持无信息风险最优报价,信息风险对风险调整 PnL 的边际影响。
- 报价一阶修正 **p.8**:
  `d^{n,k,b*}(q) = δ^{n,k,b*}(q) + (ε/c^{n,k,b}(δ^{n,k,b*}(q)))·[ D^k_+f(q) + q w^{n,k}J^{n′}(Σ_j w^{n,j}(δ^{n,j,a*}−δ^{n,j,b*}))/(Δ_kΛ^{n,k,b′}(δ^{n,k,b*})) + (q+Δ_k)(Λ^{n,k,b}ζ^{n,k})′(δ^{n,k,b*})/(Δ_kΛ^{n,k,b′}(δ^{n,k,b*})) ] + o(ε)`,ask 同构反号;c = 2 − ΛΛ″/Λ′²。
- 二次 Hamiltonian 近似(§4):ϑ̂ = −A_ε q² − B_ε q − C_ε,**式(9)–(10) p.10**;对称、ρ→0 时 **p.12**:
  `f̂(q) = ½ (Σ₊^{1,0}/F₊^{2,1}) q²`,`Σ₊^{1,0} = 2Σ_{m,j} [H^{m,j″}(0)/Λ^{m,j′}(δ̃^{m,j*}(0))]·( w^{m,j}J^{m′}(0) + (Λ^{m,j}ζ^{m,j})′(δ̃^{m,j*}(0)) )`,`F₊^{2,1} = 2Σ_{m,j}Δ_j H^{m,j″}(0)`;
  `D^k_±f̂(q) = −(Σ₊^{1,0}/F₊^{2,1})(±q + Δ_k/2)`(**p.13**)。
- 指数强度 Λ=Λ₀e^{−κδ}、J(x)=x、ζ=αe^{βδ}(**式(14) p.13**)时:
  基线 **p.14**:`δ̂^{n,k,b/a*}(q) = 1/κ^{n,k} + σ√( γe/(2Σ_{m,j}Δ_jΛ₀^{m,j}κ^{m,j}) )·(±q + Δ_k/2)`。
  Price reading 修正 **p.14**:`(d̂−δ̂)/ε = [eΣ w^{m,j} / ΣΔ_jΛ₀^{m,j}κ^{m,j}](±q+Δ_k/2) ∓ q w^{n,k}/(Δ_kκ^{n,k}Λ^{n,k}(δ̂))`。
  逆向选择修正 **p.17**:`(d̂−δ̂)/ε = [Σ α^{m,j}Λ₀^{m,j}(β^{m,j}−κ^{m,j})e^{β/κ} / ΣΔ_jΛ₀κ](±q+Δ_k/2) ∓ ((q±Δ_k)/Δ_k)((β^{n,k}−κ^{n,k})/κ^{n,k}) ζ^{n,k}(δ̂)`。
  → **符号由 β−κ 决定**:β<κ(慢信号、markout 对报价距离不敏感)时全局项使值函数凹度下降(表现得像更不风险厌恶,对无毒层收窄价差);β>κ(几 bp 快信号、只在报价陈旧时成交)时凹度上升、全面扩价差(p.12–13, 18)。

### 2.4 作者数字 [paper result]
- 论文只给图不给表;以下数值范围是**图的坐标轴范围**(提取文本可见),具体曲线数值未能从文本读出,定性结论为作者原话。
- Price reading(SVS = safe volume share,10–90%):图 3 PnL 轴 35–55 k$,图 4 风险轴 60–160 k$,图 5 PnL/Risk 轴 0.3–0.9。作者结论(p.17):"No Action" 期望 PnL 低于无读价基线、风险不受影响;"No Skew" 恢复 PnL 但"leads to a considerable increase in risk",读价者成交多(SVS 低)时尤甚;"Optimal"(式(12)–(13),ε=1)既提高 PnL 又降低风险,读价者占比低时更有效。
- 逆向选择(α^{2,k}=0.05、β^{2,k}=2<κ=3,p.18):图 7 PnL 轴 41–46 k$,图 8 风险轴 70–76 k$,图 9 PnL/Risk 轴 0.54–0.62。作者结论(p.19):不作为时期望 PnL 下降、风险几乎不变;"Optimal" 保护 PnL 并"significantly reduces risk",知情客户占比中等时最明显。图 6(SVS=50%):对无毒层零库存时**收窄**价差,对知情层扩价差但保留 top-of-book 的减库存报价("signal subscription",p.18);β>κ 情形结论相反(未画图)。
- 附录逻辑竞争力模型 τ=0.1 复现 §5.2 机制(图 10)。

### 2.5 局限
- 一阶摄动,只在信息风险"小"且报价接近基线时可靠;二阶交叉项未算(p.5)。
- 参考价是**做市商私有的**,假设做市商不从客户流中获得任何独占信息优势(Remark 3 p.3–4,作者称"保守")。
- 无 LOB/排队/延迟;线性 J 在远离市场的报价上不合理(附录修正)。
- 仿真 PnL 高于基线"并不意外,因为策略引入了可控漂移"(脚注 12 p.17)——即 price-reading 情形下的 PnL 增益部分是模型内生的。
- 数据不公开,代码不公开(p.22)。

### 2.6 对 KuCoin 做市的含义 [推导]
- 我方是 LOB 上的匿名 maker,没有 tier;"tier" 可映射为**按对手类型分的成交样本**(例如按成交后 1 s markout 分为毒/非毒,或按吃单大小分档 Δ_k)。ζ(δ) 曲线 = "在距中价 δ 的报价被成交后的 markout 均值",Λ(δ) = "在距 δ 挂单的成交强度";两者的对数斜率 β 与 κ 的差决定是扩价差还是收窄。这两条曲线可从 Tardis L2+trades 用排队最前假设估计(高估 Λ,需注记)。
- Price reading 在 LOB 中对应"我方偏斜被 order-book-imbalance 型信号读出":我方 [金额已抹] clip 在 BTC 上占比极小,J′ 可忽略;在腰部币 USDC 线(流动性仅 USDT 的 1%)我方挂单可能是显著份额,skew sniffing 现实存在 → 这是 USDC 线要检验的假设。
- 与既有结论一致:对几 bp 速度优势的毒流,论文的答案是扩价差 + 防御性偏斜,不是"利用毒流做信号订阅";"信号订阅"只对慢信号(几十 bp 到百分比级)成立。

### 2.7 假设卡
- **Strategy hypothesis (what is the edge?)**:(H1)成交后 markout 对报价距离的斜率 β 大于强度衰减 κ 时,应对全部报价扩价差并对减库存方向也保持防御;(H2)在 USDC 薄市上,我方偏斜会被读出并导致价格漂移,减小对外显示的偏斜(保留内部对冲)可以提高 PnL/Risk。
- **Economic mechanism (why should this edge exist?)**:成交是条件事件——在保守报价上仍成交意味着更强的私有信息或陈旧报价;偏斜泄露库存方向,读价者提前交易推动价格。
- **Required data (L1 / L2 / L3 / trades / order events)**:L2(中价、我方报价距离)、trades(成交后 100 ms/1 s/10 s markout,按吃单聚合)、我方实盘成交记录(实盘阶段);检验 H2 需要我方挂单事件与后续成交方向。
- **Holding horizon (1ms / 10ms / 100ms / …)**:markout 窗口 100 ms–10 s;报价调整周期 100 ms。
- **Expected signal (what observable predicts the edge?)**:ζ(δ) 与 Λ(δ) 的对数斜率之差 β−κ;对 H2:显示偏斜后 1–10 s 的对手成交方向与偏斜方向的相关。
- **Execution dependency (queue / latency / fill probability)**:Λ(δ) 依赖排队位置(排队最前假设高估 A、低估 κ 的可辨识性);延迟 1–2 ms 决定"陈旧报价"被吃的概率,直接进入 ζ 的陡度。
- **Failure modes (why might it disappear?)**:ζ 曲线在 tick ≥1 bp 的腰部币上只有 1–2 个可观测 δ 值,β 不可辨识;markout 混入我方自身冲击;毒流比例随时间变化(SVS 非平稳);一阶近似在毒流占比高时失效。
- **Evidence (paper + empirical result, with numbers)**:仅仿真(10⁵ 条 MC 路径,T=10⁴ s)——两种信息风险下 "Optimal" 的 PnL/Risk 均高于 "No Action"(图 5、图 9,轴范围分别 0.3–0.9、0.54–0.62;论文未给数值表);price reading 下 "No Skew" 风险大增。无实证、无真实数据。
- **Test (the exact experiment we should run on KuCoin Futures data: contract type, data needed, statistic, pass/fail threshold)**:KuCoin BTC-USDT 与 ETH-USDC 永续,9 月数据。步骤:(1)用排队最前撮合回放"距中价 δ∈{0.5,1,1.5,2,3} tick 挂单"的成交事件,估 Λ(δ)=成交次数/挂单时间,ζ(δ)=成交后 1 s 中价 markout 均值(bp);(2)拟合 log Λ、log ζ 对 δ 的斜率 κ、β(bootstrap 置信区间);(3)按 §5.3 公式(ε=1)生成价差/偏斜修正,与现行 U15 参数对照回测考卷 9 天。通过标准:β−κ 的 95% 区间不含 0 才进入 (3);(3) 中修正版净 PnL 配对差 >0 于 ≥6/9 天且 markout 损失(bp/成交)下降 ≥20%。H2 在 ETH-USDC:显示偏斜 ±1 tick 的两组时段,后续 5 s 对手主动成交方向差异经 χ² 检验 p<0.01 才认为 price reading 存在。

---

## 3. C. Almgren & Chriss (2000) — 组合交易最优执行

### 3.1 数据/市场背景
理论论文;数值例子(Table 1 p.25):S₀=50$,X=10⁶ 股,T=5 天,N=5,σ=0.95 $/share/√day(年化 30%),α=0.02 $/share/day,ε=1/16 $(半个点差),γ=2.5e−7 $/share²(卖出 10% 日成交量压价一个点差),η=2.5e−6(每 1% 日成交量的交易速率成本一个点差),λ=1e−6/$;两证券例子 Table 3 p.39。无实证数据。

### 3.2 机制
把清仓路径 x₀=X,…,x_N=0 的实施缺口(implementation shortfall)分解为波动风险与永久/临时冲击成本,在线性冲击下 E(x)+λV(x) 是二次型,得到指数型最优轨迹与有效前沿。

### 3.3 核心公式 [原文]
- 价格 **式(1) p.8**:`S_k = S_{k−1} + στ^{1/2}ξ_k − τ g(n_k/τ)`;成交价 **式(2) p.9**:`S̃_k = S_{k−1} − h(n_k/τ)`。
- 期望/方差 **式(4)–(5) p.10**:`E(x) = Σ τx_k g(n_k/τ) + Σ n_k h(n_k/τ)`,`V(x) = σ² Σ τ x_k²`。
- 线性冲击 **式(6)–(8) p.10–11**:`g(v)=γv`,`h(n_k/τ) = ε sgn(n_k) + (η/τ) n_k`,`E(x) = ½γX² + εΣ|n_k| + (η̃/τ)Σn_k²`,`η̃ = η − ½γτ`。
- 有效前沿 **式(14)–(15) p.13**:`min_{x:V(x)≤V*} E(x)` ⇔ `min_x E(x)+λV(x)`。
- 最优轨迹 **式(16)–(18) p.14**:`(x_{j−1}−2x_j+x_{j+1})/τ² = κ̃² x_j`,`κ̃² = λσ²/η̃`;`x_j = sinh(κ(T−t_j))/sinh(κT)·X`,`n_j = 2 sinh(½κτ)/sinh(κT)·cosh(κ(T−t_{j−½}))·X`。
- **式(19) p.15**:`κ ≈ √(λσ²/η) + O(τ)`;**半衰期 θ = 1/κ(p.15)**,与 T 无关;κT≫1 → 接近立即清仓,κT≪1 → 接近匀速。
- 效用 **式(21) p.18**:`U = λ_u V + E`,λ_u = −u″/u′;VaR **式(22) p.20**:`Var_p = λ_v√V + E`;L-VaR。
- 漂移 **式(23)–(27) p.26–27**:`x̄ = α/(2λσ²)`(式(25))为时间无关最优持仓;轨迹 = 零漂移解 + 与 X 无关、∝x̄ 的修正项。
- 多资产 **式(29)–(31) p.37**:`E = εᵀ|X| + ½XᵀΓ^S X + Στ v_kᵀH̃v_k + Στ x_kᵀΓ^A v_k`,`V = Στ x_kᵀ C x_k`,C=σσᵀ;最优条件 `(x_{k−1}−2x_k+x_{k+1})/τ² = λH̃^{-1}C x_k + H̃^{-1}Γ^A (x_{k−1}−x_{k+1})/(2τ)`;对角冲击时用 A=H̃^{-1/2}CH̃^{-1/2} 的特征分解得各模态 κ_j。
- 理论:二次效用下静态策略"时间齐次"(p.19 定理);朴素匀速策略的方差可一阶下降而成本只二阶上升(p.22),"从理论上讲永远不应交易严格风险中性的策略"(p.23)。

### 3.4 作者数字 [paper result]
- 例子中 κ≈0.6/day,κT≈3(p.24);x̄≈1 100 股 = 初始仓位 0.11%(p.26)。
- 两证券例子:高相关 + 一个更流动时,最优策略可能先在流动品种上快速做空以降风险,再慢慢整体清零(p.39)。

### 3.5 局限
- 算术随机游走、独立增量、线性冲击;作者自述非线性冲击时无显式解(p.16);大单需要按规模调 η。
- 多资产显式解需要冲击矩阵对角(p.38)。
- 时间尺度是天;在毫秒级做市对冲中"临时冲击 η"对应的是吃单穿越档位 + 对手撤单反应,估计方式不同。

### 3.6 对 KuCoin 做市的含义 [推导]
- 我方对冲参数 hedge_wait_ms=2000、hedge_max_ms=10000、hedge_chase_bp、hedge_stop_bp 的自然归一化:θ = √(η/(λσ²))。σ 用事件时间 BPV;η 从"以速率 v 吃单的平均超额成本"估计(taker 我方费率 + 穿档);λ 从我方风险预算(clip_usd × max_clips 对应的 qᵀΣq 上限)反解。
- 与 BBG 2112.02269 的"死区"结合:AC 给出死区外的**清仓速度**,BBG 给出死区边界。
- 多资产版本(Appendix A)与 Bergault Γ 矩阵是同一思想:H̃^{-1/2}CH̃^{-1/2} 的特征模态决定哪个品种先对冲。
- 漂移项 x̄=α/(2λσ²):若有 alpha(RS1/signal.rs),对冲不应清到 0 而是清到 x̄——这是"带信号的对冲目标仓位"的公式。

### 3.7 假设卡
- **Strategy hypothesis (what is the edge?)**:按半衰期 θ=√(η/(λσ²)) 归一化对冲节奏(等待/追价/止损)比固定毫秒参数在不同波动/流动性日子上更稳定,净对冲成本(bp/清仓名义)更低而库存风险不升。
- **Economic mechanism (why should this edge exist?)**:清仓速度是波动风险与临时冲击成本的权衡;σ 高或 η 低时应更快清,反之更慢;固定毫秒等价于随机地选了 κT。
- **Required data (L1 / L2 / L3 / trades / order events)**:L2 5 档(吃单穿档成本 → η)、trades、我方对冲成交记录;BPV σ。
- **Holding horizon (1ms / 10ms / 100ms / …)**:对冲窗口 1–30 s(θ 的典型量级,待估)。
- **Expected signal (what observable predicts the edge?)**:σ_t(事件时间)与 η_t(近期吃单成本斜率)→ θ_t。
- **Execution dependency (queue / latency / fill probability)**:吃单延迟 1 ms 单程决定 η 的下限(穿档时对手撤单);挂单对冲的成交概率不在 AC 模型内(需 GLFT-L/Guilbaud-Pham 补)。
- **Failure modes (why might it disappear?)**:线性冲击在 USDC 薄市失效(超线性);σ 跳变时 θ 瞬间变化;η 估计滞后;信号 x̄ 估错反而留仓。
- **Evidence (paper + empirical result, with numbers)**:理论 + 数值(κ≈0.6/day, κT≈3);无实证。
- **Test (the exact experiment we should run on KuCoin Futures data: contract type, data needed, statistic, pass/fail threshold)**:BTC-USDT 与 ETH-USDC 永续,9 月考卷 9 天。对冲模块两版:固定毫秒(现行)vs θ 归一化(η 用训练日估的"吃单成本 vs 速率"斜率,λ 由风险预算反解)。统计:对冲腿净成本(bp/名义,含 taker 费)与对冲期间库存 σ√τ 风险的日均值。通过:θ 版对冲成本下降 ≥10% 且风险不升(配对差 ≥6/9 天),否则不采纳。

---

## 4. D. 波动率估计:Corsi (2009) HAR-RV、Barndorff-Nielsen & Shephard (2004) 双幂变差、Bollerslev (1986) GARCH

### 4.1 Corsi (2009) HAR-RV
- **数据**:USD/CHF 逐笔中价 1989-12–2003-12(3599 日),S&P500 期货 1990-01–2007-07(4344 日),30 年 T-Bond 期货 1990-01–2003-10(3391 日);日 RV 用 Zhang-Aït-Sahalia-Mykland 两尺度估计、慢尺度 10 笔(p.186)。
- **机制**:异质市场假说——日/周/月三类参与者各自形成波动分量,长尺度影响短尺度(级联),叠加后近似长记忆。
- **公式 [原文]**:
  `dp(t) = μ(t)dt + σ(t)dW(t)`【式(1) p.176】;`IV_t^{(d)} = ∫_{t−1d}^{t} σ²(ω)dω`【(2)】;`RV_t^{(d)} = √(Σ_{j=0}^{M−1} r²_{t−jΔ})`【(3) p.177】(注意:Corsi 的 RV 是**平方根**);`RV_t^{(w)} = (1/5)(RV_t^{(d)}+…+RV_{t−4d}^{(d)})`【(4)】,月 22 天;
  级联 p.180:`σ̃^{(m)}_{t+1m} = c^{(m)} + φ^{(m)}RV^{(m)}_t + ω̃`,`σ̃^{(w)}_{t+1w} = c^{(w)} + φ^{(w)}RV^{(w)}_t + γ^{(w)}E_t[σ̃^{(m)}_{t+1m}] + ω̃`,`σ̃^{(d)}_{t+1d} = c^{(d)} + φ^{(d)}RV^{(d)}_t + γ^{(d)}E_t[σ̃^{(w)}_{t+1w}] + ω̃`;
  **HAR(3)-RV 式(8) p.181**:`RV^{(d)}_{t+1d} = c + β^{(d)}RV^{(d)}_t + β^{(w)}RV^{(w)}_t + β^{(m)}RV^{(m)}_t + ω_{t+1d}` —— 即施加阶梯权重约束的 AR(22),OLS + Newey-West(5 阶)估计(p.187)。
- **数字 [paper result]**:Table 2 p.187:USD/CHF c=1.121, β_d=0.352(t=13.5), β_w=0.323(7.5), β_m=0.235(6.3);S&P500 0.372/0.343/0.224;T-Bond 0.039(不显著)/0.412/0.361。仿真标定 β=(0.36,0.28,0.28)(p.182)。Table 4 p.189 样本内 1 日 R²:HAR 0.565/0.707/0.236 vs AR(1) 0.493/0.648/0.109,ARFIMA 0.559/0.703/0.237。Table 5 p.191 样本外(1000 日滚动):USD/CHF 1 日/1 周/2 周 R² HAR 0.551/0.609/0.570,AR(3) 0.530/0.523/0.316;BIC 偏好 HAR 而非 AR(22)(Table 3 p.188)。
- **局限**:日频模型;作者指出 T-Bond 日 RV 噪声大导致日项不显著(p.187);残差有 GARCH 效应(p.189)。
- **含义 [推导]**:我方需要的是**分钟到小时**的波动预测(报价缓冲、θ、Γ);HAR 结构可直接缩尺度:用 1 分钟 BPV 作最细尺度,(1 min, 15 min, 2 h) 三尺度回归,系数按训练日估计并滚动。Corsi 的结果表明三个尺度就能捕获大部分持续性,不必上 ARFIMA。

### 4.2 Barndorff-Nielsen & Shephard (2004) 幂变差与双幂变差
- **数据**:Olsen 美元/马克 5 分钟数据,1986-12-01 起(p.2);仿真 SV+跳(Table 1–3 p.22–23);实证跳检验 Table 4 p.33。
- **机制**:|y_j|^r|y_{j+1}|^s 的乘积中有限个跳只贡献 O(N(t)) 项,r,s<2 时被 δ^{1−(r+s)/2} 归一化压到 0,因此双幂变差对稀有跳稳健,RV−BPV 估计跳的二次变差。
- **公式 [原文]**:
  RV **式(1) p.2**:`[y*_M]^{[2]}_i = Σ_{j=1}^{M} y²_{j,i}`;幂变差 **式(2) p.3**:`{y*_M}^{[r]}_i = (ℏ/M)^{1−r/2} Σ|y_{j,i}|^r`;双幂变差 **p.4**:`{y*_M}^{[r,s]}_i = (ℏ/M)^{1−(r+s)/2} Σ_{j=1}^{M−1}|y_{j,i}|^r|y_{j+1,i}|^s`,**式(3)**:`{y*_M}^{[1,1]}_i = Σ|y_{j,i}||y_{j+1,i}|`。
  **Thm 1 p.8**:`{y*}^{[r]}(t) = μ_r∫₀ᵗσ^r(s)ds`,`μ_r = 2^{r/2}Γ((r+1)/2)/Γ(1/2)`(μ₁=√(2/π)≈0.798,μ₁^{-2}=π/2);**Thm 2 式(10) p.10**:`{y*}^{[r,r]}(t) = μ_r²∫₀ᵗσ^{2r}`;**p.13**:`μ_r^{-1}μ_{2−r}^{-1}{y*_M}^{[r,2−r]}_i → ∫σ²`;
  跳稳健 **Thm 4 式(18) p.15**:`μ_r^{-1}{y*}^{[r]}(t) = ∫σ^r (r∈(0,2)); [y*](t) (r=2); ∞ (r>2)`;**Thm 5 式(19) p.16**:`μ_r^{-1}μ_s^{-1}{y*}^{[r,s]}(t) = ∫σ^{r+s}` 当 max(r,s)<2 —— 即 **RV − μ₁^{-2}Σ|y_j||y_{j+1}| → Σ c_i²(跳的二次变差)**;
  渐近分布 **§6.4 p.31**:`δ^{-1/2}/√(∫σ⁴)·( Σy²_j − ∫σ², μ₁^{-2}Σ|y_j||y_{j+1}| − ∫σ² ) → N(0, [[2,2],[2,2.60907]])`,两者相关 ≈0.875,GLS 权重几乎全在 RV;差的分布 `→ N(0, 0.6091)`;可行的对数版检验 **式(26) p.32**:
  `[log Σy²_j − log(μ₁^{-2}Σ|y_j||y_{j+1}|)] / √( 0.6091·max{δ/t, Σ|y_j||y_{j+1}||y_{j+2}||y_{j+3}| / (Σ|y_j||y_{j+1}|)²} ) → N(0,1)`。
- **数字 [paper result]**:Table 4 p.33(美元/马克,5 分钟):5% 水平拒绝"无跳"的天数比例 0.215,1% 水平 0.119,0.1% 0.060。Table 1 p.22(仿真,M=288):RV 误差 95% 区间 [−.056,.059],BPV [−.066,.064],跳 QV [−.033,.037];无跳时 RV 略优于 BPV(Table 2)。
- **局限**:工作稿版本(期刊版付费未取);Thm 2 假设 σ 与 w 独立、α*=0(后续文献放宽);微观结构噪声未处理(作者用 5 分钟);无限活动 Lévy 跳只做讨论(§6.3)。
- **含义 [推导]**:我方 σ 估计应同时算 RV 与 BPV(事件时间,窗口 vol_ms 或按成交计数):BPV 用于 GLFT/Γ 的连续风险项,RV−BPV(截 0)作为"跳跃/逆向选择"缓冲的输入;式(26) 的检验统计量可作为"跳跃状态"闸门(如 z>2.33 时切到防御报价),替代目前没有出处的 tox_* 闸门。

### 4.3 Bollerslev (1986) GARCH(简)
- **公式 [原文]**:**式(1)–(2) p.309**:`ε_t|ψ_{t−1} ~ N(0,h_t)`,`h_t = α₀ + Σ_{i=1}^{q}α_iε²_{t−i} + Σ_{i=1}^{p}β_ih_{t−i}`,α₀>0,α_i≥0,β_i≥0;**Thm 1 p.310**:宽平稳 ⇔ A(1)+B(1)<1,Var(ε)=α₀/(1−A(1)−B(1));**GARCH(1,1) 式(8) p.311**:`h_t = α₀ + α₁ε²_{t−1} + β₁h_{t−1}`;四阶矩存在条件 3α₁²+2α₁β₁+β₁²<1,峰度 >0(p.312–313);ARMA 表示 **式(6) p.310**:ε² 是 ARMA(max(p,q), p)。
- **数据**:通胀率例子(§7),与我方无关。
- **含义 [推导]**:GARCH 是日频/低频返回的条件方差;对 HFT 报价我们用的是已实现量(RV/BPV),GARCH 只在"用 1 分钟收益递推 h_t 做前瞻"时有用;Münnix 2010 用 GARCH(1,1)(α₀=2.4e−4, α₁=0.15, β₁=0.84)生成仿真数据(p.5)。

### 4.4 假设卡 — Corsi (2009) HAR-RV
- **Strategy hypothesis (what is the edge?)**:用三个时间尺度(如 1 min / 15 min / 2 h)已实现波动的线性组合预测下一段波动,并据此设定报价缓冲与库存偏斜,比用单一短窗口 amove 更少出现"波动抬升前价差过窄、回落后价差过宽"。
- **Economic mechanism (why should this edge exist?)**:不同持仓周期的参与者各自产生波动分量,长尺度波动向短尺度传导(级联),因此短窗口估计既噪又缺持续性信息。
- **Required data (L1 / L2 / L3 / trades / order events)**:L1 中价(或 trades);不需要 L2 深度、L3、订单事件。
- **Holding horizon (1ms / 10ms / 100ms / …)**:预测步长 1 min–1 h;报价层每 100 ms 读取一次预测值。
- **Expected signal (what observable predicts the edge?)**:RV/BPV 在三个尺度上的取值 (RV^{1m}, RV^{15m}, RV^{2h}) 及回归系数 β。
- **Execution dependency (queue / latency / fill probability)**:估计器本身不依赖;效果通过"价差宽度 → 成交概率与 markout"间接体现。
- **Failure modes (why might it disappear?)**:tick ≥1 bp 的腰部币 1 分钟收益只有 0/±1 tick,RV 离散且受 bid-ask bounce 上偏;加密 24 h 无"日"边界,尺度选取任意;残差异方差(作者 p.189);行情结构突变时滚动系数滞后。
- **Evidence (paper + empirical result, with numbers)**:Table 2:USD/CHF β_d/β_w/β_m = 0.352/0.323/0.235;Table 5 样本外 1 周 R²:HAR 0.609(USD/CHF)、0.698(S&P)vs AR(1) 0.213、0.323,与 ARFIMA(0.611、0.678)持平。日频、非加密。
- **Test (the exact experiment we should run on KuCoin Futures data: contract type, data needed, statistic, pass/fail threshold)**:BTC-USDT 与 SOL-USDC 永续,Tardis L2 增量重建的 L1 中价,9 月训练日估系数、考卷 9 天评估。因变量 = 下一分钟 BPV 的平方根;自变量 = 过去 1 min、15 min、2 h 的平均。统计 = Mincer-Zarnowitz R²(式(11))与 QLIKE。通过:考卷期 R² ≥ AR(1) 的 R² + 0.05 且 QLIKE 更低于 ≥6/9 天;不通过则保留现行 amove。

### 4.5 假设卡 — Barndorff-Nielsen & Shephard (2004) 双幂变差
- **Strategy hypothesis (what is the edge?)**:把波动拆成连续部分(BPV)与跳跃部分(RV−BPV);跳跃检验显著的窗口之后做防御(扩 1 tick / 撤掉加库存方向挂单),可降低被逆向选择的 markout 损失而少损失成交量。
- **Economic mechanism (why should this edge exist?)**:连续波动是可通过偏斜/对冲管理的库存风险;跳跃是报价陈旧风险,且跳跃在时间上聚集,检测到一次后短时内再次发生的概率更高。
- **Required data (L1 / L2 / L3 / trades / order events)**:L1 中价按固定间隔 δ 采样(BTC 1 s,腰部币 5 s),trades 用于 markout。
- **Holding horizon (1ms / 10ms / 100ms / …)**:检验窗口 1–5 min;闸门触发后的防御持续 10 s–1 min;撤单动作本身 ~2 ms。
- **Expected signal (what observable predicts the edge?)**:式(26) 的 z 统计量;jump = max(RV − (π/2)Σ|y_j||y_{j+1}|, 0)。
- **Execution dependency (queue / latency / fill probability)**:撤单往返 1.9 ms;检验是事后的——只能防"跳后续动",防不了第一跳;防御期间放弃排队位置(回测按排队最前会低估这一代价)。
- **Failure modes (why might it disappear?)**:跳跃不聚集则闸门无效;tick 离散使 |y_j||y_{j+1}| 大量为 0,BPV 下偏、z 虚高(腰部币尤甚);微观结构噪声在 δ<1 s 时使 RV 上偏;假阳性损失成交量与返佣。
- **Evidence (paper + empirical result, with numbers)**:美元/马克 5 分钟:5%/1%/0.1% 水平拒绝"无跳"的天数比例 0.215/0.119/0.060(Table 4 p.33);无跳时 RV 与 BPV 渐近方差 2 vs 2.609、相关 ≈0.875(p.31);仿真 M=288 时 BPV 误差 95% 区间 [−.066,.064](Table 1)。
- **Test (the exact experiment we should run on KuCoin Futures data: contract type, data needed, statistic, pass/fail threshold)**:BTC-USDT、SOL-USDC 永续,9 月数据。(1)每 5 min 窗口算 z;比较 z>2.33 窗口之后 1 min 内与其它时段的"排队最前挂单成交后 1 s markout"(bp/成交):通过 = 差 ≥0.2 bp 且 t≥2.5;(2)通过后做闸门回测:考卷 9 天 markout 损失下降 ≥15% 且成交量下降 ≤10%(配对差 ≥6/9 天)。任一步不过即不启用。

### 4.6 假设卡 — Bollerslev (1986) GARCH
- **Strategy hypothesis (what is the edge?)**:(作为对照假设)用 1 分钟收益递推的 GARCH(1,1) 条件方差做 σ 前瞻,不优于 HAR-BPV;若优于,则改用 GARCH。
- **Economic mechanism (why should this edge exist?)**:条件方差对过去冲击的指数衰减记忆(α₁ε²+β₁h)是波动聚集的最简参数化;但它只用收益平方、不用日内已实现量,信息少于 RV 类估计。
- **Required data (L1 / L2 / L3 / trades / order events)**:L1 中价的 1 分钟收益。
- **Holding horizon (1ms / 10ms / 100ms / …)**:1 min 步长预测,报价层 100 ms 读取。
- **Expected signal (what observable predicts the edge?)**:h_t = α₀ + α₁ε²_{t−1} + β₁h_{t−1}。
- **Execution dependency (queue / latency / fill probability)**:无直接依赖。
- **Failure modes (why might it disappear?)**:α₁+β₁→1(IGARCH)时无条件方差不存在;正态假设下厚尾拟合差;参数需 MLE、滚动重估不稳;tick 离散收益大量为 0。
- **Evidence (paper + empirical result, with numbers)**:论文只有通胀率例子;Corsi 引 Andersen et al. 2003:"direct time series modeling of realized volatility strongly outperforms … GARCH"(Corsi p.177)。
- **Test (the exact experiment we should run on KuCoin Futures data: contract type, data needed, statistic, pass/fail threshold)**:与 4.4 同一数据与因变量,把 GARCH(1,1)(训练日 MLE)的 √h_t 作为预测加入比较。通过(=保留 HAR、放弃 GARCH):HAR 的 R² ≥ GARCH 的 R²;若 GARCH 的 R² 高出 ≥0.05 于 ≥6/9 天,则该假设被证伪、改用 GARCH。

---

## 5. E. Epps (1979) 效应 —— 原文未获得,以 Tóth & Kertész (2009) 与 Münnix et al. (2010) 为准

**说明**:Epps (1979) JASA 74:291–298 在 JSTOR(stable/2286325)与 Taylor & Francis 均付费,未取得原文。以下"Epps 效应陈述"以两篇公开论文对原文的转述为准:"1979 Epps reported results showing that stock return correlations decrease as the sampling frequency of data increases [1]"(Tóth-Kertész p.1);"The decline of calculated correlations in financial data towards smaller return intervals was first discovered by Thomas Epps in 1979"(Münnix p.1)。

### 5.1 Tóth & Kertész (2009)
- **数据**:NYSE TAQ 1993-01-04–2003-12-31,逐笔,previous-tick 价格;示例对 KO/PEP、CAT/DE、MRK/JNJ 等 20 只(p.4–5)。
- **公式 [原文]**:相关 **式(2) p.4**:`C^{A/B}_{Δt}(τ) = (⟨r^A_{Δt}(t)r^B_{Δt}(t+τ)⟩ − ⟨r^A⟩⟨r^B⟩)/(σ_Aσ_B)`,ρ_Δt = C(τ=0);分解 **式(12) p.11**:
  `ρ^{A/B}_{Δt} = [Σ_{x}(Δt/Δt₀−|x|) f^{A/B}_{Δt₀}(xΔt₀)]·[Σ_x(Δt/Δt₀−|x|) f^{A/A}]^{-1/2}·[Σ_x(Δt/Δt₀−|x|) f^{B/B}]^{-1/2}·ρ^{A/B}_{Δt₀}`,f 为滞后自/互相关衰减函数;随机游走 + 指数等待时间(λ=1/60)模型 **式(18)–(19) p.13–14**:`f^{A/B}(xΔt₀) = e^{−λΔt₀|x|}`。
- **数字 [paper result]**:KO/PEP 1993–2003 的相关随 Δt 增大而上升,"Several hours are needed for the correlation to reach its asymptotic value"(图 1 p.5,纵轴 0–0.25、横轴到 9000 s;具体曲线值未能从文本读出);渐近值定义为 Δt=6000–9000 s 的均值(p.7);特征时间(达到渐近值 1−e^{-1} 的 Δt)Table 1 p.7:CAT/DE 940/620/1320/700 s,KO/PEP 920/760/1040/800 s,MRK/JNJ 800/420/880/1060 s(1993/1997/2000/2003)——**成交频率上升 5–10 倍,特征时间不变**;实测衰减函数在 5–15 分钟内消失(p.15)。
- **结论**:异步撮合不能解释全部;存在与活跃度无关的"人的反应时间尺度"(p.3, 7)。

### 5.2 Münnix, Schäfer, Guhr (2010)
- **数据**:NYSE TAQ 2007;S&P500 各行业相关性最高的 5 对(50 只);低价股([金额已抹])25 对(p.6)。
- **公式 [原文]**:重叠 **式(1) p.2**:`Δt_o(t′) = min(γ₁(t′+Δt),γ₂(t′+Δt)) − max(γ₁(t′),γ₂(t′))`(γ_i = 最近成交时刻);**式(5) p.3**:`corr(r₁,r₂) = (1/T)Σ_t corr_t(g̃₁,g̃₂)·Δt_o(t)/Δt`;补偿 **式(6)**:`corr̂_async = ⟨g₁(t_j)g₂(t_j)·Δt/Δt_o(t_j)⟩`;tick 补偿 **式(11)–(13) p.4**:主要是 σ 被高估;合并 **式(16) p.5**:`corr̂ ≈ ⟨r̄₁r̄₂·Δt/Δt_o⟩/(σ̂_{r1}σ̂_{r2})`。
- **数字 [paper result]**:高相关对的异步补偿后,"asynchrony effects are the dominating cause for the Epps effect on return intervals down to approximately 10 minutes, where the remaining Epps effect is on average less than 3% of the correlation coefficient's saturation value"(p.6);补偿在 <3 分钟不可靠(p.7);低价股上两种统计原因合计可解释"up to 75%"的 Epps 效应(p.7);模型中 σ 高估在 Δt<3 分钟明显(图 7)。
- **对 Tóth-Kertész 的分歧**:Münnix 认为异步是主因,Tóth-Kertész 认为静态滞后/反应时间是主因(p.1, 7);两文都承认极短尺度(<3–5 分钟)由滞后互相关主导。

### 5.3 含义 [推导]
- 我方多品种 Γ 需要的 ρ_ij 若用 1 秒收益估计会严重低估(Epps),用 1–5 分钟接近饱和;但做市的库存周期是 10 s–分钟级,**在该尺度上"可对冲的相关"确实比日频低**——应使用与库存周期同尺度的 ρ,或用 Hayashi-Yoshida/Münnix 式(6) 重叠加权估计"真"ρ 再乘以滞后衰减。
- 加密永续 24h、成交极密(BTC),异步成分小;跨品种的滞后互相关(BTC 领先腰部币若干百毫秒到秒)是可检验的信号(Tóth-Kertész 的 f^{A/B}(x) 峰值位置),也是对冲腿选择的依据。

### 5.4 假设卡
- **Strategy hypothesis (what is the edge?)**:(H1)腰部币对 BTC/ETH 的收益相关在 1 s 尺度显著低于 1 min 尺度(Epps),且滞后互相关峰在 100 ms–2 s 处(BTC 领先);(H2)据此,用"BTC 最近 100 ms–1 s 收益"作为腰部币中价的前瞻修正,能降低腰部币报价被逆向选择的 markout。
- **Economic mechanism (why should this edge exist?)**:信息先在最流动的品种上定价,套利者把它传导到腰部币需要有限时间;这段时间内腰部币的挂单是"陈旧"的。
- **Required data (L1 / L2 / L3 / trades / order events)**:两品种 L2 top-of-book 中价(时间戳对齐到交易所时间)、trades。
- **Holding horizon (1ms / 10ms / 100ms / …)**:100 ms–2 s(滞后峰位置)。
- **Expected signal (what observable predicts the edge?)**:C^{A/B}_{Δt₀}(τ) 在 τ>0 的峰值与宽度;BTC 100 ms 收益对腰部币下一 500 ms 中价变动的回归系数。
- **Execution dependency (queue / latency / fill probability)**:行情单程 2.2 ms + 下单 1 ms:滞后峰若 <10 ms 则我方无法利用;峰在 100 ms 以上才可行。撤单/改价的排队损失是主要代价。
- **Failure modes (why might it disappear?)**:滞后被更快的参与者压缩到 ms 级(Tóth-Kertész 观察 1993–2003 特征时间不变,但那是分钟级现象);腰部币 tick ≥1 bp 使中价修正常常不足 1 tick、无法体现;交易所撮合时间戳与行情时间戳不一致。
- **Evidence (paper + empirical result, with numbers)**:Tóth-Kertész 特征时间 400–1300 s(股票、分钟级);Münnix 异步解释到 ~10 min 后剩余 <3%。无加密证据。
- **Test (the exact experiment we should run on KuCoin Futures data: contract type, data needed, statistic, pass/fail threshold)**:KuCoin BTC-USDT 与 SOL-USDT/SOL-USDC 永续,9 月 5 天。(1)按 Tóth-Kertész 式(2) 用 Δt₀=100 ms 计算 C(τ),τ∈[−5 s,5 s],给出峰位 τ*、ρ_{1s} 与 ρ_{60s};H1 通过:ρ_{1s}/ρ_{60s}<0.7 且 τ*≥50 ms 且 bootstrap 95% 区间不含 0;(2)若 H1 通过,回测 SOL 报价用"中价 + b·r^{BTC}_{100ms}"修正(b 由训练日回归),统计 markout(bp/成交)与成交量;H2 通过:markout 改善 ≥0.1 bp/成交且成交量不降 >10%(配对差 ≥4/5 天)。

---

## 6. F. 策略评估统计:Lo (2002)、DSR (2014)、PBO/CSCV (2017)、Bergstra-Bengio (2012)

### 6.1 Lo (2002) The statistics of Sharpe ratios
- **数据**:共同基金与对冲基金月度收益的示例(§Empirical);无 HFT 数据。
- **公式 [原文]**:SR **式(2) p.37**:`SR = (μ−R_f)/σ`;IID 渐近方差 **式(8) p.38**:`V_IID = 1 + ½SR²`;**式(9)**:`SE(ŜR) ≈ √((1+½SR²)/T)`;**式(10)** 95% 区间 `ŜR ± 1.96√((1+½ŜR²)/T)`;**式(11)**:SE/SR → 1/√(2T);**式(12)** μ̂ 贡献占比 1/(1+½SR²)(SR=0.25 时 97%,SR=2 时 33%,SR=3 时 18%,p.39);非 IID(平稳)**式(14)–(15) p.39–40**:`√T(ŜR−SR) → N(0,V_GMM)`,`V_GMM = (∂g/∂θ)Σ(∂g/∂θ)′`(GMM/Newey-West);时间聚合 **式(17) p.40**:IID 下 `SR(q) = √q·SR`;**式(19)–(20)**:`Var[R_t(q)] = qσ² + 2σ²Σ_{k=1}^{q−1}(q−k)ρ_k`,`SR(q) = η(q)SR`,`η(q) = q/√(q + 2Σ_{k=1}^{q−1}(q−k)ρ_k)`;AR(1) **式(22) p.41**:`η(q) = q[q + (2ρ/(1−ρ))(q − (1−ρ^q)/(1−ρ))]^{-1/2}`。
- **数字 [paper result]**:Table 1 p.39:T=60、SR=1.5 → SE 0.188;SR=3 → 0.303;T=12、SR=1 → 0.354。Table 2 p.41:月度 ρ₁=−20% 时年化倍数 4.17,IID 3.46,+20% 时 2.88;对冲基金年化 SR 因正自相关可高估 65%(摘要)。
- **局限**:大样本渐近;非 IID 版需要 GMM 协方差估计(HAC),小样本(T=30)时渐近本身不可靠;不处理多重比较。
- **对我方的推导**:以小时 PnL 为观测,T=30:SE(ŜR_h)≈0.18(SR_h∈0.1–0.5 几乎不变),1/√(2T)=0.129 即相对误差 ≥13% 的下限只在 SR 很大时达到,实际 SR_h≈0.1–0.3 时相对误差 60–180%。小时 PnL 若有负自相关(做市库存均值回复常见),按式(22) ρ=−0.2 时 24 h 聚合倍数 5.95 而非 √24=4.90;正自相关 +0.2 时 4.04。**日 SR 与小时 SR 的换算必须用式(20),不能乘 √24。**

### 6.2 Bailey & López de Prado (2014) Deflated Sharpe Ratio
- **数据**:数值例子(国债拍卖季节性策略);Monte Carlo 校验(Exhibit 3.1–3.2)。
- **公式 [原文]**(式(2) 与 p.10 数值已按渲染页面核对):
  期望最大 SR **式(1) p.7**:`E[max_n ŜR_n] ≈ E[{ŜR_n}] + √V[{ŜR_n}]·((1−γ)Z^{-1}[1−1/N] + γZ^{-1}[1−1/(Ne)])`,γ≈0.5772(Euler–Mascheroni),N = **独立**试验数;
  **DSR 式(2) p.8**:`DSR ≡ PSR(ŜR₀) = Z[ (ŜR − ŜR₀)√(T−1) / √(1 − γ̂₃ŜR + ((γ̂₄−1)/4)ŜR²) ]`,`ŜR₀ = √V[{ŜR_n}]((1−γ)Z^{-1}[1−1/N] + γZ^{-1}[1−1/(Ne)])`,γ̂₃ 偏度、γ̂₄ 峰度、T 样本长度,SR 均为**非年化**(每观测)单位;
  非独立试验的等效独立数 **式(9) p.14**:`N̂ = ρ̂ + (1−ρ̂)M`(ρ̂ 为平均相关,M 为实际试验数;线性插值,作者自称粗略,并指出 M>T 时相关矩阵病态、建议用信息论方法)。
  停止规则 p.10–11:1/e 法则(先随机试 37% 的合理配置,之后遇到第一个超过全部先前者的即停)。
- **数字 [paper result]**(p.10):N=100,V[{ŜR}]=1/500(非年化),T=1250,γ̂₃=−3,γ̂₄=10,ŜR=2.5/√250:ŜR₀≈0.1132,DSR=0.9004<0.95(拒绝);若 N=46 则 DSR=0.9505;若正态收益(γ̂₃=0,γ̂₄=3)则 N=88 时 DSR=0.9505。本文用 Python 复算 SR₀=0.1132、DSR=0.9004,一致。
- **局限**:假设各试验 SR 服从正态、且已知 V[{ŜR}];N 的独立性难以确定;PSR 本身是渐近正态近似,T=30 时偏度/峰度估计本身极不稳。
- **对我方的推导(N=5 变体,T=30 小时)**:E[max of 5 N(0,1)] 近似 1.193;若 5 个变体的小时 SR 离散 σ_trials=0.05/0.1/0.2,则 ŜR₀=0.060/0.119/0.239;要 DSR≥0.95(正态收益)需 ŜR_h≥0.376/0.439/0.568。反过来,在 ŜR_h=0.2、ŜR₀=0.06 时需 T≥142 小时(5.9 天);ŜR₀=0.12 时 T≥432 小时(18 天);ŜR_h=0.1、ŜR₀=0.06 时 T≥1701 小时(71 天)。**结论:30 小时上任何"最好变体"都无法通过 DSR;必须把变体比较改为配对差分(同一小时同一撮合器),并事先固定选择规则。**

### 6.3 Bailey, Borwein, López de Prado, Zhu (2017) PBO / CSCV
- **数据**:随机游走 1000 日价格 + 8 800 个季节性参数组合(§6 p.25);真实策略示例(图 3、5)。
- **定义 [原文]**:**式(2.1) p.9** 过拟合:样本内最优策略的样本外期望排名低于中位数 `Σ_n E[r̄_n|r∈Ω*_n]Prob[r∈Ω*_n] ≤ N/2`;**PBO 式(2.2) p.10**:`PBO = Σ_n Prob[r̄_n < N/2 | r∈Ω*_n]·Prob[r∈Ω*_n]`。
- **CSCV 算法 2.3 p.11–12**:T×N 的 PnL 矩阵 M;按行分成 S 个等长子矩阵;取所有 S/2 子矩阵的组合 C_S(个数 **式(2.3)** C(S,S/2);S=16 时论文写 12 780,实际 C(16,8)=12 870,论文数字有笔误);每个组合 c:训练集 J(按原顺序拼接)、测试集 J̄(补集);IS 最优 n*,OOS 相对排名 ω̄_c = r̄_{n*}/(N+1),logit λ_c = ln(ω̄_c/(1−ω̄_c));**PBO φ = ∫_{−∞}^{0} f(λ)dλ**(p.13)。配套统计:性能退化回归 R̄_{n*} = α + βR_{n*}(β 常为负)、OOS 亏损概率 Prob[R̄_{n*}<0]、随机占优(p.14, 16, 18)。
- **参数指引 [原文] p.22**:S=16 → σ[f(λ)]<0.0045;S 太大会打碎时间结构;**N 必须 ≫10**("if the investor is sensitive to values of φ<1/10 … N>>10 is required");T 应为实际选择用样本的两倍;必须报告全部试验(隐藏试验会低估 PBO,p.24);**不得用 PBO 作为选择目标**(p.25)。
- **数字 [paper result]**:随机游走上 8 800 组合最优年化 SR 1.27,PSR-stat 2.83(<1% 概率 SR<0)却 PBO=55%、53% 的 OOS SR 为负(p.25);加入真实月度效应后 SR 1.54、PBO 13%、13% OOS 为负(p.26);示例 1 PBO 74%、78% OOS 负(p.16);真实策略 PBO 0.04%、3% OOS 负(p.16)。
- **局限 [原文 §5]**:对称划分不适合强自相关的性能序列;只反映数据集内的结构性变化;高 PBO 不排除 N 个都好的情况;不评价回测本身的正确性。
- **对我方的推导**:N=5 时 ω̄ 只取 5 个值 {1/6,…,5/6},logit 只有 5 个离散值,φ 的分辨率是 0.2 —— 论文明确要求 N≫10,故 PBO 在 5 变体上**不可用**;T=30 时 S=6 → 20 个组合、每块 5 小时,S=10 → 252 组合、每块 3 小时,但每半样本只有 15 小时,SR 的 SE≈0.26(式(9)),排名本身是噪声。可用的是其"随机占优"思想:把 5 个变体的 OOS 分布与"随机选一个"比较。

### 6.4 Bergstra & Bengio (2012) 随机搜索
- **数据**:Larochelle et al. 2007 的 7 个数据集(mnist 变体、rectangles、convex),神经网络 7 维超参、DBN 32 维(§2–5)。
- **机制 [原文]**:响应面 Ψ 的**有效维度低**(p.283):"functions Ψ of interest have a low effective dimensionality";网格在不重要的维度上浪费试验,随机点在每个子空间上投影均匀(图 1 p.284)。GP 分析显示 7 维问题的有效维度 1–4(p.295);"While random search optimized these Ψ functions with 8 to 16 trials, a grid with, say, four values in each of these axes would already require 256 trials"(p.295)。
- **评估公式 [原文] 式(5)–(6) p.286**:多个试验都"近乎最好"时,报告加权平均 `μ_z = Σ_s w_s μ_s`,`σ²_z = Σ_s w_s(μ²_s+σ²_s) − μ²_z`,权重 w_s = P(Z^{(s)} < Z^{(s′)} ∀s′)(验证分数的正态抽样计数)—— 即**"最优变体"的测试表现应按其"真是最优"的概率加权**,而非直接报最优者。
- **建议 [原文] §7 p.302**:研究单个超参 X 的效应时,对其它超参用**同一组**随机值,对每个 X 值重复(受控实验);随机试验可随时停止、可追加。
- **对我方的推导**:归一化后的策略参数(γ、k、θ、Γ)有效维度可能 1–2;用 5 个手工变体等于 5 点网格。更合理:固定随机种子的其它参数,只扫一个维度;报告时用式(5)–(6) 的概率加权,而不是"最好那个"。

### 6.5 假设卡 — Lo (2002)
- **Strategy hypothesis (what is the edge?)**:(评估假设)我方各变体的小时 SR 差异小于其标准误;在 T≈30 小时上报告的 SR 排名不具统计意义。
- **Economic mechanism (why should this edge exist?)**:SR 是 μ̂/σ̂ 的比值,SR 小时 μ̂ 的抽样误差主导(SR=0.25 时占 97%,式(12));做市小时 PnL 的自相关使 √q 换算错误(式(20))。
- **Required data (L1 / L2 / L3 / trades / order events)**:回测/实盘输出的每小时净 PnL 序列(含费用/返佣),逐变体。
- **Holding horizon (1ms / 10ms / 100ms / …)**:评估单位 1 小时;聚合到日用 η(24)。
- **Expected signal (what observable predicts the edge?)**:SE(ŜR)=√((1+½ŜR²)/T)(IID)或 HAC 版 √(V̂_GMM/T);小时 PnL 的 ρ₁…ρ₂₃。
- **Execution dependency (queue / latency / fill probability)**:排队最前假设使所有变体 PnL 同向上偏,SR 水平不可信,但 SE 的量级仍适用。
- **Failure modes (why might it disappear?)**:T=30 时渐近正态本身不可靠;厚尾使 SE 更大(DSR 的 γ₃、γ₄ 修正);非平稳(行情日/平静日混合)。
- **Evidence (paper + empirical result, with numbers)**:Table 1:T=24、SR=1 → SE 0.250;T=36 → 0.204;Table 2:ρ=−20% 时 η(12)=4.17 vs √12=3.46;对冲基金年化 SR 最多高估 65%。[推导] T=30、SR_h=0.2 → SE=0.184。
- **Test (the exact experiment we should run on KuCoin Futures data: contract type, data needed, statistic, pass/fail threshold)**:评估程序——对 U15 每个变体(BTC/ETH/SOL USDT 与 USDC 永续)输出小时净 PnL(bp/成交名义);报告 ŜR_h、IID SE、HAC SE(Newey-West 滞后 6)、95% 区间、ρ₁..ρ₂₃ 与 η(24);日 SR 一律用 η(24)·ŜR_h。判定:两个变体的 SR 区间重叠即"不可区分",不得据此选参;区间不重叠且配对差 t≥2.5 才算有差异。

### 6.6 假设卡 — Bailey & López de Prado (2014) DSR
- **Strategy hypothesis (what is the edge?)**:(评估假设)我方"多变体取最优"得到的最优 SR 不超过零技能下的期望最大值 SR₀,即 DSR<0.95。
- **Economic mechanism (why should this edge exist?)**:N 个噪声估计的最大值期望随 N 增长(式(1));厚尾/负偏使 SR 的抽样方差更大。
- **Required data (L1 / L2 / L3 / trades / order events)**:全部试验(含放弃的)的小时 PnL 矩阵;被选变体的偏度、峰度;变体间相关矩阵。
- **Holding horizon (1ms / 10ms / 100ms / …)**:小时观测;T 由 MinTRL 反推。
- **Expected signal (what observable predicts the edge?)**:DSR = Z[(ŜR−ŜR₀)√(T−1)/√(1−γ̂₃ŜR+((γ̂₄−1)/4)ŜR²)];N̂ = ρ̂+(1−ρ̂)M。
- **Execution dependency (queue / latency / fill probability)**:无;但撮合假设变化(如 09-29 撮合修正)前后的试验不可混入同一 N。
- **Failure modes (why might it disappear?)**:试验数漏报(file drawer);变体高度相关时 N̂ 的线性插值粗糙;V[{ŜR}] 由 5 个点估计极不稳;T=30 时 γ̂₃、γ̂₄ 不可估。
- **Evidence (paper + empirical result, with numbers)**:N=100、T=1250、ŜR 年化 2.5、γ₃=−3、γ₄=10 → SR₀=0.1132、DSR=0.9004;N=46 → 0.9505(p.10,已复算)。[推导] 我方 N=5、T=30:σ_trials=0.1 → SR₀=0.119,需 ŜR_h≥0.44。
- **Test (the exact experiment we should run on KuCoin Futures data: contract type, data needed, statistic, pass/fail threshold)**:评估程序——每次参数选择记录 M(全部试过的变体数)、变体间小时 PnL 平均相关 ρ̂ → N̂;算被选变体的 DSR。通过:DSR≥0.95 才允许进入考卷/实盘候选;T 不足时先按 [推导] 的 MinTRL(SR_h=0.2、SR₀=0.06 → ≥142 小时)补数据,不允许用更多变体"补"。

### 6.7 假设卡 — Bailey, Borwein, López de Prado, Zhu (2017) PBO/CSCV
- **Strategy hypothesis (what is the edge?)**:(评估假设)我方参数选择流程的 PBO ≥0.5——样本内最优变体在样本外不优于中位数。
- **Economic mechanism (why should this edge exist?)**:选择过程拟合了样本内噪声;存在记忆效应时样本内越好样本外越差(回归斜率 β<0)。
- **Required data (L1 / L2 / L3 / trades / order events)**:T×N 的同步小时 PnL 矩阵(全部变体,同一小时对齐)。
- **Holding horizon (1ms / 10ms / 100ms / …)**:小时观测;每块 T/S 需保留日内季节性(块长 ≥ 数小时)。
- **Expected signal (what observable predicts the edge?)**:logit λ_c 的分布、φ=∫_{−∞}^{0}f(λ)dλ、OOS 亏损概率、SD2 随机占优。
- **Execution dependency (queue / latency / fill probability)**:无;PBO 不评价回测本身是否正确(作者 p.24)。
- **Failure modes (why might it disappear?)**:N=5 时 ω̄ 只有 5 个取值,φ 分辨率 0.2(论文要求 N≫10);T=30 时半样本 15 小时,排名即噪声;小时 PnL 强自相关时对称切块失真(§5.1);把 PBO 当优化目标(p.25 禁止)。
- **Evidence (paper + empirical result, with numbers)**:随机游走上 8 800 组合:最优年化 SR 1.27、PSR-stat 2.83,但 PBO 55%、53% OOS SR 为负;有真实月度效应时 SR 1.54、PBO 13%(p.25–26)。
- **Test (the exact experiment we should run on KuCoin Futures data: contract type, data needed, statistic, pass/fail threshold)**:评估程序——仅当 N≥20 个变体且 T≥240 小时时运行 CSCV:S=8(70 个组合,每块 30 小时),性能指标 = 小时 SR;报告 φ、OOS 亏损概率、(SR_IS, SR_OOS) 回归斜率、SD2。通过:φ≤0.2 且 OOS 亏损概率 ≤0.3 才认为选择流程可信;N<20 或 T<240 时不报 PBO,改用 6.5/6.6 的配对差与 DSR。

### 6.8 假设卡 — Bergstra & Bengio (2012) 随机搜索
- **Strategy hypothesis (what is the edge?)**:(评估假设)我方策略参数的响应面有效维度低(1–2 个参数决定大部分 PnL 差异);同样预算下随机抽样比手工网格更快找到好区域,并能识别哪个参数真正重要。
- **Economic mechanism (why should this edge exist?)**:归一化后多数参数只是尺度换算,真正的自由度是风险厌恶 γ 与少数阈值;网格在不重要维度上重复同一取值,浪费试验。
- **Required data (L1 / L2 / L3 / trades / order events)**:各试验的参数向量与训练日小时 PnL。
- **Holding horizon (1ms / 10ms / 100ms / …)**:不适用(实验设计);每个试验 = 一次完整训练日回测。
- **Expected signal (what observable predicts the edge?)**:GP/ARD 长度尺度或逐参数方差分解给出的有效维度;随机试验效率曲线(最优值随试验数的收敛)。
- **Execution dependency (queue / latency / fill probability)**:无。
- **Failure modes (why might it disappear?)**:试验数增多直接抬高 DSR 的 N(与 6.6 冲突——随机搜索只能在训练日用,且 N 必须如实计入);验证噪声大时"最优"不可辨(用式(5)–(6) 加权);参数间强交互时有效维度不低。
- **Evidence (paper + empirical result, with numbers)**:7 维神经网络超参的有效维度 1–4;随机搜索 8–16 次试验达到的效果,4 值网格需 256 次(p.295);32 维 DBN 上随机搜索在 7 个数据集中 4 个持平、1 个更优(摘要)。
- **Test (the exact experiment we should run on KuCoin Futures data: contract type, data needed, statistic, pass/fail threshold)**:评估程序——U15(BTC-USDT 永续训练日)在归一化参数的先验区间内均匀随机抽 16 组(固定种子),与现行 5 个手工变体同样预算对比;对结果做逐参数方差分解。判定:若 ≥80% 的 PnL 方差由 ≤2 个参数解释,则后续只扫这 ≤2 个参数、其余固定(论文 §7 的受控实验做法);报告"最优"时用式(5)–(6) 的概率加权均值与方差,不报单点最优。

---

## 7. G. Spooner et al. (2018) RL 做市;Milionis et al. (2022) LVR

### 7.1 Spooner, Fearnley, Savani, Koukorinis (2018)
- **数据**:10 只欧洲股票(CRDI.MI, GASI.MI, GSK.L, HSBA.L, ING.AS, LGEN.L, LSE.L, NOK1V.HE, SAN.MC, VOD.L),4 个板块、5 个交易所,2010-01–08,5 档深度 + 成交,毫秒级(p.2–3);训练 ~120 天、测试 40 天(Table 2 p.5)。撮合:重放历史簿,自家单不冲击市场;撤单在队列中**均匀分布**假设(p.3)。
- **动作空间 Table 1 p.3**:9 个 (θ_a,θ_b) 组合 ∈{(1,1),(2,2),(3,3),(4,4),(5,5),(1,3),(3,1),(2,5),(5,2)} + 市价清仓;报价 **式(1)–(2)**:`p_{a,b} = Ref + Dist_{a,b}`,`Dist_{a,b} = θ_{a,b}·Spread(t)`,Spread = 市场半价差的移动平均(即**报价距离按点差归一化**)。
- **奖励 [原文] 式(3)–(6) p.4**:`Ψ(t_i) = ψ_a + ψ_b + Inv(t_i)Δm(t_i)`,ψ_a = Matched_a·(p_a − m);PnL `r=Ψ`【(4)】;对称阻尼 `r = Ψ − η·Inv·Δm`【(5)】;**非对称阻尼 `r = Ψ − max[0, η·Inv·Δm]`【(6)】**(只削减持仓投机的利润、保留亏损)。
- **状态 p.4**:agent-state(库存、按点差归一化的报价距离)+ market-state(点差、中价变动、簿/队列不平衡、签名成交量、波动率、RSI);三种表示:agent-state、full-state、**线性组合的 tile coding(LCTC)式(7)**,权重 (0.6,0.1,0.3)。算法:Q、SARSA、R-learning 及变体,均带资格迹(λ=0.96),γ=0.97,α=0.001,ε 0.7 衰减,单量 1000,库存限 ±10 000(Table 2 p.5)。
- **数字 [paper result]**(归一化日 PnL = 利润/平均点差,单位 10⁴;MAP = 平均绝对仓位):
  基准 HSBA.L Table 3 p.6:固定 θ=1 −20.95±17.52(MAP 3646);θ=5 2.80±10.30(2678);随机 −10.82±5.63;Abernethy-Kale MMMW 多数为负(Table 6),FTL 全负(Table 7)。
  基本代理(agent-state + 原始 PnL + Q/SARSA(λ))Table 4:HSBA.L −12.65±124.26 / −12.45±155.31——高方差、大仓位。
  扩展 Table 5 p.7:非对称阻尼 η=0.6:HSBA.L 13.88±10.60,GSK.L 9.59±10.72,VOD.L 9.63±6.94;对称阻尼反而恶化(HSBA.L −11.80±214.15);full-state 全部为负且发散(HSBA.L −84.78±31.71);LCTC 恢复(−0.79±68.59)。图 2 p.6:η≈0.05–0.1 起策略从大偏向仓位切换到小中性仓位;图 3:η=0 时训练奖励标准差发散。
  合并代理 Table 6 p.8:HSBA.L 15.43±13.01(MAP 104)vs 固定 θ=5 2.80±10.30(2678);GSK.L 7.32±7.23(57);VOD.L 5.02±6.35(46);ING.AS −3.21±29.05;NOK1V.HE −5.28±33.42。
- **局限**:无费用/返佣/延迟(作者列为未来工作 p.8 第 5 条);撤单均匀分布假设(与我方 L2 差额补排队同类问题);单量固定;10 只股票 8 个月;"归一化日 PnL"不是 bp,无法直接换算。
- **含义 [推导]**:(i)奖励中的库存项应非对称阻尼——这与 GLFT 的 ½γσ²q² 惩罚同源,但只罚"靠持仓赚的钱",不罚亏损,是让代理不学趋势跟随的关键;对应我方规则"禁止以亏损为触发的奖励"的镜像:这里是"禁止以持仓盈利为奖励";(ii)市场状态变量直接进入状态空间导致发散——与我方"信号 signal.rs 对策略无实质增量"一致;(iii)按点差归一化报价距离是他们的默认做法。

### 7.2 Milionis, Moallemi, Roughgarden, Zhang (2022) LVR(一段)
- **模型/公式 [原文]**:CFMM 的池值 V(P);再平衡策略 R_t 持有与池相同的风险资产量 x*(P_t) 但在 CEX 价格成交;**Lemma 2 式(7)–(8) p.19**:`LVR_t = ∫₀ᵗ ℓ(σ_s,P_s)ds`,`ℓ(σ,P) = ½σ²P²|x*′(P)|`(非负、可预测、= 套利者累计利润);**Theorem 1 式(13) p.22**:`LP P&L_t = ∫₀ᵗ x*(P_s)dP_s [market risk "beta"] + FEE_t − LVR_t [microstructural "alpha"]`;常数乘积(Uniswap v2)**式(19) p.30**:`ℓ/V = σ²/8`;加权几何 `ℓ/V = ½σ²θ(1−θ)`【式(18)】。直觉推导 p.20–21:每次价格变 dP,池以割线价 P+dP/2 成交、再平衡策略以 P+dP 成交,损失 dx·dP/2 = |x*′|(dP)²/2。作者明确把它与 Budish et al. 2015 的报价 sniping 对应(p.22):"CFMMs … can be thought of as market makers that never proactively update quotes"。
- **数字 [paper result]**:日波动 5% 时 v2 ETH-USDC 池每天损失 σ²/8=3.125 bp(p.30);Uniswap v2 ETH-USDC 2021-08–2022-08:99.991% 的 LP PnL 方差来自 β(1 分钟再平衡对冲后残差方差 0.009%),用未对冲 PnL 做回归需 ~11 664 倍数据(p.4)。
- **对我方的含义 [推导]**:LVR 是"从不改价的做市商"的逆向选择损失上界:ℓ ∝ σ² × 边际流动性;我方每次改价延迟 ~2–3 ms(行情 2.2 + 下单 1)内相当于 CFMM,单笔陈旧损失 ≈ ½|Δq/Δp|·(σ√τ)²;这与 normalization_checklist #6 的"剩余边际 < z·σ_τ√τ"同一量纲,提供了一个按方差线性、可在线估计的 tox 门限替代。AMM 语境之外无直接用途。

### 7.3 假设卡 — Spooner et al. (2018)
- **Strategy hypothesis (what is the edge?)**:选参/学习的目标函数若把"持仓方向上的价格变动盈利"按 η 非对称削减(只削盈利、不削亏损),得到的做市策略仓位更小、PnL 方差更低,且价差捕获收益不降。
- **Economic mechanism (why should this edge exist?)**:原始 PnL 目标会奖励趋势投机(持仓×价格变动),其方差远大于价差捕获项并淹没学习信号;去掉这部分奖励后目标只剩做市本身。
- **Required data (L1 / L2 / L3 / trades / order events)**:L2(5 档)+ trades,用于排队仿真;论文无 L3,撤单按队列均匀分布处理。
- **Holding horizon (1ms / 10ms / 100ms / …)**:事件驱动(每次簿变化决策);库存周期分钟级;评估按日。
- **Expected signal (what observable predicts the edge?)**:阻尼系数 η(论文在 η≈0.05–0.1 处出现策略切换);状态仅用库存与按点差归一化的报价距离。
- **Execution dependency (queue / latency / fill probability)**:论文不含延迟、费用、返佣(p.我方费率 列为未来工作);排队靠"撤单均匀分布"假设;清仓用市价单。
- **Failure modes (why might it disappear?)**:加入 taker 我方费率 后"市价清仓"动作变贵,最优策略改变;我方费率 返佣改变最优报价距离;归一化日 PnL(利润/平均点差)不能换算成 bp;市场状态变量入状态空间会发散(Table 5 full-state 全负)。
- **Evidence (paper + empirical result, with numbers)**:Table 5:非对称阻尼 η=0.6,HSBA.L 13.88±10.60、VOD.L 9.63±6.94(×10⁴ 归一化日 PnL);基本代理 HSBA.L −12.45±155.31;合并代理 Table 6:HSBA.L 15.43±13.01、平均绝对仓位 104 vs 固定 θ=5 的 2.80±10.30、2678。10 只欧洲股票,2010 年,样本外 40 天。
- **Test (the exact experiment we should run on KuCoin Futures data: contract type, data needed, statistic, pass/fail threshold)**:BTC-USDT 与 ETH-USDC 永续,U15 规则策略(不上 RL)。训练日按两种目标选参:(a)净 PnL;(b)净 PnL − max(0, η·Σ Inv·Δm),η∈{0.1, 0.3, 0.6}。考卷 9 天配对比较。通过:(b) 的日均 |Inv| 下降 ≥30%、日 PnL 方差下降 ≥20%、净 PnL(含返佣/手续费)≥(a) 的 95%;任一不满足则不采纳。

### 7.4 假设卡 — Milionis et al. (2022) LVR
- **Strategy hypothesis (what is the edge?)**:被动挂单在"改价延迟 τ"内等价于不改价的 CFMM;其逆向选择损失率 ≈ ½σ²×边际流动性,可用 σ²(BPV)线性预测并据此设定最小价差/撤单阈值。
- **Economic mechanism (why should this edge exist?)**:价格变动 dP 时陈旧报价以割线价成交,损失 dx·dP/2;累计即二次变差乘以报价量对价格的斜率(Lemma 2);与 Budish 等的 sniping 同源。
- **Required data (L1 / L2 / L3 / trades / order events)**:L1 中价(σ²)、trades(我方被动成交与 markout)、我方挂单量/档位(回测输出或实盘订单事件)。
- **Holding horizon (1ms / 10ms / 100ms / …)**:陈旧窗口 τ ≈ 行情 2.2 ms + 下单 1 ms ≈ 3 ms;统计窗口 1 min。
- **Expected signal (what observable predicts the edge?)**:σ²_t × 我方在 ±σ√τ 范围内的挂单量。
- **Execution dependency (queue / latency / fill probability)**:完全由延迟 τ 与排队位置决定(排在队首更容易被陈旧成交);腰部币 tick ≥1 bp 时 σ√τ ≪ 1 tick,损失集中在"中价跨 tick"的少数时刻。
- **Failure modes (why might it disappear?)**:GBM/无跳假设——跳跃时损失不是 σ² 线性;我方并非从不改价;CEX 上没有"无限深的参考市场",参考价本身有噪声;BTC tick ≈0.01 bp 时排队优先完全由速度决定,公式低估损失。
- **Evidence (paper + empirical result, with numbers)**:CPMM ℓ/V = σ²/8;日波动 5% → 3.125 bp/天(p.30);Uniswap v2 ETH-USDC:99.991% 的 LP PnL 方差是市场 β,1 分钟对冲后残差 0.009%(p.4)。AMM 数据,非 CEX 永续。
- **Test (the exact experiment we should run on KuCoin Futures data: contract type, data needed, statistic, pass/fail threshold)**:BTC-USDT 与 SOL-USDC 永续回测(排队最前,延迟按 3 ms)。每分钟输出被动成交名义 Q_t、成交后 3 ms 与 1 s markout 损失 L_t(bp×名义)、BPV σ²_t。回归 L_t = a + b·σ²_t·Q_t。通过:b 的 95% 区间 >0 且 R²≥0.3(考卷 9 天中 ≥6 天成立),则以 b 作为 tox/最小价差门限的归一化常数;否则不采用 σ² 线性门限。

---

## 8. 每篇论文给我方的"KuCoin Futures 上可证伪的假设"

| 论文 | 可证伪假设(KuCoin USDT/USDC 永续;maker 我方费率/我方费率,taker 我方费率,下单单程 ~1 ms,行情单程 ~2.2 ms,回测排队最前) | 证伪条件 |
|---|---|---|
| A Bergault et al. 2021 | 用 Γ 矩阵联合偏斜的多品种 U15(ETH/SOL/SUI/XRP USDC 永续)在同等成交量下日均 qᵀΣq 比逐品种偏斜低 ≥30% 且净 PnL 不降 | 考卷 9 天中 <6 天满足,或成交量降 >10% |
| B Barzykin et al. 2025 | (i)BTC-USDT 上"成交后 markout 对报价距离的斜率 β"与"成交强度衰减 κ"之差显著非零,按 §5.3 公式修正后 markout 损失降 ≥20%;(ii)ETH-USDC 上显示偏斜 ±1 tick 会改变后续 5 s 对手主动成交方向(price reading 存在) | (i)β−κ 的 95% 区间含 0,或修正后 PnL 配对差为正 <6/9 天;(ii)χ² p≥0.01 |
| C Almgren & Chriss 2000 | 对冲节奏按 θ=√(η/(λσ²)) 归一化后,对冲净成本(bp/名义,含 taker 我方费率)比固定毫秒版低 ≥10% 且库存风险不升 | 配对差 <6/9 天满足 |
| D1 Corsi 2009 | 三尺度 HAR-BPV 对下一分钟波动的样本外 R² 比 AR(1) 高 ≥0.05 | R² 增量 <0.05 或 QLIKE 不更低(≥6/9 天口径) |
| D2 Barndorff-Nielsen & Shephard 2004 | 跳跃检验 z>2.33 的窗口之后 1 分钟内,排队最前挂单的 markout 比其它时段差 ≥0.2 bp;加闸门后 markout 损失降 ≥15%、成交量降 ≤10% | markout 差 <0.2 bp 或 t<2.5;或闸门回测不达标 |
| D3 Bollerslev 1986 | 分钟级上 GARCH(1,1) 的波动预测不优于 HAR-BPV | GARCH 的 R² 高出 HAR ≥0.05 于 ≥6/9 天 → 假设被证伪,改用 GARCH |
| E Epps 1979(经 Tóth-Kertész 2009、Münnix et al. 2010;原文未获得) | SOL 对 BTC 的 1 s 收益相关 <0.7×1 min 相关,滞后互相关峰 τ*≥50 ms(BTC 领先);用 BTC 100 ms 收益修正 SOL 中价使 markout 改善 ≥0.1 bp/成交 | ρ 比值 ≥0.7,或 τ*<50 ms,或区间含 0,或 markout 改善 <0.1 bp |
| F1 Lo 2002 | 在 T≈30 小时上,我方各变体小时 SR 的 95% 区间互相重叠(不可区分) | 存在一对变体区间不重叠且配对差 t≥2.5 |
| F2 Bailey & López de Prado 2014 | 现行"取最优变体"的 DSR<0.95(最优 SR 不超过零技能期望最大值) | 在 ≥142 小时样本上被选变体 DSR≥0.95 |
| F3 Bailey et al. 2017 | 我方参数选择流程 PBO≥0.5(N≥20、T≥240 h、S=8 的 CSCV) | φ≤0.2 且 OOS 亏损概率 ≤0.3 |
| F4 Bergstra & Bengio 2012 | U15 归一化参数的响应面有效维度 ≤2(≥80% PnL 方差由 ≤2 个参数解释) | 需要 ≥3 个参数才能解释 80% 方差 |
| G1 Spooner et al. 2018 | 用非对称阻尼目标选参,日均 \|Inv\| 降 ≥30%、PnL 方差降 ≥20%、净 PnL ≥ 原目标选参的 95% | 三条任一不满足 |
| G2 Milionis et al. 2022 | 每分钟被动成交的 markout 损失与 σ²_t×被动成交量成正比(斜率 >0,R²≥0.3) | 斜率 95% 区间含 0 或 R²<0.3 |

所有阈值为事先设定的通过/不通过标准,跑之前记入 research_log;考卷(09-02 起 9 天)只用于最终验证,不得调参;回测只用 KuCoin 数据。腰部币 tick ≥1 bp、点差 1–2 tick 时,偏斜/价差修正小于 0.5 tick 的部分无法以改价体现,只能体现为"单边撤单/退一档",各测试的报价层须按此离散化后再评估;BTC tick ≈0.01 bp 时修正可连续表达,但排队优先完全由速度决定。阈值本身(30%、20%、0.05、6/9 天等)是本文为使假设可证伪而设定的 [推导],不是论文给出的数字。
