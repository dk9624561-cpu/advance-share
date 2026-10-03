import sqlite3
import os
import logging
import datetime
import config
from config import DATABASE_PATH

logger = logging.getLogger(__name__)

def get_db_connection():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row  # Enable column access by name
    return conn

def init_db():
    logger.info("Initializing database...")
    with get_db_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS lectures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_code TEXT UNIQUE NOT NULL,
                source_chat_id INTEGER NOT NULL,
                source_message_id INTEGER NOT NULL,
                title TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS channel_mappings (
                source_channel_id INTEGER PRIMARY KEY,
                destination_channel_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS downloads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                file_code TEXT NOT NULL,
                downloaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                expires_at TIMESTAMP NOT NULL,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()
    logger.info("Database initialized successfully.")

def add_lecture(file_code: str, source_chat_id: int, source_message_id: int, title: str) -> bool:
    try:
        with get_db_connection() as conn:
            conn.execute(
                "INSERT INTO lectures (file_code, source_chat_id, source_message_id, title) VALUES (?, ?, ?, ?)",
                (file_code, source_chat_id, source_message_id, title)
            )
            conn.commit()
        return True
    except sqlite3.IntegrityError as e:
        logger.error(f"Integrity error adding lecture with code {file_code}: {e}")
        return False
    except Exception as e:
        logger.error(f"Error adding lecture: {e}")
        return False

def get_lecture(file_code: str):
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT source_chat_id, source_message_id, title FROM lectures WHERE file_code = ?",
                (file_code,)
            )
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
    except Exception as e:
        logger.error(f"Error fetching lecture with code {file_code}: {e}")
        return None

def set_setting(key: str, value: str) -> None:
    try:
        with get_db_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (key, str(value))
            )
            conn.commit()
    except Exception as e:
        logger.error(f"Error setting setting {key}: {e}")

def get_setting(key: str, default=None) -> str:
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = cursor.fetchone()
            if row:
                return row["value"]
            return default
    except Exception as e:
        logger.error(f"Error getting setting {key}: {e}")
        return default

def add_mapping(source_id: int, dest_id: int) -> bool:
    try:
        with get_db_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO channel_mappings (source_channel_id, destination_channel_id) VALUES (?, ?)",
                (source_id, dest_id)
            )
            conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error adding mapping for source {source_id}: {e}")
        return False

def remove_mapping(source_id: int) -> bool:
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM channel_mappings WHERE source_channel_id = ?", (source_id,))
            conn.commit()
            return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error removing mapping for source {source_id}: {e}")
        return False

def get_mapping(source_id: int) -> int:
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT destination_channel_id FROM channel_mappings WHERE source_channel_id = ?", (source_id,))
            row = cursor.fetchone()
            if row:
                return int(row["destination_channel_id"])
            return None
    except Exception as e:
        logger.error(f"Error getting mapping for source {source_id}: {e}")
        return None

def list_mappings() -> list:
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT source_channel_id, destination_channel_id, created_at FROM channel_mappings ORDER BY created_at DESC")
            return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Error listing channel mappings: {e}")
        return []

def add_download(user_id: int, file_code: str) -> None:
    try:
        with get_db_connection() as conn:
            conn.execute(
                "INSERT INTO downloads (user_id, file_code) VALUES (?, ?)",
                (user_id, file_code)
            )
            conn.commit()
    except Exception as e:
        logger.error(f"Error adding download log for user {user_id}: {e}")

def get_last_ist_2am_cutoff_utc() -> str:
    """Calculates the UTC timestamp string for the most recent 2:00 AM IST (India Standard Time).
    This ensures all users' daily download counts reset at 2:00 AM IST every night regardless of server timezone (e.g., Hugging Face)."""
    utc_now = datetime.datetime.now(datetime.timezone.utc)
    ist_tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    ist_now = utc_now.astimezone(ist_tz)
    
    if ist_now.hour >= 2:
        cutoff_ist = ist_now.replace(hour=2, minute=0, second=0, microsecond=0)
    else:
        cutoff_ist = (ist_now - datetime.timedelta(days=1)).replace(hour=2, minute=0, second=0, microsecond=0)
        
    cutoff_utc = cutoff_ist.astimezone(datetime.timezone.utc)
    return cutoff_utc.strftime("%Y-%m-%d %H:%M:%S")

def get_user_daily_download_count(user_id: int) -> int:
    try:
        cutoff_utc_str = get_last_ist_2am_cutoff_utc()
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # Count downloads recorded since the last 2:00 AM IST reset
            cursor.execute(
                "SELECT COUNT(*) as count FROM downloads WHERE user_id = ? AND downloaded_at >= ?",
                (user_id, cutoff_utc_str)
            )
            row = cursor.fetchone()
            if row:
                return int(row["count"])
            return 0
    except Exception as e:
        logger.error(f"Error counting daily downloads for user {user_id}: {e}")
        return 0

def reset_user_limit(user_id: int) -> bool:
    """Deletes download history for a specific user to reset their daily limit."""
    try:
        with get_db_connection() as conn:
            conn.execute("DELETE FROM downloads WHERE user_id = ?", (user_id,))
            conn.commit()
            return True
    except Exception as e:
        logger.error(f"Error resetting limit for user {user_id}: {e}")
        return False

def reset_all_limits() -> bool:
    """Deletes all download records from the database to reset limits for all users."""
    try:
        with get_db_connection() as conn:
            conn.execute("DELETE FROM downloads")
            conn.commit()
            return True
    except Exception as e:
        logger.error(f"Error resetting all user limits: {e}")
        return False

def is_admin(user_id: int) -> bool:
    try:
        # 1. Check config file
        if config.ADMIN_USER_ID and user_id == config.ADMIN_USER_ID:
            return True
            
        # 2. Check dynamic creator in database settings
        creator_val = get_setting("admin_user_id")
        if creator_val and str(user_id) == creator_val:
            return True
            
        # 3. Check admins table
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,))
            if cursor.fetchone():
                return True
        return False
    except Exception as e:
        logger.error(f"Error checking admin status for user {user_id}: {e}")
        return False

def add_admin(user_id: int) -> bool:
    try:
        with get_db_connection() as conn:
            conn.execute("INSERT OR REPLACE INTO admins (user_id) VALUES (?)", (user_id,))
            conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error adding admin {user_id}: {e}")
        return False

def remove_admin(user_id: int) -> bool:
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
            conn.commit()
            return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error removing admin {user_id}: {e}")
        return False

def list_admins() -> list:
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id, added_at FROM admins ORDER BY added_at DESC")
            return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Error listing admins: {e}")
        return []

def add_user(user_id: int, days: int) -> bool:
    try:
        expires_dt = datetime.datetime.utcnow() + datetime.timedelta(days=days)
        expires_str = expires_dt.strftime('%Y-%m-%d %H:%M:%S')
        with get_db_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO users (user_id, expires_at) VALUES (?, ?)",
                (user_id, expires_str)
            )
            conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error adding user {user_id} for {days} days: {e}")
        return False

def remove_user(user_id: int) -> bool:
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
            conn.commit()
            return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error removing user {user_id}: {e}")
        return False

def is_user_authorized(user_id: int) -> bool:
    try:
        if is_admin(user_id):
            return True
            
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM users WHERE user_id = ? AND expires_at > datetime('now')",
                (user_id,)
            )
            if cursor.fetchone():
                return True
        return False
    except Exception as e:
        logger.error(f"Error checking user authorization for {user_id}: {e}")
        return False

def list_users() -> list:
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id, expires_at, added_at FROM users ORDER BY expires_at ASC")
            rows = cursor.fetchall()
            
            users_list = []
            now = datetime.datetime.utcnow()
            for r in rows:
                expires_dt = datetime.datetime.strptime(r["expires_at"], '%Y-%m-%d %H:%M:%S')
                days_left = (expires_dt - now).days
                
                user_dict = dict(r)
                user_dict["days_left"] = max(0, days_left)
                user_dict["is_active"] = expires_dt > now
                users_list.append(user_dict)
            return users_list
    except Exception as e:
        logger.error(f"Error listing users: {e}")
        return []
