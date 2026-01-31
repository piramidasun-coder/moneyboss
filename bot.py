import asyncio
import logging
import os
import re
import sqlite3
import random
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
AI_MODEL = os.getenv("AI_MODEL", "deepseek/deepseek-chat")

# ТАЙМИНГ МАРАФОНА
START_DATE = datetime(2026, 1, 29)
PAYMENT_LINK = "https://newron.ru/moneyboss"
DB_NAME = "moneyboss.db"
GROUP_CHAT_ID = None  

# --- AI CLIENT SETUP ---
ai_client = None
if AI_API_KEY and "YOUR_KEY" not in AI_API_KEY:
    ai_client = AsyncOpenAI(api_key=AI_API_KEY, base_url=AI_BASE_URL)

user_history = {}
HISTORY_LIMIT = 10 

SYSTEM_PROMPT = """
ТВОЯ РОЛЬ:
Ты — безумный ведущий и Наставник шоу-игры Финансовый Поток. Ты ЭКСПЕРТ + ШОУМЕН + ПРОВОКАТОР. 
Ты создаешь контролируемый хаос. Тебе не терпится увидеть как люди богатеют или смешно проигрывают.

СТРОГИЕ ЗАПРЕТЫ - КРИТИЧНО:
1. ЗАПРЕЩЕНО использовать Markdown — никаких звездочек решеток подчеркиваний. Только чистый текст.
2. ЗАПРЕЩЕНО использовать скобки — вообще любые. Пиши мысли через запятую тире или новой строкой.
3. Ссылку https://newron.ru/moneyboss давай только при отчетах об успехе.

ТВОЙ СТИЛЬ:
Дерзкий провокационный но экспертный. Ты можешь тегать людей и спрашивать почему они еще не миллионеры.
Твоя задача — чтобы в чате постоянно был движ.
"""

# --- DATABASE HANDLER ---
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
                    diamonds INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'Новичок'
                )
            """)
            conn.commit()

    def upsert_user(self, user: types.User):
        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR IGNORE INTO users (user_id, full_name, username, total_earned, debt, diamonds)
                VALUES (?, ?, ?, 0, 0, 0)
            """, (user.id, user.full_name, user.username))
            cursor.execute("""
                UPDATE users SET full_name = ?, username = ? WHERE user_id = ?
            """, (user.full_name, user.username, user.id))
            conn.commit()

    def add_diamonds(self, user_id: int, amount: int):
        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET diamonds = diamonds + ? WHERE user_id = ?", (amount, user_id))
            conn.commit()

    def get_random_user(self):
        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT username, full_name FROM users WHERE username IS NOT NULL ORDER BY RANDOM() LIMIT 1")
            return cursor.fetchone()

    def get_top_users(self, limit=10):
        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT full_name, total_earned, debt, diamonds FROM users ORDER BY total_earned DESC LIMIT ?", (limit,))
            return cursor.fetchall()

    def update_income(self, user_id: int, income: int, tax: int, pay_now: bool):
        with self.connect() as conn:
            cursor = conn.cursor()
            if pay_now:
                cursor.execute("UPDATE users SET total_earned = total_earned + ? WHERE user_id = ?", (income, user_id))
            else:
                cursor.execute("UPDATE users SET total_earned = total_earned + ?, debt = debt + ? WHERE user_id = ?", (income, tax, user_id))
            conn.commit()

db = Database(DB_NAME)

# --- CALLBACKS ---
class ReportAction(CallbackData, prefix="rep"):
    action: str
    amount: int
    user_id: int

class ChaosAction(CallbackData, prefix="chs"):
    action: str
    val: int

# --- LOGIC ---
router = Router()
last_msg_time = datetime.now()

async def get_ai_response(user_message: str, context: str = "", user_id: int = 0) -> str:
    if not ai_client: return "🧠 Мозг отключен"
    now = datetime.now()
    if user_id not in user_history: user_history[user_id] = []
    user_history[user_id].append({"role": "user", "content": f"Контекст: {context}\nСообщение: {user_message}"})
    if len(user_history[user_id]) > HISTORY_LIMIT: user_history[user_id] = user_history[user_id][-HISTORY_LIMIT:]
    
    system_payload = SYSTEM_PROMPT + f"\nСЕГОДНЯ: {now.strftime('%d.%m.%Y')}. Марафон идет."
    try:
        completion = await ai_client.chat.completions.create(
            model=AI_MODEL,
            messages=[{"role": "system", "content": system_payload}] + user_history[user_id]
        )
        reply = completion.choices[0].message.content
        user_history[user_id].append({"role": "assistant", "content": reply})
        return reply
    except: return "🤯 Процессор перегрелся — попробуй позже"

# --- HANDLERS ---

@router.message(Command("start"))
async def cmd_start(message: types.Message):
    global GROUP_CHAT_ID
    if message.chat.type in ["group", "supergroup"]: GROUP_CHAT_ID = message.chat.id
    db.upsert_user(message.from_user)
    await message.answer("Йо! Я MoneyBoss — твой проводник в мир больших бабок 🔥 Скидывай отчеты и не тупи!")

@router.message(Command("top"))
async def cmd_top(message: types.Message):
    users = db.get_top_users()
    if not users: return await message.answer("Чарт пуст — начни делать деньги первым!")
    res = ["🏆 ТИТАНЫ ФИНАНСОВОГО ПОТОКА\n"]
    for i, (name, earned, debt, dm) in enumerate(users):
        icon = "🥇" if i==0 else "🥈" if i==1 else "🥉" if i==2 else "🔹"
        status = "✅" if debt == 0 else f"Долг {debt} руб"
        res.append(f"{icon} {name} — {earned:,} руб — {status} — {dm}💎")
    await message.answer("\n".join(res))

@router.message(F.new_chat_members)
async def welcome(message: types.Message):
    for m in message.new_chat_members:
        if m.is_bot: continue
        res = await get_ai_response(f"Новичок {m.first_name} зашел", "Приветствие", m.id)
        await message.answer(res)

@router.message(F.photo & F.caption)
async def report(message: types.Message):
    global last_msg_time
    last_msg_time = datetime.now()
    match = re.search(r"Отчет\s+(\d+)", message.caption, re.I)
    if not match: return
    
    amt = int(match.group(1))
    tax = int(amt * 0.1)
    user = message.from_user
    db.upsert_user(user)
    
    ai_res = await get_ai_response(f"Отчет на {amt} руб", "Денежный успех", user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"💸 Оплатить 10% — {tax}р", callback_data=ReportAction(action="now", amount=amt, user_id=user.id).pack())],
        [InlineKeyboardButton(text="⏳ В долг до финала", callback_data=ReportAction(action="later", amount=amt, user_id=user.id).pack())]
    ])
    await message.reply(f"{ai_res}\n\nЧё делаем с налогом?", reply_markup=kb)

@router.callback_query(ReportAction.filter(F.action == "later"))
async def pay_later(cb: types.CallbackQuery, callback_data: ReportAction):
    if cb.from_user.id != callback_data.user_id: return await cb.answer("Не твое дело!")
    db.update_income(cb.from_user.id, callback_data.amount, int(callback_data.amount*0.1), False)
    ai_res = await get_ai_response("Выбрал оплату в долг", "Долг", cb.from_user.id)
    await cb.message.edit_text(f"Записал в долг! {ai_res}", reply_markup=None)

@router.callback_query(ReportAction.filter(F.action == "now"))
async def pay_now(cb: types.CallbackQuery, callback_data: ReportAction, state: FSMContext):
    if cb.from_user.id != callback_data.user_id: return await cb.answer("Брысь!")
    await cb.message.reply(f"Красавчик — гони скрин перевода сюда: {PAYMENT_LINK}")
    await state.update_data(amt=callback_data.amount)
    db.update_income(cb.from_user.id, callback_data.amount, 0, True)
    await cb.message.edit_reply_markup(reply_markup=None)

# --- CHAOS MECHANICS ---

async def money_rain(bot: Bot):
    if not GROUP_CHAT_ID: return
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="ХОЧУ БАБЛО", callback_data=ChaosAction(action="rain", val=50).pack())]])
    msg = await bot.send_message(GROUP_CHAT_ID, "🚨 ВНИМАНИЕ — ОТКРЫТ ПОРТАЛ ХАЛЯВЫ\nПервые 3 человека нажавшие кнопку получат по 50 бриллиантов на счет — время пошло!", reply_markup=kb)
    await asyncio.sleep(60)
    try: await bot.delete_message(GROUP_CHAT_ID, msg.message_id)
    except: pass

@router.callback_query(ChaosAction.filter(F.action == "rain"))
async def catch_rain(cb: types.CallbackQuery, callback_data: ChaosAction):
    db.upsert_user(cb.from_user)
    db.add_diamonds(cb.from_user.id, callback_data.val)
    await cb.answer(f"Забрал {callback_data.val}💎! Скорость — это деньги!")

async def absurd_invest(bot: Bot):
    if not GROUP_CHAT_ID: return
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="ИНВЕСТИРОВАТЬ", callback_data=ChaosAction(action="invest", val=10).pack())]])
    await bot.send_message(GROUP_CHAT_ID, "📉 СРОЧНАЯ НОВОСТЬ\nАкции завода по производству дырок от бубликов выросли на 300 процентов — успей вложиться и получить статус Волк с Уолл-стрит!", reply_markup=kb)

@router.callback_query(ChaosAction.filter(F.action == "invest"))
async def do_invest(cb: types.CallbackQuery):
    await cb.answer("Статус получен! Теперь ты — Волк с Уолл-стрит! 🐺")

async def morning_kick(bot: Bot):
    if not GROUP_CHAT_ID: return
    res = await get_ai_response("Напиши утренний пендель", "Утро")
    await bot.send_message(GROUP_CHAT_ID, f"☀️ УТРЕННИЙ ПЕНДЕЛЬ\n\n{res}")

async def evening_snack(bot: Bot):
    if not GROUP_CHAT_ID: return
    res = await get_ai_response("Напиши вечерний опрос про деградацию и деньги", "Вечер")
    await bot.send_message(GROUP_CHAT_ID, f"🌙 НОЧНОЙ ДОЖОР\n\n{res}")

async def silence_checker(bot: Bot):
    global last_msg_time
    if not GROUP_CHAT_ID: return
    now = datetime.now()
    diff = (now - last_msg_time).total_seconds() / 60
    if diff >= 40:
        target = db.get_random_user()
        tag = f"@{target[0]}" if target and target[0] else "Эй ты"
        ai_res = await get_ai_response(f"В чате тишина 40 минут — наедь на {tag}", "Тишина")
        await bot.send_message(GROUP_CHAT_ID, ai_res)
        last_msg_time = now

@router.message(F.text & ~F.text.startswith("/"))
async def talk(message: types.Message):
    global last_msg_time
    last_msg_time = datetime.now()
    
    # В группе отвечаем только на значимые сообщения
    if message.chat.type in ["group", "supergroup"]:
        text = message.text.lower()
        # Игнорируем короткие фразы (меньше 10 символов) - типа "ок", "хаха"
        if len(text) < 10:
            return
        # Отвечаем если есть триггеры: вопросы, действия, упоминание бота
        triggers = ["?", "как", "что", "почему", "сделал", "звонил", "встреча", "помог", "совет", "monеyboss", "бот"]
        if not any(word in text for word in triggers):
            return
    
    res = await get_ai_response(message.text, "Общение", message.from_user.id)
    await message.reply(res)

# --- MAIN ---
async def main():
    if not TOKEN: return
    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    
    scheduler = AsyncIOScheduler()
    scheduler.add_job(morning_kick, 'cron', hour=9, minute=0, args=[bot])
    scheduler.add_job(evening_snack, 'cron', hour=22, minute=0, args=[bot])
    scheduler.add_job(silence_checker, 'interval', minutes=10, args=[bot])
    scheduler.add_job(money_rain, 'interval', hours=3, args=[bot]) 
    scheduler.add_job(absurd_invest, 'cron', day_of_week='sat', hour='10-22/2', args=[bot])
    scheduler.start()

    await bot.delete_webhook(drop_pending_updates=True)
    print("🤖 MoneyBoss CHAOS EDITION is running...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
