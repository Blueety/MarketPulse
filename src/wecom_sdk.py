"""企业微信智能机器人 — 简化版。"""
import asyncio
import logging
import subprocess

from wecom_aibot_sdk import WSClient, WSClientOptions, generate_req_id

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("wecom")

BOT_ID = "aibQlFgEwim7Ma40C3ZWee47Mbrpgg6uDCT"
SECRET = "2kwT4xhbz0yRAmvMDLgjsA2VcBBie3e9GFc3fpgAI4d"

client = None


def ask_hermes(question: str) -> str:
    try:
        r = subprocess.run(
            ["hermes", "-z", question],
            capture_output=True, text=True, timeout=120,
            encoding="utf-8",
        )
        return r.stdout.strip() or "(无回复)"
    except subprocess.TimeoutExpired:
        return "(处理超时)"
    except Exception as e:
        return f"(错误: {e})"


async def on_text(frame):
    body = frame.body or {}
    sender = body.get("from", {}).get("userid", "unknown")
    content = body.get("text", {}).get("content", "").strip()
    if not content:
        return

    log.info("收到 [%s]: %s", sender, content[:50])

    # 1. 确认收到
    s1 = generate_req_id("r")
    await client.reply_stream(frame, s1, "✅ 收到,处理中...", finish=True)

    # 2. 调 AI
    loop = asyncio.get_event_loop()
    reply = await loop.run_in_executor(None, ask_hermes, content)

    # 3. 回复
    s2 = generate_req_id("r")
    await client.reply_stream(frame, s2, reply, finish=True)
    log.info("已回复 [%s]", sender)


async def on_enter(frame):
    await client.reply_welcome(frame, {
        "msgtype": "text",
        "text": {"content": "你好!我是 MarketPulse 助手。"}
    })


async def main():
    global client
    log.info("启动...")
    options = WSClientOptions(bot_id=BOT_ID, secret=SECRET)
    client = WSClient(options)
    client.on("message.text", on_text)
    client.on("event.enter_chat", on_enter)
    await client.connect_async()
    while client.is_connected:
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
