import os
from dotenv import load_dotenv

load_dotenv()


API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))


db_host = os.getenv("MYSQLHOST")
if not db_host:
    print("⚠️ DIQQAT: MYSQLHOST topilmadi! Railway Variables-ni tekshiring.")

DB_CONFIG = {
    "host": db_host,
    "user": os.getenv("MYSQLUSER"),
    "password": os.getenv("MYSQLPASSWORD"),
    "database": os.getenv("MYSQLDATABASE"),
    "port": int(os.getenv("MYSQLPORT", 3306))
}
