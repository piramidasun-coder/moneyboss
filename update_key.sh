#!/bin/bash

echo "🔑 Обновляем API ключ OpenRouter и модель на Gemini Flash..."

cd /root/moneyboss

# Записываем новый .env с актуальным ключом и моделью Vision
cat <<EOF > .env
BOT_TOKEN=8289097456:AAFpZ7aZwdjpnRbSop-1OpqpvDUh_UjBJaA
AI_API_KEY=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
AI_MODEL=google/gemini-flash-1.5
AI_BASE_URL=https://openrouter.ai/api/v1
EOF

# Перезапуск бота
systemctl restart moneyboss

echo "-----------------------------------"
systemctl status moneyboss --no-pager | grep "Active:"
echo "-----------------------------------"
echo "✅ Готово! Бот теперь зрячий (Gemini Flash) и готов к работе."
