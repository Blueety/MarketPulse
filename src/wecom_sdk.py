"""企业微信智能机器人 — 官方 SDK 版本。"""
import logging
from wecom_aibot_sdk import WSClient, MsgHandler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("wecom")

BOT_ID = "aibQlFgEwim7Ma40C3ZWee47Mbrpgg6uDCT"
SECRET = "2kwT4xhbz0yRAmvMDLgjsA2VcBBie3e9GFc3fpgAI4d"


class MarketPulseHandler(MsgHandler):
    """处理收到的消息"""

    def on_text_msg(self, client, msg):
        user_id = msg.get("sender", {}).get("id", "unknown")
        content = msg.get("content", {}).get("text", "")
        log.info("收到 [%s]: %s", user_id, content)

        # 回复
        client.send_text(user_id, f"✅ 收到: {content}")

    def on_image_msg(self, client, msg):
        log.info("收到图片消息")

    def on_event(self, client, event):
        log.info("事件: %s", event)


def main():
    log.info("启动企业微信 WebSocket 客户端")
    client = WSClient(
        bot_id=BOT_ID,
        secret=SECRET,
        heartbeat_interval=30000,
        reconnect_interval=5000,
        max_reconnect_attempts=-1,  # 无限重连
    )
    client.register_handler(MarketPulseHandler())
    client.start()


if __name__ == "__main__":
    main()
