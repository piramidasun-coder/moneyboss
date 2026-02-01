import asyncio
import logging
import os
import re
import sqlite3
import random
import base64
import io
from datetime import datetime, timedelta
from typing import Optional

from aiogram import Bot, Dispatcher, F, Router, types, html
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters.callback_data import CallbackData
from dotenv import load_dotenv
from openai import AsyncOpenAI
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# --- CONFIGURATION ---
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
AI_API_KEY = os.getenv("AI_API_KEY")
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://openrouter.ai/api/v1")
AI_MODEL = os.getenv("AI_MODEL", "google/gemini-flash-1.5") # Важно: модель со "зрением"

START_DATE = datetime(2026, 1, 29)
PAYMENT_LINK = "https://newron.ru/moneyboss"
DB_NAME = "moneyboss.db"
GROUP_CHAT_ID = None  

# --- AI CLIENT ---
ai_client = None
if AI_API_KEY and "YOUR_KEY" not in AI_API_KEY:
    ai_client = AsyncOpenAI(api_key=AI_API_KEY, base_url=AI_BASE_URL)

user_history = {}
HISTORY_LIMIT = 10 

SYSTEM_PROMPT = """
ТВОЯ РОЛЬ:
Ты — Наставник шоу-игры "Финансовый Поток". Ты ЭКСПЕРТ + ШОУМЕН + ПРОВОКАТОР. 
Ты видишь скриншоты которые тебе присылают. Распознавай на них суммы чеков и банковских переводов.

СТРОГИЕ ЗАПРЕТЫ:
1. НИКАКОГО Markdown (звездочки решетки). Только чистый текст.
2. НИКАКИХ скобок любого вида.
3. Ссылку https://newron.ru/moneyboss давай только при признаках дохода.

ЛОГИКА ОТЧЕТОВ:
Если ты видишь на картинке или в тексте отчет о доходе — ОБЯЗАТЕЛЬНО напиши в самом конце сообщения техническую строку: 
ДЕНЬГИ: СУММА
(Например: ДЕНЬГИ: 5000)
Если это просто общение — не пиши эту строку.
"""

# --- DATABASE ---
class Database:
    def __init__(self, db_name):
        self.db_name = db_name
        self.init_db()

    def connect(self):
        return sqlite3.connect(self.db_name)

    def init_db(self):
        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    full_name TEXT,
                    username TEXT,
                    total_earned INTEGER DEFAULT 0,
                    debt INTEGER DEFAULT 0,
                    diamonds INTEGER DEFAULT 0
                )
            """)
            conn.commit()

    def upsert_user(self, user: types.User):
        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT OR IGNORE INTO users (user_id, full_name, username) VALUES (?, ?, ?)", (user.id, user.full_name, user.username))
            cursor.execute("UPDATE users SET full_name = ?, username = ? WHERE user_id = ?", (user.full_name, user.username, user.id))
            conn.commit()

    def add_income(self, user_id: int, income: int, tax: int, pay_now: bool):
        with self.connect() as conn:
            cursor = conn.cursor()
            if pay_now:
                cursor.execute("UPDATE users SET total_earned = total_earned + ? WHERE user_id = ?", (income, user_id))
            else:
                cursor.execute("UPDATE users SET total_earned = total_earned + ?, debt = debt + ? WHERE user_id = ?", (income, tax, user_id))
            conn.commit()

    def get_lazy_user(self, exclude_ids: list):
        """Выбирает случайного пользователя с 0 доходом, исключая админов"""
        with self.connect() as conn:
            cursor = conn.cursor()
            # Пробуем найти тех, у кого доход 0
            placeholders = ', '.join(['?'] * len(exclude_ids))
            query = f"SELECT username FROM users WHERE total_earned = 0 AND username IS NOT NULL AND user_id NOT IN ({placeholders}) ORDER BY RANDOM() LIMIT 1"
            cursor.execute(query, exclude_ids)
            res = cursor.fetchone()
            if res: return res[0]
            
            # Если все молодцы и заработали, берем любого не-админа
            query = f"SELECT username FROM users WHERE username IS NOT NULL AND user_id NOT IN ({placeholders}) ORDER BY RANDOM() LIMIT 1"
            cursor.execute(query, exclude_ids)
            res = cursor.fetchone()
            return res[0] if res else None

    def get_top_users(self, limit=10):
        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT full_name, total_earned, debt, diamonds FROM users ORDER BY total_earned DESC LIMIT ?", (limit,))
            return cursor.fetchall()

db = Database(DB_NAME)

# --- ADMINS LIST ---
# Сюда добавь свой ID и ID других админов
# Свой ID можно узнать у бота @userinfobot
ADMIN_IDS = [12345678, 8289097456] # Замени на реальные ID

# --- AI LOGIC WITH VISION ---
async def get_ai_response(user_message: str, user_id: int, name: str, image_b64: str = None) -> str:
    if not ai_client: return "🧠 Мозг отключен"
    
    if user_id not in user_history: user_history[user_id] = []
    
    content = [{"type": "text", "text": f"Имя: {name}. Сообщение: {user_message}"}]
    if image_b64:
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}})
    
    user_history[user_id].append({"role": "user", "content": content})
    if len(user_history[user_id]) > HISTORY_LIMIT: user_history[user_id] = user_history[user_id][-HISTORY_LIMIT:]
    
    system_msg = SYSTEM_PROMPT + f"\nСЕГОДНЯ: {datetime.now().strftime('%d.%m.%Y')}. Обращайся к {name}. Соблюдай род."
    
    try:
        completion = await ai_client.chat.completions.create(
            model=AI_MODEL,
            messages=[{"role": "system", "content": system_msg}] + user_history[user_id]
        )
        reply = completion.choices[0].message.content
        user_history[user_id].append({"role": "assistant", "content": reply})
        return reply
    except Exception as e:
        logging.error(f"DETAILED AI ERROR: {str(e)}") # Теперь мы увидим реальную причину в логах
        return "🤯 Процессор перегрелся — попробуй позже"

# --- HANDLERS ---
router = Router()
last_msg_time = datetime.now()

class ReportAction(CallbackData, prefix="rep"):
    action: str
    amount: int
    user_id: int

@router.message(Command("top"))
async def cmd_top(message: types.Message):
    users = db.get_top_users()
    res = ["🏆 ТИТАНЫ ПОТОКА\n"]
    for i, (name, earned, debt, dm) in enumerate(users):
        icon = "🥇" if i==0 else "🥈" if i==1 else "🥉" if i==2 else "🔹"
        res.append(f"{icon} {name} — {earned:,} руб — Долг: {debt} — {dm}💎")
    await message.answer("\n".join(res))

@router.message(F.photo)
async def handle_photo(message: types.Message):
    global last_msg_time, GROUP_CHAT_ID
    last_msg_time = datetime.now()
    if message.chat.type != "private": GROUP_CHAT_ID = message.chat.id
    
    user = message.from_user
    db.upsert_user(user)
    
    # Качаем фото
    file = await message.bot.get_file(message.photo[-1].file_id)
    photo_bytes = await message.bot.download_file(file.file_path)
    image_b64 = base64.b64encode(photo_bytes.getvalue()).decode('utf-8')
    
    caption = message.caption if message.caption else "Смотри скрин"
    res = await get_ai_response(caption, user.id, user.first_name, image_b64)
    
    # Ищем техническую строку про деньги
    money_match = re.search(r"ДЕНЬГИ:\s*(\d+)", res)
    if money_match:
        amt = int(money_match.group(1))
        tax = int(amt * 0.1)
        clean_res = res.replace(money_match.group(0), "").strip()
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"💸 Оплатить налог {tax}р", callback_data=ReportAction(action="now", amount=amt, user_id=user.id).pack())],
            [InlineKeyboardButton(text="⏳ В долг", callback_data=ReportAction(action="later", amount=amt, user_id=user.id).pack())]
        ])
        await message.reply(clean_res, reply_markup=kb)
    else:
        await message.reply(res)

@router.callback_query(ReportAction.filter(F.action == "later"))
async def pay_later(cb: types.CallbackQuery, callback_data: ReportAction):
    if cb.from_user.id != callback_data.user_id: return await cb.answer("Не твое!")
    db.add_income(cb.from_user.id, callback_data.amount, int(callback_data.amount*0.1), False)
    await cb.message.edit_text("Записал в долг! Не забудь вернуть энергию фонду 📉", reply_markup=None)

@router.callback_query(ReportAction.filter(F.action == "now"))
async def pay_now(cb: types.CallbackQuery, callback_data: ReportAction):
    if cb.from_user.id != callback_data.user_id: return await cb.answer("Брысь!")
    db.add_income(cb.from_user.id, callback_data.amount, 0, True)
    await cb.message.edit_text(f"Красава! Налог зачислен — ты чист перед денежным эгрегором 💎\nСсылка для оплаты: {PAYMENT_LINK}", reply_markup=None)

@router.message(F.text & ~F.text.startswith("/"))
async def talk(message: types.Message):
    global last_msg_time, GROUP_CHAT_ID
    last_msg_time = datetime.now()
    if message.chat.type != "private": GROUP_CHAT_ID = message.chat.id
    
    # Ищем деньги в тексте через ИИ
    res = await get_ai_response(message.text, message.from_user.id, message.from_user.first_name)
    
    money_match = re.search(r"ДЕНЬГИ:\s*(\d+)", res)
    if money_match:
        amt = int(money_match.group(1))
        tax = int(amt * 0.1)
        clean_res = res.replace(money_match.group(0), "").strip()
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"💸 Оплатить {tax}р", callback_data=ReportAction(action="now", amount=amt, user_id=message.from_user.id).pack())],
            [InlineKeyboardButton(text="⏳ В долг", callback_data=ReportAction(action="later", amount=amt, user_id=message.from_user.id).pack())]
        ])
        await message.reply(clean_res, reply_markup=kb)
    else:
        await message.reply(res)

# --- AUTOMATION ---
async def morning(bot: Bot):
    if not GROUP_CHAT_ID: return
    res = await get_ai_response("Напиши утреннее напутствие про чудо и финансовое задание", 0, "Команда")
    await bot.send_message(GROUP_CHAT_ID, f"☀️ ДОБРОЕ УТРО\n\n{res}")

async def evening(bot: Bot):
    if not GROUP_CHAT_ID: return
    res = await get_ai_response("Напиши глубокое вечернее послание с практикой релакса", 0, "Команда")
    await bot.send_message(GROUP_CHAT_ID, f"🌙 СЛАДКИХ СНОВ\n\n{res}")

async def silence(bot: Bot):
    global last_msg_time
    if not GROUP_CHAT_ID: return
    
    now = datetime.now()
    # Детектор тишины работает только с 10:00 до 22:00
    if not (10 <= now.hour < 22):
        return

    if (now - last_msg_time).total_seconds() > 2400: # 40 min
        target = db.get_lazy_user(ADMIN_IDS)
        if not target: return
        
        res = await get_ai_response(f"В чате тишина 40 минут — наедь на @{target} почему он не богат и молчит", 0, "Система")
        await bot.send_message(GROUP_CHAT_ID, res)
        # ВАЖНО: Обновляем время, чтобы бот не спамил сам за собой
        last_msg_time = datetime.now()

async def main():
    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    
    scheduler = AsyncIOScheduler()
    scheduler.add_job(morning, 'cron', hour=9, minute=0, args=[bot])
    scheduler.add_job(evening, 'cron', hour=22, minute=0, args=[bot])
    scheduler.add_job(silence, 'interval', minutes=15, args=[bot])
    scheduler.start()

    await bot.delete_webhook(drop_pending_updates=True)
    print("🤖 MoneyBoss VISION EDITION is running...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
