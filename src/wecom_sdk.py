"""企业微信智能机器人 — 官方 SDK (wecom-aibot-sdk-python)。"""
import asyncio
import logging
import os
import sys

# 设置 venv 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "venv", "Lib", "site-packages"))

from wecom_aibot_sdk import WSClient, generate_req_id

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("wecom")

BOT_ID = "aibQlFgEwim7Ma40C3ZWee47Mbrpgg6uDCT"
SECRET = "2kwT4xhbz0yRAmvMDLgjsA2VcBBie3e9GFc3fpgAI4d"


async def on_text(frame):
    """处理文本消息"""
    body = frame.body or {}
    sender = body.get("sender", {}).get("id", "unknown")
    content = body.get("content", {}).get("text", "")
    log.info("收到 [%s]: %s", sender, content)

    # 回复
    stream_id = generate_req_id("stream")
    await client.reply_stream(frame, stream_id, f"✅ 收到: {content}", finish=True)


async def on_enter(frame):
    """用户进入会话"""
    log.info("用户进入会话")
    await client.reply_welcome(frame, {
        "msgtype": "text",
        "text": {"content": "你好!我是 MarketPulse 通知助手。"}
    })


async def main():
    global client
    log.info("启动企业微信 WebSocket 客户端")

    client = WSClient(
        bot_id=BOT_ID,
        secret=SECRET,
        reconnect_interval=5000,
        max_reconnect_attempts=-1,
        heartbeat_interval=30000,
    )

    client.on("message.text", on_text)
    client.on("event.enter_chat", on_enter)

    await client.connect_async

    # 保持运行
    while client.is_connected:
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
