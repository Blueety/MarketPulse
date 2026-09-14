"""宏观页 refinement 的**快循环**验收（只跑 /macro 相关断言，复用 verify_ui.py 的实现）。

用法（项目根执行）：
    venv/Scripts/python tasks/2026-09-14-macro-page-refine/verify_refine_only.py

⚠️ 这是开发期快循环用的子集运行器（省掉首页 6 分钟的断言）：
   - 断言实现**只有一份**，在 `tasks/2026-09-11-frontend-bento-redesign/verify_ui.py`
     （`assert_macro_page` = MX-*，`assert_macro_refine` = M-*），本文件只负责起服务 + 调用。
   - **定稿验收仍以完整脚本为准**：`venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py`
     （首页回归 M-10 只有完整跑才会覆盖）。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tasks" / "2026-09-11-frontend-bento-redesign"))

import verify_ui as V  # noqa: E402


def main() -> int:
    V.OUT_DIR.mkdir(parents=True, exist_ok=True)
    port = V.free_port()
    url = f"http://127.0.0.1:{port}/"
    print(f"启动 uvicorn: {url}")
    if not V.PY.exists():
        print(f"找不到 venv python: {V.PY}")
        return 1
    proc = subprocess.Popen(
        [str(V.PY), "-m", "uvicorn", "web.app:app", "--port", str(port)],
        cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        V.wait_ready(url)
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()
            V.assert_macro_page(browser, url)     # MX-*
            V.assert_macro_refine(browser, url)   # M-*
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    print("\n===== 结果（宏观子集）=====")
    if V.FAILURES:
        print(f"FAILED: {len(V.FAILURES)} 条")
        for f in V.FAILURES:
            print("  - " + f)
        return 1
    print("ALL PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
