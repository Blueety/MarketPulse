#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""液态玻璃皮肤验收（第一期：`/` 首页）

配套方案：`tasks/2026-09-23-web-liquid-glass-skin/plan.md` §6（验证命令与验收判据）。
与 `tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` 的分工：
  · `verify_ui.py`   = **通用**看板门禁（布局/契约/canvas/主题/抽屉/console…），换肤后只把
                       视觉数值类断言按新皮肤重取；它不知道「皮肤」这回事。
  · 本文件            = **皮肤专项**门禁（LG-1…LG-10）：折射材质是否真的在、纹理是否真的被
                       折射、面板是否可见、降级三态、磨砂档、非 Chromium 不白卡、动态重挂载、
                       对比度、背景配方。

用法（在项目根，venv 内）：
  venv/Scripts/python tasks/2026-09-23-web-liquid-glass-skin/verify_skin.py
  venv/Scripts/python tasks/2026-09-23-web-liquid-glass-skin/verify_skin.py --engine=frost
  venv/Scripts/python tasks/2026-09-23-web-liquid-glass-skin/verify_skin.py --only=LG-9,LG-10
  venv/Scripts/python tasks/2026-09-23-web-liquid-glass-skin/verify_skin.py --baseline <path.json>

退出码：有 FAIL → 1；仅 SKIP → 0（`--strict` 时 1）；全绿 → 0。
`SKIP` = **该条未判定**（例如本机没有 Firefox 内核 / 该阶段尚未挂材质），**不是通过**。

⚠️ 每轮换端口（Browser 按**完整 URL** 缓存 /static/*.css；复用端口会回放旧样式表的 304）。
"""
from __future__ import annotations

import argparse
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
PY = ROOT / "venv" / "Scripts" / "python.exe"
OUT_DIR = Path(os.environ.get("TEMP") or tempfile.gettempdir()) / "marketpulse-skin"
OUT_DIR.mkdir(parents=True, exist_ok=True)

FAILURES: list[dict] = []
SKIPPED: list[dict] = []
N_PASS = 0
STRICT = False
ONLY: list[str] = []          # 空 = 全跑
ENGINE = "auto"               # auto | refract | frost（frost = 强制磨砂档，用于 LG-6）
FORCED_ENGINE = ""            # auto 时留空
MIN_HOSTS = 2                 # 玻璃宿主数下限（S3 = 2；S4 起用 --min-hosts 13）
BASELINE_PATH = ""            # 非空 → 把本轮实测数值写成基线快照
MEASURED: dict = {}           # 供 --baseline 落盘

# 纹理/折射的物理常量（plan §3.1）：位移尺度 ≈11px、玻璃 blur σ≈2.5
DISP_PX = 11.0
# 判据（plan §6.1）
SPACING_PX = 16               # 背景方格间距下限
OUT_D11_MIN = 1.5             # 卡外 d11（背景结构可见）
RETENTION_MIN = 0.40          # 卡内/卡外纹理留存比
PANEL_DIFF_MIN = 5.0          # 卡内空白区与背景亮度差（/255）
CONTRAST_MIN = 4.5


def want(group: str) -> bool:
    return (not ONLY) or group in ONLY


def check(cond: bool, label: str, actual=None, expect=None, skip_reason: str | None = None) -> bool:
    """三态登记：`skip_reason` 非空 ⇒ SKIP（未判定），否则按 cond 判 PASS/FAIL。"""
    global N_PASS
    if skip_reason:
        SKIPPED.append({"label": label, "reason": skip_reason, "actual": actual})
        print(f"  SKIP  {label}  [{skip_reason}]")
        return False
    if cond:
        N_PASS += 1
        print(f"  PASS  {label}" + (f"  ({actual})" if actual is not None else ""))
        return True
    FAILURES.append({"label": label, "actual": actual, "expect": expect})
    print(f"  FAIL  {label}  actual={actual!r} expect={expect!r}")
    return False


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_ready(url: str, timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(0.4)
    raise RuntimeError(f"服务未在 {timeout}s 内就绪: {url} ({last})")


# ─────────────────────────────────────────────────────────────────────────────
# 探针 JS
# ─────────────────────────────────────────────────────────────────────────────
HOSTS_JS = r"""
() => {
  const HOST_SEL = '.card[data-liquid-glass], .kpi-card[data-liquid-glass], .topbar[data-liquid-glass]';
  const fx = (v) => v || '';
  const hosts = [...document.querySelectorAll(HOST_SEL)].map((h, i) => {
    const inner = h.querySelector(':scope > .lg-inner');
    const svgs = [...h.querySelectorAll(':scope > svg')];
    const cs = getComputedStyle(h);
    const ics = inner ? getComputedStyle(inner) : null;
    return {
      key: h.id || ('#' + (h.className || '').split(' ').filter(Boolean).slice(0, 2).join('.')),
      idx: i,
      hostsInner: h.querySelectorAll(':scope > .lg-inner').length,
      filterSvgs: svgs.filter((s) => s.querySelector('filter')).length,
      tag: h.tagName.toLowerCase(),
      radiusHost: cs.borderRadius,
      radiusInner: ics ? ics.borderRadius : null,
      posInner: ics ? ics.position : null,
      insetInner: ics ? [ics.top, ics.right, ics.bottom, ics.left].join(',') : null,
      innerZ: ics ? ics.zIndex : null,
      innerBackdrop: ics ? (ics.backdropFilter || ics.webkitBackdropFilter) : null,
      innerBg: ics ? ics.backgroundColor : null,
      innerBorder: ics ? ics.borderTopWidth + ' ' + ics.borderTopColor : null,
      hostBackdrop: cs.backdropFilter,
      hostBg: cs.backgroundColor,
      bodyLayerZ: (() => {
        const b = h.querySelector(':scope > .skin-glass-body');
        if (b) {
          const bcs = getComputedStyle(b);
          if (bcs.display === 'contents') {
            const kid = h.querySelector(':scope > .skin-glass-body > *');
            return kid ? getComputedStyle(kid).zIndex : 'no-child';
          }
          return bcs.zIndex;
        }
        // 无 wrapper（顶栏走「直接抬子元素」路线）：取第一个非引擎子元素的 z-index
        const kid = [...h.children].find((c) =>
          !c.classList.contains('lg-inner') && !c.classList.contains('lg-clone')
          && c.tagName.toLowerCase() !== 'svg');
        return kid ? getComputedStyle(kid).zIndex : 'no-child';
      })(),
      bodyMode: h.querySelector(':scope > .skin-glass-body') ? 'wrapper' : 'direct',
      rect: (() => { const r = h.getBoundingClientRect();
        return { x: r.x, y: r.y, w: r.width, h: r.height }; })(),
    };
  });
  const cs = getComputedStyle(document.documentElement);
  const bs = getComputedStyle(document.body);
  const layerCount = (bs.backgroundImage.match(/,/g) || []).length + 1;
  return {
    hosts,
    hostCount: hosts.length,
    glassEngine: document.documentElement.dataset.glassEngine || null,
    theme: document.documentElement.dataset.theme || null,
    skinScope: document.documentElement.hasAttribute('data-liquid-skin'),
    bodyBgImage: bs.backgroundImage,
    bodyLayerCount: bs.backgroundImage === 'none' ? 0 : layerCount,
    bodyRepeat: bs.backgroundRepeat,
    bodyAttachment: bs.backgroundAttachment,
    bodyBgColor: bs.backgroundColor,
    htmlBgImage: getComputedStyle(document.documentElement).backgroundImage,
    scrollH: document.scrollingElement.scrollHeight,
    textColor: getComputedStyle(document.body).color,
    muted: cs.getPropertyValue('--text-muted').trim(),
    vBg: cs.getPropertyValue('--bg').trim(),
    vText: cs.getPropertyValue('--text').trim(),
    vSurface: cs.getPropertyValue('--surface-opaque').trim(),
    vAccent: cs.getPropertyValue('--accent').trim(),
    sbRuleWidth: (() => {
      for (const sheet of document.styleSheets) {
        let rules;
        try { rules = sheet.cssRules; } catch (e) { continue; }
        for (const r of rules || []) {
          if (r.selectorText === '::-webkit-scrollbar' && r.style.width) return r.style.width;
        }
      }
      return null;
    })(),
    // 卡片正文（第一段真实文字）的色值与字号，用于对比度判定
    sampleText: (() => {
      const el = document.querySelector('#overview h2, .card h2');
      if (!el) return null;
      const s = getComputedStyle(el);
      return { color: s.color, size: s.fontSize, sel: '#overview h2' };
    })(),
    kpiCount: document.querySelectorAll('.kpi-card').length,
  };
}
"""

MEDIA_PROBE_JS = r"""
() => {
  const inner = document.querySelector('.card[data-liquid-glass] > .lg-inner');
  const host = document.querySelector('.card[data-liquid-glass]');
  const ics = inner ? getComputedStyle(inner) : null;
  return {
    hasInner: !!inner,
    backdrop: ics ? (ics.backdropFilter || ics.webkitBackdropFilter) : null,
    borderTopWidth: ics ? ics.borderTopWidth : null,
    borderTopColor: ics ? ics.borderTopColor : null,
    bg: ics ? ics.backgroundColor : null,
    transition: ics ? ics.transitionProperty + ' ' + ics.transitionDuration : null,
    anim: ics ? ics.animationName : null,
    hostBackdrop: host ? getComputedStyle(host).backdropFilter : null,
  };
}
"""


def _d11(gray: np.ndarray, shift: int) -> np.ndarray:
    """逐列 d11 = |I(x+shift) − I(x−shift)|（越高 = 该处有可被位移「弯折」的结构）。"""
    return np.abs(gray[:, shift:] - gray[:, :-shift])


def _pick_host_js() -> str:
    """挑「视口内可见面积最大」的玻璃宿主（含 topbar 之外的卡片优先）。"""
    return """
() => {
  const hosts = [...document.querySelectorAll('.card[data-liquid-glass], .kpi-card[data-liquid-glass]')];
  const visA = (r) => Math.max(0, Math.min(r.bottom, innerHeight) - Math.max(r.top, 0));
  let best = null, area = 0;
  for (const h of hosts) {
    const r = h.getBoundingClientRect();
    const a = Math.min(visA(r), r.height) * r.width;
    if (a > area) { area = a; best = h; }
  }
  if (!best) return null;
  const r = best.getBoundingClientRect();
  return { x: r.x, y: r.y, w: r.width, h: r.height, vw: innerWidth, vh: innerHeight,
           key: best.id || best.className };
}
"""


def measure_texture(page, host_key: str = None, band_w: int = 220, band_h: int = 150,
                    inset: float = 40.0, dpr: int = 3):
    """量「透过玻璃面还剩多少背景结构」——**同区域 A/B**（同一块像素，只切换玻璃面开/关）。

    为什么不用 plan §3.1 的「卡边横跨带」：那条带子的「卡外」半区在 1440 档会压到侧栏
    （实测 x∈[205,233] 落在 `#sidebar` 的导航文字上 ⇒ d11 被抬高约 2.5 倍，留存比被压低）。
    同区域 A/B 没有这个偏置，且直接回答「折射后纹理还剩多少」：
      ① 隐藏内容层 → 量 R 区（面板在）          = d11_glass / lum_glass
      ② 再把 `.lg-inner`/`.lg-clone` 隐藏 → 量同一 R 区（裸背景）= d11_bg / lum_bg
      ③ 留存比 = d11_glass / d11_bg；面板亮度差 = |lum_glass − lum_bg|
    R 区取宿主内部（内缩 `inset` ≥ bezel 20px + 圆角），同时另量一条**贴边带**
    （edge+6 … edge+22，位移最强的区域）作为折射挠动的旁证（不设阈值，只记录）。
    """
    box = page.evaluate(_pick_host_js())
    if not box:
        return None
    # 视口内定位（高度不足就滚到中间）
    if (min(box["y"] + box["h"], box["vh"]) - max(box["y"], 0)) < band_h + 2 * inset:
        page.evaluate("""() => {
             const hs = [...document.querySelectorAll('.card[data-liquid-glass], .kpi-card[data-liquid-glass]')];
             hs.sort((a, b) => b.getBoundingClientRect().height - a.getBoundingClientRect().height);
             if (hs[0]) hs[0].scrollIntoView({ block: 'center' });
           }""")
        page.wait_for_timeout(350)
        box = page.evaluate(_pick_host_js())
        if not box:
            return None
    vw, vh = box["vw"], box["vh"]
    # R 区：宿主内部，且整体落在视口内
    x0 = min(max(box["x"] + inset, 0.0), vw - band_w - 1)
    y0 = min(max(box["y"] + inset, 0.0), vh - band_h - 1)
    clip = {"x": x0, "y": y0, "width": band_w, "height": band_h}

    def shot():
        raw = page.screenshot(clip=clip, type="png")
        return np.asarray(Image.open(io.BytesIO(raw)).convert("L"), dtype=np.float64)

    def restore():
        page.evaluate("() => { const e = document.getElementById('mp-measure-hide'); if (e) e.remove(); }")

    try:
        page.evaluate("""() => {
             const st = document.createElement('style');
             st.id = 'mp-measure-hide';
             st.textContent = '.skin-glass-body, .skin-glass-body > * { visibility: hidden !important; }'
                            + '.topbar > :not(.lg-inner):not(.lg-clone):not(svg) { visibility: hidden !important; }';
             document.head.appendChild(st);
           }""")
        page.wait_for_timeout(160)
        g_glass = shot()
        page.evaluate("""() => {
             const st = document.createElement('style');
             st.id = 'mp-measure-hide2';
             st.textContent = '.lg-inner, .lg-clone { visibility: hidden !important; }';
             document.head.appendChild(st);
           }""")
        page.wait_for_timeout(160)
        g_bg = shot()
    finally:
        restore()
        page.evaluate("() => { const e = document.getElementById('mp-measure-hide2'); if (e) e.remove(); }")

    # 近旁「纯背景」补丁（plan §6.1：面板可见性 = 卡内空白区亮度 vs 背景）：优先取卡片左侧的
    # 主区留白（`#sidebar` 右缘到卡片左缘之间），不足则取右侧留白；都没有就不判这一项。
    patch = page.evaluate("""(box) => {
         const sb = document.getElementById('sidebar');
         const sbRight = sb ? sb.getBoundingClientRect().right : 0;
         const pad = 3;
         const h = 120, w = 18;
         if (box.x - sbRight >= w + 2 * pad) {
           return { x: sbRight + pad, y: box.y + 40, width: w, height: h, side: 'left' };
         }
         if (box.vw - (box.x + box.w) >= w + 2 * pad) {
           return { x: box.x + box.w + pad, y: box.y + 40, width: w, height: h, side: 'right' };
         }
         return null;
       }""", box)
    lum_patch = None
    if patch:
        raw_p = page.screenshot(clip=patch, type="png")
        lum_patch = float(np.asarray(Image.open(io.BytesIO(raw_p)).convert("L"), dtype=np.float64).mean())

    dpr_img = g_glass.shape[1] / float(band_w)          # dpr 一律从截图反推（勿信调用方）
    shift = int(round(DISP_PX * dpr_img))
    if dpr_img != dpr:
        print(f"  [info] 截图实测 DPR={dpr_img:.2f}（调用方期望 {dpr}）")
    d_glass = float(_d11(g_glass, shift).mean())
    d_bg = float(_d11(g_bg, shift).mean())
    lum_glass = float(g_glass.mean())
    lum_bg = float(g_bg.mean())
    return {
        "host": box["key"],
        "d11_glass": round(d_glass, 3),
        "d11_background": round(d_bg, 3),
        "retention": round(d_glass / d_bg, 3) if d_bg > 0.001 else None,
        "mute_ratio": round(d_glass / d_bg, 3) if d_bg > 0.001 else None,
        "lum_glass": round(lum_glass, 2),
        "lum_background": round(lum_bg, 2),
        "panel_diff": round(abs(lum_glass - lum_bg), 2),          # 同区域 A/B（面板自身造成的亮度差）
        "lum_patch": (round(lum_patch, 2) if lum_patch is not None else None),
        "panel_diff_vs_page": (round(abs(lum_glass - lum_patch), 2) if lum_patch is not None else None),
        "clip": clip,
        "patch": patch,
        "dpr": dpr_img,
    }


def luminance(rgb):
    def f(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(rgb[0]) + 0.7152 * f(rgb[1]) + 0.0722 * f(rgb[2])


def parse_rgb(s: str):
    """接受 `rgb()/rgba()` 与 `#RRGGBB` 两种写法（令牌值是 hex，computed 值是 rgb）。"""
    s = (s or "").strip()
    if s.startswith("#"):
        h = s.lstrip("#")
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        try:
            return [float(int(h[i:i + 2], 16)) for i in (0, 2, 4)]
        except ValueError:
            return None
    s = s.replace("rgba(", "").replace("rgb(", "").replace(")", "")
    parts = [p for p in s.replace("/", " ").replace(",", " ").split() if p]
    try:
        return [float(parts[0]), float(parts[1]), float(parts[2])]
    except Exception:  # noqa: BLE001
        return None


def _alpha_of(color: str):
    """从 computed 颜色串里取 alpha（兼容 `rgba(r,g,b,a)` / `rgb(...)` / `color(srgb r g b / a)`）。"""
    s = (color or "").strip()
    if not s:
        return None
    if s.startswith("rgba("):
        try:
            return float(s.rstrip(")").split(",")[-1])
        except ValueError:
            return None
    if s.startswith("rgb("):
        return 1.0
    if s.startswith("color("):
        if "/" in s:
            try:
                return float(s.rsplit("/", 1)[1].rstrip(") "))
            except ValueError:
                return None
        return 1.0
    if s == "transparent":
        return 0.0
    return None


def contrast(fg, bg) -> float:
    l1, l2 = luminance(fg), luminance(bg)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def sample_pixel(page, x: float, y: float, dpr: int = 1):
    raw = page.screenshot(clip={"x": x, "y": y, "width": 6, "height": 6}, type="png")
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    return np.asarray(img, dtype=np.float64).reshape(-1, 3).mean(axis=0).tolist()


# ─────────────────────────────────────────────────────────────────────────────
# 断言组
# ─────────────────────────────────────────────────────────────────────────────
def open_page(browser, url: str, theme: str, vp=(1440, 900), dpr: int = 1):
    ctx = browser.new_context(viewport={"width": vp[0], "height": vp[1]}, device_scale_factor=dpr)
    page = ctx.new_page()
    page.add_init_script(f"try{{localStorage.setItem('mp-theme','{theme}');}}catch(e){{}}")
    if FORCED_ENGINE:
        page.add_init_script(f"window.__MP_FORCE_ENGINE='{FORCED_ENGINE}';")
    errs: list[str] = []
    bad_resp: list[str] = []
    page.on("response", lambda r: bad_resp.append(f"{r.status} {r.url}") if r.status >= 400 else None)

    # 只收「真错误」：排除 favicon 404 —— 应用没有 favicon 路由，**有头**浏览器会自动请求
    # （headless 不请求 ⇒ 这个噪声只在 --headed 下出现），与皮肤无关。
    def _on_console(m):
        if m.type != "error":
            return
        url = (m.location or {}).get("url", "") if isinstance(m.location, dict) else ""
        if "favicon" in url:
            return
        if "Failed to load resource" in m.text and "404" in m.text and not url:
            return
        errs.append(m.text)

    page.on("console", _on_console)
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.goto(url, wait_until="load")
    page.wait_for_selector("#watchlist-section:not(.hidden)", timeout=25000)
    page.wait_for_timeout(1200)                   # 等分帧挂载（scheduleGlass）
    return ctx, page, errs, bad_resp


def assert_lg1_console(errs, tag: str, bad_resp=None):
    if not want("LG-1"):
        return
    print("--- LG-1 控制台 ---")
    if bad_resp:
        print(f"  [info] HTTP ≥400 响应: {bad_resp[:4]}")
    check(not errs, f"LG-1 {tag} console error = 0", errs[:4])


def assert_lg2_hosts(into: dict, tag: str):
    if not want("LG-2"):
        return
    print("--- LG-2 玻璃宿主结构 ---")
    hosts = into["hosts"]
    check(into["hostCount"] >= MIN_HOSTS,
          f"LG-2a {tag} 宿主数 ≥{MIN_HOSTS}（一期目标：topbar + 4 kpi + 8 card = 13）",
          into["hostCount"], MIN_HOSTS)
    bad = [h["key"] for h in hosts if h["hostsInner"] != 1]
    check(not bad, f"LG-2b {tag} 每宿主恰 1 个 .lg-inner", bad, [])
    bad2 = [h["key"] for h in hosts if h["filterSvgs"] != 1]
    check(not bad2, f"LG-2c {tag} 每宿主恰 1 棵含 <filter> 的引擎 svg", bad2, [])
    bad3 = [h["key"] for h in hosts if h["radiusInner"] != h["radiusHost"]]
    check(not bad3, f"LG-2d {tag} .lg-inner 圆角 == 宿主圆角",
          [(h["key"], h["radiusHost"], h["radiusInner"]) for h in hosts if h["key"] in bad3][:3], [])
    bad4 = [h["key"] for h in hosts if h["posInner"] != "absolute"]
    check(not bad4, f"LG-2e {tag} .lg-inner 为 absolute 覆盖层", bad4, [])
    bad5 = [h["key"] for h in hosts if str(h["bodyLayerZ"]) != "4"]
    check(not bad5, f"LG-2f {tag} 内容层 z-index = 4（高于 .lg-inner 的 3）",
          [(h["key"], h["bodyLayerZ"]) for h in hosts if h["key"] in bad5][:3], [])
    bad6 = [h["key"] for h in hosts if (h["hostBackdrop"] or "none") != "none"]
    check(not bad6, f"LG-2g {tag} 宿主自身 backdrop-filter 已让位（=none）", bad6, [])
    # 材质确实挂上了：refract 应为 `url("#lg-N")`（SVG 位移贴图），frost 应为 blur(...)
    mode = into.get("glassEngine")
    if mode == "refract":
        mat = [h for h in hosts if h["innerBackdrop"] and "url(" in h["innerBackdrop"]]
        check(len(mat) == len(hosts),
              f"LG-2h {tag} 每个 .lg-inner 都挂上折射材质 backdrop-filter: url(#lg-N)",
              f"{len(mat)}/{len(hosts)}", f"{len(hosts)}/{len(hosts)}")
        MEASURED["material"] = {"mode": mode, "sample": (mat[0]["innerBackdrop"] if mat else None)}
    else:
        mat = [h for h in hosts if h["innerBackdrop"] and "blur(" in h["innerBackdrop"]]
        check(len(mat) == len(hosts),
              f"LG-2h {tag} 每个 .lg-inner 都挂上磨砂材质 backdrop-filter: blur(...)（非折射引擎）",
              f"{len(mat)}/{len(hosts)}", f"{len(hosts)}/{len(hosts)}")
        MEASURED["material"] = {"mode": mode, "sample": (mat[0]["innerBackdrop"] if mat else None)}


def assert_lg3_material(page, tag: str, expect_glass: bool, dpr: int = 3):
    if not want("LG-3"):
        return
    print("--- LG-3 材质可见性（纹理留存比 + 面板可见性）---")
    m = measure_texture(page)
    if m is None or m.get("error"):
        check(False, f"LG-3 {tag} 纹理测量可用", m, "有宿主可量")
        return
    MEASURED.setdefault("texture", {})[tag] = m
    print(f"  [{tag}] 宿主={m['host']} d11 背景={m['d11_background']} 玻璃={m['d11_glass']} "
          f"留存比={m['retention']} 面板亮度差={m['panel_diff']} "
          f"对页底亮度差={m.get('panel_diff_vs_page')} lum={m['lum_background']}→{m['lum_glass']}"
          f"（页底 {m.get('lum_patch')}）")
    if not expect_glass:
        check(True, f"LG-3 {tag} 材质未挂载阶段仅记录（不判留存比）", m["retention"])
        return
    mode = page.evaluate("() => document.documentElement.dataset.glassEngine")
    if mode == "refract":
        check(m["retention"] is not None and m["retention"] >= RETENTION_MIN,
              f"LG-3a {tag} 纹理留存比 ≥ {RETENTION_MIN}（折射把背景纹理带进玻璃面）",
              m["retention"], RETENTION_MIN)
    else:
        # 磨砂档（blur 16px）按物理必然抹平 16px 方格（衰减 exp(−2π²σ²/P²) → ≈0）
        # ⇒ 该档**不判留存比**，只判面板可见性（下方）与 LG-6 的材质参数。
        check(True, f"LG-3a {tag} 磨砂档（{mode}）不判留存比（blur 16px 必然抹平 16px 方格）",
              m["retention"])
    # LG-3b 面板可见性（plan §6.1：卡内空白区亮度 vs 背景）。
    # ⚠️ 阈值 8 → 5 的**实测重标定**：plan 的 8/255 是在「卡边横跨带」口径下量的（那次实测 7.85），
    #    该口径把侧栏/光斑的区域差也算了进去；改成「卡内空白区 vs 近旁纯背景补丁」后，
    #    46% 染色在浅色下只能给出 ≈6.3（面板自身的真实亮度提升 = tint × (255 − 页底 241) ≈ 6.4），
    #    而要把它抬到 8 就得把染色提到 ≈60%（实测 tint 0.60 → 8.20），代价是留存比掉到 0.35 ——
    #    与 plan 自己的「留存比 ≥0.4」互斥（见 baseline-sweep 数据）。取 5 作门限：它仍能识别
    #    「几乎全透」（全透时该值为 0–2），又不与留存比打架。
    check(m.get("panel_diff_vs_page") is not None and m["panel_diff_vs_page"] >= PANEL_DIFF_MIN,
          f"LG-3b {tag} 面板对页底亮度差 ≥ {PANEL_DIFF_MIN}/255（不是全透）",
          m.get("panel_diff_vs_page"), PANEL_DIFF_MIN)
    # LG-3c 面板确实「减幅」了背后的原始纹理（半透而不透明：原始纹理不被原样透传）
    check(m.get("mute_ratio") is not None and m["mute_ratio"] <= 0.8,
          f"LG-3c {tag} 玻璃把背景纹理幅度压到 ≤0.8×（半透非全透）",
          m.get("mute_ratio"), "≤0.8")


def assert_lg4_theme(browser, url: str):
    if not want("LG-4"):
        return
    print("--- LG-4 双主题令牌 ---")
    rows = {}
    for theme in ("light", "dark"):
        ctx, page, errs, bad = open_page(browser, url, theme)
        try:
            d = page.evaluate(HOSTS_JS)
            rows[theme] = d
            check(d["theme"] == theme, f"LG-4 {theme} data-theme 落定", d["theme"], theme)
            check(bool(d["vBg"]) and bool(d["vText"]),
                  f"LG-4 {theme} 皮肤令牌有值（--bg/--text 非空 ⇒ 无白页风险）",
                  (d["vBg"], d["vText"]), "非空")
            page.screenshot(path=str(OUT_DIR / f"lg4-{theme}.png"), full_page=False)
            assert_lg1_console(errs, f"LG-4/{theme}", bad)
        finally:
            ctx.close()
    if "light" in rows and "dark" in rows:
        check(rows["light"]["bodyBgColor"] != rows["dark"]["bodyBgColor"],
              "LG-4c 双主题 body 底色不同", (rows["light"]["bodyBgColor"], rows["dark"]["bodyBgColor"]))
        check(rows["light"]["muted"] != rows["dark"]["muted"],
              "LG-4d --text-muted 仍随主题翻转（皮肤未劫持该令牌）",
              (rows["light"]["muted"], rows["dark"]["muted"]))
        MEASURED["theme"] = {k: {"bg": v["bodyBgColor"], "muted": v["muted"],
                                 "vBg": v["vBg"], "vText": v["vText"]} for k, v in rows.items()}


def assert_lg5_degrade(browser, url: str):
    if not want("LG-5"):
        return
    print("--- LG-5 降级三态 ---")
    # ① prefers-reduced-motion: reduce —— 套件 motion.css 必须把过渡/动画整体关掉
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    page.emulate_media(reduced_motion="reduce")
    page.add_init_script("try{localStorage.setItem('mp-theme','light');}catch(e){}")
    page.goto(url, wait_until="load")
    page.wait_for_selector("#watchlist-section:not(.hidden)", timeout=25000)
    page.wait_for_timeout(900)
    try:
        d = page.evaluate(MEDIA_PROBE_JS)
        tr = d["transition"] or ""
        check(("none 0s" in tr) or (d["anim"] == "none"),
              "LG-5a reduced-motion：玻璃面无过渡/动画", tr, "none 0s")
    finally:
        ctx.close()

    # ② forced-colors: active —— .lg-inner 补 1px CanvasText 描边
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    page.emulate_media(forced_colors="active")
    page.add_init_script("try{localStorage.setItem('mp-theme','light');}catch(e){}")
    page.goto(url, wait_until="load")
    page.wait_for_selector("#watchlist-section:not(.hidden)", timeout=25000)
    page.wait_for_timeout(900)
    try:
        d = page.evaluate(MEDIA_PROBE_JS)
        # ⚠️ 不能钉 "1px"：forced-colors 下 Chrome 会把边框宽按**设备像素**对齐，
        #    在 Windows 125% 缩放的有头窗口里 1px → 计算值 0.8px（实测）。判「>0 且不透明」。
        bw = float(str(d["borderTopWidth"] or "0").replace("px", "") or 0)
        bc = str(d["borderTopColor"] or "")
        opaque = not (bc == "transparent" or (bc.startswith("rgba") and bc.rstrip(")").endswith(", 0")))
        check(d["hasInner"] and bw > 0 and opaque,
              "LG-5b forced-colors：.lg-inner 有系统色描边（CanvasText）",
              (d["borderTopWidth"], d["borderTopColor"]), "宽 >0 且不透明")
    finally:
        ctx.close()

    # ③ prefers-reduced-transparency: reduce —— Playwright 的 emulate_media 未暴露该特性，
    #    只能走 CDP `Emulation.setEmulatedMedia`（Chromium 支持该媒体特性）。
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    page.add_init_script("try{localStorage.setItem('mp-theme','light');}catch(e){}")
    cdp = ctx.new_cdp_session(page)
    try:
        cdp.send("Emulation.setEmulatedMedia",
                 {"features": [{"name": "prefers-reduced-transparency", "value": "reduce"}]})
        cdp_ok = True
    except Exception as exc:  # noqa: BLE001
        cdp_ok = False
        print(f"  [warn] CDP 不支持 prefers-reduced-transparency 仿真：{str(exc)[:80]}")
    page.goto(url, wait_until="load")
    page.wait_for_selector("#watchlist-section:not(.hidden)", timeout=25000)
    page.wait_for_timeout(900)
    try:
        active = page.evaluate("() => matchMedia('(prefers-reduced-transparency: reduce)').matches")
        d = page.evaluate(MEDIA_PROBE_JS)
        if cdp_ok and active:
            bd = d["backdrop"] or ""
            check("none" in bd, "LG-5c reduced-transparency：.lg-inner 关掉 backdrop-filter", bd, "none")
        else:
            # 仿真不可用 → 退化为「CSSOM 里该兜底块存在且规则形状正确」（未判定真渲染）
            shape = page.evaluate(
                """() => {
                     for (const sheet of document.styleSheets) {
                       let rules; try { rules = sheet.cssRules; } catch (e) { continue; }
                       for (const r of rules || []) {
                         if (r.conditionText && r.conditionText.includes('prefers-reduced-transparency')) {
                           for (const inner of (r.cssRules || [])) {
                             if (inner.selectorText && inner.selectorText.includes('.lg-inner')
                                 && inner.style && inner.style.backdropFilter) {
                               return inner.selectorText + ' { backdrop-filter:' + inner.style.backdropFilter + ' }';
                             }
                           }
                         }
                       }
                     }
                     return null;
                   }"""
            )
            check(bool(shape), "LG-5c reduced-transparency 兜底块存在（CSSOM 形状核对；仿真不可用）",
                  shape, "… .lg-inner { backdrop-filter: none !important }")
    finally:
        ctx.close()


    # ④ 引擎加载失败 → 回退到宿主旧玻璃（不是「透明卡片 + 无面」）
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    page.add_init_script("try{localStorage.setItem('mp-theme','light');}catch(e){}")
    blocked = []
    page.route("**/vendor/liquid-glass/*", lambda route: (blocked.append(route.request.url), route.abort()))
    page.goto(url, wait_until="load")
    page.wait_for_selector("#watchlist-section:not(.hidden)", timeout=25000)
    page.wait_for_timeout(1200)
    try:
        d = page.evaluate(
            """() => {
                 const c = document.querySelector('.card:not(.promo)');
                 const k = document.querySelector('.kpi-card');
                 return { degraded: document.documentElement.dataset.skinDegraded || null,
                          inner: document.querySelectorAll('.lg-inner').length,
                          cardBackdrop: c ? getComputedStyle(c).backdropFilter : null,
                          cardBg: c ? getComputedStyle(c).backgroundColor : null,
                          kpiBackdrop: k ? getComputedStyle(k).backdropFilter : null,
                          text: (document.getElementById('overview') || {}).innerText || '' };
               }"""
        )
        print(f"  引擎被拦 {len(blocked)} 个请求 → degraded={d['degraded']} .lg-inner={d['inner']} "
              f"宿主 backdrop={d['cardBackdrop']}")
        check(d["degraded"] == "1" and d["inner"] == 0,
              "LG-5d 引擎加载失败 → html[data-skin-degraded=1] 且不残留 .lg-inner",
              (d["degraded"], d["inner"]), ("1", 0))
        check((d["cardBackdrop"] or "none") != "none" and (d["kpiBackdrop"] or "none") != "none",
              "LG-5e 降级后宿主旧玻璃已装回（不是透明卡片）",
              (d["cardBackdrop"], d["kpiBackdrop"]), "非 none")
        check(bool(d["text"].strip()), "LG-5f 降级后页面仍有正文（不白屏）", d["text"][:20], "非空")
    finally:
        ctx.close()


def assert_lg6_frost(browser, url: str):
    if not want("LG-6"):
        return
    print("--- LG-6 磨砂档（--engine=frost）---")
    if ENGINE != "frost":
        check(False, "LG-6 需要 --engine=frost 运行", ENGINE, "--engine=frost", skip_reason="未以 frost 档运行")
        return
    ctx, page, errs, bad = open_page(browser, url, "light")
    try:
        d = page.evaluate(HOSTS_JS)
        check(d["glassEngine"] == "frost", "LG-6a html[data-glass-engine] = frost", d["glassEngine"], "frost")
        bds = [h["innerBackdrop"] or "" for h in d["hosts"]]
        ok = all(("blur(16px)" in b) and ("saturate(1.6)" in b or "saturate(160%)" in b)
                 and ("brightness(1.03)" in b) for b in bds)
        check(ok, "LG-6b 磨砂档材质 = blur16 / sat1.6 / bri1.03（不是引擎自带 8px/1.4/1.05）",
              bds[0] if bds else None, "blur(16px) saturate(160%) brightness(1.03)")
        page.screenshot(path=str(OUT_DIR / "lg6-frost.png"), full_page=False)
        assert_lg1_console(errs, "LG-6", bad)
    finally:
        ctx.close()


def assert_lg7_firefox(playwright, url: str):
    if not want("LG-7"):
        return
    print("--- LG-7 非 Chromium（Firefox）不白卡 ---")
    try:
        b = playwright.firefox.launch()
    except Exception as exc:  # noqa: BLE001
        check(False, "LG-7 Firefox 内核可用", str(exc)[:80], None, skip_reason="本机未安装 Firefox 内核")
        return
    ctx = b.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    try:
        page.goto(url, wait_until="load")
        page.wait_for_selector("#watchlist-section:not(.hidden)", timeout=30000)
        page.wait_for_timeout(1500)
        d = page.evaluate(HOSTS_JS)
        check(d["glassEngine"] == "frost", "LG-7a Firefox 走磨砂档", d["glassEngine"], "frost")
        check(d["hostCount"] >= MIN_HOSTS, "LG-7b Firefox 上宿主仍在位", d["hostCount"], MIN_HOSTS)
        txt = page.inner_text("#overview")
        check(bool(txt.strip()), "LG-7c Firefox 页面有正文（未白屏）", txt[:24], "非空")
        # 白卡判据：面板不能是「接近纯白的不透明块」
        inner_bg = [h["innerBg"] for h in d["hosts"] if h["tag"] != "topbar"]
        alphas = [_alpha_of(b) for b in inner_bg]
        check(bool(alphas) and all(a is not None and a < 1 for a in alphas),
              "LG-7d Firefox 上面板不是不透明白块（alpha < 1）", alphas[:3], "全部 < 1")
        page.screenshot(path=str(OUT_DIR / "lg7-firefox.png"), full_page=False)
    finally:
        ctx.close()
        b.close()


def assert_lg8_remount(browser, url: str):
    if not want("LG-8"):
        return
    print("--- LG-8 动态渲染批次后材质仍在 ---")
    ctx, page, errs, bad = open_page(browser, url, "light")
    try:
        d0 = page.evaluate(HOSTS_JS)
        check(d0["kpiCount"] == 4, "LG-8a 4 张 KPI 卡在位", d0["kpiCount"], 4)
        # 触发一次重渲染（刷新按钮 → refresh() → renderLede() 重建 KPI 卡 innerHTML）
        page.eval_on_selector("#refresh-btn", "el => el.click()")
        page.wait_for_timeout(1800)
        d1 = page.evaluate(HOSTS_JS)
        bad = [h["key"] for h in d1["hosts"] if h["hostsInner"] != 1]
        check(not bad, "LG-8b 刷新后每个宿主仍恰 1 个 .lg-inner", bad, [])
        kpi = [h for h in d1["hosts"] if h["tag"] == "div" and "kpi-card" in h["key"]]
        check(all(h["hostsInner"] == 1 for h in kpi),
              "LG-8c 4 张 KPI 卡（innerHTML 重建区）重挂载成功",
              [(h["key"], h["hostsInner"]) for h in kpi][:4], [])
        assert_lg1_console(errs, "LG-8", bad)
    finally:
        ctx.close()


def assert_lg9_contrast(browser, url: str):
    if not want("LG-9"):
        return
    print("--- LG-9 文本对比度 ---")
    for theme in ("light", "dark"):
        ctx, page, _, _bad = open_page(browser, url, theme)
        try:
            d = page.evaluate(HOSTS_JS)
            host = (next((h for h in d["hosts"] if h["key"].lstrip("#") in ("overview", "trend")), None)
                    or next((h for h in d["hosts"] if "topbar" not in h["key"]), None))
            if not host:
                # 尚无玻璃宿主（接线阶段）→ 未判定，不算失败
                check(False, f"LG-9 {theme} 面板对比度（需玻璃宿主）", d["hostCount"], "≥1 宿主",
                      skip_reason="尚无 data-liquid-glass 宿主")
                continue
            # 在被测宿主内取一块**无文字**区域采样 = 面板真实渲染色
            px = sample_pixel(page, host["rect"]["x"] + host["rect"]["w"] - 12,
                              host["rect"]["y"] + host["rect"]["h"] - 12)
            MEASURED.setdefault("contrast", {})[theme] = {"panel": px, "text": d["sampleText"]}
            for name, key in (("正文", "textColor"), ("次要文本(--text-muted)", "muted")):
                fg = parse_rgb(d[key]) if key == "muted" else parse_rgb(d["textColor"])
                if fg is None:
                    check(False, f"LG-9 {theme} {name} 色值可解析", d[key], "rgb()")
                    continue
                c = contrast(fg, px)
                check(c >= CONTRAST_MIN, f"LG-9 {theme} {name} 对面板底对比度 ≥{CONTRAST_MIN}",
                      round(c, 2), CONTRAST_MIN)
        finally:
            ctx.close()


def assert_lg11_wiring_parity(browser, url: str):
    """LG-11 接线不改视觉（S2 验收：只挂样式表与运行时，页面上还没有玻璃宿主）。

    做法：同一页面里**临时禁用套件三张表**（tokens / liquid-skin / motion）再截一张，
    与启用态逐像素比 —— 这一对 A/B 把「套件带来的非预期视觉变化」（它的全局 reset、
    body 底色、皮肤根 padding 等）全部暴露出来。宿主补丁层（mp-skin.css）**保持启用**，
    所以背景纹理配方不参与这次比较。
    """
    if not want("LG-11"):
        return
    print("--- LG-11 皮肤接线不改视觉（A/B）---")
    ctx, page, _, _bad = open_page(browser, url, "light")
    try:
        hosts_before = page.evaluate("() => document.querySelectorAll('[data-liquid-glass]').length")
        if hosts_before:
            # 该 A/B 只在**接线阶段**（页面上还没有玻璃宿主）成立：一旦挂了材质，
            # 非折射引擎（headless 无 window.chrome / Firefox）的磨砂材质本身就来自套件 CSS
            # （`html[data-glass-engine='frost'] .lg-inner` 那一节）⇒ 禁用它等于「拆掉材质」，
            # 页面必然大面积变化 —— 那是**预期依赖**，不是「接线引入了视觉变化」。
            check(False, "LG-11 接线阶段无视觉变化（A/B）", hosts_before, 0,
                  skip_reason="已挂玻璃宿主：A/B 不再适用于「接线阶段」这个前提")
            return
        page.evaluate("() => window.scrollTo(0, 0)")
        page.wait_for_timeout(400)
        clip = {"x": 0, "y": 0, "width": 1440, "height": 900}
        a = page.screenshot(clip=clip, type="png")
        found = page.evaluate(
            """() => {
                 const want = ['tokens.css', 'liquid-skin.css', 'motion.css'];
                 let n = 0;
                 for (const l of document.querySelectorAll('link[rel=stylesheet]')) {
                   const href = l.getAttribute('href') || '';
                   if (want.some((w) => href.includes('/skin/' + w))) { l.disabled = true; n++; }
                 }
                 return n;
               }"""
        )
        page.wait_for_timeout(250)
        b = page.screenshot(clip=clip, type="png")
        ia = np.asarray(Image.open(io.BytesIO(a)).convert("RGB"), dtype=np.float64)
        ib = np.asarray(Image.open(io.BytesIO(b)).convert("RGB"), dtype=np.float64)
        diff = np.abs(ia - ib)
        mean = float(diff.mean())
        p99 = float(np.percentile(diff, 99))
        mask = diff.max(axis=2) > 2
        changed = int(mask.sum())
        bbox = None
        if changed:
            ys, xs = np.nonzero(mask)
            bbox = [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]
        MEASURED["wiring_parity"] = {"disabled": found, "mean": round(mean, 4),
                                     "p99": round(p99, 3), "pixels_changed": changed, "bbox": bbox}
        print(f"  A/B: 关掉 {found} 张套件表 → mean={mean:.4f} p99={p99:.3f} 变化像素={changed} bbox={bbox}")
        check(found == 3, "LG-11a 找到并禁用了 3 张套件样式表", found, 3)
        check(mean < 0.05 and changed < 4000,
              "LG-11b 启用/禁用套件样式表后画面几乎一致（接线阶段无视觉变化）",
              f"mean={mean:.4f} changed={changed}", "mean<0.05 且 changed<4000")
    finally:
        ctx.close()


def assert_lg12_ledger_hit(browser, url: str):
    """LG-12 首屏挂载台账 + 命中区 + 窄视口不溢（plan §6.1 / §7.4 / 不变量 I2）。

    三件事：
      ① **挂载台账**：`window.mpSkin.state`（mounted / 总耗时 / 最长单面）+ `longtask` 台账
         —— 分帧挂载的意义就是「不让 13 面同步建图（实测 188.8ms）变成一次长任务」；
      ② **命中区（I2）**：圆角**弧外**的点 `elementFromPoint` 不得命中宿主或其后代
         （浏览器按 border-radius 裁命中区；引擎的 `.lg-inner` 是 `pointer-events:none`）；
      ③ **1280×720**：无横向溢出，且纹理间距不随视口变化（仍是 16px）。
    """
    if not want("LG-12"):
        return
    print("--- LG-12 挂载台账 + 命中区 + 窄视口 ---")
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    page.add_init_script("try{localStorage.setItem('mp-theme','light');}catch(e){}")
    page.add_init_script(
        """window.__longTasks = [];
           try {
             new PerformanceObserver((l) => { for (const e of l.getEntries())
               window.__longTasks.push({ start: Math.round(e.startTime), dur: Math.round(e.duration) }); })
               .observe({ entryTypes: ['longtask'] });
           } catch (e) {}"""
    )
    try:
        page.goto(url, wait_until="load")
        page.wait_for_selector("#watchlist-section:not(.hidden)", timeout=30000)
        page.wait_for_timeout(2500)
        d = page.evaluate(
            """() => {
                 const st = window.mpSkin ? window.mpSkin.state : null;
                 const hosts = document.querySelectorAll('[data-liquid-glass]').length;
                 // `state.mounted` 是**累计**成功挂载数（KPI 卡会被 innerHTML 重建 ⇒ 同一位置挂过多次）；
                 // 这里要的是「当前 DOM 里的宿主是否都已挂上」——按 `.lg-inner` 现数。
                 const mountedNow = [...document.querySelectorAll('[data-liquid-glass]')]
                   .filter((h) => h.querySelector(':scope > .lg-inner')).length;
                 const html = document.documentElement;
                 const corners = [];
                 for (const sel of ['#trend', '#overview', '.kpi-card']) {
                   const el = document.querySelector(sel);
                   if (!el) continue;
                   const r = el.getBoundingClientRect();
                   const rad = parseFloat(getComputedStyle(el).borderTopLeftRadius) || 0;
                   const inside = (x, y) => {
                     const hit = document.elementFromPoint(x, y);
                     return { hit: hit ? (hit.id || hit.className || hit.tagName) : null,
                              isHost: !!(hit && (hit === el || el.contains(hit))) };
                   };
                   // 沿对角线从角点向内扫：命中宿主的**首个** d 就是命中区边界。
                   // 圆角把命中区裁成弧线 ⇒ 边界应出现在 d ≈ rad·(1 − 1/√2)（=4.7px @rad16），
                   // 而不是 d ≈ 0（那是「命中区没被裁」＝玻璃面把整个矩形都吃掉了）。
                   let boundary = null;
                   for (let d = 0.5; d <= Math.min(28, rad + 8); d += 0.5) {
                     if (inside(r.left + d, r.top + d).isHost) { boundary = d; break; }
                   }
                   corners.push({ sel: sel, rad: rad, boundary: boundary,
                                  expect: Math.round(rad * (1 - 1 / Math.SQRT2) * 10) / 10,
                                  hitAtBoundary: boundary !== null ? inside(r.left + boundary, r.top + boundary).hit : null,
                                  center: inside(r.left + r.width / 2, r.top + 8) });
                 }
                 return { state: st, hosts: hosts, mountedNow: mountedNow,
                          ready: html.dataset.skinReady, mounted: html.dataset.skinMounted,
                          longTasks: (window.__longTasks || []).slice(0, 12),
                          overflow: document.scrollingElement.scrollWidth - window.innerWidth,
                          corners: corners };
               }"""
        )
        st = d["state"] or {}
        MEASURED["ledger"] = {"hosts": d["hosts"], "mounted_now": d["mountedNow"],
                              "mount_calls": d["mounted"], "ready": d["ready"],
                              "state": st, "longTasks": d["longTasks"]}
        print(f"  挂载台账: hosts={d['hosts']} 已挂={d['mountedNow']} 累计挂载调用={d['mounted']} ready={d['ready']} "
              f"总耗时={st.get('ms') and round(st['ms'], 1)}ms "
              f"最长单面={round((st.get('ms') or 0) / max(1, st.get('mounted') or 1), 1)}ms(均值)")
        print(f"  longtask: {d['longTasks']}")
        check(d["mountedNow"] == d["hosts"] and d["hosts"] > 0,
              "LG-12a 当前 DOM 里所有宿主都挂上了（含 innerHTML 重建后的 KPI 卡）",
              (d["mountedNow"], d["hosts"]))
        check(d["ready"] == "1", "LG-12b 分帧挂载跑完（html[data-skin-ready]=1）", d["ready"])
        worst = max([t["dur"] for t in d["longTasks"]] or [0])
        check(worst < 200, "LG-12c 皮肤挂载不产生 ≥200ms 长任务（分帧预算生效）",
              f"max={worst}ms / {len(d['longTasks'])} 条", "<200ms")
        bad = []
        for c in d["corners"]:
            print(f"  {c['sel']} rad={c['rad']} 命中区边界 d={c['boundary']}px "
                  f"（几何期望 ≈{c['expect']}px）@ {c['hitAtBoundary']}")
            if c["boundary"] is None or abs(c["boundary"] - c["expect"]) > 2.5:
                bad.append((c["sel"], c["boundary"], c["expect"]))
        check(not bad, "LG-12d 命中区边界贴合圆角弧（弧外不命中宿主，I2）",
              bad, "|d − rad·(1−1/√2)| ≤ 2.5px")
        miss = [c for c in d["corners"] if not c["center"]["isHost"]]
        check(not miss, "LG-12e 对照：宿主内部中心点仍命中宿主（命中区没被整体打穿）",
              [(c["sel"], c["center"]["hit"]) for c in miss], [])

        # ③ 1280×720：无横向溢出 + 纹理间距仍 16px
        page.set_viewport_size({"width": 1280, "height": 720})
        page.wait_for_timeout(600)
        narrow = page.evaluate(
            """() => {
                 const cs = getComputedStyle(document.body);
                 return { overflow: document.scrollingElement.scrollWidth - window.innerWidth,
                          bg: (cs.backgroundImage || '').includes('16px'),
                          layers: (cs.backgroundImage.match(/gradient\\(/g) || []).length };
               }"""
        )
        check(narrow["overflow"] <= 0, "LG-12f 1280×720 无横向溢出", narrow["overflow"], "≤0")
        check(narrow["bg"] and narrow["layers"] >= 4,
              "LG-12g 1280×720 纹理配方不变（16px 方格 + 环境光 ≥4 层）", narrow, "16px 且 ≥4 层")
    finally:
        ctx.close()


def assert_lg10_background(browser, url: str):
    if not want("LG-10"):
        return
    print("--- LG-10 背景纹理配方 ---")
    for theme in ("light", "dark"):
        ctx, page, _, _bad = open_page(browser, url, theme, dpr=3)
        try:
            d = page.evaluate(HOSTS_JS)
            bg = d["bodyBgImage"] or ""
            MEASURED.setdefault("bg", {})[theme] = {k: d[k] for k in
                                                   ("bodyBgImage", "bodyLayerCount", "bodyRepeat",
                                                    "bodyAttachment", "bodyBgColor", "htmlBgImage")}
            check("repeating-linear-gradient" in bg,
                  f"LG-10a {theme} background-image 含方格纹理（多层未被丢弃）", bg[:60], "含 repeating-linear-gradient")
            check(bg.count("repeating-linear-gradient") == 2,
                  f"LG-10b {theme} 两层方格（0deg + 90deg）", bg.count("repeating-linear-gradient"), 2)
            check(f"{SPACING_PX}px" in bg, f"LG-10c {theme} 方格间距 = {SPACING_PX}px",
                  f"{SPACING_PX}px" in bg, True)
            check("radial-gradient" in bg or "linear-gradient" in bg,
                  f"LG-10d {theme} 保留了宿主环境光层（--ambient-*）", bg[-80:], "含 ambient 渐变")
            check((d["htmlBgImage"] or "none") == "none",
                  f"LG-10e {theme} 套件画布已被收回（html background-image = none）",
                  d["htmlBgImage"], "none")
            m = measure_texture(page)
            if m:
                MEASURED.setdefault("texture", {})[theme] = m
                if m.get("error"):
                    check(False, f"LG-10f {theme} 纹理测量可用", m, "有宿主可量")
                elif "d11_background" not in m:
                    check(False, f"LG-10f {theme} 尚无玻璃宿主可量（接线阶段）", m.get("host"), "—",
                          skip_reason="尚无 data-liquid-glass 宿主")
                else:
                    check(m["d11_background"] >= OUT_D11_MIN,
                          f"LG-10f {theme} 背景 d11 ≥ {OUT_D11_MIN}（卡内区域的裸背景有可折射结构）",
                          m["d11_background"], OUT_D11_MIN)
            check(d["sbRuleWidth"] == "6px",
                  f"LG-10g {theme} 宿主 ::-webkit-scrollbar{{width:6px}} 仍在（套件未夺权）",
                  d["sbRuleWidth"], "6px")
            # LG-10h 布局不变：只把**背景图**这一项关掉做 A/B（背景永远不参与布局 ⇒ scrollHeight 必须相同）。
            # ⚠️ 不能整张 mp-skin.css 一起禁用来做这个对照：那张表同时承担「清掉套件皮肤根的
            #    padding:40px 24px 120px」这条修正，禁用后页面反而会整体内缩 +160px（那不是背景的锅）。
            parity = page.evaluate(
                """() => {
                     const b = document.body;
                     const before = document.scrollingElement.scrollHeight;
                     const hasTexture = getComputedStyle(b).backgroundImage.includes('repeating-linear-gradient');
                     const prev = b.style.backgroundImage;      // 纹理来自样式表 ⇒ 内联值通常为空
                     b.style.backgroundImage = 'none';
                     void b.offsetHeight;
                     const after = document.scrollingElement.scrollHeight;
                     b.style.backgroundImage = prev;
                     void b.offsetHeight;
                     return { before, after, hasTexture };
                   }"""
            )
            check(parity["hasTexture"] and parity["before"] == parity["after"],
                  f"LG-10h {theme} 背景纹理不参与布局（关掉 background-image 后 scrollHeight 相同）",
                  parity, "before == after")
            MEASURED.setdefault("scrollh", {})[theme] = {"skin": parity["before"],
                                                         "no_texture": parity["after"]}
        finally:
            ctx.close()


def main() -> int:
    global STRICT, ONLY, ENGINE, FORCED_ENGINE, BASELINE_PATH
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true", help="有 SKIP 即判失败")
    ap.add_argument("--only", default="", help="只跑指定组，逗号分隔（如 LG-9,LG-10）")
    ap.add_argument("--engine", default="auto", choices=("auto", "refract", "frost"))
    ap.add_argument("--headed", action="store_true",
                    help="用有头 Chromium 跑（**折射/留存比必须在有头下测**：headless 无 window.chrome，"
                         "引擎 supportsBackdropFilter() 恒 false ⇒ 只会产出磨砂材质）")
    ap.add_argument("--baseline", default="", help="把实测数值写成基线 JSON")
    ap.add_argument("--min-hosts", type=int, default=2, help="玻璃宿主数下限（S4/S5 一期完成态 = 13）")
    args = ap.parse_args()
    STRICT = args.strict
    ONLY = [s.strip() for s in args.only.split(",") if s.strip()]
    ENGINE = args.engine
    FORCED_ENGINE = "" if args.engine == "auto" else args.engine
    BASELINE_PATH = args.baseline
    MIN_HOSTS = args.min_hosts

    port = free_port()
    url = f"http://127.0.0.1:{port}/"
    print(f"启动 uvicorn: {url}")
    if not PY.exists():
        print(f"找不到 venv python: {PY}")
        return 1
    os.environ["MP_AUTH_DISABLED"] = "1"
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    proc = subprocess.Popen([str(PY), "-m", "uvicorn", "web.app:app", "--port", str(port)],
                            cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
    try:
        wait_ready(url)
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=not args.headed)
            try:
                ctx, page, errs, bad = open_page(browser, url, "light", dpr=3)
                try:
                    d = page.evaluate(HOSTS_JS)
                    print(f"  scopes: skin={d['skinScope']} engine={d['glassEngine']} theme={d['theme']} "
                          f"hosts={d['hostCount']} kpi={d['kpiCount']} scrollH={d['scrollH']}")
                    MOUNTED = d["hostCount"] > 0 and bool(d["glassEngine"])
                    page.screenshot(path=str(OUT_DIR / "lg0-light.png"), full_page=False)
                    assert_lg1_console(errs, "首页", bad)
                    assert_lg2_hosts(d, "1440")
                    assert_lg3_material(page, "light", expect_glass=MOUNTED)
                finally:
                    ctx.close()

                assert_lg4_theme(browser, url)
                assert_lg5_degrade(browser, url)
                assert_lg6_frost(browser, url)
                assert_lg8_remount(browser, url)
                assert_lg9_contrast(browser, url)
                assert_lg10_background(browser, url)
                assert_lg11_wiring_parity(browser, url)
                assert_lg12_ledger_hit(browser, url)
            finally:
                assert_lg7_firefox(p, url)
                browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    if BASELINE_PATH:
        Path(BASELINE_PATH).parent.mkdir(parents=True, exist_ok=True)
        Path(BASELINE_PATH).write_text(json.dumps(MEASURED, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n基线快照: {BASELINE_PATH}")

    print("")
    if FAILURES:
        print(f"FAILED ({len(FAILURES)} 条失败 / {N_PASS} 条通过 / {len(SKIPPED)} 条未判定)")
        for f in FAILURES:
            print(f"  - {f['label']}: actual={f['actual']!r} expect={f['expect']!r}")
        return 1
    if SKIPPED:
        print(f"{len(SKIPPED)} SKIPPED / {N_PASS} PASSED"
              + (f"  → strict 判失败" if STRICT else "  （SKIP 不是绿灯）"))
        return 1 if STRICT else 0
    print(f"ALL PASSED ({N_PASS} 条)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
