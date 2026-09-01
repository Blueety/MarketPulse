"""企业微信智能机器人 WebSocket 长连接客户端。

连接地址: wss://openws.work.weixin.qq.com
协议: aibot_subscribe / aibot_send_msg
"""
import asyncio
import json
import logging
import uuid
from datetime import datetime

import websockets

log = logging.getLogger("wecom-ws")

# 配置
BOT_ID = "aibQlFgEwim7Ma40C3ZWee47Mbrpgg6uDCT"
SECRET = "2kwT4xhbz0yRAmvMDLgjsA2VcBBie3e9GFc3fpgAI4d"
WS_URL = "wss://openws.work.weixin.qq.com"
PING_INTERVAL = 30  # 心跳间隔(秒)


def _req_id() -> str:
    """生成请求 ID"""
    return str(uuid.uuid4())


async def subscribe(ws) -> bool:
    """发送订阅请求"""
    payload = {
        "cmd": "aibot_subscribe",
        "headers": {"req_id": _req_id()},
        "body": {"bot_id": BOT_ID, "secret": SECRET},
    }
    await ws.send(json.dumps(payload))
    log.info("已发送订阅请求")

    # 等待订阅响应
    try:
        resp = await asyncio.wait_for(ws.recv(), timeout=10)
        data = json.loads(resp)
        if data.get("errcode") == 0 or data.get("ret") == 0:
            log.info("订阅成功")
            return True
        else:
            log.error("订阅失败: %s", data)
            return False
    except asyncio.TimeoutError:
        log.error("订阅超时")
        return False


async def send_message(ws, user_id: str, content: str, msg_id: str = None):
    """发送消息给用户"""
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
    if msg_id:
        payload["body"]["msg_id"] = msg_id

    await ws.send(json.dumps(payload))
    log.info("已发送消息给 %s", user_id)


async def handle_message(ws, raw: str):
    """处理收到的消息"""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("无法解析消息: %s", raw[:200])
        return

    cmd = data.get("cmd")
    if cmd == "aibot_msg":
        # 收到用户消息
        body = data.get("body", {})
        user_id = body.get("sender", {}).get("id", "unknown")
        content = body.get("content", {}).get("text", "")
        msg_id = body.get("msg_id", "")

        log.info("收到消息 [%s]: %s", user_id, content[:100])

        # TODO: 这里接入 Hermes 处理逻辑
        # 目前先回复一条确认消息
        reply = f"收到你的消息: {content}"
        await send_message(ws, user_id, reply, msg_id)

    elif cmd == "aibot_chat_quit":
        # 用户退出对话
        log.info("用户退出对话")

    elif cmd == "aibot_error":
        # 错误通知
        log.error("企业微信错误: %s", data.get("body"))


async def heartbeat(ws):
    """心跳保活"""
    while True:
        try:
            await asyncio.sleep(PING_INTERVAL)
            await ws.ping()
        except Exception as e:
            log.warning("心跳失败: %s", e)
            break


async def connect():
    """建立 WebSocket 连接并保持"""
    while True:
        try:
            log.info("正在连接 %s ...", WS_URL)
            async with websockets.connect(
                WS_URL,
                ping_interval=None,  # 我们自己管理心跳
                close_timeout=5,
            ) as ws:
                log.info("连接成功")

                # 订阅
                if not await subscribe(ws):
                    log.error("订阅失败,5 秒后重试")
                    await asyncio.sleep(5)
                    continue

                # 启动心跳
                hb_task = asyncio.create_task(heartbeat(ws))

                # 接收消息循环
                try:
                    async for raw in ws:
                        asyncio.create_task(handle_message(ws, raw))
                except websockets.ConnectionClosed as e:
                    log.warning("连接断开: %s", e)
                finally:
                    hb_task.cancel()

        except Exception as e:
            log.error("连接异常: %s", e)

        log.info("5 秒后重试...")
        await asyncio.sleep(5)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    log.info("启动企业微信 WebSocket 客户端")
    asyncio.run(connect())


if __name__ == "__main__":
    main()
