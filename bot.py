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

# --- MEMORY STORAGE ---
# Simple in-memory storage: {user_id: [{"role": "user", "content": "..."}, ...]}
user_history = {}
HISTORY_LIMIT = 10 # Сколько сообщений помнить (5 пар вопрос-ответ)

# --- ADMINS LIST ---
ADMIN_IDS = [] 

SYSTEM_PROMPT = """
ТВОЯ РОЛЬ:
Ты — дерзкий но заботливый Наставник и ведущий бизнес-игры "Финансовый Поток". Это игра-путешествие.
Старт был 29 января 2026 года.
Твоя цель — раскачать чат на деньги общение и отчеты. Ты создаешь атмосферу где стыдно сидеть тихо и бедно.

СТРОГИЕ ЗАПРЕТЫ - КРИТИЧНО:
1. ЗАПРЕЩЕНО использовать Markdown. Не пиши звездочки нижние подчеркивания решетки. Только чистый текст.
2. ЗАПРЕЩЕНО использовать скобки любого вида - круглые квадратные фигурные. ВООБЩЕ никаких скобок в тексте. Пиши мысли через запятую или тире.
3. НЕ давай ссылку на оплату просто так. Ссылку на оплату налога давай ТОЛЬКО если человек написал отчет о доходе и спросил куда платить налог или если контекст прямо требует оплаты.

ТВОИ СЦЕНАРИИ ПОВЕДЕНИЯ:

Сценарий 1 - Если прилетел ОТЧЕТ:
Ключевые слова: Отчет, доход, заработал, налог.
Ты видишь суммы. Например: Доход 50000 Налог 5000.
Твоя реакция: Бурно хвали! Пиши: Принято! Зафиксировал твои 50000 рублей и налог 5000. Ты автоматически поднимаешься в моем личном рейтинге. Красавчик!
Обязательно мотивируй других повторить этот успех.
Если человек написал доход но забыл про налог — мягко напомни что Вселенная любит энергообмен.

Сценарий 2 - Если зашел НОВИЧОК:
Сразу атакуй вниманием. Не давай отмолчаться.
Пример: Привет! Добро пожаловать на борт. Мы тут делаем деньги. Сразу рассказывай: какая ниша что продаешь и почем? Не сиди молча тут это не выгодно.

Сценарий 3 - Если в чате ТИШИНА или тебя разбудили триггером:
Не пиши банальное "Как дела?".
Запускай игру или провокацию.
Примеры:
— Ребята тишина в эфире не приносит денег. Давайте поиграем.
— Кто чем сейчас занят? Кидайте фото рабочего места оценим денежную энергию!
— Игра "Продай мне". Я хочу купить слона. Кто предложит лучший оффер?
Спрашивай конкретно по контексту если знаешь имена.

Сценарий 4 - УТРО и ВЕЧЕР - Ритуалы:
УТРОМ: Пиши фразу: Я уверен сегодня с тобой произойдет приятное финансовое ЧУДО! Дай простое задание на день — улыбнуться 5 людям или сделать 1 смелый звонок.
ВЕЧЕРОМ: Желай сладких снов. Напиши: Отдыхай воин. Завтра новые победы. Дай мини-практику на расслабление — дыхание или благодарность.

Сценарий 5 - ОБЩЕНИЕ И ПОМОЩЬ:
Проявляй инициативу. Спрашивай: Расскажи о своем бизнесе подробнее. Какой у тебя средний чек? Давай подумаем как его поднять.
Накидывай идеи. Будь полезным а не просто болталкой.

ТОН ОБЩЕНИЯ:
Энергичный на "ты" без официоза. Используй смайлики 🔥 🚀 💰 чтобы оживить текст.
Ты — двигатель этого процесса.

ВАЖНО ПРО АДМИНОВ:
Админы — организаторы. Они вне игры и не участвуют в отчетах. С ними общайся как с партнерами уважительно.
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
async def get_ai_response(user_message: str, context: str = "", user_id: int = 0) -> str:
    if not ai_client:
        return "🧠 Мозг AI пока не подключен. Но я все равно слежу за тобой!"
    
    now = datetime.now()
    days_until = (START_DATE - now).days + 1
    
    # Динамическая логика по дням марафона
    if now < START_DATE:
        link_instruction = "ВАЖНО: До 29 января ССЫЛКИ НА ОПЛАТУ НЕ ДАВАЙ. Просто говори что скоро начнем."
        marathon_status = f"До старта марафона {max(0, days_until)} дн. Этап прогрева."
        day_strategy = "Подогревай интерес. Провоцируй на разговоры о деньгах."
    else:
        current_day = (now - START_DATE).days + 1
        link_instruction = "Ссылку на оплату налога давай ТОЛЬКО если человек прямо спросил куда платить или если контекст требует."
        
        if current_day == 1:
            day_strategy = "День 1 - Точка А. Знакомься с участниками. Подкалывай тех кто пришел просто посмотреть. Провоцируй на первые отчеты."
        elif current_day in [2, 3]:
            day_strategy = "День 2-3 - Раскачка. Активно хвали за действия: звонки встречи договора. Напоминай что фундамент денег строится сейчас."
        elif current_day in [4, 5]:
            day_strategy = "День 4-5 - Экватор. Жестче прожаривай молчунов. Спрашивай конкретно: Где твой результат? Половина игры позади."
        elif current_day == 6:
            day_strategy = "День 6 - Финишная прямая. Нагнетай суету: Осталось 48 часов! Напоминай про долги по налогу."
        elif current_day >= 7:
            day_strategy = "День 7+ - Финал. Подводи итоги. Чествуй миллионеров. Жестко напоминай должникам платить."
        else:
            day_strategy = "Марафон идет. Поддерживай движуху."
        
        marathon_status = f"Марафон ИДЕТ. Сегодня День {current_day} из 7. Стратегия дня: {day_strategy}"

    # --- MEMORY MANAGEMENT ---
    if user_id not in user_history:
        user_history[user_id] = []
    
    # Добавляем сообщение юзера в историю
    user_history[user_id].append({"role": "user", "content": f"Контекст: {context}\nСообщение: {user_message}"})
    
    # Обрезаем историю, если слишком длинная
    if len(user_history[user_id]) > HISTORY_LIMIT:
        user_history[user_id] = user_history[user_id][-HISTORY_LIMIT:]

    # Формируем полный промпт
    current_date_str = now.strftime('%d.%m.%Y')
    system_msg = {
        "role": "system", 
        "content": SYSTEM_PROMPT + 
                 f"\n\nСЕГОДНЯШНЯЯ ДАТА: {current_date_str} (2026 ГОД!). Не путай год, сейчас 2026!" +
                 f"\nТЕКУЩИЙ СТАТУС МАРАФОНА: {marathon_status}" +
                 f"\n{link_instruction}" +
                 "\nПРАВИЛО ОФОРМЛЕНИЯ: Не используй Markdown скобки []. Пиши ссылки просто текстом или делай их красивыми через HTML (например <a href='ссылка'>текст</a>)."
    }
    
    messages_payload = [system_msg] + user_history[user_id]

    try:
        completion = await ai_client.chat.completions.create(
            model=AI_MODEL,
            messages=messages_payload
        )
        ai_reply = completion.choices[0].message.content
        
        # Сохраняем ответ бота в историю
        user_history[user_id].append({"role": "assistant", "content": ai_reply})
        
        return ai_reply
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
        ai_msg = await get_ai_response("Я пытаюсь скинуть отчет до старта игры. Отфутболь меня красиво, скажи что ждем 29 января.", user_id=user.id)
        await message.reply(ai_msg)
        return
    
    # Check if sender is admin
    try:
        member = await message.chat.get_member(user.id)
        if member.status in ["creator", "administrator"]:
            ai_comment = await get_ai_response(
                f"Админ {user.first_name} прислал что-то похожее на отчет. Напомни ему в шутливой форме, что админы вне игры, но их пример вдохновляет.",
                context="Админ скинул отчет",
                user_id=user.id
            )
            await message.reply(ai_comment)
            return
    except Exception:
        pass 

    amount = int(match.group(1))
    tax = int(amount * 0.1)

    db.upsert_user(user)

    # Use AI to generate hype/roast
    safe_name = user.first_name
    ai_comment = await get_ai_response(
        f"Пользователь {safe_name} заработал {amount} рублей. Если сумма маленькая (<5000) — пошути над ним. Если большая — восхитись.",
        context="Отчет о доходе",
        user_id=user.id
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
    
    ai_comment = await get_ai_response("Пользователь решил не платить налог сейчас, а записать в долг. Пошути про коллекторов или проценты.", user_id=callback.from_user.id)
    
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
    
    ai_comment = await get_ai_response("Пользователь оплатил налог. Похвали его за честность и очищенную карму.", user_id=message.from_user.id)
    
    await msg_wait.delete()
    await message.reply(f"✅ Оплата принята!\n\n🤖 {ai_comment}")
    await state.clear()

# --- NEW MEMBER GREETING ---
@router.message(F.new_chat_members)
async def welcome_new_member(message: types.Message):
    global GROUP_CHAT_ID
    if message.chat.type in ["group", "supergroup"]:
        GROUP_CHAT_ID = message.chat.id
    
    for new_member in message.new_chat_members:
        if new_member.is_bot:
            continue  # Не приветствуем ботов
        
        greeting = await get_ai_response(
            f"В чат зашел новый участник {new_member.first_name}. Поприветствуй его дерзко и весело, расскажи кратко про марафон.",
            context="Приветствие новичка",
            user_id=new_member.id
        )
        await message.answer(greeting)

@router.message(F.text & ~F.text.startswith("/"))
async def chat_with_ai(message: types.Message):
    global GROUP_CHAT_ID
    if message.chat.type in ["group", "supergroup"]:
        GROUP_CHAT_ID = message.chat.id
        # Обновляем время последнего сообщения (для детектора тишины)
        last_message_time[GROUP_CHAT_ID] = datetime.now()

    user_text = message.text
    user_name = message.from_user.first_name
    
    is_action = any(word in user_text.lower() for word in ["сделал", "звонил", "продал", "встреча", "договор", "клиент"])
    
    context = "Пользователь просто общается."
    if is_action:
        context = "Пользователь сообщает о выполненном БИЗНЕС-ДЕЙСТВИИ но это не деньги. Похвали его бурно."
    
    await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")
    
    response = await get_ai_response(f"{user_name}: {user_text}", context=context, user_id=message.from_user.id)
    await message.reply(response)

# --- SCHEDULED MESSAGES ---
# Хранение времени последнего сообщения для детектора тишины
last_message_time = {}

async def send_daily_motivation(bot: Bot):
    """Утреннее сообщение в 09:00"""
    if not GROUP_CHAT_ID:
        return
        
    motivation = await get_ai_response(
        "Придумай утреннее мотивирующее сообщение. Начни с фразы: Я уверен сегодня с тобой произойдет приятное финансовое ЧУДО! Дай простое задание на день. Используй эмодзи. Без скобок.",
        context="Утреннее сообщение"
    )
    try:
        await bot.send_message(GROUP_CHAT_ID, f"☀️ <b>ДОБРОЕ УТРО</b>\n\n{motivation}")
    except Exception as e:
        logging.error(f"Daily msg error: {e}")

async def send_evening_ritual(bot: Bot):
    """Вечернее сообщение в 21:00"""
    if not GROUP_CHAT_ID:
        return
        
    evening = await get_ai_response(
        "Придумай вечернее пожелание. Начни с: Отдыхай воин. Завтра новые победы. Дай мини-практику на расслабление — дыхание или благодарность. Используй эмодзи. Без скобок.",
        context="Вечернее сообщение"
    )
    try:
        await bot.send_message(GROUP_CHAT_ID, f"🌙 <b>СЛАДКИХ СНОВ</b>\n\n{evening}")
    except Exception as e:
        logging.error(f"Evening msg error: {e}")

async def check_silence(bot: Bot):
    """Проверка тишины каждые 2 часа"""
    if not GROUP_CHAT_ID:
        return
    
    now = datetime.now()
    if GROUP_CHAT_ID in last_message_time:
        silence_duration = (now - last_message_time[GROUP_CHAT_ID]).seconds / 3600  # в часах
        
        # Если тишина больше 2 часов днем (с 10:00 до 20:00)
        if silence_duration > 2 and 10 <= now.hour <= 20:
            provocation = await get_ai_response(
                "В чате тишина уже больше 2 часов. Придумай провокационное сообщение чтобы растормошить людей. Запусти игру или вопрос. Без скобок.",
                context="Детектор тишины"
            )
            try:
                await bot.send_message(GROUP_CHAT_ID, f"🔔 {provocation}")
                last_message_time[GROUP_CHAT_ID] = now  # Обновляем время
            except Exception as e:
                logging.error(f"Silence check error: {e}")

async def main():
    if not TOKEN:
        print("Error: BOT_TOKEN not found in .env")
        return

    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    scheduler = AsyncIOScheduler()
    # Утреннее сообщение в 09:00
    scheduler.add_job(send_daily_motivation, 'cron', hour=9, minute=0, args=[bot])
    # Вечернее сообщение в 21:00
    scheduler.add_job(send_evening_ritual, 'cron', hour=21, minute=0, args=[bot])
    # Проверка тишины каждые 2 часа (с 10:00 до 20:00)
    scheduler.add_job(check_silence, 'cron', hour='10-20/2', minute=0, args=[bot])
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
