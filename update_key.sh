#!/bin/bash

echo "🚀 ПОДКЛЮЧАЕМ GPT-4o: Ум + Зрение + Стабильность..."

cd /root/moneyboss

# Записываем .env с новым ключом и топовой моделью GPT-4o
cat <<EOF > .env
BOT_TOKEN=8289097456:AAFpZ7aZwdjpnRbSop-1OpqpvDUh_UjBJaA
AI_API_KEY=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
AI_MODEL=openai/gpt-4o
AI_BASE_URL=https://openrouter.ai/api/v1
EOF

# Перезапуск
systemctl restart moneyboss

echo "-----------------------------------"
systemctl status moneyboss --no-pager | grep "Active:"
echo "-----------------------------------"
echo "✅ ГОТОВО! Теперь бот работает на GPT-4o."
echo "Попробуй скинуть скриншот. Теперь он ДОЛЖЕН его увидеть и понять."
