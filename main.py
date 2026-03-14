import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from telethon import TelegramClient
from telethon.sessions import StringSession

import config
from database import DB

# Sozlamalar
logging.basicConfig(level=logging.INFO)
bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher()
db = DB()

# --- 1. START: FAQAT BITTA TUGMA ---
@dp.message(Command("start"))
async def start_cmd(message: types.Message, state: FSMContext):
    kb = ReplyKeyboardBuilder()
    kb.button(text="📱 Akkauntni ulash", request_contact=True)
    await message.answer(
        "Xush kelibsiz! Botdan foydalanish uchun avval akkauntni ulashingiz kerak.",
        reply_markup=kb.as_markup(resize_keyboard=True)
    )
    await state.set_state(BotStates.auth_phone)

# --- 2. RAQAM YUBORILGANDAN SO'NG ---
@dp.message(BotStates.auth_phone, F.contact | F.text)
async def process_phone(message: types.Message, state: FSMContext):
    phone = message.contact.phone_number if message.contact else message.text
    if not phone.startswith('+'): phone = f"+{phone}"
    
    await state.update_data(phone=phone)
    client = TelegramClient(StringSession(), config.API_ID, config.API_HASH)
    await client.connect()
    
    try:
        # Kod so'rash
        sent_code = await client.send_code_request(phone)
        await state.update_data(phone_code_hash=sent_code.phone_code_hash)
        
        # Tugmani yo'qotish va kod so'rash
        await message.answer(
            "📩 Kod yuborildi. Iltimos, kodni kiriting (shunchaki matn ko'rinishida):",
            reply_markup=types.ReplyKeyboardRemove()
        )
        await state.set_state(BotStates.auth_code)
    except Exception as e:
        await message.answer(f"❌ Xato: {e}")
    finally:
        await client.disconnect()

# --- 3. KOD KIRITILSA VA ASOSIY MENYU ---
@dp.message(BotStates.auth_code)
async def process_code(message: types.Message, state: FSMContext):
    data = await state.get_data()
    code = message.text.strip()
    
    client = TelegramClient(StringSession(), config.API_ID, config.API_HASH)
    await client.connect()
    try:
        await client.sign_in(data['phone'], code, phone_code_hash=data['phone_code_hash'])
        session_str = client.session.save()
        db.save_user_session(message.from_user.id, session_str) # Sessiyani saqlash
        
        await message.answer("✅ Akkaunt muvaffaqiyatli ulandi!")
        await show_main_menu(message, state)
    except Exception as e:
        await message.answer(f"❌ Kod xato yoki muddati o'tgan: {e}")
    finally:
        await client.disconnect()

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

# --- 4. GURUHLARNI BOSHQARISH (MULTI-SELECT) ---
@dp.callback_query(F.data == "menu_groups")
@dp.callback_query(F.data.startswith("toggle_group_"))
@dp.callback_query(F.data == "select_all")
async def manage_groups(call: types.CallbackQuery, state: FSMContext):
    user_id = call.from_user.id
    # Bu yerda DB dan guruhlarni va tanlangan holatni olamiz
    # Misol uchun mantiq:
    data = await state.get_data()
    selected = data.get("selected_groups", []) # IDlar ro'yxati
    
    if call.data == "select_all":
        # Hammasini tanlash mantiqi
        pass
    elif call.data.startswith("toggle_group_"):
        group_id = int(call.data.split("_")[2])
        if group_id in selected: selected.remove(group_id)
        else: selected.append(group_id)
        await state.update_data(selected_groups=selected)

    kb = InlineKeyboardBuilder()
    # Guruhlar ro'yxatini DB dan chiqaramiz
    all_groups = db.get_user_groups(user_id)
    for g_id, g_name in all_groups:
        mark = "✅" if g_id in selected else "❌"
        kb.button(text=f"{mark} {g_name}", callback_data=f"toggle_group_{g_id}")
    
    kb.button(text="🌟 Hammasini tanlash", callback_data="select_all")
    kb.button(text="🔙 Ortga", callback_data="back_to_menu")
    kb.adjust(1)
    
    await call.message.edit_text("Guruhlarni boshqarish:", reply_markup=kb.as_markup())

# --- 5. XABAR YUBORISH JARAYONI ---
@dp.callback_query(F.data == "menu_send")
async def start_sending(call: types.CallbackQuery, state: FSMContext):
    await call.message.edit_text("Xabaringizni yuboring (matn, rasm yoki video):")
    await state.set_state(BotStates.waiting_message)

@dp.message(BotStates.waiting_message)
async def catch_ad_message(message: types.Message, state: FSMContext):
    # Xabarni copy qilish uchun IDlarni saqlaymiz
    await state.update_data(msg_id=message.message_id, chat_id=message.chat.id)
    
    kb = InlineKeyboardBuilder()
    for t in [5, 10, 15, 20, 30, 60]:
        kb.button(text=f"{t} min", callback_data=f"time_{t}")
    kb.adjust(3)
    
    await message.answer("Intervalni tanlang:", reply_markup=kb.as_markup())
    await state.set_state(BotStates.selecting_interval)

@dp.callback_query(F.data.startswith("time_"))
async def confirm_step(call: types.CallbackQuery, state: FSMContext):
    t = call.data.split("_")[1]
    await state.update_data(interval=t)
    
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Ha", callback_data="confirm_yes")
    kb.button(text="❌ Yo'q", callback_data="back_to_menu")
    kb.adjust(1)
    
    await call.message.edit_text(f"Interval: {t} min. Jarayonni boshlaymizmi?", reply_markup=kb.as_markup())
    await state.set_state(BotStates.confirm_sending)

@dp.callback_query(F.data == "confirm_yes")
async def start_process(call: types.CallbackQuery, state: FSMContext):
    await call.message.answer("🚀 Jarayon boshlandi! Asosiy menyuga qaytilmoqda...")
    # Bu yerda APScheduler ga topshiriq beriladi
    await show_main_menu(call, state)

@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu_handler(call: types.CallbackQuery, state: FSMContext):
    await show_main_menu(call, state)
