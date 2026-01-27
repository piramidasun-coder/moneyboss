#!/bin/bash

echo "🔄 Переключаем на Qwen 2.5..."

cd /root/moneyboss

# Обновляем конфиг
# Используем Qwen 2.5 72B (Instruct) - лучшее соотношение цены/качества на OpenRouter
# ID: qwen/qwen-2.5-72b-instruct
sed -i 's|AI_MODEL=.*|AI_MODEL=qwen/qwen-2.5-72b-instruct|g' .env

echo "🔄 Перезапускаем сервис..."
systemctl restart moneyboss

echo "✅ Готово! MoneyBoss теперь думает мозгами Qwen."
