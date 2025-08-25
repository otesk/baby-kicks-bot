#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Полноценный Baby Movements Telegram Bot с гибким таймером
--------------------------------------------------------
Функции:
- 👣 Запись движения до 10 за день
- Кнопка подсвечивается 🟢/🔴 в зависимости от таймера
- ↩️ Отменить последнее нажатие
- 🔄 Сбросить таймер
- ⏱ Настройка таймера через меню (сохраняется в SQLite)
- 📖 Дневник по дням
- 📤 Экспорт CSV
- 📊 Статистика за неделю

Запуск: python baby_movements_bot.py
"""

import os
import sqlite3
import csv
from datetime import datetime, timedelta, date
from typing import Optional, Tuple, List

from aiogram import Bot, Dispatcher, executor, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, InputFile

BOT_TOKEN = os.getenv("BOT_TOKEN", "PASTE_YOUR_BOT_TOKEN_HERE")
DB_PATH = os.getenv("DB_PATH", "movements.db")
GOAL_PER_DAY = 10
DEFAULT_COOLDOWN_SECONDS = 10*60

if BOT_TOKEN == "PASTE_YOUR_BOT_TOKEN_HERE":
    print("[ВНИМАНИЕ] Вставьте токен вашего бота в BOT_TOKEN или задайте через переменную окружения.")

force_green_flag = {}
user_manual_timer_input = set()

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

# ==== Инициализация базы данных ====

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS movements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                ts INTEGER NOT NULL
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER PRIMARY KEY,
                cooldown_seconds INTEGER NOT NULL
            );
        """)
        conn.commit()

# ==== Таймер пользователя ====

def get_user_cooldown(user_id: int) -> int:
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT cooldown_seconds FROM user_settings WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        if row:
            return row[0]
        else:
            cur.execute("INSERT OR IGNORE INTO user_settings(user_id, cooldown_seconds) VALUES(?, ?)"
                        , (user_id, DEFAULT_COOLDOWN_SECONDS))
            conn.commit()
            return DEFAULT_COOLDOWN_SECONDS


def set_user_cooldown(user_id: int, seconds: int):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("INSERT OR REPLACE INTO user_settings(user_id, cooldown_seconds) VALUES(?, ?)"
                    , (user_id, seconds))
        conn.commit()

# ==== Движения ====

def now_local():
    return datetime.now()

def to_epoch(dt: datetime) -> int:
    return int(dt.timestamp())

def from_epoch(ts: int) -> datetime:
    return datetime.fromtimestamp(ts)


def insert_movement(user_id: int, ts: Optional[int] = None):
    if ts is None:
        ts = to_epoch(now_local())
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO movements (user_id, ts) VALUES (?, ?)" , (user_id, ts))
        conn.commit()


def delete_last_movement(user_id: int) -> Optional[int]:
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, ts FROM movements WHERE user_id = ? ORDER BY ts DESC LIMIT 1", (user_id,))
        row = cur.fetchone()
        if not row:
            return None
        rec_id, ts = row
        cur.execute("DELETE FROM movements WHERE id = ?", (rec_id,))
        conn.commit()
        return ts


def fetch_last_movement(user_id: int) -> Optional[int]:
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT ts FROM movements WHERE user_id = ? ORDER BY ts DESC LIMIT 1", (user_id,))
        row = cur.fetchone()
        return row[0] if row else None


def fetch_day_movements(user_id: int, for_date: Optional[date] = None) -> List[int]:
    if for_date is None:
        for_date = now_local().date()
    start = datetime.combine(for_date, datetime.min.time())
    end = start + timedelta(days=1)
    start_ts = to_epoch(start)
    end_ts = to_epoch(end)
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT ts FROM movements WHERE user_id=? AND ts >= ? AND ts < ? ORDER BY ts ASC", (user_id, start_ts, end_ts))
        return [r[0] for r in cur.fetchall()]

# ==== Проверка интервала ====

def is_press_allowed(user_id: int) -> Tuple[bool, Optional[int]]:
    if force_green_flag.get(user_id):
        return True, None
    last = fetch_last_movement(user_id)
    if last is None:
        return True, None
    delta = to_epoch(now_local()) - last
    cooldown = get_user_cooldown(user_id)
    if delta >= cooldown:
        return True, None
    else:
        return False, cooldown - delta

# ==== Клавиатуры ====

def main_reply_kb() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton("👣 Нажать"))
    kb.add(KeyboardButton("↩️ Отменить последнее"), KeyboardButton("🔄 Сбросить таймер"))
    kb.add(KeyboardButton("📖 Дневник"))
    kb.add(KeyboardButton("📤 Экспорт CSV"), KeyboardButton("📊 Статистика"))
    kb.add(KeyboardButton("⏱ Настройка таймера"))
    return kb


def press_inline_kb(allowed: bool) -> InlineKeyboardMarkup:
    text = "🟢 👣 Нажать" if allowed else "🔴 👣 Рано"
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(text, callback_data="kick"))
    return kb

# ==== Настройка таймера через меню ====
@dp.message_handler(lambda m: m.text == "⏱ Настройка таймера")
async def on_set_timer(message: types.Message):
    kb = InlineKeyboardMarkup(row_width=4)
    options = [5,10,15,20]
    for val in options:
        kb.insert(InlineKeyboardButton(f"{val} мин", callback_data=f"set_timer:{val}"))
    kb.add(InlineKeyboardButton("Ввести вручную", callback_data="set_timer_manual"))
    await message.answer("Выберите интервал таймера:", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith("set_timer:"))
async def on_set_timer_cb(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    try:
        val_min = int(callback_query.data.split(":")[1])
        set_user_cooldown(user_id, val_min*60)
        await callback_query.answer(f"Интервал установлен на {val_min} минут ✅", show_alert=True)
    except:
        await callback_query.answer("Ошибка ❌", show_alert=True)

@dp.callback_query_handler(lambda c: c.data == "set_timer_manual")
async def on_set_timer_manual(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    user_manual_timer_input.add(user_id)
    await callback_query.message.answer("Введите интервал в минутах:")
    await callback_query.answer()

@dp.message_handler(lambda m: m.from_user.id in user_manual_timer_input)
async def on_manual_timer_input(message: types.Message):
    user_id = message.from_user.id
    try:
        val_min = int(message.text)
        if val_min <= 0:
            raise ValueError
        set_user_cooldown(user_id, val_min*60)
        await message.answer(f"Интервал установлен на {val_min} минут ✅")
    except:
        await message.answer("Ошибка, введите положительное число минут")
    finally:
        user_manual_timer_input.discard(user_id)

# ==== Обработчики нажатий, дневника, экспорта CSV и статистики ====
@dp.message_handler(lambda m: m.text == "👣 Нажать")
async def handle_press(message: types.Message):
    user_id = message.from_user.id
    allowed, wait_sec = is_press_allowed(user_id)
    if allowed:
        insert_movement(user_id)
        await message.answer(f"Движение зафиксировано ✅", reply_markup=main_reply_kb())
    else:
        await message.answer(f"Подождите ещё {int(wait_sec/60)+1} мин 🔴", reply_markup=main_reply_kb())

@dp.message_handler(lambda m: m.text == "↩️ Отменить последнее")
async def handle_undo(message: types.Message):
    ts = delete_last_movement(message.from_user.id)
    if ts:
        await message.answer(f"Последнее движение удалено 🗑️", reply_markup=main_reply_kb())
    else:
        await message.answer(f"Нет записей для удаления", reply_markup=main_reply_kb())

@dp.message_handler(lambda m: m.text == "🔄 Сбросить таймер")
async def handle_reset_timer(message: types.Message):
    force_green_flag[message.from_user.id] = True
    await message.answer(f"Таймер сброшен, кнопка снова зелёная ✅", reply_markup=main_reply_kb())

@dp.message_handler(lambda m: m.text == "📖 Дневник")
async def handle_diary(message: types.Message):
    movements = fetch_day_movements(message.from_user.id)
    if not movements:
        await message.answer("Нет движений за сегодня 📅", reply_markup=main_reply_kb())
    else:
        text = "Дневник за сегодня:\n" + "\n".join([from_epoch(ts).strftime('%H:%M') for ts in movements])
        await message.answer(text, reply_markup=main_reply_kb())

@dp.message_handler(lambda m: m.text == "📤 Экспорт CSV")
async def handle_export_csv(message: types.Message):
    user_id = message.from_user.id
    movements = fetch_day_movements(user_id)
    if not movements:
        await message.answer("Нет данных для экспорта", reply_markup=main_reply_kb())
        return
    filename = f"movements_{user_id}_{datetime.now().strftime('%Y%m%d')}.csv"
    with open(filename, "w", newline="", encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["ДатаВремя"])
        for ts in movements:
            writer.writerow([from_epoch(ts).strftime('%Y-%m-%d %H:%M:%S')])
    await message.answer_document(InputFile(filename))

@dp.message_handler(lambda m: m.text == "📊 Статистика")
async def handle_stats(message: types.Message):
    user_id = message.from_user.id
    text = "Статистика за неделю:\n"
    for i in range(6,-1,-1):
        d = (now_local() - timedelta(days=i)).date()
        count = len(fetch_day_movements(user_id, d))
        text += f"{d.strftime('%d.%m')}: {count} движений\n"
    await message.answer(text, reply_markup=main_reply_kb())

# ==== Запуск ====
if __name__ == "__main__":
    init_db()
    print("Запуск бота... Нажмите Ctrl+C для остановки.")
    executor.start_polling(dp, skip_updates=True)
