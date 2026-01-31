#!/bin/bash

echo "🚨 ЭКСТРЕННОЕ ВОССТАНОВЛЕНИЕ БОТА..."

# 1. Удаляем остатки (если есть)
cd /root
rm -rf moneyboss

# 2. Заново клонируем с GitHub
echo "📥 Скачиваем бота с GitHub..."
git clone https://github.com/piramidasun-coder/moneyboss.git
cd moneyboss

# 3. Создаем файл с секретными ключами
echo "🔑 Создаем .env с ключами..."
cat <<EOF > .env
BOT_TOKEN=8289097456:AAFpZ7aZwdjpnRbSop-1OpqpvDUh_UjBJaA
AI_API_KEY=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
AI_MODEL=deepseek/deepseek-chat
AI_BASE_URL=https://openrouter.ai/api/v1
EOF

# 4. Устанавливаем Python окружение
echo "🐍 Настраиваем Python..."
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 5. Создаем службу заново
echo "⚙️ Создаем systemd службу..."
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

# 6. Запускаем
echo "✅ Запускаем бота..."
systemctl daemon-reload
systemctl enable moneyboss
systemctl restart moneyboss

# 7. Финальная проверка
echo "-----------------------------------"
systemctl status moneyboss --no-pager
echo "-----------------------------------"
echo "🎉 ВОССТАНОВЛЕНИЕ ЗАВЕРШЕНО!"
