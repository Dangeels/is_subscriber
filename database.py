import aiosqlite

DB_NAME = "bot.db"

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS monitored_chats (
                chat_id     INTEGER PRIMARY KEY,
                title       TEXT,
                username    TEXT,
                invite_link TEXT
            )
        """)
        # Миграции: добавляем колонки если их нет
        async with db.execute("PRAGMA table_info(monitored_chats)") as cursor:
            columns = [row[1] for row in await cursor.fetchall()]
        if "username" not in columns:
            await db.execute("ALTER TABLE monitored_chats ADD COLUMN username TEXT")
        if "invite_link" not in columns:
            await db.execute("ALTER TABLE monitored_chats ADD COLUMN invite_link TEXT")

        # Проверяем схему таблицы admins — если создана по старой схеме (user_id PRIMARY KEY),
        # пересоздаём с новой схемой (id AUTOINCREMENT, user_id UNIQUE NULLABLE)
        async with db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='admins'"
        ) as cursor:
            row = await cursor.fetchone()

        needs_migration = False
        if row is None:
            needs_migration = False
        elif "AUTOINCREMENT" not in (row[0] or ""):
            needs_migration = True

        if needs_migration:
            async with db.execute("SELECT user_id, username FROM admins") as cursor:
                old_data = await cursor.fetchall()
            await db.execute("DROP TABLE admins")
        else:
            old_data = []

        await db.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id  INTEGER UNIQUE,
                username TEXT    UNIQUE COLLATE NOCASE
            )
        """)

        for uid, uname in old_data:
            await db.execute(
                "INSERT OR IGNORE INTO admins (user_id, username) VALUES (?, ?)",
                (uid, uname)
            )

        await db.commit()

async def add_chat(chat_id: int, title: str, username: str = None):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT INTO monitored_chats (chat_id, title, username) VALUES (?, ?, ?) "
            "ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title, username=excluded.username",
            (chat_id, title, username)
        )
        await db.commit()

async def set_invite_link(chat_id: int, invite_link: str):
    """Сохраняет invite_link для чата."""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "UPDATE monitored_chats SET invite_link = ? WHERE chat_id = ?",
            (invite_link, chat_id)
        )
        await db.commit()

async def remove_chat(chat_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM monitored_chats WHERE chat_id = ?", (chat_id,))
        await db.commit()

async def get_all_chats():
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT chat_id, title, username, invite_link FROM monitored_chats") as cursor:
            return await cursor.fetchall()

async def add_admin(user_id: int, username: str = None):
    """Добавляет/обновляет администратора по user_id. Если запись с таким username уже есть — привязывает user_id к ней."""
    clean_username = username.lower() if username else None
    async with aiosqlite.connect(DB_NAME) as db:
        # Если есть запись с таким username (добавленная ранее без user_id) — обновляем её
        if clean_username:
            await db.execute(
                "UPDATE admins SET user_id = ? WHERE lower(username) = ? AND user_id IS NULL",
                (user_id, clean_username)
            )
        # Upsert по user_id: если такой user_id уже есть — обновляем username
        await db.execute(
            "INSERT INTO admins (user_id, username) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET username = excluded.username",
            (user_id, clean_username)
        )
        await db.commit()

async def add_admin_by_username(username: str):
    """Добавляет администратора только по username (user_id пока неизвестен)."""
    clean = username.lstrip("@").lower()
    async with aiosqlite.connect(DB_NAME) as db:
        # Если уже есть запись с таким username — ничего не делаем
        await db.execute(
            "INSERT INTO admins (user_id, username) VALUES (NULL, ?) "
            "ON CONFLICT(username) DO NOTHING",
            (clean,)
        )
        await db.commit()

async def remove_admin(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
        await db.commit()

async def remove_admin_by_username(username: str):
    """Удаляет администратора по username. Возвращает удалённый user_id или None."""
    clean = username.lstrip("@").lower()
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT user_id FROM admins WHERE lower(username) = ?", (clean,)
        ) as cursor:
            row = await cursor.fetchone()
        await db.execute("DELETE FROM admins WHERE lower(username) = ?", (clean,))
        await db.commit()
        return row[0] if row else None

async def get_admin_by_username(username: str):
    """Возвращает (user_id, username) по username или None."""
    clean = username.lstrip("@").lower()
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT user_id, username FROM admins WHERE lower(username) = ?", (clean,)
        ) as cursor:
            return await cursor.fetchone()

async def get_admins():
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_id, username FROM admins") as cursor:
            return await cursor.fetchall()

async def is_admin(user_id: int) -> bool:
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchone() is not None

async def is_admin_by_username(username: str) -> bool:
    """Проверяет, является ли пользователь с данным username администратором."""
    clean = username.lstrip("@").lower()
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT 1 FROM admins WHERE lower(username) = ?", (clean,)
        ) as cursor:
            return await cursor.fetchone() is not None
