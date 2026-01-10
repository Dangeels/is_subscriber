import aiosqlite

DB_NAME = "bot.db"

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS monitored_chats (
                chat_id INTEGER PRIMARY KEY,
                title TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY,
                username TEXT
            )
        """)
        await db.commit()

async def add_chat(chat_id: int, title: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO monitored_chats (chat_id, title) VALUES (?, ?)", (chat_id, title))
        await db.commit()

async def remove_chat(chat_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM monitored_chats WHERE chat_id = ?", (chat_id,))
        await db.commit()

async def get_all_chats():
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT chat_id, title FROM monitored_chats") as cursor:
            return await cursor.fetchall()

async def add_admin(user_id: int, username: str = None):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO admins (user_id, username) VALUES (?, ?)", (user_id, username))
        await db.commit()

async def remove_admin(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
        await db.commit()

async def get_admins():
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_id, username FROM admins") as cursor:
            return await cursor.fetchall()

async def is_admin(user_id: int) -> bool:
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchone() is not None
