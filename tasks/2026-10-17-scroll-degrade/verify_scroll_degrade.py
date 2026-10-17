"""验收回路：滚动期降级（Chromium 的 refract 引擎在页面滚动时掉到 ~10fps）

判据（四项，缺一不可）：
  D1 静止时玻璃**未被降级**：`.lg-inner` 计算值仍是引擎内联的 `url("#lg-N")`（折射保留）
  D2 真实滚动期间**被降级**：计算值变成 `blur(...) saturate(1.4)`
  D3 滚动帧率：中位帧间隔 ≤ 20ms 且 >50ms 的帧 ≤ 5%（修前实测 ~100ms / 97%）
  D4 只跑跑马灯（不滚页面）时**不降级**：元素级 scroll 不得触发（否则玻璃被永久降级）

用法：
  venv/Scripts/python tasks/2026-10-17-scroll-degrade/verify_scroll_degrade.py            # 本地起服
  venv/Scripts/python tasks/2026-10-17-scroll-degrade/verify_scroll_degrade.py --url https://…  # 打线上
"""
import argparse
import io
import os
import socket
import subprocess
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
TMP = os.environ.get("TEMP", "/tmp")

SAMPLE = """
() => {
  const el = document.querySelector('.lg-inner');
  return (getComputedStyle(el).backdropFilter || '').slice(0, 40);
}
"""

ARM = """
() => {
  window.__d = { deltas: [], bf: [] };
  window.__d.t0 = performance.now();
  window.__d.started = false;
  window.__d.ev = [];
  window.__d.pass = 0;          // 与 skin.js 同款守卫「通过」的次数
  window.__d.added = 0;         // 观察到的 class 由无到有次数
  const htmlEl = document.documentElement;
  window.__d.cls = [];
  new MutationObserver(() => window.__d.cls.push([Math.round(performance.now() - window.__d.t0),
      htmlEl.classList.contains('is-scrolling') ? '+' : '-'])).observe(htmlEl, { attributes: true, attributeFilter: ['class'] });
  let wasOn = htmlEl.classList.contains('is-scrolling');
  window.addEventListener('scroll', (e) => {
    const kind = e.target === document ? 'doc' : (e.target === document.scrollingElement ? 'html' : (e.target.id || e.target.className || 'el'));
    window.__d.ev.push([Math.round(performance.now() - window.__d.t0), kind]);
    if (e.target === document || e.target === document.scrollingElement) { window.__d.pass++; window.__d.started = true; }
    const on = htmlEl.classList.contains('is-scrolling');
    if (on && !wasOn) window.__d.added++;
    wasOn = on;
  }, { passive: true, capture: true });
  window.__d.trace = [];
  window.__d.timer = setInterval(() => {
    if (!window.__d.started) return;      // 只在真正开始滚动后才采样
    const el = document.querySelector('.lg-inner');
    window.__d.bf.push((getComputedStyle(el).backdropFilter || '').slice(0, 40));
    window.__d.trace.push([Math.round(performance.now() - window.__d.t0),
                           document.documentElement.className.includes('is-scrolling') ? 'S' : '-',
                           (getComputedStyle(el).backdropFilter || '').slice(0, 22)]);
  }, 100);
  let last = 0;
  (function tick(t) {
    if (!window.__d.started) { window.__d.raf = requestAnimationFrame(tick); return; }
    const d = last ? t - last : 0; last = t;
    if (d > 0) window.__d.deltas.push([Math.round(t - window.__d.t0), d]);
    window.__d.raf = requestAnimationFrame(tick);
  })(performance.now());
  return true;
}
"""

DISARM = """
() => {
  cancelAnimationFrame(window.__d.raf);
  clearInterval(window.__d.timer);
  const docTs = window.__d.ev.filter(r => r[1] === 'doc').map(r => r[0]);
  const w0 = docTs.length ? docTs[0] : 0, w1 = docTs.length ? docTs[docTs.length - 1] : 0;
  // 只统计「真实滚动窗口」内的帧：否则窗口里混进滚动前的长空闲，数字失真
  const win = window.__d.deltas.filter(r => r[0] >= w0 && r[0] <= w1 + 250);
  const s = win.map(r => r[1]).sort((a, b) => a - b);
  const p = (q) => s[Math.min(s.length - 1, Math.floor(s.length * q))] || 0;
  const tr = window.__d.trace.filter(r => r[0] >= w0 - 200 && r[0] <= w1 + 250);
  return { frames: s.length, median: +p(0.5).toFixed(1), p95: +p(0.95).toFixed(1),
           janky: s.filter(d => d > 50).length, win: [w0, w1], allFrames: window.__d.deltas.length,
           uniq: [...new Set(window.__d.bf)].slice(0, 3),
           onPct: tr.length ? Math.round(100 * tr.filter(r => r[1] === 'S').length / tr.length) : -1,
           first12: tr.slice(0, 6), evCount: window.__d.ev.length,
           evKinds: [...new Set(window.__d.ev.map(r => r[1]))].slice(0, 4),
           evGaps: (() => { const ts = window.__d.ev.map(r => r[0]); const g = [];
             for (let i = 1; i < ts.length; i++) g.push(ts[i] - ts[i - 1]);
             g.sort((a, b) => a - b); return g.length ? [g[Math.floor(g.length / 2)], g[g.length - 1]] : []; })(),
           byKind: (() => { const m = {}; window.__d.ev.forEach(r => { m[r[1]] = (m[r[1]] || 0) + 1; }); return m; })(),
           guardPass: window.__d.pass, classAdded: window.__d.added,
           clsTimeline: window.__d.cls.slice(0, 20), clsCount: window.__d.cls.length,
           docFirstLast: (() => { const ts = window.__d.ev.filter(r => r[1] === 'doc').map(r => r[0]);
             return ts.length ? [ts[0], ts[ts.length - 1]] : []; })(),
           docGaps: (() => { const ts = window.__d.ev.filter(r => r[1] === 'doc').map(r => r[0]); const g = [];
             for (let i = 1; i < ts.length; i++) g.push(ts[i] - ts[i - 1]);
             g.sort((a, b) => a - b); return { n: ts.length, med: g.length ? g[Math.floor(g.length / 2)] : -1,
               max: g.length ? g[g.length - 1] : -1, gt200: g.filter(x => x > 200).length }; })() };
}
"""


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="")
    ap.add_argument("--headed", action="store_true", default=True)
    args = ap.parse_args()

    proc = log = None
    url = args.url
    if not url:
        port = free_port()
        url = f"http://127.0.0.1:{port}/"
        log = io.open(os.path.join(TMP, "verify-scroll-degrade.log"), "wb")
        env = dict(os.environ, MP_AUTH_DISABLED="1", PYTHONIOENCODING="utf-8")
        proc = subprocess.Popen([os.path.join(ROOT, "venv", "Scripts", "python.exe"), "-m", "uvicorn",
                                 "web.app:app", "--host", "127.0.0.1", "--port", str(port)],
                                cwd=ROOT, env=env, stdout=log, stderr=log)
        for _ in range(60):
            try:
                urllib.request.urlopen(url + "healthz", timeout=2)
                break
            except Exception:
                time.sleep(0.5)

    fails = []

    def check(ok, name, actual, expect=""):
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ← {actual!r}" if not ok else f"  ← {actual!r}"))
        if not ok:
            fails.append(name)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=False,
                                        args=["--window-size=1600,1000", "--ignore-certificate-errors"])
            ctx = browser.new_context(viewport={"width": 1600, "height": 900}, ignore_https_errors=True)
            page = ctx.new_page()
            errs = []
            page.on("pageerror", lambda e: errs.append(str(e)[:120]))
            page.goto(url, wait_until="load", timeout=60000)
            page.wait_for_timeout(7000)

            engine = page.evaluate("() => document.documentElement.dataset.glassEngine")
            rest = page.evaluate(SAMPLE)
            print(f"  引擎={engine}  静止 backdrop={rest!r}")

            if engine == "refract":
                check(rest.startswith('url('), "D1 静止时未被降级（折射保留）", rest, 'url("#lg-N")')
            else:
                print("  (引擎非 refract ⇒ 跳过 D1 的 url() 判据)")

            # D4：只跑跑马灯（页面不动）
            page.evaluate(ARM)
            page.wait_for_timeout(2500)
            only_ticker = page.evaluate("""() => ({
              cls: document.documentElement.className,
              uniq: [...new Set(window.__d.bf)].slice(0, 3) })""")
            page.evaluate("() => { cancelAnimationFrame(window.__d.raf); clearInterval(window.__d.timer); }")
            check("is-scrolling" not in only_ticker["cls"], "D4 只跑跑马灯时不降级", only_ticker, "无 is-scrolling")
            print(f"     跑马灯期间采样={only_ticker['uniq']!r}")

            # D2/D3：真实滚轮滚动
            # 用 CDP 的合成滚动手势：产生**连续**的 scroll 事件（page.mouse.wheel 是一跳一跳的，
            # 事件成簇到达、簇间 >200ms ⇒ 会把降级状态打成 5% 覆盖率的假红，不代表真实手感）
            page.mouse.move(800, 500)
            page.evaluate(ARM)
            page.wait_for_timeout(300)
            cdp = ctx.new_cdp_session(page)
            for direction in (1, -1):
                cdp.send("Input.synthesizeScrollGesture", {
                    "x": 800, "y": 500, "xDistance": 0, "yDistance": direction * 1400,
                    "speed": 350, "gestureSourceType": "mouse", "repeatCount": 1, "repeatDelayMs": 0,
                })
            r = page.evaluate(DISARM)
            pct = 100.0 * r["janky"] / max(1, r["frames"])
            print(f"  滚动：帧={r['frames']} median={r['median']}ms p95={r['p95']}ms "
                  f"janky={r['janky']}({pct:.0f}%) 采样={r['uniq']!r}")
            print(f"     覆盖率={r['onPct']}%  事件按来源={r['byKind']}  守卫通过={r['guardPass']} 次  "
                  f"class 由无到有={r['classAdded']} 次")
            js = page.evaluate("""() => fetch('/static/skin.js').then(r => r.text()).then(t => ({ cap: t.includes('capture: true'), guard: t.includes('scrollingElement'), len: t.length }))""")
            print(f"     线上 skin.js: {js}")
            print(f"     class 变更时间线（前 20）= {r['clsTimeline']}  共 {r['clsCount']} 次  doc 事件首末={r['docFirstLast']}ms")
            print(f"     doc(视口) 事件 n={r['docGaps']['n']} 间隔中位={r['docGaps']['med']}ms 最大={r['docGaps']['max']}ms "
                  f">200ms 的间隔={r['docGaps']['gt200']} 次")
            check(any("blur(" in s for s in r["uniq"]), "D2 滚动期间被降级成 blur", r["uniq"], "blur(...)")
            check(r["onPct"] >= 90, "D2b 滚动期降级状态稳定（覆盖率 ≥90%）", f"{r['onPct']}%", "≥90%")
            check(r["median"] <= 20.0, "D3a 中位帧间隔 ≤ 20ms", r["median"], "≤20")
            check(pct <= 5.0, "D3b >50ms 帧占比 ≤ 5%", f"{pct:.0f}%", "≤5%")
            check(not errs, "D5 零 pageerror", errs[:2], "[]")
            browser.close()
    finally:
        if proc:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:
                proc.kill()
        if log:
            log.close()

    print(f"\n{'ALL PASSED' if not fails else 'FAILED: ' + ', '.join(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
