import asyncio
import logging
import os
import re
import sqlite3
import random
from datetime import datetime
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
START_DATE = datetime(2026, 1, 29) # Официальный старт

PAYMENT_INFO = "Ссылка для оплаты: https://newron.ru/moneyboss"
DB_NAME = "moneyboss.db"
GROUP_CHAT_ID = None  # Will be saved dynamically or set manually

# --- AI CLIENT SETUP ---
ai_client = None
if AI_API_KEY and "YOUR_KEY" not in AI_API_KEY:
    ai_client = AsyncOpenAI(
        api_key=AI_API_KEY,
        base_url=AI_BASE_URL,
    )

# --- ADMINS LIST ---
ADMIN_IDS = [] 

SYSTEM_PROMPT = """
Ты — MoneyBoss, дерзкий, но полезный бизнес-наставник в Telegram-чате денежного марафона.
Твой характер:
1. Ты "свой в доску", используешь сленг (кэш, бабки, движ, тема).
2. Ты любишь деньги и ненавидишь лень.
3. Ты жестко шутишь над нытиками, но поддерживаешь тех, кто действует.
4. Если пользователь пишет про нематериальные действия (звонки, встречи, договора) — хвали его, ведь это ведет к деньгам.
5. Отвечай кратко, емко, весело. Не пиши поэмы.

ВАЖНО ПРО АДМИНОВ:
В чате есть администраторы. Они твои "союзники", а не игроки.
1. Администраторы НЕ участвуют в отчетах. Если админ скинет фото с текстом "Отчет", не создавай для него кнопки оплаты, просто поприветствуй или пошути, что "Шеф вне игры".
2. Ты общаешься с админами уважительно, как с партнерами по организации этого движа.
3. Не вовлекай их в соревнование /top.

Твоя задача: мотивировать участников зарабатывать больше, платить налог в фонд по ссылке https://newron.ru/moneyboss и создавать движуху.
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
                    debt INTEGER DEFAULT 0
                )
            """)
            conn.commit()

    def upsert_user(self, user: types.User):
        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR IGNORE INTO users (user_id, full_name, username, total_earned, debt)
                VALUES (?, ?, ?, 0, 0)
            """, (user.id, user.full_name, user.username))
            cursor.execute("""
                UPDATE users SET full_name = ?, username = ? WHERE user_id = ?
            """, (user.full_name, user.username, user.id))
            conn.commit()

    def add_income_pay_later(self, user_id: int, income: int, tax: int):
        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE users 
                SET total_earned = total_earned + ?, 
                    debt = debt + ?
                WHERE user_id = ?
            """, (income, tax, user_id))
            conn.commit()

    def add_income_pay_now(self, user_id: int, income: int):
        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE users 
                SET total_earned = total_earned + ?
                WHERE user_id = ?
            """, (income, user_id))
            conn.commit()

    def get_top_users(self, limit=10):
        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT full_name, total_earned, debt 
                FROM users 
                ORDER BY total_earned DESC 
                LIMIT ?
            """, (limit,))
            return cursor.fetchall()

db = Database(DB_NAME)

# --- STATES & CALLBACKS ---
class PaymentFlow(StatesGroup):
    waiting_for_tax_proof = State()

class ReportAction(CallbackData, prefix="rep"):
    action: str
    amount: int
    user_id: int

# --- LOGIC SETUP ---
router = Router()

# --- AI HELPER FUNCTION ---
async def get_ai_response(user_message: str, context: str = "") -> str:
    if not ai_client:
        return "🧠 Мозг AI пока не подключен. Но я все равно слежу за тобой!"
    
    now = datetime.now()
    days_until = (START_DATE - now).days + 1
    
    # Формируем динамическую инструкцию по ссылкам
    if now < START_DATE:
        link_instruction = "ВАЖНО: До 29 января ССЫЛКИ НА ОПЛАТУ НЕ ДАВАЙ. Просто говори, что скоро начнем."
        marathon_status = f"До старта марафона {max(0, days_until)} дн. Этап прогрева. Ссылки на оплату ЗАПРЕЩЕНЫ."
    else:
        link_instruction = f"Если уместно, напоминай про ссылку для оплаты: {PAYMENT_INFO}"
        current_day = (now - START_DATE).days + 1
        marathon_status = f"Марафон ИДЕТ. Сегодня {current_day}-й день из 7."

    try:
        completion = await ai_client.chat.completions.create(
            model=AI_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT + 
                 f"\n\nТЕКУЩИЙ СТАТУС: {marathon_status}" +
                 f"\n{link_instruction}" +
                 "\nПРАВИЛО ОФОРМЛЕНИЯ: Не используй Markdown скобки []. Пиши ссылки просто текстом или делай их красивыми через HTML (например <a href='ссылка'>текст</a>)."},
                {"role": "user", "content": f"Контекст: {context}\nСообщение юзера: {user_message}"}
            ]
        )
        return completion.choices[0].message.content
    except Exception as e:
        logging.error(f"AI Error: {e}")
        return "🤯 Перегрелся процессор... Попробуй позже!"

# --- HANDLERS ---

@router.message(Command("start"))
async def cmd_start(message: types.Message):
    global GROUP_CHAT_ID
    if message.chat.type in ["group", "supergroup"]:
        GROUP_CHAT_ID = message.chat.id
        
    await message.answer(
        "👋 Йо! Я <b>MoneyBoss</b>. \n\n"
        "Правила просты:\n"
        "1. Заработал денег? Кидай фото с подписью <code>Отчет &lt;сумма&gt;</code>.\n"
        "2. Сделал полезное действие (звонок, встреча)? Пиши в чат, я оценю.\n"
        "3. Нужен совет? Спрашивай прямо тут.\n"
        "4. <code>/top</code> — доска почета."
    )

@router.message(Command("top"))
async def cmd_top(message: types.Message):
    users = db.get_top_users()
    if not users:
        await message.answer("🤷‍♂️ Пока никто не отчитывался. Будь первым!")
        return

    lines = ["🏆 <b>ТОП MONEY MAKERS</b> 🏆\n"]
    medals = ["🥇", "🥈", "🥉"]

    for idx, (name, earned, debt) in enumerate(users):
        rank = medals[idx] if idx < 3 else f"{idx + 1}."
        status = f"✅" if debt == 0 else f"(Долг: {debt} руб)"
        safe_name = html.quote(name)
        lines.append(f"{rank} <b>{safe_name}</b>: {earned:,} руб {status}")

    await message.answer("\n".join(lines))

@router.message(F.photo & F.caption)
async def process_report(message: types.Message):
    global GROUP_CHAT_ID
    if message.chat.type in ["group", "supergroup"]:
        GROUP_CHAT_ID = message.chat.id

    match = re.search(r"^Отчет\s+(\d+)$", message.caption, re.IGNORECASE)
    if not match:
        return

    user = message.from_user

    # Проверка даты
    if datetime.now() < START_DATE:
        ai_msg = await get_ai_response("Я пытаюсь скинуть отчет до старта игры. Отфутболь меня красиво, скажи что ждем 29 января.")
        await message.reply(ai_msg)
        return
    
    # Check if sender is admin
    try:
        member = await message.chat.get_member(user.id)
        if member.status in ["creator", "administrator"]:
            ai_comment = await get_ai_response(
                f"Админ {user.first_name} прислал что-то похожее на отчет. Напомни ему в шутливой форме, что админы вне игры, но их пример вдохновляет.",
                context="Админ скинул отчет"
            )
            await message.reply(ai_comment)
            return
    except Exception:
        pass 

    amount = int(match.group(1))
    tax = int(amount * 0.1)

    db.upsert_user(user)

    safe_name = user.first_name
    ai_comment = await get_ai_response(
        f"Пользователь {safe_name} заработал {amount} рублей. Если сумма маленькая (<5000) — пошути над ним. Если большая — восхитись.",
        context="Отчет о доходе"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"💸 Оплатить 10% ({tax} р) сейчас", callback_data=ReportAction(action="pay_now", amount=amount, user_id=user.id).pack())],
        [InlineKeyboardButton(text=f"⏳ В долг до финала", callback_data=ReportAction(action="pay_later", amount=amount, user_id=user.id).pack())]
    ])

    await message.reply(
        f"{ai_comment}\n\n"
        f"💰 Доход: {amount} руб\n"
        f"👮 Налог: {tax} руб\n\n"
        f"Чё делаем?",
        reply_markup=kb
    )

@router.callback_query(ReportAction.filter(F.action == "pay_later"))
async def cb_pay_later(callback: types.CallbackQuery, callback_data: ReportAction):
    if callback.from_user.id != callback_data.user_id:
        await callback.answer("Не лезь не в свое дело!", show_alert=True)
        return

    tax = int(callback_data.amount * 0.1)
    db.add_income_pay_later(callback.from_user.id, callback_data.amount, tax)
    
    ai_comment = await get_ai_response("Пользователь решил не платить налог сейчас, а записать в долг. Пошути про коллекторов или проценты.")
    
    await callback.message.edit_text(
        f"✍️ Записал: +{callback_data.amount} руб.\n"
        f"📉 Долг вырос на {tax} руб.\n\n"
        f"🤖 {ai_comment}",
        reply_markup=None
    )

@router.callback_query(ReportAction.filter(F.action == "pay_now"))
async def cb_pay_now(callback: types.CallbackQuery, callback_data: ReportAction, state: FSMContext):
    if callback.from_user.id != callback_data.user_id:
        await callback.answer("Брысь!", show_alert=True)
        return

    tax = int(callback_data.amount * 0.1)
    await state.set_state(PaymentFlow.waiting_for_tax_proof)
    await state.update_data(amount=callback_data.amount, tax=tax)

    await callback.message.reply(
        f"Реквизиты:\n<code>{PAYMENT_INFO}</code>\n\n"
        f"Сумма: <b>{tax} руб</b>\n"
        f"👇 Жду скрин!"
    )
    await callback.message.edit_reply_markup(reply_markup=None)

@router.message(PaymentFlow.waiting_for_tax_proof, F.photo)
async def process_proof(message: types.Message, state: FSMContext):
    data = await state.get_data()
    amount = data.get("amount")
    
    msg_wait = await message.answer("⏳ Проверяю...")
    await asyncio.sleep(2)
    
    db.add_income_pay_now(message.from_user.id, amount)
    
    ai_comment = await get_ai_response("Пользователь оплатил налог. Похвали его за честность и очищенную карму.")
    
    await msg_wait.delete()
    await message.reply(f"✅ Оплата принята!\n\n🤖 {ai_comment}")
    await state.clear()

@router.message(F.text & ~F.text.startswith("/"))
async def chat_with_ai(message: types.Message):
    global GROUP_CHAT_ID
    if message.chat.type in ["group", "supergroup"]:
        GROUP_CHAT_ID = message.chat.id

    user_text = message.text
    user_name = message.from_user.first_name
    
    is_action = any(word in user_text.lower() for word in ["сделал", "звонил", "продал", "встреча", "договор", "клиент"])
    
    context = "Пользователь просто общается."
    if is_action:
        context = "Пользователь сообщает о выполненном БИЗНЕС-ДЕЙСТВИИ (но это не деньги). Похвали его."
    
    await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")
    
    response = await get_ai_response(f"{user_name}: {user_text}", context=context)
    await message.reply(response)

async def send_daily_motivation(bot: Bot):
    if not GROUP_CHAT_ID:
        return
        
    motivation = await get_ai_response(
        "Придумай очень короткое, дерзкое и мотивирующее сообщение для чата предпринимателей. Доброе утро, призыв работать. Используй эмодзи.",
        context="Утреннее сообщение"
    )
    try:
        await bot.send_message(GROUP_CHAT_ID, f"☀️ <b>MORNING HYPE</b>\n\n{motivation}")
    except Exception as e:
        logging.error(f"Daily msg error: {e}")

async def main():
    if not TOKEN:
        print("Error: BOT_TOKEN not found in .env")
        return

    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    scheduler = AsyncIOScheduler()
    scheduler.add_job(send_daily_motivation, 'cron', hour=9, minute=0, args=[bot])
    scheduler.start()

    await bot.delete_webhook(drop_pending_updates=True)
    print("🤖 MoneyBoss AI Edition is running...")
    
    if ai_client:
        print("🧠 AI Client initialized.")
    else:
        print("⚠️ AI Client NOT initialized (Check .env)")

    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped")
