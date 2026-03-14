import asyncio
import logging
import re
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from telethon import TelegramClient
from telethon.sessions import StringSession

import config
from database import DB

# 1. HOLATLAR (STATES)
class BotStates(StatesGroup):
    auth_phone = State()      
    auth_code = State()       
    main_menu = State()       
    selecting_groups = State() 
    waiting_message = State()  
    selecting_interval = State() 
    confirm_sending = State()

# 2. LOGGING VA OBYEKTLAR
logging.basicConfig(level=logging.INFO)
bot = Bot(token=config.BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
db = DB()

# --- 3. HANDLERLAR (FUNKSIYALAR) ---

# START buyrug'i har doim eng tepada turishi kerak
@dp.message(Command("start"), F.state("*"))
async def start_cmd(message: types.Message, state: FSMContext):
    logging.info(f"START bosildi: {message.from_user.id}")
    await state.clear() 
    
    kb = ReplyKeyboardBuilder()
    kb.button(text="📱 Akkauntni ulash", request_contact=True)
    
    await message.answer(
        "Xush kelibsiz! Botdan foydalanish uchun avval akkauntni ulashingiz kerak.",
        reply_markup=kb.as_markup(resize_keyboard=True)
    )
    await state.set_state(BotStates.auth_phone)

# Raqamni qabul qilish
@dp.message(BotStates.auth_phone, F.contact | F.text)
async def process_phone(message: types.Message, state: FSMContext):
    phone = message.contact.phone_number if message.contact else message.text
    if not phone.startswith('+'): phone = f"+{phone}"
    
    await state.update_data(phone=phone)
    client = TelegramClient(StringSession(), config.API_ID, config.API_HASH)
    await client.connect()
    
    try:
        sent_code = await client.send_code_request(phone)
        await state.update_data(phone_code_hash=sent_code.phone_code_hash)
        
        await message.answer(
            "📩 Kod yuborildi.\n\n⚠️ **DIQQAT:** Telegram bloklamasligi uchun kodni nuqta bilan yuboring: `1.2.3.4.5`",
            reply_markup=types.ReplyKeyboardRemove(),
            parse_mode="Markdown"
        )
        await state.set_state(BotStates.auth_code)
    except Exception as e:
        await message.answer(f"❌ Xato: {e}")
    finally:
        await client.disconnect()

# Nuqtali kodni qabul qilish
@dp.message(BotStates.auth_code)
async def process_code(message: types.Message, state: FSMContext):
    data = await state.get_data()
    clean_code = "".join(re.findall(r'\d', message.text)) 
    
    if len(clean_code) < 5:
        await message.answer("❌ Xato kod. Kamida 5 ta raqam bo'lishi kerak.")
        return

    client = TelegramClient(StringSession(), config.API_ID, config.API_HASH)
    await client.connect()
    try:
        await client.sign_in(data['phone'], clean_code, phone_code_hash=data['phone_code_hash'])
        session_str = client.session.save()
        db.save_user_session(message.from_user.id, session_str) 
        
        # Guruhlarni bazaga yuklash
        dialogs = await client.get_dialogs()
        for d in dialogs:
            if d.is_group or d.is_channel:
                db.add_group(message.from_user.id, d.id, d.title)

        await message.answer("✅ Akkaunt ulandi!")
        await show_main_menu(message, state)
    except Exception as e:
        await message.answer(f"❌ Xatolik: {e}")
    finally:
        await client.disconnect()

# Asosiy menyu ko'rinishi
async def show_main_menu(message: types.Message, state: FSMContext):
    kb = InlineKeyboardBuilder()
    kb.button(text="👥 Guruhlarni tanlash", callback_data="menu_groups")
    kb.button(text="🚀 Xabar yuborish", callback_data="menu_send")
    kb.button(text="ℹ️ Qo'llanma", callback_data="menu_help")
    kb.adjust(1)
    
    text = "Asosiy menyu:"
    if isinstance(message, types.CallbackQuery):
        await message.message.edit_text(text, reply_markup=kb.as_markup())
    else:
        await message.answer(text, reply_markup=kb.as_markup())
    await state.set_state(BotStates.main_menu)

# Guruhlarni ✅/❌ bilan boshqarish
@dp.callback_query(F.data == "menu_groups")
@dp.callback_query(F.data.startswith("toggle_"))
@dp.callback_query(F.data == "select_all")
async def manage_groups(call: types.CallbackQuery, state: FSMContext):
    user_id = call.from_user.id
    if call.data == "select_all":
        db.select_all_groups(user_id, True)
    elif call.data.startswith("toggle_"):
        g_id = call.data.split("_")[1]
        db.toggle_group_status(user_id, g_id)

    groups = db.get_user_groups(user_id)
    kb = InlineKeyboardBuilder()
    for gid, name, status in groups:
        mark = "✅" if status else "❌"
        kb.button(text=f"{mark} {name}", callback_data=f"toggle_{gid}")
    
    kb.button(text="🌟 Hammasini tanlash", callback_data="select_all")
    kb.button(text="🔙 Ortga", callback_data="back_to_menu")
    kb.adjust(1)
    await call.message.edit_text("Guruhlarni tanlang:", reply_markup=kb.as_markup())

# Xabar va interval bosqichi
@dp.callback_query(F.data == "menu_send")
async def start_send(call: types.CallbackQuery, state: FSMContext):
    await call.message.edit_text("Xabaringizni yuboring:")
    await state.set_state(BotStates.waiting_message)

@dp.message(BotStates.waiting_message)
async def catch_msg(message: types.Message, state: FSMContext):
    await state.update_data(msg_id=message.message_id, chat_id=message.chat.id)
    kb = InlineKeyboardBuilder()
    for t in [5, 10, 15, 30, 60]: kb.button(text=f"{t} min", callback_data=f"time_{t}")
    kb.adjust(3)
    await message.answer("Interval tanlang:", reply_markup=kb.as_markup())
    await state.set_state(BotStates.selecting_interval)

@dp.callback_query(F.data.startswith("time_"))
async def confirm_send(call: types.CallbackQuery, state: FSMContext):
    t = call.data.split("_")[1]
    await state.update_data(interval=t)
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Ha", callback_data="confirm_yes")
    kb.button(text="❌ Yo'q", callback_data="back_to_menu")
    await call.message.edit_text(f"Interval: {t} min. Boshlaymizmi?", reply_markup=kb.as_markup())
    await state.set_state(BotStates.confirm_sending)

@dp.callback_query(F.data == "confirm_yes")
async def process_start(call: types.CallbackQuery, state: FSMContext):
    await call.message.answer("🚀 Jarayon boshlandi!")
    await show_main_menu(call, state)

@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu(call: types.CallbackQuery, state: FSMContext):
    await show_main_menu(call, state)

# --- 4. ISHGA TUSHIRISH (MAIN) ---
async def main():
    # Eng muhim joyi: webhookni o'chirib pollingni toza boshlash
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("Bot pollingni boshladi...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot to'xtatildi")
