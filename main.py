import logging
import asyncio
import os
from typing import Callable, Dict, Any, Awaitable
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, BaseMiddleware
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, TelegramObject
from aiogram.enums import ChatMemberStatus, ChatType

import database

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPER_ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
FOLDER_LINK = os.getenv("FOLDER_LINK", "")

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


@dp.startup()
async def on_startup():
    await database.init_db()
    for admin_id in SUPER_ADMIN_IDS:
        if not await database.is_admin(admin_id):
            await database.add_admin(admin_id, None)
    logging.info("База данных инициализирована.")


async def is_user_admin(user_id: int, username: str = None) -> bool:
    if user_id in SUPER_ADMIN_IDS:
        return True
    if await database.is_admin(user_id):
        return True
    if username:
        if await database.is_admin_by_username(username):
            await database.add_admin(user_id, username)
            return True
    return False


async def check_subscription(user_id: int) -> bool:
    chats = await database.get_all_chats()
    for chat_id, _, __, ___ in chats:
        try:
            member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
            if member.status in [ChatMemberStatus.LEFT, ChatMemberStatus.KICKED]:
                return False
            if member.status == ChatMemberStatus.RESTRICTED:
                if not getattr(member, "is_member", True):
                    return False
        except Exception as e:
            logging.warning(f"Ошибка проверки подписки user={user_id} chat={chat_id}: {e}")
            continue
    return True


# --- Middleware: перехватывает ВСЕ сообщения в группах до любого хендлера ---

class SubscriptionMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message):
            return await handler(event, data)

        message: Message = event

        # Только группы/супергруппы
        if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
            return await handler(event, data)

        if not message.from_user or message.from_user.is_bot:
            return await handler(event, data)

        # Администраторы бота пропускаются
        if await is_user_admin(message.from_user.id, message.from_user.username):
            return await handler(event, data)

        # Проверяем подписку
        if not await check_subscription(message.from_user.id):
            try:
                await message.delete()
            except Exception as e:
                logging.warning(f"Не удалось удалить сообщение: {e}")

            bot_info = await bot.get_me()
            sent_msg = await message.answer(
                f"⚠️ {message.from_user.first_name}, ваше сообщение удалено.\n\n"
                f"Чтобы писать в этом чате, необходимо подписаться на все наши каналы и чаты.\n"
                f"Напишите боту @{bot_info.username} — он пришлёт список каналов для подписки."
            )

            await asyncio.sleep(5)
            try:
                await sent_msg.delete()
            except Exception:
                pass

            # Прерываем цепочку — хендлер не вызывается
            return

        return await handler(event, data)


dp.message.middleware(SubscriptionMiddleware())
dp.edited_message.middleware(SubscriptionMiddleware())


async def get_or_create_invite_link(chat_id: int, stored_link: str | None) -> str | None:
    if stored_link:
        return stored_link
    try:
        link_obj = await bot.create_chat_invite_link(chat_id)
        await database.set_invite_link(chat_id, link_obj.invite_link)
        return link_obj.invite_link
    except Exception as e:
        logging.warning(f"Не удалось создать invite link для chat_id={chat_id}: {e}")
        return None


# --- /start — только в личке, доступна всем ---

@dp.message(Command("start"))
async def cmd_start(message: Message):
    if message.chat.type != ChatType.PRIVATE:
        return

    chats = await database.get_all_chats()

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📁 Подписаться на папку", url=FOLDER_LINK)]
    ]) if FOLDER_LINK else None

    if chats:
        chat_lines = []
        for chat_id, title, username, invite_link in chats:
            link = await get_or_create_invite_link(chat_id, invite_link)
            if link:
                chat_lines.append(f'  • <a href="{link}">{title}</a>')
            else:
                chat_lines.append(f"  • {title}")
        chats_text = "\n".join(chat_lines)
        text = (
            f"👋 Привет, {message.from_user.first_name}!\n\n"
            "Для того чтобы писать в наших чатах, необходимо быть подписанным на следующие каналы и чаты:\n\n"
            f"{chats_text}\n\n"
            "📌 Подпишитесь на все каналы и чаты из списка, после чего вы сможете свободно общаться."
        )
    else:
        text = (
            f"👋 Привет, {message.from_user.first_name}!\n\n"
            "Для того чтобы писать в наших чатах, необходимо подписаться на наши каналы и чаты.\n\n"
            "📌 Нажмите кнопку ниже, чтобы подписаться."
        )

    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


# --- Админские команды — только в личке ---

@dp.message(Command("help"))
async def cmd_help(message: Message):
    if message.chat.type != ChatType.PRIVATE:
        return
    if not await is_user_admin(message.from_user.id, message.from_user.username):
        return

    help_text = (
        "🤖 <b>Инструкция по использованию бота</b>\n\n"

        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "📌 <b>Как работает бот</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Бот проверяет каждое сообщение пользователя в группе. "
        "Если пользователь не подписан хотя бы на один чат из списка обязательных — "
        "его сообщение автоматически удаляется, а ему отправляется уведомление. "
        "Уведомление само удаляется через 5 секунд.\n\n"

        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🚀 <b>Первоначальная настройка (шаг за шагом)</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>Шаг 1.</b> Добавьте бота в <b>каждую группу</b>, где нужно проверять подписку, "
        "и назначьте его <b>администратором</b> с правом удалять сообщения.\n\n"
        "<b>Шаг 2.</b> Добавьте бота в каждый <b>обязательный канал/чат</b> (те, на которые должны быть подписаны пользователи), "
        "также с правами администратора — чтобы он мог проверять участников и создавать ссылки-приглашения.\n\n"
        "<b>Шаг 3.</b> В личке с ботом добавьте каждый обязательный чат по ID:\n"
        "<code>/add_chat -100XXXXXXXXX</code>\n\n"
        "<b>Шаг 4.</b> Убедитесь, что список настроен верно: <code>/list_chats</code>\n\n"
        "<b>Шаг 5.</b> Как узнать ID чата:\n"
        "  — Перешлите любое сообщение из нужного чата боту @userinfobot — он покажет ID.\n"
        "  — Или откройте Telegram Web, зайдите в чат — в адресной строке будет что-то вроде "
        "<code>-1001234567890</code>.\n"
        "  — ID группы/канала всегда начинается с <code>-100</code>.\n\n"

        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🛠 <b>Команды управления чатами</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "/add_chat <code>-100XXXXXXXXX</code> — добавить чат по его ID.\n"
        "/rem_chat <code>-100XXXXXXXXX</code> — удалить чат по ID.\n"
        "/list_chats — показать все чаты в списке обязательных подписок.\n\n"

        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "👥 <b>Команды управления администраторами</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "/add_admin <code>@username</code> — добавить администратора по Telegram-нику.\n"
        "/add_admin <code>123456789</code> — добавить администратора по числовому ID.\n"
        "  <i>Узнать ID пользователя можно через бот @userinfobot.</i>\n"
        "/rem_admin <code>@username</code> — удалить администратора по Telegram-нику.\n"
        "/rem_admin <code>123456789</code> — удалить администратора по ID.\n"
        "/list_admins — показать список всех администраторов бота.\n\n"

        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚠️ <b>Важные замечания</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "• Все команды работают только в <b>личных сообщениях</b> с ботом.\n"
        "• Бот должен быть <b>администратором</b> во всех чатах из списка.\n"
        "• Супер-администраторы указываются в <code>.env</code> (переменная <code>ADMIN_IDS</code>) — "
        "их нельзя удалить через команды бота.\n"
        "• Сообщения самих администраторов бот <b>не проверяет</b> и не удаляет.\n\n"

        "/help — показать эту инструкцию."
    )
    await message.answer(help_text, parse_mode="HTML")


@dp.message(Command("add_admin"))
async def cmd_add_admin(message: Message):
    if message.chat.type != ChatType.PRIVATE:
        return
    if not await is_user_admin(message.from_user.id, message.from_user.username):
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("Использование: /add_admin <id или @username>")
        return

    target = args[1]

    if target.lstrip("-").isdigit():
        user_id = int(target)
        await database.add_admin(user_id, username=None)
        await message.answer(f"✅ Пользователь <code>{user_id}</code> добавлен в администраторы.", parse_mode="HTML")
    elif target.startswith("@"):
        clean_username = target.lstrip("@")
        await database.add_admin_by_username(clean_username)
        await message.answer(
            f"✅ Администратор @{clean_username} добавлен в базу данных.\n"
            f"<i>ID будет автоматически привязан, когда пользователь напишет боту.</i>",
            parse_mode="HTML"
        )
    else:
        await message.answer("Некорректный формат. Используйте числовой ID или @username.")


@dp.message(Command("rem_admin"))
async def cmd_rem_admin(message: Message):
    if message.chat.type != ChatType.PRIVATE:
        return
    if not await is_user_admin(message.from_user.id, message.from_user.username):
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("Использование: /rem_admin <id или @username>")
        return

    target = args[1]

    if target.lstrip("-").isdigit():
        target_id = int(target)
        if target_id in SUPER_ADMIN_IDS:
            await message.answer("❌ Нельзя удалить супер-админа (прописан в .env).")
            return
        await database.remove_admin(target_id)
        await message.answer(f"🗑 Пользователь <code>{target_id}</code> удалён из администраторов.", parse_mode="HTML")
    elif target.startswith("@"):
        row = await database.get_admin_by_username(target)
        if row and row[0] in SUPER_ADMIN_IDS:
            await message.answer("❌ Нельзя удалить супер-админа (прописан в .env).")
            return
        removed_id = await database.remove_admin_by_username(target)
        if removed_id:
            await message.answer(f"🗑 Администратор {target} (ID: <code>{removed_id}</code>) удалён.", parse_mode="HTML")
        else:
            await message.answer(f"⚠️ Администратор {target} не найден в базе данных.")
    else:
        await message.answer("Некорректный формат. Используйте числовой ID или @username.")


@dp.message(Command("list_admins"))
async def cmd_list_admins(message: Message):
    if message.chat.type != ChatType.PRIVATE:
        return
    if not await is_user_admin(message.from_user.id, message.from_user.username):
        return

    admins = await database.get_admins()
    lines = ["📋 <b>Список администраторов:</b>\n"]

    for said in SUPER_ADMIN_IDS:
        lines.append(f"👑 <code>{said}</code> (Super)")

    for uid, uname in admins:
        if uid in SUPER_ADMIN_IDS:
            continue
        if uid is None:
            lines.append(f"👤 @{uname} <i>(ID не привязан)</i>")
        else:
            name_part = f" (@{uname})" if uname else ""
            lines.append(f"👤 <code>{uid}</code>{name_part}")

    await message.answer("\n".join(lines), parse_mode="HTML")


@dp.message(Command("add_chat"))
async def cmd_add_chat(message: Message):
    if message.chat.type != ChatType.PRIVATE:
        return
    if not await is_user_admin(message.from_user.id, message.from_user.username):
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("Использование: /add_chat <id чата>\nПример: /add_chat -1001234567890")
        return

    try:
        chat_id = int(args[1])
    except ValueError:
        await message.answer("Некорректный ID чата. ID должен быть числом, например: -1001234567890")
        return

    try:
        chat = await bot.get_chat(chat_id)
        title = chat.title or "Unknown"
        username = chat.username
    except Exception:
        await message.answer(
            f"❌ Не удалось получить информацию о чате <code>{chat_id}</code>.\n"
            "Убедитесь, что бот добавлен в этот чат.",
            parse_mode="HTML"
        )
        return

    await database.add_chat(chat_id, title, username)
    await message.answer(
        f"✅ Чат <b>{title}</b> (ID: <code>{chat_id}</code>) добавлен в список обязательных подписок.",
        parse_mode="HTML"
    )


@dp.message(Command("rem_chat"))
async def cmd_remove_chat(message: Message):
    if message.chat.type != ChatType.PRIVATE:
        return
    if not await is_user_admin(message.from_user.id, message.from_user.username):
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("Использование: /rem_chat <id чата>\nПример: /rem_chat -1001234567890")
        return

    try:
        chat_id = int(args[1])
    except ValueError:
        await message.answer("Некорректный ID чата.")
        return

    await database.remove_chat(chat_id)
    await message.answer(
        f"🗑 Чат (ID: <code>{chat_id}</code>) удалён из списка обязательных подписок.",
        parse_mode="HTML"
    )


@dp.message(Command("list_chats"))
async def cmd_list_chats(message: Message):
    if message.chat.type != ChatType.PRIVATE:
        return
    if not await is_user_admin(message.from_user.id, message.from_user.username):
        return

    chats = await database.get_all_chats()
    if not chats:
        await message.answer("Список отслеживаемых чатов пуст.")
        return

    lines = ["📋 <b>Список чатов для обязательной подписки:</b>\n"]
    for chat_id, title, username, invite_link in chats:
        link = invite_link or (f"https://t.me/{username}" if username else None)
        title_part = f'<a href="{link}">{title}</a>' if link else title
        lines.append(f"• {title_part}\n  ID: <code>{chat_id}</code>")

    await message.answer("\n".join(lines), parse_mode="HTML")


@dp.message()
async def catch_all(message: Message):
    """Catch-all хендлер — нужен для того, чтобы SubscriptionMiddleware
    срабатывал на любые сообщения, не только на команды."""
    pass


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

