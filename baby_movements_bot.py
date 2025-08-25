import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils import executor
import asyncio
import os

# --- Настройки ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
MINUTES_INTERVAL = int(os.environ.get("INTERVAL_MINUTES", 10))
TIMEZONE = os.environ.get("TIMEZONE", "Europe/Minsk")
tz = ZoneInfo(TIMEZONE)
UPDATE_INTERVAL = 10  # секунд между обновлениями кнопки

# --- База данных ---
conn = sqlite3.connect("movements.db")
cursor = conn.cursor()
cursor.execute("""
               CREATE TABLE IF NOT EXISTS movements (
                                                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                                                        timestamp TEXT
               )
               """)
conn.commit()

# --- Бот ---
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)
main_message_id = None  # ID основного сообщения с кнопкой

# --- Функции ---
def get_today_count():
    now = datetime.now(tz)
    today_str = now.strftime("%Y-%m-%d")
    cursor.execute("SELECT COUNT(*) FROM movements WHERE DATE(timestamp)=?", (today_str,))
    count = cursor.fetchone()[0]
    return count

def get_last_movement_time():
    cursor.execute("SELECT timestamp FROM movements ORDER BY id DESC LIMIT 1")
    row = cursor.fetchone()
    if row:
        return datetime.fromisoformat(row[0]).astimezone(tz)
    return None

def build_keyboard():
    last_time = get_last_movement_time()
    now = datetime.now(tz)
    count = get_today_count()

    # Определяем "цвет" кнопки
    if last_time and (now - last_time) < timedelta(minutes=MINUTES_INTERVAL):
        emoji = "🔴"
    else:
        emoji = "🟢"

    foot_button = InlineKeyboardButton(f"{emoji} 👣 ({count})", callback_data="movement")

    keyboard = InlineKeyboardMarkup()
    keyboard.add(foot_button)
    keyboard.add(InlineKeyboardButton("🔄 Начать новый день", callback_data="reset_day"))
    keyboard.add(InlineKeyboardButton("⏱ Настроить таймер", callback_data="set_timer"))
    return keyboard

async def update_main_message(chat_id, message_id):
    while True:
        try:
            await bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=build_keyboard())
        except Exception:
            pass  # Игнорируем, если сообщение удалено или ещё не создано
        await asyncio.sleep(UPDATE_INTERVAL)

# --- Хэндлеры ---
@dp.message_handler(commands=["start"])
async def start(msg: types.Message):
    global main_message_id
    sent = await msg.answer("Добро пожаловать! Ведём дневник движений плода.", reply_markup=build_keyboard())
    main_message_id = sent.message_id
    asyncio.create_task(update_main_message(msg.chat.id, main_message_id))

@dp.callback_query_handler(lambda c: c.data == "movement")
async def movement_callback(query: types.CallbackQuery):
    last_time = get_last_movement_time()
    now = datetime.now(tz)
    if last_time and (now - last_time) < timedelta(minutes=MINUTES_INTERVAL):
        await query.answer(f"Подождите {MINUTES_INTERVAL} минут между движениями.", show_alert=True)
        return
    cursor.execute("INSERT INTO movements (timestamp) VALUES (?)", (now.isoformat(),))
    conn.commit()
    await query.answer("Засчитано движение!")

@dp.callback_query_handler(lambda c: c.data == "reset_day")
async def reset_day(query: types.CallbackQuery):
    now = datetime.now(tz)
    today_str = now.strftime("%Y-%m-%d")
    cursor.execute("DELETE FROM movements WHERE DATE(timestamp)=?", (today_str,))
    conn.commit()
    await query.answer("Счётчик за сегодня сброшен!")

@dp.callback_query_handler(lambda c: c.data == "set_timer")
async def set_timer(query: types.CallbackQuery):
    await query.message.answer("Введите новый интервал между движениями в минутах:")
    await query.answer()

@dp.message_handler(lambda msg: msg.text.isdigit())
async def timer_set(msg: types.Message):
    global MINUTES_INTERVAL
    MINUTES_INTERVAL = int(msg.text)
    await msg.answer(f"Интервал между движениями обновлён на {MINUTES_INTERVAL} минут.")

# --- Запуск ---
if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
