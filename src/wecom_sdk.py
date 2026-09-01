"""企业微信智能机器人 — 官方 SDK + Hermes AI (主动推送模式)。"""
import asyncio
import logging
import subprocess

from wecom_aibot_sdk import WSClient, WSClientOptions, generate_req_id

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("wecom")

BOT_ID = "aibQlFgEwim7Ma40C3ZWee47Mbrpgg6uDCT"
SECRET = "2kwT4xhbz0yRAmvMDLgjsA2VcBBie3e9GFc3fpgAI4d"

client = None


def ask_hermes_sync(question: str) -> str:
    """同步调用 Hermes"""
    try:
        result = subprocess.run(
            ["hermes", "-z", question],
            capture_output=True, text=True, timeout=300,
            encoding="utf-8",
        )
        return result.stdout.strip() or "(无回复)"
    except subprocess.TimeoutExpired:
        return "(AI 处理超时,请稍后再试)"
    except Exception as e:
        return f"(AI 错误: {e})"


async def on_text(frame):
    """处理文本消息 — 先回复确认,后台调 AI,完成后主动推送"""
    body = frame.body or {}
    sender = body.get("from", {}).get("userid", "unknown")
    content = body.get("text", {}).get("content", "").strip()

    if not content:
        return

    log.info("收到 [%s]: %s", sender, content[:100])

    # 1. 立即回复确认(5 秒内)
    stream_id = generate_req_id("stream")
    await client.reply_stream(frame, stream_id, "✅ 收到!AI 正在处理,请稍候...", finish=True)

    # 2. 后台调用 Hermes
    loop = asyncio.get_event_loop()
    reply = await loop.run_in_executor(None, ask_hermes_sync, content)

    # 3. 主动推送最终回复(新消息)
    await client.send_message(sender, {
        "msgtype": "text",
        "text": {"content": reply}
    })
    log.info("已推送 [%s]", sender)


async def on_enter(frame):
    """用户进入会话"""
    log.info("用户进入会话")
    await client.reply_welcome(frame, {
        "msgtype": "text",
        "text": {"content": "你好!我是 MarketPulse AI 助手。\n\n发送任意消息,我会用 AI 回复你。"}
    })


async def main():
    global client
    log.info("启动企业微信 WebSocket 客户端 (Hermes AI - 主动推送模式)")

    options = WSClientOptions(
        bot_id=BOT_ID,
        secret=SECRET,
        reconnect_interval=5000,
        max_reconnect_attempts=-1,
        heartbeat_interval=30000,
    )
    client = WSClient(options)

    client.on("message.text", on_text)
    client.on("event.enter_chat", on_enter)

    await client.connect_async()

    while client.is_connected:
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
