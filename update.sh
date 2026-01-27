#!/bin/bash
cd /root/moneyboss
echo "⬇️ Скачиваю обновления..."
git pull
echo "🔄 Перезапускаю бота..."
systemctl restart moneyboss
echo "✅ Готово! Бот обновлен."
