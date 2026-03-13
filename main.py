import asyncio
import logging
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove

from telethon import TelegramClient, functions, types as tele_types
from telethon.sessions import StringSession
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from database import DB
import config
from users import ALLOWED_USERS

# Loglarni sozlash
logging.basicConfig(level=logging.INFO)

# Sessions papkasini yaratish
if not os.path.exists("sessions"):
    os.makedirs("sessions")

bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher()
db = DB()
scheduler = AsyncIOScheduler()

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

# --- LOGIN JARAYONI ---
@dp.callback_query(F.data == "connect")
async def start_login(call: types.CallbackQuery, state: FSMContext):
    # Raqam yuborish tugmasi
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Raqamni yuborish", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await call.message.answer("Pastdagi tugmani bosing yoki raqamni yuboring:", reply_markup=kb)
    await state.set_state(LoginSteps.phone)
    await call.answer()

@dp.message(LoginSteps.phone)
async def process_phone(message: types.Message, state: FSMContext):
    if message.contact:
        phone = message.contact.phone_number
        if not phone.startswith('+'): phone = f"+{phone}"
    else:
        phone = message.text.strip()
    
    await state.update_data(phone=phone)
    
    # Telethon client yaratish
    client = TelegramClient(f"sessions/{message.from_user.id}", config.API_ID, config.API_HASH)
    await client.connect()
    
    try:
        # Telethonda kod yuborish so'rovi
        result = await client.send_code_request(phone)
        await state.update_data(phone_code_hash=result.phone_code_hash)
        
        await message.answer("📩 Kod Telegram ilovangizga yuborildi. Uni kiriting:", reply_markup=ReplyKeyboardRemove())
        await state.set_state(LoginSteps.code)
    except Exception as e:
        logging.error(f"TELETHON ERROR: {e}")
        await message.answer(f"❌ Xatolik: {str(e)}", reply_markup=ReplyKeyboardRemove())
        await state.clear()
    finally:
        await client.disconnect()

@dp.message(LoginSteps.code)
async def process_code(message: types.Message, state: FSMContext):
    data = await state.get_data()
    code = message.text.strip()
    
    client = TelegramClient(f"sessions/{message.from_user.id}", config.API_ID, config.API_HASH)
    await client.connect()
    
    try:
        await client.sign_in(data['phone'], code, phone_code_hash=data['phone_code_hash'])
        db.add_allowed_user(message.from_user.id)
        await message.answer("✅ Akkaunt muvaffaqiyatli ulandi!")
    except Exception as e:
        await message.answer(f"❌ Xato: {str(e)}")
    finally:
        await client.disconnect()
        await state.clear()

# --- GURUHLARNI YANGILASH ---
@dp.callback_query(F.data == "refresh_groups")
async def refresh_groups(call: types.CallbackQuery):
    user_id = call.from_user.id
    client = TelegramClient(f"sessions/{user_id}", config.API_ID, config.API_HASH)
    await client.connect()
    
    if not await client.is_user_authorized():
        await client.disconnect()
        return await call.answer("Avval akkauntni ulang!", show_alert=True)

    groups = []
    async for dialog in client.iter_dialogs():
        if dialog.is_group or dialog.is_channel:
            # Telethonda dialog.is_channel ham guruhlarni (supergroup) o'z ichiga oladi
            groups.append((dialog.id, dialog.name))
    
    db.sync_groups(user_id, groups)
    await client.disconnect()
    await call.message.answer(f"✅ {len(groups)} ta guruh bazaga qo'shildi!")
    await call.answer()

# --- INTERVAL VA SOZLAMALAR ---
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

@dp.message(F.text | F.photo | F.video)
async def catch_msg(message: types.Message):
    db.update_user(message.from_user.id, message_id=message.message_id, from_chat_id=message.chat.id)
    await message.answer("✅ Reklama xabari saqlandi!")

async def check_and_run_tasks():
    logging.info("Tekshirilmoqda...")

async def main():
    scheduler.add_job(check_and_run_tasks, "interval", minutes=1)
    scheduler.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
