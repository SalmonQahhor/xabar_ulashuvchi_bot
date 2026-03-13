import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from pyrogram import Client, filters
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from database import DB
import config
from users import ALLOWED_USERS


# Loglarni sozlash
logging.basicConfig(level=logging.INFO)

bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher()
db = DB()
scheduler = AsyncIOScheduler()
active_userbots = {} # {user_id: Client}

class LoginSteps(StatesGroup):
    phone = State()
    code = State()

# --- XABAR YUBORISH FUNKSIYASI ---
async def send_advertisement(user_id):
    user = db.get_user(user_id)
    if not user or not user['bot_status'] or not user['message_id']:
        return

    # UserBot clientini olish
    client = active_userbots.get(user_id)
    if not client:
        client = Client(f"sessions/{user_id}", config.API_ID, config.API_HASH)
        await client.start()
        active_userbots[user_id] = client

    enabled_groups = db.get_enabled_groups(user_id)
    for chat_id in enabled_groups:
        try:
            await client.copy_message(
                chat_id=chat_id,
                from_chat_id=user['from_chat_id'],
                message_id=user['message_id']
            )
            await asyncio.sleep(3) # Telegram ban bermasligi uchun kichik pauza
        except Exception as e:
            logging.error(f"Xatolik yuborishda ({chat_id}): {e}")

# --- BOT INTERFEYSI ---

@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    user_id = message.from_user.id
    
    # Ruxsatni tekshirish
    if user_id not in ALLOWED_USERS:
        return await message.answer(
            f"❌ Kechirasiz, sizga ruxsat berilmagan.\nSizning ID: {user_id}"
        )
    
    # Agar ruxsat bo'lsa, menyuni ko'rsatish
    kb = InlineKeyboardBuilder()
    kb.button(text="📱 Akkauntni ulash", callback_data="connect")
    kb.button(text="🕒 Interval", callback_data="time_menu")
    kb.button(text="👥 Guruhlar", callback_data="groups_menu")
    kb.button(text="🚀 Start/Stop", callback_data="toggle_bot")
    kb.adjust(2)
    
    await message.answer("Xush kelibsiz! Bot boshqaruv paneli:", reply_markup=kb.as_markup())



# Interval tanlash
@dp.callback_query(F.data == "time_menu")
async def time_menu(call: types.CallbackQuery):
    kb = InlineKeyboardBuilder()
    for t in [5, 10, 15, 20, 30, 60]:
        kb.button(text=f"{t} min", callback_data=f"settime_{t}")
    kb.button(text="⬅️ Orqaga", callback_data="back_home")
    kb.adjust(3, 1)
    await call.message.edit_text("Xabar yuborish oralig'ini tanlang:", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("settime_"))
async def set_time(call: types.CallbackQuery):
    t = int(call.data.split("_")[1])
    db.update_user(call.from_user.id, interval_min=t)
    await call.answer(f"Vaqt {t} minutga sozlandi!", show_alert=True)
    await start_cmd(call.message)

# Xabarni sozlash (Reply orqali)
@dp.callback_query(F.data == "set_msg")
async def ask_msg(call: types.CallbackQuery):
    await call.message.answer("Yubormoqchi bo'lgan reklama xabaringizni shu yerga yuboring (rasm, matn, video bo'lishi mumkin).")

@dp.message(F.text | F.photo | F.video)
async def catch_msg(message: types.Message):
    db.update_user(message.from_user.id, message_id=message.message_id, from_chat_id=message.chat.id)
    await message.answer("✅ Reklama xabari saqlandi!")

# --- ISHGA TUSHIRISH ---
async def startup_setup():
    # Bu yerda har 1 minutda tekshiradigan global job qo'shamiz
    scheduler.add_job(check_and_run_tasks, "interval", minutes=1)
    scheduler.start()

async def check_and_run_tasks():
    # Bazadan barcha faol foydalanuvchilarni tekshirish logikasi
    pass

async def main():
    await startup_setup()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
