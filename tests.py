import pytest
import pytest_asyncio
import sqlite3
import os
import aiosqlite
from unittest.mock import AsyncMock, MagicMock, patch

# Импортируем модули для тестирования
import database
# Для тестирования main нам придется немного замокать, так как там создается bot и dp
# Мы будем импортировать отдельные функции, если это возможно, или мокать модули

# --- Тесты для database.py ---

@pytest_asyncio.fixture
async def test_db():
    """Создает временную БД для тестов."""
    test_db_name = "test_bot.db"

    # Подменяем имя БД в модуле database
    original_db_name = database.DB_NAME
    database.DB_NAME = test_db_name

    # Инициализируем
    await database.init_db()

    yield

    # Очистка
    if os.path.exists(test_db_name):
        os.remove(test_db_name)
    database.DB_NAME = original_db_name

@pytest.mark.asyncio
async def test_database_chats(test_db):
    # Проверка добавления чата
    await database.add_chat(12345, "Test Chat")
    chats = await database.get_all_chats()
    assert len(chats) == 1
    assert chats[0] == (12345, "Test Chat")

    # Проверка удаления чата
    await database.remove_chat(12345)
    chats = await database.get_all_chats()
    assert len(chats) == 0

@pytest.mark.asyncio
async def test_database_admins(test_db):
    # Проверка добавления админа
    await database.add_admin(999, "admin_user")
    admins = await database.get_admins()
    assert len(admins) == 1
    assert admins[0] == (999, "admin_user")

    # Проверка is_admin
    assert await database.is_admin(999) is True
    assert await database.is_admin(888) is False

    # Проверка удаления админа
    await database.remove_admin(999)
    assert await database.is_admin(999) is False

# --- Тесты для main.py (логика) ---

# Мокаем main.py, чтобы не загружать переменные окружения и не создавать реального бота
with patch("main.Bot"), patch("main.Dispatcher"):
    import main as bot_main

@pytest.mark.asyncio
async def test_check_subscription_success():
    """Пользователь подписан на все чаты."""
    user_id = 100
    chats = [(1, "Chat 1"), (2, "Chat 2")]

    # Мокаем БД
    with patch("database.get_all_chats", return_value=chats):
        # Мокаем bot.get_chat_member
        bot_mock = AsyncMock()
        bot_main.bot = bot_mock

        # Настраиваем mock так, чтобы он возвращал статус MEMBER
        member_mock = MagicMock()
        member_mock.status = "member"
        bot_mock.get_chat_member.return_value = member_mock

        result = await bot_main.check_subscription(user_id)
        assert result is True

        # Проверяем, что бот проверил оба чата
        assert bot_mock.get_chat_member.call_count == 2

@pytest.mark.asyncio
async def test_check_subscription_failure():
    """Пользователь не подписан на один из чатов."""
    user_id = 100
    chats = [(1, "Chat 1")]

    with patch("database.get_all_chats", return_value=chats):
        bot_mock = AsyncMock()
        bot_main.bot = bot_mock

        # Возвращаем статус LEFT
        member_mock = MagicMock()
        member_mock.status = "left"
        bot_mock.get_chat_member.return_value = member_mock

        result = await bot_main.check_subscription(user_id)
        assert result is False

@pytest.mark.asyncio
async def test_is_user_admin():
    """Проверка логики определения админа (ENV + DB)."""
    # Мокаем SUPER_ADMIN_IDS в main
    bot_main.SUPER_ADMIN_IDS = [1, 2]

    # 1. Супер-админ
    assert await bot_main.is_user_admin(1) is True

    # 2. Обычный админ из БД
    with patch("database.is_admin", return_value=True):
        assert await bot_main.is_user_admin(3) is True

    # 3. Никто
    with patch("database.is_admin", return_value=False):
        assert await bot_main.is_user_admin(4) is False

