#!/bin/bash
# MarketPulse 推送重试脚本
cd D:/AGENT/MarketPulse

echo "=== MarketPulse 推送重试 ==="
echo "时间: $(date '+%Y-%m-%d %H:%M:%S')"

# 尝试推送
if git push origin master 2>&1; then
    echo "✅ 推送成功!"
    # 通知QQBot
    python3 -c "
from wecom_aibot_sdk import WSClient, WSClientOptions
client = WSClient(WSClientOptions(bot_id='aibQlFgEwim7Ma40C3ZWee47Mbrpgg6uDCT'))
client.send_text('ZhuangJianHua', '✅ MarketPulse推送成功！已自动取消重试。')
" 2>/dev/null || true
    # 删除自身cron任务
    # 找到并删除MarketPulse推送重试的cron
    hermes cron rm "MarketPulse推送重试" 2>/dev/null || true
    echo "已取消重试cron"
else
    echo "❌ 推送仍失败，等待下次重试..."
fi
