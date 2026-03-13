import asyncio
import logging
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from pyrogram import Client, enums
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from database import DB
import config
from users import ALLOWED_USERS

# Loglarni sozlash
logging.basicConfig(level=logging.INFO)

# Sessions papkasini yaratish (Xato bermasligi uchun)
if not os.path.exists("sessions"):
    os.makedirs("sessions")

bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher()
db = DB()
scheduler = AsyncIOScheduler()
active_userbots = {}

class LoginSteps(StatesGroup):
    phone = State()
    code = State()

# --- START BUYRUG'I ---
@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    user_id = message.from_user.id
    if user_id not in ALLOWED_USERS:
        return await message.answer(f"❌ Ruxsat yo'q. ID: {user_id}")
    
    kb = InlineKeyboardBuilder()
    kb.button(text="📱 Akkauntni ulash", callback_data="connect")
    kb.button(text="🕒 Interval", callback_data="time_menu")
    kb.button(text="👥 Guruhlar", callback_data="refresh_groups")
    kb.button(text="🚀 Start/Stop", callback_data="toggle_bot")
    kb.adjust(2)
    await message.answer("Boshqaruv paneli:", reply_markup=kb.as_markup())

# --- LOGIN JARAYONI (AKKAUNT ULASH) ---
@dp.callback_query(F.data == "connect")
async def start_login(call: types.CallbackQuery, state: FSMContext):
    await call.message.answer("📞 Telefon raqamingizni yuboring (masalan: +998901234567):")
    await state.set_state(LoginSteps.phone)
    await call.answer()



@dp.message(LoginSteps.phone)
async def process_phone(message: types.Message, state: FSMContext):
    phone = message.text.strip()
    if not phone.startswith('+'):
        return await message.answer("❌ Raqamni +998901234567 formatida yuboring!")

    await state.update_data(phone=phone)
    
    client = Client(
        name=f"sessions/{message.from_user.id}",
        api_id=config.API_ID,
        api_hash=config.API_HASH,
        device_model="XabarBot Server"
    )
    
    await client.connect()
    try:
        # Kod yuborishni sinash
        code_info = await client.send_code(phone)
        await state.update_data(hash=code_info.phone_code_hash)
        await message.answer("📩 Kod Telegram ilovangizga yuborildi. Uni shu yerga yozing:")
        await state.set_state(LoginSteps.code)
    except Exception as e:
        # Xatoni logga yozish va foydalanuvchiga aytish
        logging.error(f"Telegram Error: {e}")
        await message.answer(f"❌ Telegram kod yubormadi.\nSababi: {str(e)}")
        await state.clear()
    finally:
        await client.disconnect()



@dp.message(LoginSteps.code)
async def process_code(message: types.Message, state: FSMContext):
    data = await state.get_data()
    code = message.text.strip()
    client = Client(f"sessions/{message.from_user.id}", config.API_ID, config.API_HASH)
    await client.connect()
    try:
        await client.sign_in(data['phone'], data['hash'], code)
        db.add_allowed_user(message.from_user.id) # Bazaga qo'shish
        await message.answer("✅ Akkaunt muvaffaqiyatli ulandi!")
    except Exception as e:
        await message.answer(f"❌ Xato: {e}")
    finally:
        await client.disconnect()
        await state.clear()

# --- GURUHLARNI YANGILASH ---
@dp.callback_query(F.data == "refresh_groups")
async def refresh_groups(call: types.CallbackQuery):
    user_id = call.from_user.id
    client = Client(f"sessions/{user_id}", config.API_ID, config.API_HASH)
    await client.connect()
    
    groups = []
    async for dialog in client.get_dialogs():
        if dialog.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
            groups.append((dialog.chat.id, dialog.chat.title))
    
    db.sync_groups(user_id, groups)
    await client.disconnect()
    await call.message.answer(f"✅ {len(groups)} ta guruh bazaga qo'shildi!")
    await call.answer()

# --- INTERVAL VA BOSHQALAR ---
@dp.callback_query(F.data == "time_menu")
async def time_menu(call: types.CallbackQuery):
    kb = InlineKeyboardBuilder()
    for t in [5, 10, 15, 30, 60]:
        kb.button(text=f"{t} min", callback_data=f"settime_{t}")
    kb.adjust(3)
    await call.message.edit_text("Intervalni tanlang:", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("settime_"))
async def set_time(call: types.CallbackQuery):
    t = int(call.data.split("_")[1])
    db.update_user(call.from_user.id, interval_min=t)
    await call.answer(f"Sozlandi: {t} min", show_alert=True)

# --- REKLAMA XABARINI TUTISH ---
@dp.message(F.text | F.photo | F.video)
async def catch_msg(message: types.Message):
    # Agar foydalanuvchi login qilgan bo'lsa xabarni saqlash
    db.update_user(message.from_user.id, message_id=message.message_id, from_chat_id=message.chat.id)
    await message.answer("✅ Reklama xabari saqlandi!")

async def check_and_run_tasks():
    logging.info("Tekshirilmoqda...")
    # Bu yerda yuborish logikasi bo'ladi

async def main():
    scheduler.add_job(check_and_run_tasks, "interval", minutes=1)
    scheduler.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
