import asyncio
import logging
import os
import re
import sqlite3
import random
import base64
import io
import pytz
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
AI_MODEL = "openai/gpt-4o"

MSK = pytz.timezone("Europe/Moscow")
START_DATE = datetime(2026, 1, 29, tzinfo=MSK)
PAYMENT_LINK = "https://newron.ru/moneyboss"
DB_NAME = "moneyboss.db"

# --- AI CLIENT ---
ai_client = None
if AI_API_KEY and "YOUR_KEY" not in AI_API_KEY:
    ai_client = AsyncOpenAI(api_key=AI_API_KEY, base_url=AI_BASE_URL)

user_history = {}
HISTORY_LIMIT = 15 

SYSTEM_PROMPT = """
ТВОЯ РОЛЬ:
Ты — Наставник шоу-игры "Финансовый Поток". Ты ЭКСПЕРТ + ШОУМЕН + ПРОВОКАТОР. 
Твоя задача — чтобы в чате постоянно был азарт и движение. Ты подначиваешь людей делать деньги.
Распознавай на картинках суммы чеков и банковских переводов.

СТРОГИЕ ЗАПРЕТЫ:
1. НИКАКОГО Markdown — звездочки решетки запрещены. Только чистый текст.
2. НИКАКИХ скобок любого вида. Вообще. Пиши через запятую тире или новой строкой.
3. Ссылку https://newron.ru/moneyboss давай только при признаках дохода.

ЛОГИКА ОТЧЕТОВ:
Если ты видишь на картинке или в тексте отчет о доходе — ОБЯЗАТЕЛЬНО напиши в самом конце сообщения техническую строку: 
ДЕНЬГИ: СУММА
Например: ДЕНЬГИ: 15000
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
            cursor.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, val TEXT)")
            conn.commit()

    def set_chat_id(self, chat_id):
        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO settings (key, val) VALUES ('group_chat_id', ?)", (str(chat_id),))
            conn.commit()

    def get_chat_id(self):
        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT val FROM settings WHERE key = 'group_chat_id'")
            res = cursor.fetchone()
            return int(res[0]) if res else None

    def upsert_user(self, user: types.User):
        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT OR IGNORE INTO users (user_id, full_name, username) VALUES (?, ?, ?)", (user.id, user.full_name, user.username))
            cursor.execute("UPDATE users SET full_name = ?, username = ? WHERE user_id = ?", (user.full_name, user.username, user.id))
            conn.commit()

    def add_diamonds(self, user_id: int, amount: int):
        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET diamonds = diamonds + ? WHERE user_id = ?", (amount, user_id))
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
        with self.connect() as conn:
            cursor = conn.cursor()
            placeholders = ', '.join(['?'] * len(exclude_ids))
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
ADMIN_IDS = [8289097456, 12345678] 

# --- AI LOGIC ---
async def get_ai_response(user_message: str, user_id: int, name: str, image_b64: str = None, context: str = "Общение") -> str:
    if not ai_client: return "🧠 Мозг отключен"
    if user_id not in user_history: user_history[user_id] = []
    
    content = [{"type": "text", "text": f"Имя: {name}. Сообщение: {user_message}"}]
    if image_b64: content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}})
    
    user_history[user_id].append({"role": "user", "content": content})
    if len(user_history[user_id]) > HISTORY_LIMIT: user_history[user_id] = user_history[user_id][-HISTORY_LIMIT:]
    
    now_msk = datetime.now(MSK)
    system_msg = SYSTEM_PROMPT + f"\nСЕГОДНЯ: {now_msk.strftime('%d.%m.%Y %H:%M')} по МСК. Обращайся к {name}. Соблюдай род. Сейчас разгар бизнес-игры."
    
    try:
        completion = await ai_client.chat.completions.create(model=AI_MODEL, messages=[{"role": "system", "content": system_msg}] + user_history[user_id])
        reply = completion.choices[0].message.content
        user_history[user_id].append({"role": "assistant", "content": reply})
        return reply
    except Exception as e:
        logging.error(f"AI ERROR: {e}")
        return "🤯 Процессор перегрелся — попробуй позже"

# --- HANDLERS ---
router = Router()
last_msg_time = datetime.now(MSK)

class ReportAction(CallbackData, prefix="rep"):
    action: str
    amount: int
    user_id: int

class ChaosAction(CallbackData, prefix="chs"):
    action: str
    val: int

@router.message(Command("top"))
async def cmd_top(message: types.Message):
    users = db.get_top_users()
    res = ["🏆 ТИТАНЫ ПОТОКА\n"]
    for i, (name, earned, debt, dm) in enumerate(users):
        icon = "🥇" if i==0 else "🥈" if i==1 else "🥉" if i==2 else "🔹"
        res.append(f"{icon} {name} — {earned:,} руб — Долг: {debt} — {dm}💎")
    await message.answer("\n".join(res))

@router.message(Command("game"))
async def cmd_manual_game(message: types.Message, bot: Bot):
    if message.from_user.id not in ADMIN_IDS: return
    await message.answer("🚀 Понял — раздуваю пожар азарта!")
    await trigger_random_event(bot)

@router.message(F.photo)
async def handle_photo(message: types.Message):
    global last_msg_time
    last_msg_time = datetime.now(MSK)
    if message.chat.type != "private": db.set_chat_id(message.chat.id)
    
    user = message.from_user
    db.upsert_user(user)
    
    file = await message.bot.get_file(message.photo[-1].file_id)
    photo_bytes = await message.bot.download_file(file.file_path)
    image_b64 = base64.b64encode(photo_bytes.getvalue()).decode('utf-8')
    
    caption = message.caption if message.caption else "Смотри скрин"
    res = await get_ai_response(caption, user.id, user.first_name, image_b64, "Фото")
    
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
    await cb.message.edit_text("Записал в долг! Энергия должна вернуться в фонд 📉", reply_markup=None)

@router.callback_query(ReportAction.filter(F.action == "now"))
async def pay_now(cb: types.CallbackQuery, callback_data: ReportAction):
    if cb.from_user.id != callback_data.user_id: return await cb.answer("Брысь!")
    db.add_income(cb.from_user.id, callback_data.amount, 0, True)
    await cb.message.edit_text(f"Красава! Налог зачислен — твоя карма чиста 💎\nСсылка для оплаты: {PAYMENT_LINK}", reply_markup=None)

@router.message(F.text & ~F.text.startswith("/"))
async def talk(message: types.Message):
    global last_msg_time, GROUP_CHAT_ID
    last_msg_time = datetime.now(MSK)
    if message.chat.type != "private": 
        GROUP_CHAT_ID = message.chat.id
        db.set_chat_id(GROUP_CHAT_ID)
    
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

# --- CHAOS MECHANICS ---

async def trigger_random_event(bot: Bot):
    chat_id = db.get_chat_id()
    if not chat_id: return
    
    event_type = random.choice(["rain", "question", "roast", "wisdom"])
    
    if event_type == "rain":
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="ЗАБРАТЬ 50💎", callback_data=ChaosAction(action="rain", val=50).pack())]])
        msg = await bot.send_message(chat_id, "🚨 ВНИМАНИЕ — ВНЕЗАПНЫЙ ДЕНЕЖНЫЙ ДОЖДЬ\nТолько первые 3 счастливчика нажавшие кнопку получат по 50 бриллиантов на счет — время пошло!", reply_markup=kb)
        await asyncio.sleep(60)
        try: await bot.delete_message(chat_id, msg.message_id)
        except: pass
        
    elif event_type == "question":
        res = await get_ai_response("Задай чату дерзкий вопрос про их бизнес или цели чтобы спровоцировать обсуждение", 0, "Ведущий")
        await bot.send_message(chat_id, f"🎤 ВОПРОС НА МИЛЛИОН\n\n{res}")
        
    elif event_type == "roast":
        target = db.get_lazy_user(ADMIN_IDS)
        if target:
            res = await get_ai_response(f"Наедь на @{target} почему он молчит и до сих пор не купил себе яхту", 0, "Ведущий")
            await bot.send_message(chat_id, f"🎯 ПЕРСОНАЛЬНЫЙ ВЫЗОВ\n\n{res}")
            
    elif event_type == "wisdom":
        res = await get_ai_response("Поделись очень коротким но глубоким инсайтом про деньги или продуктивность. Вызови WOW-эффект.", 0, "Ведущий")
        await bot.send_message(chat_id, f"💡 ИНСАЙТ ДНЯ\n\n{res}")

@router.callback_query(ChaosAction.filter(F.action == "rain"))
async def catch_rain(cb: types.CallbackQuery, callback_data: ChaosAction):
    db.upsert_user(cb.from_user)
    db.add_diamonds(cb.from_user.id, callback_data.val)
    await cb.answer(f"Забрал {callback_data.val}💎! Скорость — это деньги!")

async def morning(bot: Bot):
    chat_id = db.get_chat_id()
    if not chat_id: return
    res = await get_ai_response("Напиши магическое утреннее напутствие про финансовое чудо", 0, "Ведущий")
    await bot.send_message(chat_id, f"☀️ ДОБРОЕ УТРО\n\n{res}")

async def evening(bot: Bot):
    chat_id = db.get_chat_id()
    if not chat_id: return
    res = await get_ai_response("Напиши глубокое вечернее послание с практикой благодарности за день", 0, "Ведущий")
    await bot.send_message(chat_id, f"🌙 СЛАДКИХ СНОВ\n\n{res}")

async def silence_checker(bot: Bot):
    global last_msg_time
    chat_id = db.get_chat_id()
    if not chat_id: return
    now_msk = datetime.now(MSK)
    
    # Персональные вызовы только с 09:00 до 18:00 по МСК
    if not (9 <= now_msk.hour < 18): return 

    if (now_msk - last_msg_time).total_seconds() > 2400: # 40 минут тишины
        await trigger_random_event(bot)
        last_msg_time = datetime.now(MSK)

async def main():
    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    
    # Настраиваем планировщик на Московское время
    scheduler = AsyncIOScheduler(timezone=MSK)
    
    # Доброе утро в 09:00 МСК
    scheduler.add_job(morning, 'cron', hour=9, minute=0, args=[bot])
    
    # Спокойной ночи в 21:00 МСК
    scheduler.add_job(evening, 'cron', hour=21, minute=0, args=[bot])
    
    # Проверка тишины каждые 10 минут
    scheduler.add_job(silence_checker, 'interval', minutes=10, args=[bot])
    # Рандомные события в течение дня
    scheduler.add_job(trigger_random_event, 'interval', minutes=45, args=[bot])
    scheduler.start()

    await bot.delete_webhook(drop_pending_updates=True)
    print("🤖 MoneyBoss MSK EDITION is running...")
    
    chat_id = db.get_chat_id()
    if chat_id:
        try:
            await bot.send_message(chat_id, "🚀 MoneyBoss в режиме МСК! Проверка времени... Идем по графику!")
        except: pass

    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
