#!/bin/bash

echo "🚀 ЗАПУСК ПОЛНОЙ ПЕРЕУСТАНОВКИ..."

# 1. Останавливаем старого бота (если есть)
systemctl stop moneyboss
systemctl disable moneyboss

# 2. Удаляем старые файлы (чистый лист)
rm -rf /root/moneyboss
rm -f /etc/systemd/system/moneyboss.service

# 3. Скачиваем код (Публичный репозиторий)
echo "📥 Скачиваем бота с GitHub..."
git clone https://github.com/piramidasun-coder/moneyboss.git /root/moneyboss
cd /root/moneyboss

# 4. Создаем ключи
echo "🔑 Прописываем секреты..."
cat <<EOF > .env
BOT_TOKEN=8289097456:AAFpZ7aZwdjpnRbSop-1OpqpvDUh_UjBJaA
AI_API_KEY=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
AI_MODEL=deepseek/deepseek-chat
AI_BASE_URL=https://openrouter.ai/api/v1
EOF

# 5. Настраиваем Python
echo "🐍 Устанавливаем библиотеки..."
apt update
apt install -y python3-pip python3-venv
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 6. Создаем службу автозапуска
echo "⚙️ Настраиваем сервис..."
cat <<EOF > /etc/systemd/system/moneyboss.service
[Unit]
Description=MoneyBoss Telegram Bot
After=network.target

[Service]
User=root
WorkingDirectory=/root/moneyboss
ExecStart=/root/moneyboss/venv/bin/python bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# 7. Запускаем
echo "✅ Запускаем..."
systemctl daemon-reload
systemctl enable moneyboss
systemctl start moneyboss

# 8. Проверка
echo "-----------------------------------"
systemctl status moneyboss --no-pager
echo "-----------------------------------"
echo "🎉 ЕСЛИ ВИДИШЬ 'active (running)' - МЫ ПОБЕДИЛИ!"
