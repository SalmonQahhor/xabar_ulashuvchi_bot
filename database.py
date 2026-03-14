import mysql.connector
import logging
from config import DB_CONFIG

class DB:
    def __init__(self):
        self.conn = None
        self.cursor = None
        self.connect()

    def connect(self):
        """Baza bilan ulanishni o'rnatish"""
        try:
            if self.conn:
                self.conn.close()
            self.conn = mysql.connector.connect(**DB_CONFIG)
            self.cursor = self.conn.cursor(dictionary=True, buffered=True)
            logging.info("✅ MySQL bazasiga muvaffaqiyatli ulandi.")
            self._create_tables() # Jadvallar mavjudligini tekshirish
        except mysql.connector.Error as err:
            logging.error(f"❌ MySQL ulanish xatosi: {err}")
            raise err

    def _check_conn(self):
        """Ulanish borligini tekshirish, bo'lmasa qayta ulanish"""
        try:
            self.conn.ping(reconnect=True, attempts=3, delay=1)
        except:
            self.connect()


def _create_tables(self):
        """Jadvallar va ustunlar borligini tekshirish"""
        self._check_conn()
        # 1. Jadvalni yaratish (agar yo'q bo'lsa)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                message_id INT,
                from_chat_id BIGINT,
                is_active BOOLEAN DEFAULT TRUE
            )
        """)
        
        # 2. session_str ustuni borligini tekshirish va qo'shish
        try:
            self.cursor.execute("SELECT session_str FROM users LIMIT 1")
        except mysql.connector.Error as err:
            if err.errno == 1054:  # Unknown column xatosi
                logging.info("Adding 'session_str' column to 'users' table...")
                self.cursor.execute("ALTER TABLE users ADD COLUMN session_str TEXT")
        
        # 3. user_groups jadvali
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_groups (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id BIGINT,
                chat_id BIGINT,
                chat_title VARCHAR(255),
                is_enabled BOOLEAN DEFAULT FALSE,
                UNIQUE KEY user_chat (user_id, chat_id)
            )
        """)
        self.conn.commit()


    # --- SIZDA YO'Q BO'LGAN VA KERAKLI FUNKSIYALAR ---

    def save_user_session(self, user_id, session_str):
        """Sessiya satrini bazaga saqlash (Skrinshotdagi xatoni tuzatadi)"""
        self._check_conn()
        sql = """
            INSERT INTO users (user_id, session_str) 
            VALUES (%s, %s) 
            ON DUPLICATE KEY UPDATE session_str = %s
        """
        self.cursor.execute(sql, (user_id, session_str, session_str))
        self.conn.commit()

    def add_group(self, user_id, chat_id, title):
        """Bitta guruhni bazaga qo'shish (main.py dagi process_code uchun)"""
        self._check_conn()
        sql = """
            INSERT IGNORE INTO user_groups (user_id, chat_id, chat_title) 
            VALUES (%s, %s, %s)
        """
        self.cursor.execute(sql, (user_id, chat_id, title))
        self.conn.commit()

    def get_user_groups(self, user_id):
        """Foydalanuvchining barcha guruhlarini olish"""
        self._check_conn()
        self.cursor.execute("SELECT chat_id, chat_title, is_enabled FROM user_groups WHERE user_id = %s", (user_id,))
        rows = self.cursor.fetchall()
        return [(r['chat_id'], r['chat_title'], r['is_enabled']) for r in rows]

    def toggle_group_status(self, user_id, chat_id):
        """Guruh holatini (yoqilgan/o'chirilgan) o'zgartirish"""
        self._check_conn()
        sql = "UPDATE user_groups SET is_enabled = NOT is_enabled WHERE user_id = %s AND chat_id = %s"
        self.cursor.execute(sql, (user_id, chat_id))
        self.conn.commit()

    def select_all_groups(self, user_id, status):
        """Hamma guruhlarni baravariga yoqish yoki o'chirish"""
        self._check_conn()
        sql = "UPDATE user_groups SET is_enabled = %s WHERE user_id = %s"
        self.cursor.execute(sql, (status, user_id))
        self.conn.commit()

    # --- ESKI FUNKSIYALAR (SAQLAB QOLINDI) ---

    def get_user(self, user_id):
        self._check_conn()
        try:
            self.cursor.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
            return self.cursor.fetchone()
        except Exception as e:
            logging.error(f"get_user xatosi: {e}")
            return None

    def set_user_message(self, user_id, message_id, chat_id):
        self._check_conn()
        self.cursor.execute("UPDATE users SET message_id = %s, from_chat_id = %s WHERE user_id = %s", 
                            (message_id, chat_id, user_id))
        self.conn.commit()

    def get_enabled_groups(self, user_id):
        self._check_conn()
        self.cursor.execute("SELECT chat_id FROM user_groups WHERE user_id = %s AND is_enabled = TRUE", (user_id,))
        return [row['chat_id'] for row in self.cursor.fetchall()]
