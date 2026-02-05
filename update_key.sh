#!/bin/bash

echo "🔑 Обновляем API ключ OpenRouter на новый..."

cd /root/moneyboss

# Записываем новый .env с актуальным ключом и GPT-4o
cat <<EOF > .env
BOT_TOKEN=8289097456:AAFpZ7aZwdjpnRbSop-1OpqpvDUh_UjBJaA
AI_API_KEY=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
AI_MODEL=openai/gpt-4o
AI_BASE_URL=https://openrouter.ai/api/v1
EOF

# Перезапуск бота
systemctl restart moneyboss

echo "-----------------------------------"
systemctl status moneyboss --no-pager | grep "Active:"
echo "-----------------------------------"
echo "✅ Ключ обновлен! Бот перезапущен на GPT-4o."
