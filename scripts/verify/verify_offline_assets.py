"""验收回路：离线自包含（阻断一切第三方域后，3 个出图页面仍能画出图）。

要证的可观察事实：**页面不依赖任何第三方 CDN**。
做法 = 真实浏览器 + 真实模板 + 本地起服，`context.route("**/*")` 把**所有**非本机请求 abort，
再断言 Chart.js 已加载且页面指定 canvas 上有活的 Chart 实例。

判据（每个 页面 × 视口）：
  A1 `window.Chart` 为真（自托管脚本真的取到了）
  A2 `window.__chartFailed` 为假（模板里的 `onerror` 降级没被触发）
  A3 canvas 上有实例：`Chart.getChart(el)` 非空
  A4 canvas 可见：`display !== 'none'` 且 `getBoundingClientRect()` 宽高 > 0

为什么这么测（而不是 grep 模板里有没有 `cdn.jsdelivr`）：
  文本断言换个变量名/换个 CDN 就漏，且无法证明「断网仍出图」。这里直接复现用户手机上的条件
  （第三方域不可达），失败信息落在「哪页哪个 canvas」。

用法：
  venv/Scripts/python scripts/verify/verify_offline_assets.py
  venv/Scripts/python scripts/verify/verify_offline_assets.py --headed
"""
from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = ROOT / "venv" / "Scripts" / "python.exe"

#: 页面 → 该页主图 canvas（`/` = 首页趋势卡；宏观页 = `macro-chart`；中国宏观页 = `cn-chart`）
CASES = [
    ("/", "#chart-main"),
    ("/macro", "#macro-chart"),
    ("/macro/cn", "#cn-chart"),
]

#: 桌面 + 移动（移动那档必须 `is_mobile` + touch + Android UA：用户报的就是手机端）
VIEWPORTS = [
    {"label": "1440x900", "viewport": {"width": 1440, "height": 900}},
    {"label": "375x812", "viewport": {"width": 375, "height": 812},
     "is_mobile": True, "has_touch": True,
     "user_agent": ("Mozilla/5.0 (Linux; Android 13; Pixel 7 Build/TQ3A.230805.001) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36")},
]

#: 页面是异步取数 + 骨架屏 ⇒ 必须轮询到实例出现；超时才算失败（固定 sleep 既慢又脆）
CHART_TIMEOUT = 20.0
LIB_TIMEOUT = 20.0
POLL = 0.25

STATE_JS = """
(sel) => {
  const el = document.querySelector(sel);
  const out = {
    chart: !!window.Chart,
    failed: window.__chartFailed === true,
    zoomFailed: window.__zoomFailed === true,
    el: !!el,
    instance: false, display: null, w: 0, h: 0,
    // 页面自己的降级文案：把「资源没取到」与「取到了但上游无数据」分开
    // （宏观两页在上游取数失败时会合法地不出图，`macro.js` / `macro_cn.js` 用 `.mac-fail` 提示）
    fallbacks: []
  };
  out.fallbacks = Array.from(document.querySelectorAll('.chart-empty, .mac-fail, .mac-empty'))
    .filter(e => !e.classList.contains('hidden') && e.textContent.trim())
    .map(e => e.textContent.trim().slice(0, 40));
  if (el) {
    try { out.instance = !!(window.Chart && window.Chart.getChart(el)); } catch (e) { out.instance = false; }
    out.display = getComputedStyle(el).display;
    const r = el.getBoundingClientRect();
    out.w = Math.round(r.width); out.h = Math.round(r.height);
  }
  return out;
}
"""


def free_port() -> int:
    # ⚠️ Chromium 把一批端口列为 unsafe（实测抽到 6665 直接 `net::ERR_UNSAFE_PORT`），
    #    而 Windows 的动态端口范围能给出这些值 ⇒ 必须跳过，否则整轮假红。
    unsafe = {1, 7, 9, 11, 13, 15, 17, 19, 20, 21, 22, 23, 25, 37, 42, 43, 53, 69, 77, 79, 87, 95,
              101, 102, 103, 104, 109, 110, 111, 113, 115, 117, 119, 123, 135, 137, 139, 143, 161,
              179, 389, 427, 465, 512, 513, 514, 515, 526, 530, 531, 532, 540, 548, 554, 556, 563,
              587, 601, 636, 989, 990, 993, 995, 1719, 1720, 1723, 2049, 3659, 4045, 4190, 5060,
              5061, 6000, 6566, 6665, 6666, 6667, 6668, 6669, 6697, 10080}
    for _ in range(64):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        if port not in unsafe:
            return port
    raise RuntimeError("连续 64 次都抽到 Chromium 禁用端口")


def wait_ready(url: str, timeout: float = 40.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return
        except Exception:
            pass
        time.sleep(0.4)
    raise RuntimeError(f"服务未在 {timeout}s 内就绪: {url}")


def _is_local(url: str) -> bool:
    """只放行本机（否则连页面本身都被 abort，全部假红）。"""
    return url.startswith("http://127.0.0.1") or url.startswith("http://localhost") \
        or url.startswith("ws://127.0.0.1") or url.startswith("ws://localhost")


def _make_router(blocked: list[str]):
    def handle(route):
        url = route.request.url
        if _is_local(url):
            route.continue_()
        else:
            blocked.append(url)
            route.abort()
    return handle


def _wait_chart(page, sel: str) -> dict:
    """轮询到实例出现或 `__chartFailed` / 超时。返回最后一次测量快照。"""
    deadline = time.time() + CHART_TIMEOUT
    state = {"chart": False, "failed": False, "el": False, "instance": False,
             "display": None, "w": 0, "h": 0, "fallbacks": []}
    while time.time() < deadline:
        state = page.evaluate(STATE_JS, sel)
        if state["instance"]:
            return state
        if state["failed"]:
            # 已是确定失败态，无需等满 CHART_TIMEOUT。
            # ⚠️ 曾经写成 `chart and failed` —— 恒假（`__chartFailed` 只由 Chart.js 的 onerror 置位，
            #    那时 `window.Chart` 必然 missing），于是每例白等 20s、6 组 ≈2 分钟才报红。
            return state
        time.sleep(POLL)
    return state


def run_case(browser, url: str, path: str, sel: str, vp: dict) -> list[str]:
    """跑一个 页面 × 视口；返回失败原因列表（空 = 通过）。"""
    label = f"{path} {vp['label']} {sel}"
    ctx_args = {k: v for k, v in vp.items() if k != "label"}
    ctx = browser.new_context(**ctx_args)
    blocked: list[str] = []
    ctx.route("**/*", _make_router(blocked))
    page = ctx.new_page()
    fails: list[str] = []
    try:
        page.goto(url + path.lstrip("/"), wait_until="domcontentloaded", timeout=30000)
        # A1：脚本加载（给足 20s；模板 head 是同源静态文件，正常应在首帧内就绪）
        try:
            page.wait_for_function("() => !!window.Chart || window.__chartFailed === true",
                                   timeout=int(LIB_TIMEOUT * 1000))
        except Exception:
            pass                                # 交给下面的断言给具体原因
        state = _wait_chart(page, sel)
        fb = state.get("fallbacks") or []
        hint = f"（页面降级文案：{' / '.join(fb)}）" if fb else ""
        if not state["chart"]:
            fails.append("window.Chart 未加载（自托管脚本没取到）")
        if state["failed"]:
            fails.append("window.__chartFailed=true（onerror 降级被触发）")
        if not state["el"]:
            fails.append("canvas 不存在")
        elif not state["instance"]:
            # 附上页面自己的降级文案：宏观两页在上游取数失败时也会合法地不出图，
            # 没有这行时「静态资源坏了」与「/api/macro 那类上游返回空」在报告里长得一样。
            fails.append("canvas 上没有 Chart 实例" + hint)
        elif state["display"] == "none" or state["w"] <= 0 or state["h"] <= 0:
            fails.append(f"canvas 不可见（display={state['display']} {state['w']}x{state['h']}）")
        # 阻断列表只作诊断输出：真正判据是上面四条
        third = sorted({u.split("/")[2] for u in blocked if "://" in u})
        detail = f"instance={state['instance']} display={state['display']} {state['w']}x{state['h']}"
        if third:
            detail += f" 阻断第三方域={','.join(third)}"
        for f in fails:
            print(f"[FAIL] {label} {f}")
        if not fails:
            print(f"[OK] {label} {detail}")
    finally:
        ctx.close()
    return fails


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--headed", action="store_true", help="有头模式（调试用）")
    args = ap.parse_args()

    if not PY.exists():
        print(f"找不到 venv python: {PY}")
        return 1

    port = free_port()
    url = f"http://127.0.0.1:{port}/"
    print(f"启动 uvicorn: {url}")
    env = dict(os.environ)
    env["MP_AUTH_DISABLED"] = "1"      # 鉴权在本任务之外，验收只关心资源可达性
    proc = subprocess.Popen(
        [str(PY), "-m", "uvicorn", "web.app:app", "--port", str(port)],
        cwd=str(ROOT), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    fails: list[str] = []
    try:
        wait_ready(url + "healthz")
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=not args.headed)
            try:
                for vp in VIEWPORTS:
                    for path, sel in CASES:
                        fails += run_case(browser, url, path, sel, vp)
            finally:
                browser.close()
    except Exception as exc:                       # noqa: BLE001 — 起服/浏览器异常一律判失败
        print(f"[FAIL] 运行异常: {exc}")
        fails.append(str(exc))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)

    if fails:
        print(f"\nFAILED: {len(fails)} 条")
        return 1
    print(f"\nALL PASSED（{len(CASES) * len(VIEWPORTS)} 组）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
