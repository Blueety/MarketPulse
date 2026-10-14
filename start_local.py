#!/usr/bin/env python
"""本地一键启动 MarketPulse 看板（只监听 127.0.0.1，不对外）。

用法（在仓库根目录）：
    venv\\Scripts\\python.exe start_local.py
    venv\\Scripts\\python.exe start_local.py --port 8010
    venv\\Scripts\\python.exe start_local.py --no-proxy     # 不设代理（Yahoo/BLS 大概率空态）
    venv\\Scripts\\python.exe start_local.py --no-browser   # 不自动开浏览器

为什么需要代理：本机直连 Yahoo / BLS 会 403（实测）。Clash 在跑时走 127.0.0.1:7890，
/api/macro 从 1.3KB 空态变成 198KB 全量、/api/econ 从降级变成正常；
AkShare（东财/中债）不受影响（Clash 规则把国内域名走直连）。
"""
from __future__ import annotations

import argparse
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser

ROOT = os.path.dirname(os.path.abspath(__file__))
PROXY_CANDIDATES = [7890, 7891, 7897, 10809, 1080]  # Clash / V2Ray / 常见本地混合端口


def _free(port: int) -> bool:
    with socket.socket() as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _listening(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def pick_port(preferred: int) -> int:
    for p in range(preferred, preferred + 20):
        if _free(p):
            return p
    raise SystemExit(f"端口 {preferred}-{preferred + 19} 全被占用，用 --port 指定别的")


def setup_proxy(enabled: bool) -> str | None:
    if not enabled:
        return None
    for p in PROXY_CANDIDATES:
        if _listening(p):
            url = f"http://127.0.0.1:{p}"
            for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
                os.environ[k] = url
            # 本机回环不绕代理，避免自检被拦
            os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"
            return url
    return None


def open_when_ready(url: str, timeout: float = 40.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url + "healthz", timeout=2).read()
            webbrowser.open(url)
            return
        except Exception:
            time.sleep(0.4)
    print(f"[warn] {timeout:.0f}s 内没等到服务就绪，请手动打开 {url}", flush=True)


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    ap = argparse.ArgumentParser(description="本地启动 MarketPulse 看板")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--no-proxy", action="store_true")
    args = ap.parse_args()

    os.chdir(ROOT)
    sys.path.insert(0, ROOT)
    os.environ["MP_AUTH_DISABLED"] = "1"  # 只绑回环，本地看不需要 Basic Auth

    port = pick_port(args.port)
    proxy = setup_proxy(not args.no_proxy)
    url = f"http://127.0.0.1:{port}/"

    print("=" * 62)
    print(f"  MarketPulse 本地看板   {url}")
    print(f"  代理: {proxy or '未启用（Yahoo/BLS 可能空态）'}")
    print(f"  数据: {os.path.join(ROOT, 'data', 'marketpulse.db')}")
    print("  Ctrl+C 停止")
    print("=" * 62, flush=True)

    try:
        import uvicorn  # noqa: PLC0415
        from web.app import app  # noqa: PLC0415
    except ImportError as exc:
        print(f"[error] 依赖缺失（{exc}）。先跑：venv\\Scripts\\pip install -r requirements.txt")
        return 1

    if not args.no_browser:
        threading.Thread(target=open_when_ready, args=(url,), daemon=True).start()

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
