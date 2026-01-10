import logging
import asyncio
import os
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ChatMemberStatus

import database

# Загрузка переменных окружения
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
# Берем супер-админов из ENV, но основную проверку будем делать через БД
SUPER_ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
FOLDER_LINK = os.getenv("FOLDER_LINK", "")

# Настройка логирования
logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Инициализация БД при старте
@dp.startup()
async def on_startup():
    await database.init_db()

    # Добавляем супер-админов из .env в базу данных при старте
    for admin_id in SUPER_ADMIN_IDS:
        await database.add_admin(admin_id, "SuperAdmin")

    logging.info("База данных инициализирована.")

async def is_user_admin(user_id: int) -> bool:
    if user_id in SUPER_ADMIN_IDS:
        return True
    return await database.is_admin(user_id)

# --- Админские команды ---

@dp.message(Command("help"))
async def cmd_help(message: Message):
    if not await is_user_admin(message.from_user.id):
        return

    help_text = (
        "🤖 <b>Инструкция по использованию бота</b>\n\n"
        "Бот проверяет подписку пользователей на все чаты из списка. "
        "Если пользователь не подписан хотя бы на один чат, его сообщения удаляются.\n\n"
        "<b>Команды админа:</b>\n"
        "/add_chat — добавить текущий чат в список обязательных.\n"
        "/add_chat &lt;id&gt; — добавить чат по ID.\n"
        "/rem_chat — удалить текущий чат из списка.\n"
        "/rem_chat &lt;id&gt; — удалить чат по ID.\n"
        "/list_chats — показать список отслеживаемых чатов.\n"
        "/add_admin &lt;id|username&gt; — добавить администратора.\n"
        "/rem_admin &lt;id&gt; — удалить администратора.\n"
        "/list_admins — список всех администраторов.\n"
        "/help — показать это сообщение.\n\n"
        "ℹ️ <i>Важно:</i> Бот должен быть администратором во всех чатах, которые нужно проверять."
    )
    await message.answer(help_text, parse_mode="HTML")

@dp.message(Command("add_admin"))
async def cmd_add_admin(message: Message):
    if not await is_user_admin(message.from_user.id):
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("Использование: /add_admin <id или @username>")
        return

    target = args[1]
    user_id = None
    username = None

    # Попытка парсить как ID
    if target.isdigit():
        user_id = int(target)
    elif target.startswith("@"):
        # Если юзернейм, нам нужно получить ID.
        # Боты не могут резолвить юзернеймы в ID без взаимодействия (ограничение API),
        # НО, get_chat для приватного чата с юзером может работать только если бот видел юзера.
        # В общем случае это проблема. Но попробуем просто сохранить юзернейм?
        # Нет, для проверок нужен ID.
        # Единственный способ узнать ID по username - если юзер писал боту (или есть в базе).
        # Как workaround: можно попросить пользователя переслать сообщение.
        # Но мы попробуем стандартные методы, может прокатит кэш. (Шанс мал)
        # Самый надежный, но требующий участия способ - переслать сообщение, или просто айди.

        # Если мы не можем узнать ID, придется просить ID.
        username = target
        await message.answer("⚠️ К сожалению, добавление по @username работает ненадежно (из-за ограничений Telegram Bots API).\n"
                             "Пожалуйста, укажите **ID пользователя**.\n"
                             "Узнать ID можно @userinfobot")
        return
    else:
        await message.answer("Некорректный формат. Используйте числовой ID.")
        return

    await database.add_admin(user_id, username)
    await message.answer(f"✅ Пользователь {user_id} добавлен в администраторы.")

@dp.message(Command("rem_admin"))
async def cmd_rem_admin(message: Message):
    if not await is_user_admin(message.from_user.id):
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("Использование: /rem_admin <id>")
        return

    if not args[1].isdigit():
        await message.answer("Пожалуйста, укажите числовой ID для удаления.")
        return

    target_id = int(args[1])

    # Нельзя удалить супер-админа из ENV
    if target_id in SUPER_ADMIN_IDS:
        await message.answer("❌ Нельзя удалить супер-админа (прописан в .env).")
        return

    await database.remove_admin(target_id)
    await message.answer(f"🗑 Пользователь {target_id} удален из администраторов.")

@dp.message(Command("list_admins"))
async def cmd_list_admins(message: Message):
    if not await is_user_admin(message.from_user.id):
        return

    admins = await database.get_admins()
    text = "📋 **Список администраторов:**\n"

    # Сначала супер-админы
    for said in SUPER_ADMIN_IDS:
        text += f"👑 `{said}` (Super)\n"

    for uid, uname in admins:
        if uid not in SUPER_ADMIN_IDS:
            name_part = f" (@{uname})" if uname else ""
            text += f"👤 `{uid}`{name_part}\n"

    await message.answer(text, parse_mode="Markdown")

@dp.message(Command("add_chat"))
async def cmd_add_chat(message: Message):
    if not await is_user_admin(message.from_user.id):
        return

    args = message.text.split()
    if len(args) > 1:
        try:
            chat_id = int(args[1])
            try:
                chat = await bot.get_chat(chat_id)
                title = chat.title or "Unknown"
            except:
                title = "Unknown (Manual ID)"
        except ValueError:
            await message.answer("Некорректный ID чата.")
            return
    else:
        # Добавляем текущий чат
        chat_id = message.chat.id
        title = message.chat.title or "Unknown"

    await database.add_chat(chat_id, title)
    await message.answer(f"Чат '{title}' (ID: {chat_id}) добавлен в список обязательных подписок.")

@dp.message(Command("rem_chat"))
async def cmd_remove_chat(message: Message):
    if not await is_user_admin(message.from_user.id):
        return

    args = message.text.split()
    if len(args) > 1:
        try:
            chat_id = int(args[1])
        except ValueError:
            await message.answer("Некорректный ID чата.")
            return
    else:
        chat_id = message.chat.id

    await database.remove_chat(chat_id)
    await message.answer(f"Чат (ID: {chat_id}) удален из списка обязательных подписок.")

@dp.message(Command("list_chats"))
async def cmd_list_chats(message: Message):
    if not await is_user_admin(message.from_user.id):
        return

    chats = await database.get_all_chats()
    if not chats:
        await message.answer("Список отслеживаемых чатов пуст.")
        return

    text = "Список чатов для подписки:\n"
    for chat_id, title in chats:
        text += f"- {title} (`{chat_id}`)\n"

    await message.answer(text, parse_mode="Markdown")

# --- Проверка подписки ---

async def check_subscription(user_id: int) -> bool:
    chats = await database.get_all_chats()

    for chat_id, _ in chats:
        try:
            member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)

            # Если статус один из: left, kicked (banned) - значит не подписан
            if member.status in [ChatMemberStatus.LEFT, ChatMemberStatus.KICKED]:
                return False

            # Если restricted, проверяем поле is_member (в aiogram 3.x оно доступно в ChatMemberRestricted)
            if member.status == ChatMemberStatus.RESTRICTED:
                if not getattr(member, "is_member", True):
                    return False

        except Exception as e:
            logging.warning(f"Ошибка проверки подписки user={user_id} chat={chat_id}: {e}")
            # Если проверка не удалась (например, бот удален из того чата),
            # мы не можем утверждать, что пользователь НЕ подписан.
            # Чтобы не блокировать общение из-за ошибки бота, пропускаем (считаем "ок" для этого чата).
            # Хотя в строгом режиме можно было бы возвращать False.
            continue

    return True

@dp.message()
async def check_user_message(message: Message):
    # Игнорируем личные сообщения, или сообщения от самих админов/бота
    if message.chat.type == "private":
        return

    if message.from_user.is_bot:
        return

    if await is_user_admin(message.from_user.id):
        return

    # Проверяем, находится ли текущий чат в списке мониторимых?
    # По ТЗ: "Бот будет находиться во всех чатах и каналах папки".
    # Логично проверять подписку везде, где бот есть.
    # Но если мы перехватываем все сообщения, это может быть накладно.
    # Предполагаем, что бот работает только там, где его добавили.

    is_subscribed = await check_subscription(message.from_user.id)

    if not is_subscribed:
        try:
            await message.delete()
        except Exception as e:
            logging.warning(f"Не удалось удалить сообщение: {e}")

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Подписаться на папку", url=FOLDER_LINK)]
        ])

        sent_msg = await message.answer(
            f"Привет, {message.from_user.first_name}! \n"
            "Чтобы писать в этом чате, нужно подписаться на нашу папку с каналами и чатами.",
            reply_markup=keyboard
        )

        # Удаляем предупреждение через 15 секунд, чтобы не спамить
        await asyncio.sleep(15)
        try:
            await sent_msg.delete()
        except:
            pass

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
