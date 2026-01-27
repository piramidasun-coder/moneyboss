#!/bin/bash

echo "🔄 Переключаем MoneyBoss на Gemini 1.5 Flash..."

# Меняем модель в конфиге
sed -i 's|AI_MODEL=deepseek/deepseek-chat|AI_MODEL=google/gemini-flash-1.5|g' /root/moneyboss/.env

# Перезапускаем бота
systemctl restart moneyboss

# Проверяем статус
echo "-----------------------------------"
systemctl status moneyboss --no-pager
echo "-----------------------------------"
echo "✅ Готово! Теперь бот работает на дешевой Gemini."
