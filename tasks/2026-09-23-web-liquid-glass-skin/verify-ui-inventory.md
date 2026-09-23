# verify_ui.py 断言清点（S0 · 换肤前置门禁）

> 目标文件：`tasks/2026-09-11-frontend-bento-redesign/verify_ui.py`（5436 行，只读清点，未修改任何文件）
> 说明：本机无写工具（工具集仅 read/grep/glob/web_search/yield），故完整清单以本文件承载，请原样落盘为 `local://verify-ui-inventory.md`。

---

## 分类汇总

### A 类｜结构 / 契约断言（换肤后必须保持，保留）

| 组 | 函数（行号范围） | 断言内容（关键行） | main() 调用点 |
|---|---|---|---|
| 视口基础 | `assert_viewport(w,h,m,expect_date)` `:4861-4902` | `.dash` 存在 `:4866`；`scrollW==innerW` 无横向溢出 `:4867`；`window.__chartFailed`false（Chart.js CDN）`:4868`；**canvas 位图==显示尺寸** `:4873-4875`；主图容器高度>0 `:4876`；KPI 4 张 `:4887`；概览 6 小卡 `:4888`；A股/美股有行 `:4889-4890`；自选可见有行 `:4891`；占位 1 个且文案「数据未接入」`:4892-4893`；trend tab 4 个 `:4894`；`isWeekendDate` 语义 `:4895-4896`；顶栏数据日与 `/api/latest.date` 同源 `:4901-4902` | `:4989`（五视口循环）、`:5167`（375 复测） |
| 1920 布局专项 | `main()` `:4998-5010` | row-kpi 5 列 `:4998`；row-main 2 列 `:4999`；row-3 3 列 `:5000`；row-news 2 列 `:5001`；侧栏贴底 sticky `:5007-5008`；z-index `topbar>sidebar>backdrop` `:5009-5010` | 同函数内 |
| G-9 双 tab/行重排 | `assert_g9` `:503-554` | 行4 2 列 `:511`；`#sectors` 3 子块 `:512`；占位计数/文案 `:514-515`；5 个契约 id 保留 `:517-518`；panel 2 个 `:519`；radio 未 `display:none`（坑①）`:522`；radio 前置同级（坑②）`:521`；nav 文案「板块表现」`:523`；两面板各有行 `:524-525`；默认 A股激活 `:526`；切美股 `:539`；切回 A股 + 锚点定位 `:553-554` | `:5034` |
| 悬停/吸附交互 | `assert_crosshair` `:557-635`、`assert_crosshair_snap` `:791-860`、`assert_crosshair_dpr2` `:863-886`、`assert_macro_cn_crosshair` `:889-944` | 插件挂载 `:583`/`:912`；tooltip 显示 `:602`；气泡格式 `:618`；移出回基线 `:623`；切 tab 实例唯一 `:633-634`；吸附误差<0.5px `:815-816`/`:882-883`/`:923-924`；`$crossSource` 列/集语义 `:832-834`；读数随 x 变 `:852`/`:930`；**CS-D2 canvas 位图==显示宽×2** `:879`；DPR=2 无 pageerror `:884` | `:5129`、`:5131`、`:5173`、`:5174` |
| 保真结构（非数值） | `assert_fidelity` `:990-1057` | 四列表图标数==行数 `:999-1006`；y 轴 position=right `:1010`/`:1054`；品牌字 MarketPulse `:1011`；旗/素材计数 `:1016-1018`；**nav=12 + 5 个跨页 href 全命中** `:1031-1033`；crosshair 在轴右侧仍出读数 `:1054` | `:5127` |
| 资讯 DOM/数据契约 | `assert_news` `:1123-1171` | `.news-item` 数==API 条数 `:1145-1146`；每行≤121 字 `:1147`；死元素清零 `:1149-1150`；href/title 合法 `:1153-1155`；summary≤120 `:1156-1157`；`white-space`/`overflow-x:auto` `:1166-1169`；`#news` 与 `#alerts` 等高（±2px）`:1170-1171` | `:5035` |
| 语义/骨架契约 | `assert_polish` `:1271-1322` | 千分位 `:1283-1285`；无溢出 `:1286-1287`；chg-pill 色与 `--green/--red` 同源 `:1288-1291`；未复用 `.pill` `:1292`；表头/数据对齐 `:1293-1294`；**模板源级 colspan/骨架类名** `:1310-1316`；数据到达骨架清零 `:1318`；无横向溢出 `:1322` | `:5036` |
| 美股表格同构 | `assert_us_table` `:1368-1455` | tab 切换 `:1382`；`<table>` 同构 `:1383-1385`；表头 5 列逐列相同 `:1386-1387`；有空态行 `:1388`；无 `.bar-row` 残留 `:1389`；表头右对齐 `:1390-1391`；空态文案 `:1393`；mock 5 行 `:1442`；两 tab 行数相等 `:1443-1444`；图标/chg-pill 计数 `:1445-1446`；右对齐 `:1447-1448`；无横向溢出 `:1452` | `:5037` |
| 数据日标注 | `assert_sector_asof` `:1517-1571`、`assert_asof_narrow` `:1574-1584` | 标注在 h2 内 `:1537`；A股/美股/切回文案 == 各自 `as_of`（期望取自 API）`:1548`/`:1563`/`:1566`；零增高 `:1568-1571`；375 零增高 `:1584` | `:5038`、`:5137` |
| 宏观页模块/口径 | `assert_macro_page` `:1640-1778`、`assert_macro_cn_page` `:1899-2075` | MX：7 模块 `:1674`；canvas 位图==显示 `:1676-1678`；胶囊/档位 `:1681-1684`；10Y 口径 `:1693-1695`；关系 2~3 条+展开 6 对 `:1700-1706`；数据月份 `:1714-1716`；无「最新/实时」`:1718`；归一化 100 `:1729-1731`；5Y 点数>1000 `:1735`；主题切换 `:1744-1745`；无横向溢出/单列 `:1753-1755`；降级 7 模块在位 `:1770-1774`。CN：模块 7 `:2007`；canvas 位图 `:2010-2012`；PMI 水平口径 `:2015-2016`；京沪 2 城 `:2018-2020`；chg title `:2024-2028`；bp 口径 `:2033-2043`；数据月份 `:2045-2048`；nav active `:2050-2051`；主题同源 `:2053`；胶囊 6 项 `:2054-2055`；无溢出 `:2056`/`:2068`；宽度覆盖度 5 档 `:2071` | `:5169`、`:5170` |
| 宏观 refinement / 悬停 | `assert_macro_refine` `:2078-2193`、`assert_macro_crosshair` `:2223-2330` | 主题分叉 `:2105-2110`；无横向溢出 `:2127`/`:2184`；关系口径自洽 `:2134-2142`；展开/收起 `:2143-2153`；两列/单列 `:2186`/`:2188`；XC 读数按轴语义分派 `:2265-2298`；吸附 `:2307-2314`；移出清空 `:2319`；重建不丢插件 `:2324-2326` | `:5171`、`:5172` |
| KPI 截断扫描 | `assert_kpi_no_truncation` `:2376-2420` | 12 宽度扫描覆盖率 `:2418`；仅报告项 `:2415-2416` | `:5175` |
| 市场状态 | `assert_market_session` `:2518-2661` | 同源钩子 `:2559`；DOM==`window.__marketSession` `:2561-2563`；两行/dot id/文案互异/北京时间 `:2567-2580`；MS-0 防空集假绿 `:2585-2588`；注入时刻表 `:2593-2594`；逐点着色 `:2604-2611`；三页逐字一致 `:2627-2632`；无滚动条/不溢出/贴底 `:2647-2657` | `:5176` |
| 四象限矩阵 | `assert_quadrant_matrix` `:2882-3079` | 4 格 `:2918-2919`/`:3053-3054`；文案与 QUADRANTS 同源 `:2920-2923`/`:3055-3056`；高亮位置下标 `:2926-2934`；断供 0 高亮 + 「数据暂缺」`:2954-2958`；375 无溢出 `:2974-2977`；CN mock `:3025-3033`；页间同源 `:3069-3072` | `:5178` |
| 宏观四态/chip | `assert_macro_states` `:3101-3477` | 骨架在场/清零 `:3131-3146`；失败条 `:3148-3150`/`:3234-3236`；11 块结算 `:3153-3155`；重试 3 次禁用 `:3207-3209`；只 warn 不 error `:3167-3169`/`:3211-3212`；chip/badge 计数 `:3238-3241`；素材/破图 `:3242-3251`；chip 在组内且 badge 在后 `:3257-3261`；中性行去重 `:3279-3284`；Score 语义色 `:3315-3318`；CN 零影响 `:3348-3351`；NA-11 方向同源+覆盖度 `:3384-3390`；双主题 `:3403-3405` | `:5177` |
| 首页体验/走查 | `assert_home_ux` `:3495-3614`、`assert_walkthrough` `:3705-3829` | UX-2 主题初始化隔离 app.js `:3545-3547`；UX-3 失败条/旧图/按钮态 `:3568-3612`；UX-4 抽屉锁滚动/焦点/Escape `:3627-3639`；PW-1/2/3 文案与表头语义 `:3733-3761`；PW-3b 模板源级 `:3757-3761`；PW-4 四态高度不变量 `:3785-3827` | `:5185`、`:5186` |
| 日历/值层/鉴权 | `assert_timeline` `:3883-4047`、`assert_timeline_values` `:4203-4414`、`assert_auth` `:4125-4194` | TL-0/2c 独立核算前提 `:3910`/`:3926`；db↔API↔DOM 对账 `:3932-3934`/`:3954-3956`；类型枚举/去重/因果措辞 `:3961-4000`；中文化与原文保留 `:4011-4024`；nav/200 `:4028-4032`；375 无溢出 `:4045`；EV 8 键 `:4229`；三方对账 `:4265-4267`；值渲染规则 `:4277-4280`/`:4289-4302`；「待公布」`:4315`；口径三条 `:4323`；EV-6/EV-11 降级与断点 `:4349-4412`；AUTH 401/200/healthz/凭据 `:4151-4191` | `:5179`、`:5180`、`:5181` |
| 滚动/A11y | `assert_autoscroll` `:4615-4725`、`assert_reduced_motion` `:4728-4745`、`assert_short_content` `:4818-4842`、`assert_firefox_scrollbar` `:4777-4815` | 双份内容/aria-hidden `:4637-4640`；滚动生效/暂停/恢复 `:4657-4675`；回绕不变量 `:4688-4695`；两半一致 `:4698-4699`；速率 `:4703`/`:4721`；reduce-motion `:4741-4744`；不足一屏不滚 `:4837-4840` | `:5050-5054`、`:5191` |
| 回测/设置/组合 | `assert_backtest` `:5242-5301`、`assert_settings` `:5338-5367`、`assert_portfolio` `:5400-5432` | BT 标题/概览/行数对账/口径/7 条/375 无溢出/nav `:5264-5299`；ST 参数在场/8+4 行/按钮/边界/nav/无溢出 `:5348-5365`；PF 6 列/每行盈亏/不显示假收益/概览对账/色命名空间 `:5415-5430` | `:5182`、`:5183`、`:5184` |
| console error=0（LG-1 对标） | 分散在 10 处 | `:884`（CS-D4 DPR=2）、`:942`（CNC-6）、`:1721`（MX-15）、`:2073`（CN-11）、`:2191`（M-9b 三档）、`:2328`（XC-9）、`:2632`（MS-5c 三页）、`:2659`（MS-7）、`:5103`（tab 切换）、`:5187`（全流程） | 各调用点 |

### B 类｜视觉数值断言（**必须重写**）

> 格式：`函数(行号)` + 断言原文 + 当前期望值/区间 + 测量选择器

#### B-1 玻璃判据组（G-1，主战场）

**`GLASS_RANGES` `:389-394`（区间表本身）**
```python
GLASS_RANGES = {
    "dark": {"kpiMax": 0.2, "dataLo": 0.6, "dataHi": 0.8,
             "highlight": (0.04, 0.15), "border": (0.15, 0.30)},
    "light": {"kpiMax": 1.0, "dataLo": 0.5, "dataHi": 1.01,
              "highlight": (0.85, 1.01), "border": (0.75, 1.01)},
}
```

| 行号 | 断言原文（摘） | 期望值/区间 | 选择器 / 来源 |
|---|---|---|---|
| `:408-409` | `check(g["glassCovered"], f"{w} 卡片 backdrop-filter 全覆盖（{g['coveredCount']}/{g['cardCount']}）", ...)` | `True`（全体非 none） | `.card:not(.card.promo), .kpi-card`（`GLASS_JS:342`），`backdropFilter !== 'none'` |
| `:410-411` | `check((g["promoBackdrop"] or "none") == "none", f"{w} promo 卡显式 backdrop-filter=none（1b）")` | `"none"` | `.card.promo` |
| `:412-413` | `check(g["kpiAlpha"] is not None and g["kpiAlpha"] < r["kpiMax"], f"{w} .kpi-card 背景 alpha < {r['kpiMax']}")` | dark `<0.2`；light `<1.0` | `.kpi-card` 的 `backgroundColor` alpha |
| `:414-416` | `check(a is not None and r["dataLo"] <= a <= r["dataHi"], f"{w} 数据卡 {sel} alpha ∈ [{r['dataLo']}, {r['dataHi']}]")` | dark `[0.6,0.8]`；light `[0.5,1.01]` | `#overview` `#trend` `#alerts` 的 `backgroundColor` alpha |
| `:417` | `check(g["bodyLayers"] >= 2, f"{w} body 氛围渐变层 ≥ 2")` | `≥2` | `body` 的 `backgroundImage` 中 `gradient(` 计数 |
| `:419-420` | `check(g["highlightAlpha"] is not None and lo <= g["highlightAlpha"] <= hi, f"{w} 顶边内高光白 alpha ∈ [{lo}, {hi}]")` | dark `[0.04,0.15]`；light `[0.85,1.01]` | `#overview` `box-shadow` 中 `inset` 段的白色 alpha 最大值 |
| `:422-423` | `check(g["borderAlpha"] is not None and lo <= g["borderAlpha"] <= hi, f"{w} 卡片边框 alpha ∈ [{lo}, {hi}]")` | dark `[0.15,0.30]`；light `[0.75,1.01]` | `#overview` `borderTopColor` alpha |
| `:424-425` | `check(g["shadowBlur"] is not None and g["shadowBlur"] >= 24, f"{w} 卡片外阴影模糊半径 ≥ 24px")` | `≥24px` | `#overview` `box-shadow` 非 inset 段第 3 个长度 |
| `:427-428` | `check((g["topbarBackdrop"] or "none") != "none", f"{w} .topbar backdrop-filter 生效")` | `!= none` | `.topbar` `backdropFilter` |
| `:433-435` | `check((g["sidebarBackdrop"] or "none") == "none", f"{w} #sidebar 无 backdrop-filter（两个分支共同要求）")` | `none` | `#sidebar` |
| `:437-439` | `check((g["sidebarBg"] or "") in ("rgba(0, 0, 0, 0)", "transparent"), f"{w} #sidebar 透明且无 backdrop-filter（G-6：桌面与页面同层）")` | 透明 | `#sidebar`（`w>768` 分支） |
| `:441-443` | `check((g["sidebarBg"] or "") == (g["elevatedBg"] or ""), f"{w} #sidebar 抽屉为实底 --bg-elevated …")` | 等于 `--bg-elevated` 解析值 | `#sidebar`（`≤768` 分支），`elevatedBg` 由探针 div 解析 CSS 变量得到 |
| `:444-445` | `check(g["hasFallbackRule"] is True, f"{w} 存在 backdrop-filter 的 @supports 降级块（G-8）")` | `True` | CSSOM 中 `CSSSupportsRule.conditionText` 含 `backdrop-filter` |

#### B-2 总高基线 `scrollHeight ≤ 1240`（6 处，硬编码）

| 行号 | 断言原文 | 期望 | 来源 |
|---|---|---|---|
| `:586` | `check(sh <= 1240, "CS-5 scrollHeight @1920 ≤ 1240", sh)` | `≤1240` | `document.scrollingElement.scrollHeight` |
| `:1035` | `check(m["scrollH"] <= 1240, "F-6a scrollHeight @1920 ≤ 1240", m["scrollH"])` | `≤1240` | `MEASURE_JS` `:283` |
| `:1321` | `check(d["scrollH"] <= 1240, "P-7a scrollHeight @1920 ≤1240", d["scrollH"])` | `≤1240` | `POLISH_JS` `:1258` |
| `:1451` | `check(scroll_h <= 1240, "U-6 mock 5 行后 scrollHeight @1920 ≤1240", scroll_h)` | `≤1240` | 页面 evaluate |
| `:4724` | `check(d["scrollH"] <= 1240, f"{p}-10a scrollHeight @1920 ≤1240", d["scrollH"])` | `≤1240` | `autoscroll_js` `:4455` |
| `:5003` | `check(m["scrollH"] <= 1240, "1920 页面总高 ≤ 1240（≤1.15 屏）", m["scrollH"])` | `≤1240` | `MEASURE_JS` |

#### B-3 硬编码几何 / 尺寸 / 令牌色值

| 行号 | 函数 | 断言原文（摘） | 期望值 | 选择器 / 来源 |
|---|---|---|---|---|
| `:1008` | `assert_fidelity` | `check(f["icoSize"][0] == 16 and f["icoSize"][1] == 16, "F-1e 图标尺寸 16×16", f["icoSize"])` | `16×16` | 首个 `.ico` 的 `offsetWidth/offsetHeight`（`FIDELITY_JS:982`） |
| `:1012-1013` | `assert_fidelity` | `check(f["avatarRadius"] is not None and f["avatarRadius"] != "50%", "F-4 头像为圆角方块（radius≠50%）")` | `≠50%` | `.avatar` `borderRadius` |
| `:1038-1039` | `assert_fidelity` | `check(g.get("glassCovered") is True, "F-6c backdrop 全覆盖", …)` | `True` | 同 `:408-409` |
| `:1151-1152` | `assert_news` | `check(dom["overflowY"] == "auto" and dom["maxHeight"] == "132px", "N-4 #news-body max-height 132px + overflow-y auto")` | `132px` + `auto` | `#news-body` computed |
| `:1159-1161` | `assert_news` | `check(dom["sbRuleWidth"] == "6px", "N-11a 样式表含 ::-webkit-scrollbar{width:6px}（系统默认 15px）")` | `6px` | CSSOM `::-webkit-scrollbar{width}`（`NEWS_JS:1107-1117`） |
| `:1162-1164` | `assert_news` | `check(all((v is not None and v <= 8) for v in dom["scrollbarW"].values()), "N-11b 各滚动容器实测宽 ≤8px …")` | `≤8px` | `#news-body` / `.alert-list` / `#sidebar` |
| `:1165` | `assert_news` | `check(dom["weight"] == "400", "N-8 .news-item a 字重 400（它是正文不是标题）")` | `"400"` | `#news-body .news-item a` `fontWeight` |
| `:1281-1282` | `assert_polish` | `check(d["muted"].upper() == "#8E9BAE", "P-1 dark --text-muted = #8E9BAE（对比度 ≈6.9:1）", d["muted"])` | `#8E9BAE` | `getComputedStyle(document.documentElement).getPropertyValue('--text-muted')`（`POLISH_JS:1180`） |
| `:1449-1450` | `assert_us_table` | `check(bool(m["chgCells"]) and all(c["pad"] == "3px/3px" for c in m["chgCells"]), "U-4c td.chg padding 3px（P-3 零增高对冲…）")` | `3px/3px` | `#us-sectors-body tr td.chg` 的 `paddingTop/paddingBottom`（`US_TABLE_JS:1350-1353`） |
| `:1580-1583` | `assert_asof_narrow` | `check(d["h2ClientH"] is not None and d["lineHeight"] is not None and d["h2ClientH"] <= d["lineHeight"] * 1.6, "V-7 375 档 h2 未换行（单行：clientHeight ≈ line-height）")` | `clientHeight ≤ line-height×1.6` | `#us-sectors .card-head h2`（`ASOF_JS`） |
| `:1679-1680` | `assert_macro_page` | `check(d["chartWrapH"] is not None and d["chartWrapH"] >= 300, "MX-3b 主图容器有确定高度 ≥300px（R1/C2）")` | `≥300px` | `#macro-chart-wrap` |
| `:2066-2067` | `assert_macro_cn_page` | `check(m["chartWrapH"] is not None and abs(m["chartWrapH"] - exp) <= 2, f"CN-10b {vw} 主图容器 ≈{exp:.0f}px（clamp 生效，非固定值）")` | `clamp(340px,46vh,560px)`（`≤768` 为 `clamp(360px,48vh,420px)`）±2px | `#cn-chart-wrap`；期望值由 `_expect_chart_wrap_h` `:1889-1896` 现算 |
| `:2156-2157` | `assert_macro_refine` | `check(d["regimeIsCard"] is False and str(d["regimeBorderTop"]).startswith("0"), "M-7 「当前宏观环境」为无边框区块（不再是等权卡片）")` | `borderTopWidth == 0` 且无 `.mac-card` | `#mac-regime` |
| `:2159-2160` | `assert_macro_refine` | `check(d["factorsSlack"] is not None and d["factorsSlack"] <= 20, "M-6 宏观因子列额外留白 ≤ 20px（D5 改前 77px）")` | `≤20px` | `#mac-factors`（slack = 高 − 标题 − 子元素 − padding，`MACRO_REFINE_JS:1805-1812`） |
| `:2171-2172` | `assert_macro_refine` | `check(bool(bw) and len(set(bw)) > 1 and max(bw) >= 2.0 and min(bw) <= 1.4, "M-4 全部对比：选中序列描边显著重于其他（有主次，D3）", bw, deps=("macro",))` | `max≥2.0` 且 `min≤1.4` | `Chart.data.datasets[].borderWidth` |
| `:2189-2190` | `assert_macro_refine` | `check(dv["chartWrapH"] is not None and dv["chartWrapH"] >= 360, "M-8 375 档主图高 ≥360px（D11 改前 325px）")` | `≥360px` | `#macro-chart-wrap` @375 |
| `:2408-2410` | `assert_kpi_no_truncation` | `check(not d["bad"], f"KY-1 W={w} KPI（数值/副标题/标签）无省略号截断", …)` | 无元素 `scrollWidth > clientWidth+1` | `.kpi-val, .kpi-sub, .kpi-label`（`SCAN_JS:2340`） |
| `:2643-2644` | `assert_market_session` | `check(g.get("footerH") == 65, f"MS-6a {w}x{h} .sidebar-footer 高 65（45+18+2，F1 .ms-time 11px）", g.get("footerH"), 65)` | `==65` | `.sidebar-footer`（`MS_JS:2492`） |
| `:2645-2646` | `assert_market_session` | `check(g.get("msH") == 52, f"MS-6b {w}x{h} .market-status 高 52（16+16+17+gap2×2）", g.get("msH"), 52)` | `==52` | `.market-status`（`MS_JS:2493`） |
| `:3252-3253` | `assert_macro_states` | `check(d["factorsSlack"] is not None and d["factorsSlack"] <= 20, "NA-6 加 chip 后 #mac-factors 留白仍 ≤20px（M-6 上限；基线 12px）")` | `≤20px` | `#mac-factors`（`NA_JS:2733-2741`） |
| `:3352-3353` | `assert_macro_states` | `check(cn["rowCols"] == ["72px", "70px"], "NA-8b 共享 .mac-factor-row 网格未被改（CN 页仍是 72px/70px）")` | `["72px","70px"]` | `#cn-factors .mac-factor-row` `gridTemplateColumns` 前两段（`CN_NA_JS:3338`） |
| `:3518-3519` | `assert_home_ux` | `check(c_muted >= 4.5, f"UX-1 {theme} --text-muted 对页底对比度 ≥4.5（走查报告：light 2.54:1）", round(c_muted, 2))` | `≥4.5:1` | `--text-muted` vs `body` 首个非透明祖先底色（`HOME_UX_JS:3426`/`:3430`） |
| `:3523-3524` | `assert_home_ux` | `check(c_ixic >= 4.5, "UX-1b light --c-ixic（被 .chart-meta 当文字色用）对比度 ≥4.5（原 #13C2C2 ≈2.21:1）")` | `≥4.5:1` | `--c-ixic` vs `.card` 底色（仅 light） |
| `:3526-3527` | `assert_home_ux` | `check(d["msTimeFont"] is not None and d["msTimeFont"] >= 11, "UX-5 .ms-time 字号 ≥11px（走查报告：10px 过小）")` | `≥11px` | `.ms-time` `fontSize` |
| `:3529-3531` | `assert_home_ux` | `check(d["sidebarBg"] in ("rgba(0, 0, 0, 0)", "transparent"), "UX-1c 桌面端 #sidebar 保持透明（G-6 不回退；透明只允许出现在 >768）")` | 透明 | `#sidebar` @1440 |
| `:3641-3643` | `assert_home_ux` | `check(d2["sidebarBg"] == d2["elevatedBg"] and d2["elevatedBg"] is not None, "UX-4e 抽屉为实底 --bg-elevated（覆盖层不可透；修复前为 rgba(0,0,0,0)）")` | 等于 `--bg-elevated` | `#sidebar` @375 |
| `:4641-4642` | `assert_autoscroll` | `check(d["offsetHeight"] <= 132 and d["maxHeight"] == "132px", f"{p}-3 容器高 ≤132 且 max-height=132px（护栏不变）")` | `132px` | `#news-body` / `#alert-list` |
| `:4643-4647` | `assert_autoscroll` | `check(d["offsetHeight"] == 132, f"{p}-3b 内容超限时恰好钳在 132px …")` / `check(d["offsetHeight"] <= 132, …)` | `==132` / `≤132` | 同上 |
| `:4811-4812` | `assert_firefox_scrollbar` | `check("auto" not in str(d["scrollbarColor"]) and "rgb" in str(d["scrollbarColor"]), "N-12a Firefox 下 scrollbar-color 被主题色覆盖（证明 -moz-appearance 门控在 FF 命中）")` | 非 `auto` 且含 `rgb(` | `#news-body` computed `scrollbar-color`（`FF_SCROLLBAR_JS:4749`） |
| `:4814-4815` | `assert_firefox_scrollbar` | `check(d["gateScrollbarWidth"] == "thin", "N-12b CSSOM 内 Firefox 门控块含 scrollbar-width:thin")` | `"thin"` | CSSOM 门控块 |
| `:4882` | `assert_viewport` | `check(card.get("boxSizing") == "border-box", f"{w} .card box-sizing=border-box", …)` | `border-box` | `#overview`（`MEASURE_JS:215`） |
| `:4883` | `assert_viewport` | `check(card.get("borderRadius") == "12px", f"{w} .card 圆角 12px", card.get("borderRadius"))` | **`12px` 硬编码** | `#overview` `borderRadius` |
| `:4884` | `assert_viewport` | `check(bool(card.get("shadow")), f"{w} .card 有卡片阴影")` | `boxShadow !== 'none'` | `#overview` |
| `:5002` | `main()` | `check(m["chartWrapH"] == 432, "主图容器 = 40vh = 432px", m["chartWrapH"])` | **`==432`** | `#chart-main-wrap` |
| `:5004-5005` | `main()` | `check(m["kpiBox"] and m["kpiBox"]["w"] >= 260 and m["kpiBox"]["h"] >= 96, "KPI 卡 ≥260×96")` | `≥260×96` | `.kpi-card` rect |
| `:5074-5076` | `main()` | `check(bg_before != theme_after["bg"], "切换后卡片底色变化", …)` / `check(border_before != theme_after["border"], "切换后卡片边框色变化（断言 12）", …)` | 颜色**必须变化** | `#overview` `backgroundColor` / `borderTopColor`；`border_before` 取自 `GLASS_JS.borderRaw` |
| `:5164` | `main()` | `check(mob["chartWrapH"] == 280, "375 主图高度 280px", mob["chartWrapH"])` | **`==280`** | `#chart-main-wrap` @375 |

#### B-4 次级（不钉死数值，但换肤后**须重新取数核对**）

| 行号 | 断言 | 为何要复核 |
|---|---|---|
| `:1568-1571` | V-5 「标注零增高」（h2 与卡片高度不变） | 新皮肤若改 h2/行高（字体替换）会连带改变 |
| `:1584` | V-7b 375 零增高 | 同上 |
| `:347` `GLASS_JS:228-233` | `.card:not(.card.promo), .kpi-card` 覆盖集 | 换肤后卡片集合/类名若变，`coveredCount/cardCount` 分母随之变 |
| `:296` `GLASS_JS` | `bodyLayers` 统计口径（`gradient(` 计数） | 新背景改为「16px 方格纸 + 光斑」（plan D-3/D-6）后该口径要重定义 |
| `:439` / `:441` | `elevatedBg` 探针依赖 `--bg-elevated` 未改名 | 若皮肤重命名令牌，探针静默取到空值 |
| `:1288-1291` | P-4 `.chg-pill` 色 == `--green`/`--red` 现场解析 | 自洽性断言，令牌改名/作用域被覆盖（plan R5）即红 |
| `:2607-2611` | MS-4b/4c 点色 == `--green`/`--text-muted` | 同上 |
| `:470  ` 附近 `SCAN_JS` | KY-1 依赖字体度量 | 换字体（含数字字体）会改变截断边界 |

### C 类｜页面与分组索引（新增 LG-* 的挂载点）

#### C-1 既有分组 ID 前缀 → 函数 → 行号范围 → 调用点

| 前缀 | 函数 | 行号范围 | main() 调用点 |
|---|---|---|---|
| G-1（玻璃） | `assert_glass(w,h,g)` | `397-445` | `:4991`（五视口循环）、`:5079`（light 复跑） |
| G-9（双 tab/行重排） | `assert_g9(page,g9)` | `503-554` | `:5034` |
| CS / CS-2a·2b·3~10 | `assert_crosshair(page)` | `557-635` | `:5129` |
| CS-8/8b/9/10 | `assert_crosshair_snap(page)` | `791-860` | `:5131` |
| CS-D0~D4 | `assert_crosshair_dpr2(browser,url)` | `863-886` | `:5174` |
| CNC-0~6 | `assert_macro_cn_crosshair(browser,url)` | `889-944` | `:5173` |
| F-1~F-8 | `assert_fidelity(page,m)` | `990-1057` | `:5127` |
| N-1~N-11 | `assert_news(page,base_url)` | `1123-1171` | `:5035` |
| P-1~P-8 | `assert_polish(page,base_url)` | `1271-1322` | `:5036` |
| U-1~U-7 | `assert_us_table(page,browser,url)` | `1368-1455` | `:5037` |
| V-1~V-6 | `assert_sector_asof(page,url)` | `1517-1571` | `:5038` |
| V-7 | `assert_asof_narrow(page)` | `1574-1584` | `:5137` |
| MX-1~MX-15 | `assert_macro_page(browser,url)` | `1640-1778` | `:5169` |
| CN-1~CN-14 | `assert_macro_cn_page(browser,url)` | `1899-2075` | `:5170` |
| MR / M-1~M-10 | `assert_macro_refine(browser,url)` | `2078-2193` | `:5171` |
| XC-0~XC-9 | `assert_macro_crosshair(browser,url)` | `2223-2330` | `:5172` |
| KY-1~KY-3 | `assert_kpi_no_truncation(browser,url)` | `2376-2420` | `:5175` |
| MS-0~MS-7 | `assert_market_session(browser,url)` | `2518-2661` | `:5176` |
| QM-1~QM-5 | `assert_quadrant_matrix(browser,url)` | `2882-3079` | `:5178` |
| NA-1~NA-11 | `assert_macro_states(browser,url)` | `3101-3477` | `:5177` |
| UX-1~UX-5 | `assert_home_ux(browser,url)` | `3495-3614` | `:5185` |
| PW-1~PW-4 | `assert_walkthrough(browser,url)` | `3705-3829` | `:5186` |
| TL-0~TL-10 | `assert_timeline(browser,url)` | `3883-4047` | `:5179` |
| EV-1~EV-11 | `assert_timeline_values(browser,url)` | `4203-4414` | `:5180` |
| AUTH-1~AUTH-5 | `assert_auth(browser)` | `4125-4194` | `:5181` |
| A-*（资讯滚动） | `assert_autoscroll(page,url,CFG_NEWS)` | `4615-4725`（cfg `:4603-4607`） | `:5050` |
| B-*（告警滚动） | `assert_autoscroll(page,url,CFG_ALERTS)` | 同上（cfg `:4608-4612`） | `:5051` |
| A/B-11 | `assert_reduced_motion(browser,url,cfg)` | `4728-4745` | `:5053` |
| A/B-12 | `assert_short_content(browser,url,cfg)` | `4818-4842` | `:5054` |
| N-12 | `assert_firefox_scrollbar(p,url)` | `4777-4815` | `:5191` |
| （无前缀，视口通用） | `assert_viewport(w,h,m,expect_date)` | `4861-4902` | `:4989`、`:5167` |
| BT-1~BT-8 | `assert_backtest(browser,url)` | `5242-5301` | `:5182` |
| ST-1~ST-7 | `assert_settings(browser,url)` | `5338-5367` | `:5183` |
| PF-1~PF-5 | `assert_portfolio(browser,url)` | `5400-5432` | `:5184` |
| —— | `main()` 内联断言（无前缀） | `:4998-5010`、`:5018-5024`、`:5071-5077`、`:5101-5110`、`:5123-5124`、`:5161-5165`、`:5187` | — |

> 现状：**`LG-*` 前缀在 verify_ui.py 中零命中**（`grep LG-|SKIN|skin` → No matches），plan §6.2 `:210-211` 的 LG-1~LG-10 尚待新建。

#### C-2 新增一组断言要改哪里（接线点，全部带行号）

1. **结果登记 / SKIP 语义**：`check(cond, label, actual=None, expect=None, deps=())` `:130-157`
   - `N_PASS += 1`（`:141`）；`deps` 命中且 `UPSTREAM[dep] is False` → `SKIPPED.append({label, reason, detail})`（`:144-149`）；否则 `FAILURES.append(...)`（`:153`）。
   - `deps=()` 默认 **永不 SKIP**（LG 组应保持默认，皮肤回归与上游无关，与 plan §2.4① 口径一致）。
2. **全局状态**：`FAILURES` `:37`、`SKIPPED` `:40`、`N_PASS` `:42`、`UPSTREAM` `:45`、`STRICT` `:48`、`VIEWPORTS` `:35`、`OUT_DIR` `:30`、`ROOT/PY` `:28-29`。
3. **汇总与退出码**：`summarize_and_exit(strict=None)` `:4905-4937` —— `:4915` 三数合计、`:4917-4920` 打印 PASS/FAIL/SKIP、`:4922-4926` SKIP>50% 警告、`:4927-4930` 有 FAIL⇒`return 1`、`:4931-4934` 有 SKIP ⇒ strict?1:0、`:4936` ALL PASSED；`main()` 末尾 `:5239` `return summarize_and_exit(STRICT)`。**新增组不需要改汇总代码**，只要用 `check()`。
4. **上游探测（决定 SKIP）**：`_probe_get` `:57-86`、`_probe_bls` `:88-109`、`probe_upstream` `:111-128`；`main()` 内触发于 `:4956`，`MP_VERIFY_UPSTREAM_DOWN=1` 强制 DOWN 用于验证分层机制。
5. **起服务**：`free_port()` `:167-171` → `main()` `:4942`；`wait_ready(url,40)` `:173-183` → `:4968`；`os.environ["MP_AUTH_DISABLED"]="1"` `:4952`；`subprocess.Popen([PY, "-m", "uvicorn", "web.app:app", "--port", port], cwd=ROOT)` `:4962-4965`；`proc.terminate()/kill()` `:5193-5198`。
6. **浏览器基座**：`p.chromium.launch()` `:4977`；`browser.new_page(viewport=1920x1080, device_scale_factor=1)` `:4978`；`page.add_init_script("localStorage.setItem('mp-theme','dark')")` **`:4982`**（LG 主题断言要沿用这个固定口径）；console/pageerror 收集器 `:4983-4985`；五视口循环 `:4987-4993`。
7. **截图**：无独立函数，一律 `page.screenshot(path=str(OUT_DIR / "shot-*.png"), full_page=True)`；现例 `:1723`（macro-1920）、`:1747`（macro-dark）、`:1756`（macro-375）、`:5041-5047`（asof-us/cn）、`:3343`（na-cn）、`:3401`（na-macro-theme）、`:4847`（measure 内 shot-{w}x{h}.png）。报告 JSON 写入 `OUT_DIR / "verify-report.json"` `:5208-5210`。
8. **测量辅助函数（LG-* 直接可复用）**：
   - `measure(page,url,w,h)` `:4845-4858`（切视口→goto→等 `#watchlist-section:not(.hidden)`→`MEASURE_JS`→整页截图）
   - `MEASURE_JS` `:185-287`（几何/溢出/栅格/canvas/令牌聚合）、`GLASS_JS` `:290-387`（玻璃与令牌 alpha/阴影/降级块）
   - `HOME_UX_JS` `:3414-3465`（对比度用的 `--text-muted`/`--c-ixic`/祖先底色/字号/抽屉态）、`_contrast(fg,bg)` `:3480-3492`（WCAG）
   - `api_latest(url)` `:1505-1514` + `_LATEST_CACHE` `:1502`（期望值取自数据，不写死日期）
   - `_na_open(browser,url,handler,*,timeout_ms,viewport)` `:3082-3099`（带 mock 的独立 context，返回 `(ctx,page,console_msgs,pageerrors)`）
   - `_http_status(url,user,pwd)` `:4110-4122`（原始 HTTP + Basic 凭据）
   - `_tpl(js,cfg)` `:4422-4427` + `autoscroll_js/sample_js/wrap_js/halves_js/rate_js` `:4430-4589`（滚动/动效类探针模板）
   - `_expect_chart_wrap_h(vw,vh)` `:1889-1896`（从 CSS clamp 推导期望而非写死）、`_ms_js/_ms_labels` `:2508-2515`、`_has_pair` `:2812-2814`、`_date_from_iso` `:4417-4419`
9. **新增组织的建议插入点**：定义紧随 `assert_timeline_values` 之后 / `_date_from_iso` 之前（`:4415` 附近），或与 BT/ST/PF 一样追加到文件末尾 `assert_portfolio` 之后（`:5433`）；调用点插在 `main()` `:5186 assert_walkthrough(...)` 之后、`:5187 check(not errors, ...)` 之前 —— 这样 LG 组触发的 console error 会被 `:5187` 的全流程收口，同时 LG 可自带 `LG-1 console error=0`（对标既有 10 处 console 断言）。
10. **静态资源指纹**：新增皮肤静态文件需登记 `web/app.py` `_ASSET_FILES`（plan `:143`），与 verify_ui.py 无耦合但属同批改动。

---

## 换肤必改清单（行号升序）

| 行号 | 改动点 | 为什么必须改 |
|---|---|---|
| `:389-394` | `GLASS_RANGES` dark/light 两套区间（kpiMax/dataLo/dataHi/highlight/border） | 换肤后宿主不再用 backdrop-filter + 半透明白，全部 alpha 区间失效；须按新材质重取基线（plan R3/§6.2） |
| `:408-409` | 卡片 `backdrop-filter` **全覆盖**（`.card:not(.card.promo), .kpi-card`） | S1「旧玻璃让位」要求宿主 backdrop-filter 关掉、改由 `.lg-inner` 承担 ⇒ 期望反转（宿主应≈none，`.lg-inner` 才是玻璃） |
| `:410-411` | `.card.promo` backdrop-filter=`none` | 同上，promo 与卡片的分工语义变化 |
| `:412-413` | `.kpi-card` 背景 alpha `<0.2`（dark） | 新面板染色 `color-mix(… 46%, transparent)`（plan D-7）⇒ alpha 由 <0.2 变 ≈0.46，恒 FAIL |
| `:414-416` | 数据卡 `#overview/#trend/#alerts` alpha ∈ `[0.6,0.8]`（dark） | 同上，染色 46% 后落在区间外 |
| `:417` | `body` 氛围渐变层 ≥2 | 背景换成「16px 方格纸 + 光斑」（plan D-3/D-6），层数口径需重定义（LG-10 纹理留存比替代） |
| `:419-420` | `#overview` 顶边内高光白 alpha ∈ `[0.04,0.15]` | 套件自带高光/描边参数不同 |
| `:422-423` | `#overview` 边框 alpha ∈ `[0.15,0.30]` | 同上 |
| `:424-425` | `#overview` 外阴影模糊 ≥24px | 套件阴影规格不同（须重取基线） |
| `:427-428` | `.topbar` backdrop-filter ≠ none | 顶栏改由 `.lg-inner` 上材质 ⇒ 宿主应让位 |
| `:433-435` | `#sidebar` 无 backdrop-filter | 若侧栏也上皮肤需反向；若不上则保留（需明确决策后写死） |
| `:437-439` | 桌面 `#sidebar` 透明 | 若皮肤对侧栏染色/加边框，此断言必红 |
| `:441-443` | ≤768 `#sidebar` == `--bg-elevated` | 令牌若被皮肤重命名/覆盖（plan R5），探针取空 ⇒ 假绿或假红 |
| `:444-445` | 存在含 `backdrop-filter` 的 `@supports` 降级块（G-8） | 新皮肤降级三态不同，须改为对 LG-5 的判据 |
| `:586` | CS-5 `scrollHeight @1920 ≤1240` | 总高基线随材质/圆角/内边距变化，须重取（plan §7.4 要求「与基线一致」） |
| `:1008` | F-1e `.ico` 尺寸 `16×16` | 套件换图标规格时须重取 |
| `:1012-1013` | F-4 `.avatar` 圆角 ≠ `50%` | 套件形状令牌（圆角档 24/22/16/14/12/10/6）若改变 avatar 形状，语义变化 |
| `:1035` | F-6a `scrollHeight ≤1240` | 同 `:586` |
| `:1038-1039` | F-6c `backdrop` 全覆盖 | 同 `:408-409` |
| `:1151-1152` | N-4 `#news-body` `max-height:132px` | 与 `:4641-4647` 同源；皮肤若改容器内边距/行高需同步重取 |
| `:1159-1161` | `::-webkit-scrollbar{width:6px}` | 皮肤自带滚动条样式（套件 CSS）会覆盖该规则 ⇒ 必须重写判据或改由皮肤令牌断言 |
| `:1162-1164` | 滚动条实测宽 ≤8px | 同上 |
| `:1165` | `.news-item a` 字重 400 | 换字体后字重档位可能变（400→450/其他） |
| `:1281-1282` | `--text-muted == #8E9BAE` | 皮肤同名令牌冲突（plan R5 明示 `--text-muted` 同名）；色值必然变，须改为「对比度 ≥4.5」而非钉色值 |
| `:1321` | P-7a `scrollHeight ≤1240` | 同 `:586` |
| `:1449-1450` | `td.chg` padding `3px/3px` | 皮肤间距令牌改变 padding ⇒ 必须重取 |
| `:1451` | U-6 mock 后 `scrollHeight ≤1240` | 同 `:586` |
| `:1568-1571` / `:1584` | V-5 / V-7b「零增高」 | 换字体/行高会连带改变 h2 与卡片高度 |
| `:1580-1583` | V-7 `h2ClientH ≤ lineHeight×1.6` | 依赖字号/行高，换字体后须复测 |
| `:1679-1680` | MX-3b `#macro-chart-wrap ≥300px` | 主图容器高度与皮肤无关但受全局间距影响，须复测 |
| `:2066-2067` | CN-10b 容器高 == clamp 推导值（公式 `:1889-1896`） | clamp 定义在 `style.css`，皮肤若改 `.mac-chart-wrap` 需同步改公式 |
| `:2156-2157` | M-7 `#mac-regime` `borderTopWidth == 0` 且非 `.mac-card` | 皮肤给卡片加边框/底色后必红（plan「降卡片感」与皮肤「加玻璃卡片」方向冲突，须重定义） |
| `:2159-2160` | M-6 `#mac-factors` slack ≤20px | 皮肤改变内边距/行高 ⇒ 留白量变 |
| `:2171-2172` | M-4 `dataset.borderWidth` max≥2.0 / min≤1.4 | 图表描边宽度受皮肤主题令牌影响，须重取 |
| `:2189-2190` | M-8 375 档主图 ≥360px | 同 `:1679-1680` |
| `:2408-2410` | KY-1 无 ellipsis 截断（12 宽度） | 换字体（尤其数字字体）+ 间距变化会改变截断边界，须重跑取新基线 |
| `:2643-2644` | MS-6a `.sidebar-footer` **== 65** | 硬编码几何（45+18+2），依赖 `.ms-time` 11px 字号；皮肤改字号/间距即红 |
| `:2645-2646` | MS-6b `.market-status` **== 52** | 同上（16+16+17+gap×2） |
| `:3252-3253` | NA-6 `#mac-factors` slack ≤20px | 同 `:2159-2160` |
| `:3352-3353` | NA-8b `.mac-factor-row` 网格 `["72px","70px"]` | 皮肤栅格/间距令牌改变列宽即红 |
| `:3518-3519` | UX-1 对比度 ≥4.5（`--text-muted` vs 页底） | 新背景纹理 + 面板染色改变有效底色 ⇒ 必须重测（plan R2 明示进 LG-9） |
| `:3523-3524` | UX-1b 对比度 ≥4.5（light `--c-ixic` vs 卡底） | 同上 |
| `:3526-3527` | UX-5 `.ms-time` 字号 ≥11px | 皮肤字体方案若缩小辅助字号即红 |
| `:3529-3531` | UX-1c 桌面 `#sidebar` 透明 | 同 `:437-439` |
| `:3641-3643` | UX-4e 抽屉底色 == `--bg-elevated` | 令牌值/名变化 ⇒ 重取 |
| `:4641-4647` | A/B-3、3b 容器 `max-height:132px` 与钳位 | 同 `:1151-1152` |
| `:4724` | A/B-10a `scrollHeight ≤1240` | 同 `:586` |
| `:4811-4812` | N-12a Firefox `scrollbar-color` 被主题色覆盖 | 皮肤滚动条实现替换后门控判据变化 |
| `:4814-4815` | N-12b CSSOM 门控含 `scrollbar-width:thin` | 同上 |
| `:4882` | `.card box-sizing == border-box` | 套件 reset 可能覆盖（plan §7.3 已点出「套件 reset 吃掉了垂直 margin」风险） |
| `:4883` | `.card` 圆角 **== 12px** | plan §7.3 `:229` 明文：「圆角只能给宿主，`data-radius` 在 v1.2.0 不存在，`verify_ui.py:4882-4884` 钉着旧值 ⇒ S0 先改断言」 |
| `:4884` | `.card` 有阴影 | 套件阴影参数替换后须重取（或改断 `.lg-inner`/宿主阴影存在性） |
| `:5002` | 主图容器 **== 432px**（40vh） | 皮肤改变全局间距/主图区留白会动到该值 |
| `:5003` | 1920 总高 ≤1240 | 同 `:586` |
| `:5004-5005` | KPI 卡 ≥260×96 | 皮肤内边距/字号变化影响卡尺寸 |
| `:5074-5076` | 切主题后卡片底色/边框色**必须变化** | 若皮肤用 `[data-liquid-skin]` 作用域令牌导致 `#overview` 自身颜色不再随主题变（颜色改由 `.lg-inner` 承载），这两条必红 —— 须改为断言 `.lg-inner` 或令牌解析值 |
| `:5109` | 1Y 档 canvas 位图==显示尺寸（A 类，复核即可） | 皮肤新增包裹层可能改变 canvas 可见尺寸 ⇒ 需确认为「结构断言仍成立」 |
| `:5164` | 375 主图 **== 280px** | 同 `:5002` |

> 另注：`:1310-1316`（P-6 模板源级 `colspan`）与 `:3757-3761`（PW-3b 模板源级 `aria-label`）直接读 `web/templates/index.html` 全文；换肤若把首页拆成 include，这两条的正则/子串匹配可能失效（属 A 类但需一并复核）。
