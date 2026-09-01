"""企业微信智能机器人 — 官方 SDK + Hermes AI (全消息类型)。"""
import asyncio
import logging
import subprocess
import os

from wecom_aibot_sdk import WSClient, WSClientOptions, generate_req_id

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("wecom")

BOT_ID = "aibQlFgEwim7Ma40C3ZWee47Mbrpgg6uDCT"
SECRET = "2kwT4xhbz0yRAmvMDLgjsA2VcBBie3e9GFc3fpgAI4d"

client = None
DOWNLOAD_DIR = "D:/AGENT/MarketPulse/tmp/wecom_uploads"


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
    """处理文本消息"""
    body = frame.body or {}
    sender = body.get("from", {}).get("userid", "unknown")
    content = body.get("text", {}).get("content", "").strip()

    if not content:
        return

    log.info("收到文本 [%s]: %s", sender, content[:100])

    # 回复确认
    stream_id = generate_req_id("stream")
    await client.reply_stream(frame, stream_id, "✅ 收到文本!AI 正在处理...", finish=True)

    # 调用 Hermes
    loop = asyncio.get_event_loop()
    reply = await loop.run_in_executor(None, ask_hermes_sync, content)

    # 发送回复
    stream_id2 = generate_req_id("stream")
    await client.reply_stream(frame, stream_id2, reply, finish=True)
    log.info("已回复文本 [%s]", sender)


async def on_image(frame):
    """处理图片消息"""
    body = frame.body or {}
    sender = body.get("from", {}).get("userid", "unknown")
    image_info = body.get("image", {})
    url = image_info.get("url", "")
    aes_key = image_info.get("aeskey", "")

    log.info("收到图片 [%s]: url=%s", sender, url[:50] if url else "无")

    # 回复确认
    stream_id = generate_req_id("stream")
    await client.reply_stream(frame, stream_id, "✅ 收到图片!正在下载...", finish=True)

    # 下载图片
    if url:
        try:
            os.makedirs(DOWNLOAD_DIR, exist_ok=True)
            buffer, filename = await client.download_file(url, aes_key)
            filepath = os.path.join(DOWNLOAD_DIR, filename)
            with open(filepath, "wb") as f:
                f.write(buffer)
            log.info("图片已保存: %s", filepath)

            # 调用 Hermes 分析图片
            loop = asyncio.get_event_loop()
            reply = await loop.run_in_executor(
                None, ask_hermes_sync, f"请分析这张图片: {filepath}"
            )

            stream_id2 = generate_req_id("stream")
            await client.reply_stream(frame, stream_id2, reply, finish=True)
        except Exception as e:
            log.error("图片下载失败: %s", e)
            stream_id2 = generate_req_id("stream")
            await client.reply_stream(frame, stream_id2, f"❌ 图片下载失败: {e}", finish=True)
    else:
        stream_id2 = generate_req_id("stream")
        await client.reply_stream(frame, stream_id2, "❌ 无法获取图片URL", finish=True)


async def on_file(frame):
    """处理文件消息"""
    body = frame.body or {}
    sender = body.get("from", {}).get("userid", "unknown")
    file_info = body.get("file", {})
    url = file_info.get("url", "")
    aes_key = file_info.get("aeskey", "")
    filename = file_info.get("filename", "unknown")

    log.info("收到文件 [%s]: %s", sender, filename)

    # 回复确认
    stream_id = generate_req_id("stream")
    await client.reply_stream(frame, stream_id, f"✅ 收到文件: {filename}", finish=True)

    # 下载文件
    if url:
        try:
            os.makedirs(DOWNLOAD_DIR, exist_ok=True)
            buffer, fname = await client.download_file(url, aes_key)
            filepath = os.path.join(DOWNLOAD_DIR, fname)
            with open(filepath, "wb") as f:
                f.write(buffer)
            log.info("文件已保存: %s", filepath)

            # 调用 Hermes 处理文件
            loop = asyncio.get_event_loop()
            reply = await loop.run_in_executor(
                None, ask_hermes_sync, f"请处理这个文件: {filepath}"
            )

            stream_id2 = generate_req_id("stream")
            await client.reply_stream(frame, stream_id2, reply, finish=True)
        except Exception as e:
            log.error("文件下载失败: %s", e)
            stream_id2 = generate_req_id("stream")
            await client.reply_stream(frame, stream_id2, f"❌ 文件下载失败: {e}", finish=True)
    else:
        stream_id2 = generate_req_id("stream")
        await client.reply_stream(frame, stream_id2, "❌ 无法获取文件URL", finish=True)


async def on_voice(frame):
    """处理语音消息"""
    body = frame.body or {}
    sender = body.get("from", {}).get("userid", "unknown")

    log.info("收到语音 [%s]", sender)

    stream_id = generate_req_id("stream")
    await client.reply_stream(frame, stream_id, "✅ 收到语音!暂不支持语音识别,请发送文字。", finish=True)


async def on_mixed(frame):
    """处理混合内容消息"""
    body = frame.body or {}
    sender = body.get("from", {}).get("userid", "unknown")
    content = body.get("content", [])

    log.info("收到混合内容 [%s]: %d 项", sender, len(content) if isinstance(content, list) else 0)

    # 提取文本部分
    text_parts = []
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(item.get("text", ""))

    if text_parts:
        text = "\n".join(text_parts)
        stream_id = generate_req_id("stream")
        await client.reply_stream(frame, stream_id, "✅ 收到混合消息!AI 正在处理文字部分...", finish=True)

        loop = asyncio.get_event_loop()
        reply = await loop.run_in_executor(None, ask_hermes_sync, text)

        stream_id2 = generate_req_id("stream")
        await client.reply_stream(frame, stream_id2, reply, finish=True)
    else:
        stream_id = generate_req_id("stream")
        await client.reply_stream(frame, stream_id, "✅ 收到混合消息,但没有可处理的文字内容。", finish=True)


async def on_enter(frame):
    """用户进入会话"""
    log.info("用户进入会话")
    await client.reply_welcome(frame, {
        "msgtype": "text",
        "text": {"content": "你好!我是 MarketPulse AI 助手。\n\n支持:\n• 文字消息\n• 图片分析\n• 文件处理\n• 语音(暂不支持识别)"}
    })


async def main():
    global client
    log.info("启动企业微信 WebSocket 客户端 (Hermes AI - 全消息类型)")

    options = WSClientOptions(
        bot_id=BOT_ID,
        secret=SECRET,
        reconnect_interval=5000,
        max_reconnect_attempts=-1,
        heartbeat_interval=30000,
    )
    client = WSClient(options)

    client.on("message.text", on_text)
    client.on("message.image", on_image)
    client.on("message.file", on_file)
    client.on("message.voice", on_voice)
    client.on("message.mixed", on_mixed)
    client.on("event.enter_chat", on_enter)

    await client.connect_async()

    while client.is_connected:
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
