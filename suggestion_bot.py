import asyncio
import logging
import os
import re
import sqlite3
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiohttp import web

# --- НАСТРОЙКИ ---
BOT_TOKEN = "8888033833:AAHCof6gsdhNajXrF8Uk2XnnhkZmCfNCS9U"
SUPER_ADMIN_ID = 8626592837  # Ваш Telegram ID (главный админ)

DB_NAME = "bot_data.db"

# --- ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ ---
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Таблица пользователей
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY
        )
    """)
    
    # Таблица администраторов
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            user_id INTEGER PRIMARY KEY
        )
    """)
    
    # Таблица настроек (тексты)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    
    # Значения по умолчанию
    cursor.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (SUPER_ADMIN_ID,))
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('start_text', 'Привет! Напишите сюда ваше предложение или вопрос, и администратор вам ответит.')")
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('info_text', 'Информация о данном боте предложки.')")
    
    conn.commit()
    conn.close()

def add_user(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()

def is_admin(user_id: int) -> bool:
    if user_id == SUPER_ADMIN_ID:
        return True
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM admins WHERE user_id = ?", (user_id,))
    res = cursor.fetchone()
    conn.close()
    return res is not None

def get_all_users():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = [row[0] for row in cursor.fetchall()]
    conn.close()
    return users

def get_all_admins():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM admins")
    admins = [row[0] for row in cursor.fetchall()]
    conn.close()
    return admins

def add_admin_db(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()

def remove_admin_db(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def get_setting(key: str) -> str:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    res = cursor.fetchone()
    conn.close()
    return res[0] if res else ""

def set_setting(key: str, value: str):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

# --- FSM (Состояния для ввода данных) ---
class AdminStates(StatesGroup):
    waiting_for_broadcast = State()
    waiting_for_add_admin = State()
    waiting_for_del_admin = State()
    waiting_for_start_text = State()
    waiting_for_info_text = State()

# --- ФЕЙК-СЕРВЕР ДЛЯ RENDER ---
async def handle_ping(request):
    return web.Response(text="Bot is running!")

async def start_dummy_server():
    app = web.Application()
    app.router.add_get('/', handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

# --- БОТ ---
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Главная клавиатура для пользователей
user_keyboard = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="ℹ️ Информация")]],
    resize_keyboard=True
)

# Инлайн-клавиатура админ-панели
def get_admin_ikb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
            [InlineKeyboardButton(text="➕ Добавить админа", callback_data="admin_add"),
             InlineKeyboardButton(text="➖ Удалить админа", callback_data="admin_del")],
            [InlineKeyboardButton(text="👥 Список админов", callback_data="admin_list"),
             InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
            [InlineKeyboardButton(text="✏️ Изменить «Приветствие»", callback_data="admin_edit_start")],
            [InlineKeyboardButton(text="✏️ Изменить «Информацию»", callback_data="admin_edit_info")]
        ]
    )

# --- ХЭНДЛЕРЫ ПОЛЬЗОВАТЕЛЕЙ ---

@dp.message(CommandStart())
async def start_cmd(message: types.Message):
    add_user(message.from_user.id)
    text = get_setting('start_text')
    await message.answer(text, reply_markup=user_keyboard)

@dp.message(F.text == "ℹ️ Информация")
async def info_cmd(message: types.Message):
    add_user(message.from_user.id)
    text = get_setting('info_text')
    await message.answer(text)

# --- АДМИН ПАНЕЛЬ КОМАНДА /ворк ---

# Пересылка сообщений от пользователей админам
@dp.message(~F.text.startswith("/"))
async def forward_to_admin(message: types.Message):
    if is_admin(message.from_user.id):
        return

    add_user(message.from_user.id)
    admins = get_all_admins()
    user = message.from_user
    
    # Служебный текст без форматирования
    info_header = f"📩 Сообщение от пользователя:\n🆔 #id{user.id}\n-------------------\n"
    
    for admin_id in admins:
        try:
            if message.text:
                await bot.send_message(
                    chat_id=admin_id,
                    text=info_header + message.text
                )
            else:
                # Сначала отправляем ID, затем медиа
                await bot.send_message(chat_id=admin_id, text=info_header)
                await message.copy_to(chat_id=admin_id)
        except Exception as e:
            logging.error(f"Ошибка отправки админу {admin_id}: {e}")
            
    await message.answer("✅ Ваше сообщение отправлено администраторам!")

# Ответы от любого админа пользователю
@dp.message(F.reply_to_message)
async def reply_to_user(message: types.Message):
    if not is_admin(message.from_user.id):
        return

    reply = message.reply_to_message
    text_to_search = reply.text or reply.caption or ""
    
    # Поиск ID
    match = re.search(r"#id(\d+)", text_to_search)
    
    if match:
        user_id = int(match.group(1))
        try:
            await message.copy_to(chat_id=user_id)
            await message.answer("🚀 Ответ успешно отправлен!")
        except Exception as e:
            await message.answer(f"❌ Ошибка отправки пользователю {user_id}:\n{e}")
    else:
        await message.answer("⚠️ Не удалось найти #id. Убедитесь, что отвечаете (Reply) на сообщение бота с ID пользователя.")
            
    await message.answer(f"✅ Рассылка завершена! Успешно доставлено: {count} из {len(users)}")

@dp.message(AdminStates.waiting_for_add_admin)
async def process_add_admin(message: types.Message, state: FSMContext):
    await state.clear()
    if message.text and message.text.isdigit():
        new_admin = int(message.text)
        add_admin_db(new_admin)
        await message.answer(f"✅ Пользователь `{new_admin}` добавлен в список администраторов!", parse_mode="Markdown")
    else:
        await message.answer("❌ Некорректный ID. Введите число.")

@dp.message(AdminStates.waiting_for_del_admin)
async def process_del_admin(message: types.Message, state: FSMContext):
    await state.clear()
    if message.text and message.text.isdigit():
        del_admin = int(message.text)
        if del_admin == SUPER_ADMIN_ID:
            await message.answer("❌ Нельзя удалить главного администратора!")
            return
        remove_admin_db(del_admin)
        await message.answer(f"✅ Пользователь `{del_admin}` удален из администраторов!", parse_mode="Markdown")
    else:
        await message.answer("❌ Некорректный ID. Введите число.")

@dp.message(AdminStates.waiting_for_start_text)
async def process_start_text(message: types.Message, state: FSMContext):
    await state.clear()
    set_setting('start_text', message.text)
    await message.answer("✅ Текст приветствия успешно обновлен!")

@dp.message(AdminStates.waiting_for_info_text)
async def process_info_text(message: types.Message, state: FSMContext):
    await state.clear()
    set_setting('info_text', message.text)
    await message.answer("✅ Текст информации успешно обновлен!")

# --- ПЕРЕСЫЛКА СООБЩЕНИЙ И ОТВЕТЫ ---

# Сообщения от обычных пользователей админам
@dp.message(~F.text.startswith("/"))
async def forward_to_admin(message: types.Message):
    if is_admin(message.from_user.id):
        return  # Игнорируем обычные сообщения от админов, если это не reply

    add_user(message.from_user.id)
    admins = get_all_admins()
    
    user = message.from_user
    caption_text = f"\n\n📩 *Сообщение от:* {user.full_name} (@{user.username or 'нет_юзернейма'})\n🆔 `#id{user.id}`"
    
    for admin_id in admins:
        try:
            if message.text:
                await bot.send_message(
                    chat_id=admin_id,
                    text=message.text + caption_text,
                    parse_mode="Markdown"
                )
            else:
                await message.copy_to(
                    chat_id=admin_id,
                    caption=(message.caption or "") + caption_text,
                    parse_mode="Markdown"
                )
        except Exception as e:
            logging.error(f"Не удалось отправить админу {admin_id}: {e}")
            
    await message.answer("✅ Ваше сообщение отправлено администраторам!")

# Ответы от любого админа пользователю
@dp.message(F.reply_to_message)
async def reply_to_user(message: types.Message):
    if not is_admin(message.from_user.id):
        return

    reply = message.reply_to_message
    text_to_search = reply.text or reply.caption or ""
    match = re.search(r"#id(\d+)", text_to_search)
    
    if match:
        user_id = int(match.group(1))
        try:
            await message.copy_to(chat_id=user_id)
            await message.answer("🚀 Ответ успешно отправлен!")
        except Exception as e:
            await message.answer(f"❌ Не удалось отправить ответ. Ошибка: {e}")
    else:
        await message.answer("⚠️ Не удалось определить ID пользователя в сообщении, на которое вы отвечаете.")

# --- ЗАПУСК ---
async def main():
    logging.basicConfig(level=logging.INFO)
    init_db()
    await start_dummy_server()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
