#!/bin/bash

echo "🔑 Обновляем API ключ OpenRouter..."

cd /root/moneyboss

# 1. Записываем новый .env с актуальным ключом
cat <<EOF > .env
BOT_TOKEN=8289097456:AAFpZ7aZwdjpnRbSop-1OpqpvDUh_UjBJaA
AI_API_KEY=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
AI_MODEL=deepseek/deepseek-chat
AI_BASE_URL=https://openrouter.ai/api/v1
EOF

# 2. Перезапуск
systemctl restart moneyboss

# 3. Проверка
echo "-----------------------------------"
systemctl status moneyboss --no-pager
echo "-----------------------------------"
echo "✅ Ключ обновлен! Бот перезапущен."
