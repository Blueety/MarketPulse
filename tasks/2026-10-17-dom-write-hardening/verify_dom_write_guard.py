"""DOM 写入语义哨兵 + 写入语义修复 验收（2026-10-17；方案 ③ 检测 + 方案 ① 修回替换语义）。

回路（闸门 A）：把「DOM 写入语义被第三方脚本改写」这一环境**注入**进来，断言
（a）哨兵能认出它并留下肇事 setter 的源码片段，（b）修复后**用户可见症状消失**（渲染不再累积），
（c）改不动时优雅降级（页面照常渲染、如实报失败）。
四例：
  C1 干净环境      —— 6 页都不得有任何标记与 warn（不得误报），页面正常
  C2 前置语义注入  —— 必须打 patched + repaired；warn 含 setter 源码片段；
                      **连点 3 次刷新后概览仍恒为 6 小卡**（症状消失），页面零 pageerror
  C3 克隆型注入    —— 必须打 data-dom-write-dup-ids + 一条重复 id 的 warn
  C4 锁死描述符    —— 改不动时必须**不炸页面**：patched + repair-failed + 页面仍渲染、零 pageerror

用法：venv/Scripts/python tasks/2026-10-17-dom-write-hardening/verify_dom_write_guard.py
退出码：有 FAIL → 1，否则 0。
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = ROOT / "venv" / "Scripts" / "python.exe"
# 用户实际用 Firefox 看页面；Chromium 是本仓既有验收口径（verify_ui.py）。两个都跑，避免「只在无头 Chromium 通过」。
ENGINES = ("chromium", "firefox")

FAILS: list[str] = []
PASSES: list[str] = []


def check(ok: bool, label: str, detail: object = "") -> None:
    (PASSES if ok else FAILS).append(label)
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  ← {detail}" if detail != "" else ""))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_ready(url: str, timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url + "healthz", timeout=2) as r:
                if r.status == 200:
                    return
        except Exception:  # noqa: BLE001
            time.sleep(0.3)
    raise RuntimeError(f"服务未就绪: {url}")


# ── 注入脚本（模拟第三方改写的三种形态）────────────────────────────────────────
# C2：把 innerHTML / textContent 的写入语义改成「前置插入、旧内容留在后面」
#     （用户截图里的签名：新内容在前、旧内容在后、原文冻结在初始值）
PATCH_PREPEND = r"""
(() => {
  const d = Object.getOwnPropertyDescriptor(Element.prototype, 'innerHTML');
  Object.defineProperty(Element.prototype, 'innerHTML', {
    configurable: true,
    get: d.get,
    set(v) { const t = document.createElement('template'); d.set.call(t, String(v)); this.insertBefore(t.content, this.firstChild); },
  });
  const tc = Object.getOwnPropertyDescriptor(Node.prototype, 'textContent');
  Object.defineProperty(Node.prototype, 'textContent', {
    configurable: true,
    get: tc.get,
    set(v) { this.insertBefore(document.createTextNode(String(v)), this.firstChild); },
  });
})();
"""

# C3：克隆一个带 id 的元素并前置插入（克隆型注入 ⇒ 同一 id 出现两次，写入只落进第一个副本）
PATCH_CLONE = r"""
(() => {
  document.addEventListener('DOMContentLoaded', () => {
    const el = document.getElementById('overview-body');
    if (el && el.parentElement) el.parentElement.insertBefore(el.cloneNode(true), el);
  });
})();
"""

# C4：改写后把描述符设成 non-configurable ⇒ 恢复必须失败（且不能把页面带崩）
PATCH_LOCKED = r"""
(() => {
  const d = Object.getOwnPropertyDescriptor(Element.prototype, 'innerHTML');
  Object.defineProperty(Element.prototype, 'innerHTML', {
    configurable: false,
    get: d.get,
    set(v) { const t = document.createElement('template'); d.set.call(t, String(v)); this.insertBefore(t.content, this.firstChild); },
  });
})();
"""

PROBE = r"""
() => ({
  patched: document.documentElement.getAttribute('data-dom-write-patched'),
  repaired: document.documentElement.getAttribute('data-dom-write-repaired'),
  repairFailed: document.documentElement.getAttribute('data-dom-write-repair-failed'),
  dupIds: document.documentElement.getAttribute('data-dom-write-dup-ids'),
  guardError: document.documentElement.getAttribute('data-dom-write-guard-error'),
  miniCards: document.querySelectorAll('#overview-body .mini-card').length,
  bodyChildren: document.body.children.length,
  // 免疫判据：连写两次应只剩最后一次（原生语义）
  writeSemantics: (() => { const d = document.createElement('div'); d.innerHTML = 'aaa'; d.innerHTML = 'b'; return d.innerHTML; })(),
})
"""


def run_case(browser, url: str, name: str, init_script: str | None,
             page_url: str | None = None, refreshes: int = 0,
             late_script: str | None = None, late_delay_ms: int = 0) -> tuple[dict, list[str], dict]:
    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
    page = ctx.new_page()
    logs: list[str] = []
    page.on("console", lambda m: logs.append(m.text))
    page.on("pageerror", lambda e: logs.append(f"pageerror: {e}"))
    if init_script:
        page.add_init_script(init_script)
    page.goto(page_url or url, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)          # 哨兵的复查 + 重复 id 检查在 DOMContentLoaded +1.5s
    probe = page.evaluate(PROBE)
    print(f"\n--- {name} ---")
    print("   probe:", probe)
    if late_script:                      # C5/C6：**晚改写** —— 在哨兵最后一轮（+1.5s）之后才改写入语义
        if late_delay_ms:
            page.wait_for_timeout(late_delay_ms)
        page.evaluate(late_script)
        page.wait_for_timeout(400)
        print("   after late patch:", page.evaluate(PROBE))
    after = probe
    if refreshes:                        # 触发多轮渲染：症状（累积）在未免疫时必然出现
        for _ in range(refreshes):
            try:
                page.click("#refresh-btn")
            except Exception as exc:  # noqa: BLE001
                print("   refresh 点击失败:", str(exc)[:80])
                break
            page.wait_for_timeout(900)
        after = page.evaluate(PROBE)
        print("   after refreshes:", after)
    warns = [t for t in logs if "[dom-write]" in t or t.startswith("pageerror")]
    for w in warns:
        print("   warn:", w.replace("\n", " ")[:260])
    ctx.close()
    return probe, warns, after


def main() -> int:
    port = free_port()
    url = f"http://127.0.0.1:{port}/"
    if not PY.exists():
        print(f"找不到 venv python: {PY}")
        return 1
    os.environ["MP_AUTH_DISABLED"] = "1"     # 与 verify_ui.py 同款：验收实例关鉴权
    log_path = Path(os.environ.get("TEMP", "/tmp")) / "marketpulse-dom-write-verify-uvicorn.log"
    log_fh = open(log_path, "wb")
    proc = subprocess.Popen(
        [str(PY), "-m", "uvicorn", "web.app:app", "--port", str(port)],
        cwd=str(ROOT), stdout=log_fh, stderr=subprocess.STDOUT,
    )
    try:
        try:
            wait_ready(url)
        except RuntimeError:
            print(f"服务未就绪；uvicorn 日志（{log_path}）尾部：")
            print(log_path.read_text(encoding="utf-8", errors="replace")[-1500:])
            raise
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            # 两个引擎都跑：用户实际用的是 Firefox（页面是在 Firefox 里看的），Chromium 是本仓既有验收口径。
            for engine in ENGINES:
                browser = getattr(p, engine).launch()
                print(f"\n===== 引擎 {engine} =====")

                # ── C1 干净环境：6 页都不得误报（哨兵装在 6 个模板里，任一页误报都会污染 console）──
                for path in ("", "macro", "macro_cn", "timeline", "backtest", "settings"):
                    probe, warns, _ = run_case(browser, url, f"[{engine}] C1 干净环境 {path or '/'}", None,
                                               page_url=url + path)
                    tag = f"{engine}|{path or '/'}"
                    check(probe["patched"] is None, f"C1[{tag}] 无 data-dom-write-patched", probe["patched"])
                    check(probe["repaired"] is None, f"C1[{tag}] 无 data-dom-write-repaired", probe["repaired"])
                    check(probe["dupIds"] is None, f"C1[{tag}] 无 data-dom-write-dup-ids", probe["dupIds"])
                    check(probe["guardError"] is None, f"C1[{tag}] 哨兵自身无异常", probe["guardError"])
                    check(not warns, f"C1[{tag}] 无 [dom-write] warn / 无 pageerror", warns[:1])
                    if path == "":
                        check(probe["miniCards"] == 6, f"C1[{tag}] 页面正常（概览 6 小卡）", probe["miniCards"])

                # ── C2 前置语义注入：认出 + 恢复 + 症状消失 ──────────────────────
                probe, warns, after = run_case(browser, url, f"[{engine}] C2 前置语义注入", PATCH_PREPEND,
                                               refreshes=3)
                check(probe["patched"] == "innerHTML,textContent", f"C2[{engine}] 认出被改写的 API", probe["patched"])
                blob = " ".join(warns)
                check("insertBefore" in blob, f"C2[{engine}] warn 含被改写 setter 的源码片段", "insertBefore" in blob)
                check(probe["repaired"] == "innerHTML,textContent", f"C2[{engine}] 写入语义修回替换（repaired）", probe["repaired"])
                check(probe["writeSemantics"] == "b", f"C2[{engine}] 免疫判据（连写两次只剩最后一次）", probe["writeSemantics"])
                check(after["miniCards"] == 6, f"C2[{engine}] 连点 3 次刷新后概览恒为 6 小卡（症状消失）", after["miniCards"])
                check(after["guardError"] is None, f"C2[{engine}] 哨兵自身无异常", after["guardError"])
                check(not [w for w in warns if w.startswith("pageerror")], f"C2[{engine}] 零 pageerror",
                      [w for w in warns if w.startswith("pageerror")][:1])

                # ── C3 克隆型注入：重复 id 必须被认出 ────────────────────────────
                probe, warns, _ = run_case(browser, url, f"[{engine}] C3 克隆型注入", PATCH_CLONE)
                dup = int(probe["dupIds"] or 0)
                check(dup > 0, f"C3[{engine}] 标记重复 id 数 > 0", probe["dupIds"])
                check(any("重复 id" in w for w in warns), f"C3[{engine}] warn 说明重复 id", len(warns))
                check(probe["guardError"] is None, f"C3[{engine}] 哨兵自身无异常", probe["guardError"])

                # ── C4 锁死描述符：恢复必须失败且不炸页面 ────────────────────────
                probe, warns, _ = run_case(browser, url, f"[{engine}] C4 锁死描述符", PATCH_LOCKED)
                check(probe["patched"] == "innerHTML", f"C4[{engine}] 认出 innerHTML 被改写", probe["patched"])
                check(probe["repairFailed"] == "innerHTML", f"C4[{engine}] 如实报修复失败", probe["repairFailed"])
                check(probe["miniCards"] == 6, f"C4[{engine}] 页面照常渲染（优雅降级）", probe["miniCards"])
                check(probe["guardError"] is None, f"C4[{engine}] 哨兵自身无异常", probe["guardError"])
                check(not [w for w in warns if w.startswith("pageerror")], f"C4[{engine}] 零 pageerror",
                      [w for w in warns if w.startswith("pageerror")][:1])

                # ── C5 晚改写：在哨兵最后一轮（+1.5s）**之后**才改写入语义 ────────
                # 线上症状复现路径：用户浏览器里的注入脚本在 idle 阶段才跑 ⇒ 首帧检查扑空 ⇒ 之后每轮渲染都前置插入。
                probe, warns, after = run_case(browser, url, f"[{engine}] C5 晚改写", None,
                                               late_script=PATCH_PREPEND, refreshes=3)
                check(after["patched"] == "innerHTML,textContent", f"C5[{engine}] 晚改写仍被认出", after["patched"])
                check(after["repaired"] == "innerHTML,textContent", f"C5[{engine}] 晚改写仍被修回（repaired）", after["repaired"])
                check(after["writeSemantics"] == "b", f"C5[{engine}] 修回后写入语义=替换", after["writeSemantics"])
                check(after["miniCards"] == 6, f"C5[{engine}] 晚改写后连点 3 次刷新概览恒为 6 小卡", after["miniCards"])
                check(after["guardError"] is None, f"C5[{engine}] 哨兵自身无异常", after["guardError"])
                check(not [w for w in warns if w.startswith("pageerror")], f"C5[{engine}] 零 pageerror",
                      [w for w in warns if w.startswith("pageerror")][:1])

                # ── C6 修回之后**再次**被覆盖（改写层比哨兵晚跑第二次）───────────
                probe, warns, after = run_case(browser, url, f"[{engine}] C6 修回后再被覆盖", PATCH_PREPEND,
                                               late_script=PATCH_PREPEND, refreshes=3)
                check(after["writeSemantics"] == "b", f"C6[{engine}] 再被覆盖后写入语义仍为替换", after["writeSemantics"])
                check(after["miniCards"] == 6, f"C6[{engine}] 再被覆盖后连点 3 次刷新概览恒为 6 小卡", after["miniCards"])
                check(after["guardError"] is None, f"C6[{engine}] 哨兵自身无异常", after["guardError"])
                check(not [w for w in warns if w.startswith("pageerror")], f"C6[{engine}] 零 pageerror",
                      [w for w in warns if w.startswith("pageerror")][:1])

                browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    print(f"\n汇总: PASS {len(PASSES)} / FAIL {len(FAILS)}")
    if FAILS:
        for f in FAILS:
            print(f"  FAIL: {f}")
        return 1
    print("ALL PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
