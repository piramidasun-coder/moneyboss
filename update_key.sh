#!/bin/bash

echo "🔑 Обновляем API ключ OpenRouter..."

cd /root/moneyboss

# 1. Записываем новый .env с правильным ключом и моделью Qwen
cat <<EOF > .env
BOT_TOKEN=8289097456:AAFpZ7aZwdjpnRbSop-1OpqpvDUh_UjBJaA
AI_API_KEY=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
AI_MODEL=qwen/qwen-2.5-72b-instruct
AI_BASE_URL=https://openrouter.ai/api/v1
EOF

# 2. Перезапуск
systemctl restart moneyboss

# 3. Проверка
echo "-----------------------------------"
systemctl status moneyboss --no-pager
echo "-----------------------------------"
echo "✅ Ключ обновлен! Бот перезапущен."
