"""企业微信智能机器人 — 带上下文记忆。"""
import asyncio
import logging
import subprocess
from collections import defaultdict

from wecom_aibot_sdk import WSClient, WSClientOptions, generate_req_id

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("wecom")

BOT_ID = "aibQlFgEwim7Ma40C3ZWee47Mbrpgg6uDCT"
SECRET = "2kwT4xhbz0yRAmvMDLgjsA2VcBBie3e9GFc3fpgAI4d"

client = None

# 每个用户的对话历史(最近 10 条)
chat_history = defaultdict(list)
MAX_HISTORY = 10


def ask_hermes_with_history(user_id: str, question: str) -> str:
    """带上下文调用 Hermes"""
    history = chat_history[user_id]

    # 构建带历史的 prompt
    if history:
        context = "之前的对话:\n"
        for msg in history[-MAX_HISTORY:]:
            role = "用户" if msg["role"] == "user" else "助手"
            context += f"{role}: {msg['content']}\n"
        context += f"\n用户: {question}\n\n请基于以上上下文回答。"
    else:
        context = question

    try:
        r = subprocess.run(
            ["hermes", "-z", context],
            capture_output=True, text=True, timeout=120,
            encoding="utf-8",
        )
        reply = r.stdout.strip() or "(无回复)"
    except subprocess.TimeoutExpired:
        reply = "(处理超时)"
    except Exception as e:
        reply = f"(错误: {e})"

    # 保存历史
    chat_history[user_id].append({"role": "user", "content": question})
    chat_history[user_id].append({"role": "assistant", "content": reply})

    # 只保留最近 N 条
    if len(chat_history[user_id]) > MAX_HISTORY * 2:
        chat_history[user_id] = chat_history[user_id][-MAX_HISTORY * 2:]

    return reply


async def on_text(frame):
    body = frame.body or {}
    sender = body.get("from", {}).get("userid", "unknown")
    content = body.get("text", {}).get("content", "").strip()
    if not content:
        return

    log.info("收到 [%s]: %s", sender, content[:50])

    # 确认收到
    s1 = generate_req_id("r")
    await client.reply_stream(frame, s1, "✅ 收到,处理中...", finish=True)

    # 调 AI(带上下文)
    loop = asyncio.get_event_loop()
    reply = await loop.run_in_executor(None, ask_hermes_with_history, sender, content)

    # 回复
    s2 = generate_req_id("r")
    await client.reply_stream(frame, s2, reply, finish=True)
    log.info("已回复 [%s]", sender)


async def on_enter(frame):
    await client.reply_welcome(frame, {
        "msgtype": "text",
        "text": {"content": "你好!我是 MarketPulse 助手。\n\n我会记住我们的对话。"}
    })


async def main():
    global client
    log.info("启动(带上下文)...")
    options = WSClientOptions(bot_id=BOT_ID, secret=SECRET)
    client = WSClient(options)
    client.on("message.text", on_text)
    client.on("event.enter_chat", on_enter)
    await client.connect_async()
    while client.is_connected:
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
