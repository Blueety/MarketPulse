"""企业微信 WebSocket 通知渠道 — Hermes 集成。

作为后台守护进程运行,接收用户消息并转发给 Hermes 处理。
"""
import asyncio
import json
import logging
import uuid
from datetime import datetime

import websockets

log = logging.getLogger("wecom-channel")

# 企业微信配置
BOT_ID = "aibQlFgEwim7Ma40C3ZWee47Mbrpgg6uDCT"
SECRET = "2kwT4xhbz0yRAmvMDLgjsA2VcBBie3e9GFc3fpgAI4d"
WS_URL = "wss://openws.work.weixin.qq.com"
PING_INTERVAL = 30


def _req_id() -> str:
    return str(uuid.uuid4())


async def subscribe(ws) -> bool:
    """发送订阅请求"""
    payload = {
        "cmd": "aibot_subscribe",
        "headers": {"req_id": _req_id()},
        "body": {"bot_id": BOT_ID, "secret": SECRET},
    }
    await ws.send(json.dumps(payload))

    try:
        resp = await asyncio.wait_for(ws.recv(), timeout=10)
        data = json.loads(resp)
        if data.get("errcode") == 0 or data.get("ret") == 0:
            log.info("企业微信订阅成功")
            return True
        else:
            log.error("订阅失败: %s", data)
            return False
    except asyncio.TimeoutError:
        log.error("订阅超时")
        return False


async def send_text(ws, user_id: str, content: str):
    """发送文本消息"""
    payload = {
        "cmd": "aibot_send_msg",
        "headers": {"req_id": _req_id()},
        "body": {
            "bots": [{"bot_id": BOT_ID}],
            "receiver": {"type": "user", "id": user_id},
            "msg_type": "text",
            "content": {"text": content},
        },
    }
    await ws.send(json.dumps(payload))
    log.info("已发送消息给 %s", user_id)


async def handle_incoming(ws, raw: str):
    """处理收到的用户消息 — 转发给 Hermes"""
    log.info("原始消息: %s", raw[:500])
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return

    cmd = data.get("cmd")
    if cmd not in ("aibot_msg", "aibot_msg_callback"):
        log.info("非消息命令: %s", cmd)
        return

    body = data.get("body", {})
    user_id = body.get("sender", {}).get("id", "unknown")
    content = body.get("content", {}).get("text", "").strip()
    msg_id = body.get("msg_id", "")

    if not content:
        return

    log.info("收到消息 [%s]: %s", user_id, content[:100])

    # TODO: 这里调用 Hermes API 或本地处理
    # 目前先回复确认
    reply = f"✅ 已收到: {content}"
    await send_text(ws, user_id, reply)


async def heartbeat(ws):
    """心跳保活"""
    while True:
        try:
            await asyncio.sleep(PING_INTERVAL)
            await ws.ping()
        except Exception:
            break


async def connect():
    """主连接循环"""
    while True:
        try:
            async with websockets.connect(
                WS_URL, ping_interval=None, close_timeout=5
            ) as ws:
                if not await subscribe(ws):
                    await asyncio.sleep(5)
                    continue

                hb = asyncio.create_task(heartbeat(ws))
                try:
                    async for raw in ws:
                        asyncio.create_task(handle_incoming(ws, raw))
                except websockets.ConnectionClosed as e:
                    log.warning("连接断开: %s", e)
                finally:
                    hb.cancel()

        except Exception as e:
            log.error("连接异常: %s", e)

        await asyncio.sleep(5)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    log.info("启动企业微信 WebSocket 通知渠道")
    asyncio.run(connect())


if __name__ == "__main__":
    main()
