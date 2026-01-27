#!/bin/bash

echo "🔧 Фиксим настройки .env..."

cd /root/moneyboss

# Полная перезапись файла .env
cat <<EOF > .env
BOT_TOKEN=8289097456:AAFpZ7aZwdjpnRbSop-1OpqpvDUh_UjBJaA
AI_API_KEY=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
# Используем точное название модели OpenRouter
AI_MODEL=google/gemini-2.0-flash-exp:free
AI_BASE_URL=https://openrouter.ai/api/v1
EOF

echo "🔄 Перезапускаем бота..."
systemctl restart moneyboss

echo "✅ Готово! Проверяй."
