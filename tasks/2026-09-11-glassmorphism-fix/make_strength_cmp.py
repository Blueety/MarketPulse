"""玻璃观感选型对比（一次性设计工具，可复跑）。

背景：第一轮只对比「玻璃强度」（--glass-bg / --glass-blur）时，三档在视觉上几乎
无差别 —— 根因是**氛围光束只集中在右上角约 1/4 区域**，左侧 60%（KPI 行、趋势图）
坐在近乎平坦的暗底上，玻璃背后没有可见内容。故本轮把「强度」与「氛围覆盖」两个
轴拆开对照，用于确认哪个才是真正的杠杆。

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

# 裁切区：覆盖 4 张 KPI 卡 + promo + 趋势卡上半（含右侧光束区），
# 是「暗底 + 氛围 + 卡片」三者交互最密集的带状区域。
CROP = {"x": 264, "y": 56, "width": 1650, "height": 520}

# ---- 两个正交轴 -------------------------------------------------------------

# 轴 1：氛围覆盖。cur = 当前实现（右上单点 + 斜带）；dist = 分布化（三点，覆盖左中/底部）
AMBIENT = {
    "cur": (
        "radial-gradient(1200px 820px at 78% -8%, rgba(150, 190, 255, {a1}), transparent 62%), "
        "linear-gradient(148deg, transparent 18%, rgba(120, 160, 220, {a2}) 40%, transparent 64%)"
    ),
    "dist": (
        "radial-gradient(900px 700px at 84% -6%, rgba(150, 190, 255, {a1}), transparent 60%), "
        "radial-gradient(1150px 800px at 2% 44%, rgba(118, 150, 235, {a1b}), transparent 63%), "
        "radial-gradient(1250px 860px at 58% 110%, rgba(90, 200, 220, {a2}), transparent 65%)"
    ),
}

# 轴 2：玻璃强度
PRESETS = [
    {
        "id": "a", "name": "A · 当前实现（基准）",
        "desc": "氛围=右上单点+斜带；强度=已落地的 dark 校准值。作为对照组",
        "bg": "rgba(255, 255, 255, .035)", "blur": "blur(20px) saturate(150%)",
        "amb": "cur", "a1": ".14", "a1b": ".09", "a2": ".07",
    },
    {
        "id": "b", "name": "B · 强度→轻",
        "desc": "只调强度：面板更透、模糊更弱、光束更淡。用于验证「强度是不是主要杠杆」",
        "bg": "rgba(255, 255, 255, .02)", "blur": "blur(14px) saturate(130%)",
        "amb": "cur", "a1": ".10", "a1b": ".07", "a2": ".05",
    },
    {
        "id": "c", "name": "C · 强度→重",
        "desc": "只调强度：面板更实、模糊更强、光束更亮。与 B 一起界定强度区间",
        "bg": "rgba(255, 255, 255, .065)", "blur": "blur(28px) saturate(190%)",
        "amb": "cur", "a1": ".20", "a1b": ".13", "a2": ".10",
    },
    {
        "id": "d", "name": "D · 氛围→分布化（推荐对照）",
        "desc": "强度与 A 完全相同，只把氛围从「右上单点」改成「右上+左中+底部三点」→ 验证覆盖才是主要杠杆",
        "bg": "rgba(255, 255, 255, .035)", "blur": "blur(20px) saturate(150%)",
        "amb": "dist", "a1": ".14", "a1b": ".09", "a2": ".08",
    },
    {
        "id": "e", "name": "E · 分布化 + 强度略重",
        "desc": "在 D 的基础上把强度提到中档（bg .05 / blur 24）→ 候选落地值",
        "bg": "rgba(255, 255, 255, .05)", "blur": "blur(24px) saturate(165%)",
        "amb": "dist", "a1": ".16", "a1b": ".11", "a2": ".09",
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
    dataAlpha: ov ? alphaOf(cs(ov).backgroundColor) : null,
    kpiBackdrop: k ? cs(k).backdropFilter : null,
    ambientLayers: ((cs(document.body).backgroundImage || '').match(/(?:radial|linear|conic)-gradient\(/g) || []).length,
    borderRaw: ov ? cs(ov).borderTopColor : null,
    scrollH: document.scrollingElement.scrollHeight,
  };
}
"""


def override_css(p: dict) -> str:
    """覆盖 glass token + 氛围层（dark 档）。

    同时命中 `:root` 与 `[data-theme="dark"]`：注入的 <style> 在主样式表之后 →
    同特异性下后者胜出，必定生效。
    """
    amb = AMBIENT[p["amb"]].format(a1=p["a1"], a1b=p["a1b"], a2=p["a2"])
    return f"""
:root, [data-theme="dark"] {{
  --glass-bg: {p['bg']};
  --glass-blur: {p['blur']};
  --ambient-1: {amb};
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


def build_html(rows: list[dict]) -> str:
    def tr(r):
        p = r["preset"]
        return (f"<tr><td class='nm'>{p['name']}</td><td>{p['bg']}</td><td>{p['blur']}</td>"
                f"<td>{'右上单点' if p['amb'] == 'cur' else '三点分布'}</td>"
                f"<td>{r['kpiAlpha']}</td><td>{r['dataAlpha']}</td><td>{r['ambientLayers']}</td></tr>")

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
  h2 {{ font-size:15px; margin:30px 0 10px; padding-top:14px; border-top:1px solid #1E2733; }}
  h3 {{ font-size:14px; margin:22px 0 4px; color:#66A8E0; }}
  .lede {{ color:#9BA3AF; font-size:13px; line-height:1.7; margin:0 0 8px; max-width:1150px; }}
  .warn {{ background:rgba(224,145,62,.12); border-left:3px solid #E0913E; padding:11px 13px;
           font-size:12.5px; color:#F0C48A; line-height:1.65; margin:14px 0 22px; max-width:1150px; }}
  .key {{ background:rgba(59,130,246,.12); border-left:3px solid #3B82F6; padding:11px 13px;
          font-size:12.5px; color:#AFCBF7; line-height:1.7; margin:14px 0 22px; max-width:1150px; }}
  table {{ border-collapse:collapse; font-size:12.5px; margin:8px 0 4px; }}
  th,td {{ border-bottom:1px solid #1E2733; padding:7px 11px; text-align:left; white-space:nowrap; }}
  th {{ color:#9BA3AF; font-weight:500; font-size:11px; }}
  .nm {{ color:#66A8E0; white-space:nowrap; }}
  .desc {{ color:#9BA3AF; font-size:12px; line-height:1.6; margin:0 0 8px; max-width:1150px; }}
  .blk img {{ display:block; max-width:100%; border:1px solid #1E2733; border-radius:6px; margin-bottom:10px; }}
  pre {{ background:#111827; border:1px solid #1E2733; border-radius:6px; padding:10px 12px;
         font-size:11.5px; overflow:auto; color:#9BA3AF; }}
  code {{ background:#111827; padding:1px 5px; border-radius:3px; }}
</style></head><body>

<h1>玻璃观感选型 · 两轴对照（强度 / 氛围覆盖）</h1>
<p class="lede">
  同一视口（1920×1080，DPR=1）、同一实时数据、同一主题（dark）。全部通过注入
  <code>&lt;style&gt;</code> 覆盖 CSS 变量实现，未改动任何仓库文件。
</p>

<p class="key">
  <b>第一轮的发现</b>：只对比「强度」（<code>--glass-bg</code> / <code>--glass-blur</code>）时，
  三档几乎看不出差别。根因不是强度不够，而是 <b>氛围光束只集中在右上角约 1/4 区域</b> ——
  左侧 60%（KPI 行、趋势图）坐在近乎平坦的暗底上，<b>玻璃背后没有可见内容</b>，
  所以「透光度」这个参数在该区域没有作用对象。<br>
  → 本轮把两个轴拆开：<b>A/B/C 只变强度</b>（氛围保持现状），<b>D 只变氛围覆盖</b>（强度与 A 相同），
  <b>E = D + 中档强度</b>。请重点对比 <b>A vs D</b>。
</p>

<p class="warn">
  ⚠️ <b>效果图原图不在仓库里</b>（`*.png` 全仓搜索为 0），本页无法把原图并排放进来。
  请把效果图单独打开，与本页对照着看。
</p>

<h2>测量值对照</h2>
<table>
  <thead><tr><th>变体</th><th>--glass-bg</th><th>--glass-blur</th><th>氛围几何</th>
  <th>KPI alpha</th><th>数据卡 alpha</th><th>body 渐变层数</th></tr></thead>
  <tbody>{''.join(tr(r) for r in rows)}</tbody>
</table>
<p class="desc">
  注：<code>--glass-bg-strong</code>（数据卡 <code>#overview/#trend/#alerts</code>）五组**一律固定 0.66**
  —— 它是 12px 小字的可读性下限，不在本轮选型范围内。所以「数据卡 alpha」一列恒为 0.66 属预期。
</p>

<h2>逐组合对照</h2>
<p class="desc">每组先给「KPI 行 + 趋势卡上半」100% 裁切，再给全页。</p>
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
            print(f"[{preset['id']}] amb={preset['amb']:4} kpiAlpha={rows[-1]['kpiAlpha']} "
                  f"layers={rows[-1]['ambientLayers']} backdrop={rows[-1]['kpiBackdrop']}")
        browser.close()

    (OUT_DIR / "compare.html").write_text(build_html(rows), encoding="utf-8")
    print(f"\nOK -> {OUT_DIR / 'compare.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
