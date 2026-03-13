import mysql.connector
from config import DB_CONFIG

class DB:
    def __init__(self):
        self.conn = mysql.connector.connect(**DB_CONFIG)
        self.cursor = self.conn.cursor(dictionary=True, buffered=True)

    def get_user(self, user_id):
        self.cursor.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
        return self.cursor.fetchone()

    def add_allowed_user(self, user_id):
        self.cursor.execute("INSERT IGNORE INTO users (user_id, is_active) VALUES (%s, TRUE)", (user_id,))
        self.conn.commit()

    def set_user_message(self, user_id, message_id, chat_id):
        self.cursor.execute("UPDATE users SET message_id = %s, from_chat_id = %s WHERE user_id = %s", 
                           (message_id, chat_id, user_id))
        self.conn.commit()

    def get_enabled_groups(self, user_id):
        self.cursor.execute("SELECT chat_id FROM user_groups WHERE user_id = %s AND is_enabled = TRUE", (user_id,))
        return [row['chat_id'] for row in self.cursor.fetchall()]

    def sync_groups(self, user_id, groups):
        for chat_id, title in groups:
            self.cursor.execute("""
                INSERT IGNORE INTO user_groups (user_id, chat_id, chat_title) 
                VALUES (%s, %s, %s)""", (user_id, chat_id, title))
        self.conn.commit()