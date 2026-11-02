"""玻璃观感选型对比（一次性设计工具，可复跑）。

三轮迭代记录（本文件承载第 3 轮）：
  第 1 轮：只变「强度」（--glass-bg 0.02/0.035/0.065 + blur 14/20/28）→ 三档**几乎无差别**。
  第 2 轮：加入「氛围覆盖」轴（右上单点 vs 三点分布）→ A 与 D **仍无可见差别**。
  第 3 轮（本轮）：改为测**真正的杠杆**。

第 1/2 轮零差异的机制根因（两条，均已实测确认）：
  ① `backdrop-filter: blur()` 在**平滑渐变**背景上是**空操作** —— 模糊平滑渐变的结果与不模糊
     肉眼无法区分。blur 只在背景存在**高频细节**（文字 / 边缘 / 纹理）时才可见。
  ② 面板 alpha 0.02→0.067 在 `#0B0F14` 上仅差约 8 个色阶（0.035×255≈9），处于感知阈值附近。

→ 故本轮对照三件事：**面板实度（F）**、**背景局部对比（G）**、**给 blur 一个作用对象（H）**。

用法（项目根执行）：
    venv/Scripts/python -m uvicorn web.app:app --port 8031
    venv/Scripts/python tasks/2026-09-11-glassmorphism-fix/make_strength_cmp.py --port 8031

产出（全部落 %TEMP%/mp_glass_cmp/，**不进仓库** —— 见 plan R14）：
    {id}-full.png / {id}-crop.png / compare.html
只注入 <style> 覆盖 CSS 变量，不动任何仓库文件。
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT_DIR = Path(os.environ.get("TEMP") or tempfile.gettempdir()) / "mp_glass_cmp"

# 裁切区：4 张 KPI 卡 + promo + 趋势卡上半（含右侧光束区）
CROP = {"x": 264, "y": 56, "width": 1650, "height": 520}

TEX = ("repeating-linear-gradient(115deg, rgba(255,255,255,.022) 0 1px, "
       "rgba(255,255,255,0) 1px 6px)")

PRESETS = [
    {
        "id": "a", "name": "A · 当前实现（基准）",
        "desc": "氛围=柔和右上单点+斜带；强度=已落地的 dark 校准值（bg .035 / blur 20）。第 1/2 轮的对照组",
        "bg": "rgba(255, 255, 255, .035)", "blur": "blur(20px) saturate(150%)",
        "amb": "cur", "a1": ".14", "a1b": ".09", "a2": ".07", "peak": ".14",
    },
    {
        "id": "f", "name": "F · 只提面板实度",
        "desc": "氛围与 A 完全相同，只把 --glass-bg 从 .035 提到 .12（约 3.4×）。检验「面板变浅」是否就等于「玻璃感」",
        "bg": "rgba(255, 255, 255, .12)", "blur": "blur(20px) saturate(150%)",
        "amb": "cur", "a1": ".14", "a1b": ".09", "a2": ".07", "peak": ".14",
    },
    {
        "id": "g", "name": "G · 提背景局部对比（强光斑）",
        "desc": "面板/模糊与 A 完全相同，只把氛围换成**高对比局部光斑**（peak α .35，落在 KPI 行与趋势卡之间）。检验「透光」是否能被看见",
        "bg": "rgba(255, 255, 255, .035)", "blur": "blur(20px) saturate(150%)",
        "amb": "glow", "a1": ".14", "a1b": ".14", "a2": ".07", "peak": ".35",
    },
    {
        "id": "h", "name": "H · G + 细纹理（给 blur 一个作用对象）",
        "desc": "在 G 之上叠一层极细斜纹（1px 线 / 6px 周期）。这是**让 blur 从空操作变成可见**的标准手法 —— 代价是背景会出现细纹路",
        "bg": "rgba(255, 255, 255, .035)", "blur": "blur(20px) saturate(150%)",
        "amb": "glow_tex", "a1": ".14", "a1b": ".14", "a2": ".07", "peak": ".35",
    },
]

MEASURE_JS = r"""
() => {
  const q = (s) => document.querySelector(s);
  const cs = (el) => (el ? getComputedStyle(el) : null);
  const alphaOf = (c) => {
    if (!c) return null;
    const m = /rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:[,\s/]+([\d.]+))?\s*\)/.exec(c);
    return m ? (m[4] === undefined ? 1 : parseFloat(m[4])) : null;
  };
  const k = q('.kpi-card'), ov = q('#overview');
  return {
    kpiAlpha: k ? alphaOf(cs(k).backgroundColor) : null,
    kpiBackdrop: k ? cs(k).backdropFilter : null,
    ambientLayers: ((cs(document.body).backgroundImage || '')
        .match(/(?:radial|linear|repeating-linear|conic)-gradient\(/g) || []).length,
    borderRaw: ov ? cs(ov).borderTopColor : null,
    scrollH: document.scrollingElement.scrollHeight,
  };
}
"""


def ambient_css(p: dict) -> str:
    """按 amb 模式生成 body 背景层（逗号分隔的多层 background-image）。"""
    a1, a1b, a2, peak = p["a1"], p["a1b"], p["a2"], p["peak"]
    if p["amb"] == "cur":
        return (f"radial-gradient(1200px 820px at 78% -8%, rgba(150, 190, 255, {a1}), transparent 62%), "
                f"linear-gradient(148deg, transparent 18%, rgba(120, 160, 220, {a2}) 40%, transparent 64%)")
    glow = (
        f"radial-gradient(760px 520px at 30% 12%, rgba(150, 200, 255, {peak}), transparent 58%), "
        f"radial-gradient(900px 620px at 74% 34%, rgba(120, 170, 255, {a1b}), transparent 60%), "
        f"linear-gradient(148deg, transparent 18%, rgba(120, 160, 220, {a2}) 40%, transparent 64%)"
    )
    return glow + (", " + TEX if p["amb"] == "glow_tex" else "")


def override_css(p: dict) -> str:
    """覆盖 glass token + 氛围层（dark 档）。

    同时命中 `:root` 与 `[data-theme="dark"]`：注入的 <style> 在主样式表之后 →
    同特异性下后者胜出，必定生效。
    """
    return f"""
:root, [data-theme="dark"] {{
  --glass-bg: {p['bg']};
  --glass-blur: {p['blur']};
  --ambient-1: {ambient_css(p)};
  --ambient-2: none;
}}
"""


def shot(page, p: dict, url: str) -> dict:
    page.goto(url, wait_until="load")
    # 自选股走 AkShare 冷启动（服务端限时 10s），不等落定会让自选卡高度不定
    try:
        page.wait_for_selector("#watchlist-section:not(.hidden)", timeout=25000)
    except Exception:
        pass
    page.wait_for_timeout(1200)
    page.add_style_tag(content=override_css(p))
    page.wait_for_timeout(900)          # 等样式重算 + backdrop-filter 重合成
    m = page.evaluate(MEASURE_JS)
    page.screenshot(path=str(OUT_DIR / f"{p['id']}-full.png"), full_page=True)
    page.screenshot(path=str(OUT_DIR / f"{p['id']}-crop.png"), clip=CROP)
    m["preset"] = p
    return m


def diff_stats(base_path, path) -> dict:
    """与基准图的整页像素差分：变化像素占比 / 最大差 / 包围盒。

    这是本工具的**判定依据** —— 缩略图目视在深色小区域上不可靠（本次实测：
    面板 alpha 从 .035 提到 .12，肉眼在缩略图上"看不出差别"，但像素差分显示
    32.6% 的像素变了、卡片/背景对比从 (9,14,14) 升到 (29,34,33)）。
    """
    from PIL import Image, ImageChops

    a = Image.open(base_path).convert("RGB")
    b = Image.open(path).convert("RGB")
    if a.size != b.size:
        return {"pct": None, "maxv": None, "box": f"尺寸不同 {a.size} vs {b.size}"}
    d = ImageChops.difference(a, b).convert("L")
    px = list(d.getdata())
    n = len(px)
    big = [(i, v) for i, v in enumerate(px) if v > 6]
    if not big:
        return {"pct": 0.0, "maxv": 0, "box": "—"}
    xs = [i % a.width for i, _ in big]
    ys = [i // a.width for i, _ in big]
    return {"pct": round(100 * len(big) / n, 1), "maxv": max(px),
            "box": f"x[{min(xs)},{max(xs)}] y[{min(ys)},{max(ys)}]"}


def build_html(rows: list[dict]) -> str:
    def tr(r):
        p = r["preset"]
        d = r.get("diff") or {}
        return (f"<tr><td class='nm'>{p['name']}</td><td>{p['bg']}</td>"
                f"<td>{p['amb']}</td><td>{r['kpiAlpha']}</td>"
                f"<td><b>{d.get('pct')}%</b></td><td>{d.get('maxv')}</td>"
                f"<td class='box'>{d.get('box')}</td></tr>")

    def blk(r):
        p = r["preset"]
        return (f"<section class='blk'><h3>{p['name']}</h3><p class='desc'>{p['desc']}</p>"
                f"<img src='{p['id']}-crop.png'>"
                f"<img src='{p['id']}-full.png'></section>")

    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>玻璃观感选型 — MarketPulse</title>
<style>
  body {{ margin:0; padding:26px 30px 80px; background:#0B0F14; color:#E5E7EB;
          font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif; }}
  h1 {{ font-size:19px; margin:0 0 8px; }}
  h2 {{ font-size:15px; margin:32px 0 10px; padding-top:14px; border-top:1px solid #1E2733; }}
  h3 {{ font-size:14px; margin:24px 0 4px; color:#66A8E0; }}
  .lede {{ color:#9BA3AF; font-size:13px; line-height:1.7; margin:0 0 8px; max-width:1150px; }}
  .warn {{ background:rgba(224,145,62,.12); border-left:3px solid #E0913E; padding:11px 13px;
           font-size:12.5px; color:#F0C48A; line-height:1.7; margin:14px 0 22px; max-width:1150px; }}
  .key {{ background:rgba(59,130,246,.12); border-left:3px solid #3B82F6; padding:11px 13px;
          font-size:12.5px; color:#AFCBF7; line-height:1.75; margin:14px 0 22px; max-width:1150px; }}
  .key b {{ color:#DCE9FB; }}
  table {{ border-collapse:collapse; font-size:12.5px; margin:8px 0 4px; }}
  th,td {{ border-bottom:1px solid #1E2733; padding:7px 11px; text-align:left; white-space:nowrap; }}
  th {{ color:#9BA3AF; font-weight:500; font-size:11px; }}
  .nm {{ color:#66A8E0; white-space:nowrap; }}
  .box {{ font-family:ui-monospace,Consolas,monospace; color:#9BA3AF; font-size:11px; }}
  .desc {{ color:#9BA3AF; font-size:12px; line-height:1.65; margin:0 0 8px; max-width:1150px; }}
  .blk img {{ display:block; max-width:100%; border:1px solid #1E2733; border-radius:6px; margin-bottom:10px; }}
  pre {{ background:#111827; border:1px solid #1E2733; border-radius:6px; padding:10px 12px;
         font-size:11.5px; overflow:auto; color:#9BA3AF; }}
  code {{ background:#111827; padding:1px 5px; border-radius:3px; }}
</style></head><body>

<h1>玻璃观感选型 · 第 3 轮（测真正的杠杆）</h1>
<p class="lede">
  同一视口（1920×1080，DPR=1）、同一实时数据、同一主题（dark）。
  全部通过注入 <code>&lt;style&gt;</code> 覆盖 CSS 变量实现，未改动任何仓库文件。
</p>

<p class="key">
  <b>结论 —— 以「整页像素差分」为判定依据，不以缩略图目视为准</b><br>
  （缩略图目视在深色小区域上不可靠：本次 F 组把面板 alpha 从 .035 提到 .12，肉眼看「没差别」，
  但像素差分显示 32.6% 的像素变了。）<br><br>
  · <b>面板 alpha 是有效杠杆，但需要足够跨度</b>：<code>.035 → .12</code>（3.4×）才产生
  <b>32.6% 像素变化</b>（卡片/背景对比 (9,14,14) → (29,34,33)）；而 <code>.035 → .02</code> 几乎无变化（均值差 1.94）。
  → <b>第 1 轮「强度无差别」是「跨度给得太小」造成的，不是强度无效</b>。
  且 F 幅度偏小（最大差 21），得到的是「整体变亮一点」，通透 / 折射感并不强。<br>
  · <b><code>backdrop-filter: blur()</code> 在平滑渐变背景上是空操作</b>（模糊平滑渐变 ≈ 原样），
  故 <code>blur</code> 14→28 无可见效果 —— 这一条成立。<br>
  · <b>背景局部对比（G）最有效</b>：在<b>不改面板 alpha</b>（文字可读性不变）的前提下取得
  14.7% 像素变化、<b>最大差 54</b>，且带方向性（蓝通道抬升）→ 真正的「光透过玻璃」；
  影响集中在 <b>y0–619（上半页）</b>，可控。<br>
  · <b>纹理（H）几乎无额外收益</b>：H 与 G 的差分指标基本持平（14.7% → 15.3%）→
  <b>原先判定「那是噪声、不加」是正确的</b>，可以继续不加（省一个合成层）。<br>
  → <b>推荐方向：G（背景局部对比）+ 「适度」面板 alpha（.05~.06 量级，而非 .12）。</b><br>
  ⚠️ 需注意：G 的光斑之一落在趋势卡绘图区上方，蓝色序列线（<code>#66A8E0</code>）在该区域
  可能损失一点对比 → 落地时应把光斑位置**避让绘图区**（偏 KPI 行与卡片间隙）。
</p>

<p class="warn">
  ⚠️ 两点需要你知道：<br>
  ① <b>效果图原图不在仓库里</b>（全仓 <code>*.png</code> 搜索为 0），本页无法并排放原图，请单独打开对照。<br>
  ② <b>H 的细纹路就是你在效果图上判定为「噪声」的那层斜纹</b>。本轮把它加回来是<b>有技术理由</b>的：
  没有高频背景内容，<code>blur()</code> 就永远看不出效果。若你不接受背景有纹路，那就只能走 G 的路线
  （不靠 blur，改用「背景局部对比 + 卡片透光」来表达玻璃）。
</p>

<h2>测量值对照</h2>
<table>
  <thead><tr><th>变体</th><th>--glass-bg</th><th>氛围模式</th><th>KPI alpha</th>
  <th>像素变化占比<br>（vs A）</th><th>最大差</th><th>变化区域</th></tr></thead>
  <tbody>{''.join(tr(r) for r in rows)}</tbody>
</table>

<h2>逐组合对照</h2>
<p class="desc">每组先给「KPI 行 + 趋势卡上半」100% 裁切（看细节），再给全页（看整体）。</p>
{''.join(blk(r) for r in rows)}

<h2>原始测量值</h2>
<pre>{json.dumps([{k: v for k, v in r.items() if k != 'preset'} | {'preset': r['preset']['name']} for r in rows], ensure_ascii=False, indent=1)}</pre>
</body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8031)
    args = ap.parse_args()
    url = f"http://127.0.0.1:{args.port}/"
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    rows = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
        page.add_init_script("try { localStorage.setItem('mp-theme','dark'); } catch (e) {}")
        for preset in PRESETS:
            rows.append(shot(page, preset, url))
            print(f"[{preset['id']}] amb={preset['amb']:9} bg={preset['bg'][-8:]} "
                  f"kpiAlpha={rows[-1]['kpiAlpha']} layers={rows[-1]['ambientLayers']}")
        browser.close()

    base = OUT_DIR / f"{rows[0]['preset']['id']}-full.png"
    for r in rows:
        r["diff"] = diff_stats(base, OUT_DIR / f"{r['preset']['id']}-full.png")
        d = r["diff"]
        print(f"[{r['preset']['id']}] 差分 vs {rows[0]['preset']['id']}: {d['pct']}% "
              f"最大差={d['maxv']} {d['box']}")

    (OUT_DIR / "compare.html").write_text(build_html(rows), encoding="utf-8")
    print(f"\nOK -> {OUT_DIR / 'compare.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
