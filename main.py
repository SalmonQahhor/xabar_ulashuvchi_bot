import asyncio
import logging
import re
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, PhoneCodeExpiredError

import config
from database import DB

# 1. GLOBAL CLIENT MANAGER
active_clients = {}

# 2. HOLATLAR (STATES)
class BotStates(StatesGroup):
    auth_phone = State()      
    auth_code = State()       
    auth_password = State()    # YANGA: 2-Bosqichli parol (2FA) uchun
    main_menu = State()       
    selecting_groups = State() 
    waiting_message = State()  
    selecting_interval = State() 
    confirm_sending = State()

# 3. LOGGING VA OBYEKTLAR
logging.basicConfig(level=logging.INFO)
bot = Bot(token=config.BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
db = DB()

# --- YORDAMCHI FUNKSIYA (Xotirani tozalash uchun) ---
async def cleanup_client(user_id):
    if user_id in active_clients:
        try:
            await active_clients[user_id].disconnect()
        except:
            pass
        active_clients.pop(user_id, None)

# --- 4. HANDLERLAR ---

# START - HAR DOIM ISHLAYDI (StateFilter("*") orqali)
@dp.message(Command("start"), StateFilter("*"))
async def start_cmd(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    logging.info(f"🚀 START bosildi: {user_id}")
    
    await state.clear()
    await cleanup_client(user_id) # Vaqtinchalik ulanishlarni yopish

    # 1. Bazadan foydalanuvchi ma'lumotlarini olish
    user_data = db.get_user(user_id)

    # 2. Agar sessiya satri bazada mavjud bo'lsa
    if user_data and user_data.get('session_str'):
        logging.info(f"✅ Sessiya topildi: {user_id}")
        await message.answer(f"👋 Xush kelibsiz, {message.from_user.first_name}!")
        await show_main_menu(message, state)
    else:
        # 3. Sessiya bo'lmasa, ulanishni boshlash
        logging.info(f"🔍 Sessiya topilmadi, login boshlanmoqda: {user_id}")
        kb = ReplyKeyboardBuilder()
        kb.button(text="📱 Akkauntni ulash", request_contact=True)
        await message.answer(
            "Xush kelibsiz! Botdan foydalanish uchun avval akkauntingizni ulashingiz kerak.",
            reply_markup=kb.as_markup(resize_keyboard=True)
        )
        await state.set_state(BotStates.auth_phone)

# RAQAM QABUL QILISH
@dp.message(BotStates.auth_phone, F.contact | F.text)
async def process_phone(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    phone = message.contact.phone_number if message.contact else message.text
    if not phone.startswith('+'): phone = f"+{phone}"
    
    await message.answer("🔄 Telegramga ulanilmoqda, kuting...")
    await cleanup_client(user_id) # Xavfsizlik uchun eskisini yopamiz
    
    client = TelegramClient(StringSession(), config.API_ID, config.API_HASH)
    await client.connect()
    
    try:
        sent_code = await client.send_code_request(phone)
        active_clients[user_id] = client # Sessiyani tirik saqlaymiz
        
        await state.update_data(phone=phone, phone_code_hash=sent_code.phone_code_hash)
        
        await message.answer(
            "📩 Telegramdan kod keldi.\n\n⚠️ **MUHIM:** Kodni probel yoki nuqta bilan yuboring (Misol: `1 2 3 4 5` yoki `1.2.3.4.5`)",
            reply_markup=types.ReplyKeyboardRemove(),
            parse_mode="Markdown"
        )
        await state.set_state(BotStates.auth_code)
    except Exception as e:
        await cleanup_client(user_id)
        await message.answer(f"❌ Xatolik yuz berdi: {e}\n\nIltimos, qaytadan /start bosing.")

# KOD QABUL QILISH VA TEKSHIRISH
@dp.message(BotStates.auth_code)
async def process_code(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    data = await state.get_data()
    
    # Faqat raqamlarni ajratib olish
    clean_code = "".join(re.findall(r'\d', message.text))
    
    if len(clean_code) < 5:
        await message.answer("❌ Xato: Kod kamida 5 ta raqamdan iborat bo'lishi kerak.")
        return

    if user_id not in active_clients:
        await message.answer("❌ Sessiya eskirgan. Qaytadan /start bosing.")
        return

    client = active_clients[user_id]
    
    try:
        await client.sign_in(
            phone=data['phone'], 
            code=clean_code, 
            phone_code_hash=data['phone_code_hash']
        )
        await save_and_finish_login(message, state, client, user_id)
        
    except SessionPasswordNeededError:
        # Agar akkauntda 2FA o'rnatilgan bo'lsa
        await message.answer("🔐 Akkauntingizda 2-bosqichli parol (2FA) bor ekan. Iltimos, parolingizni yuboring:")
        await state.set_state(BotStates.auth_password)
        
    except PhoneCodeInvalidError:
        await message.answer("❌ Kod noto'g'ri. Iltimos tekshirib, qaytadan yuboring.")
    except PhoneCodeExpiredError:
        await cleanup_client(user_id)
        await message.answer("❌ Kodning vaqti o'tib ketgan. Qaytadan /start bosing.")
    except Exception as e:
        await message.answer(f"❌ Noma'lum xatolik: {e}")

# 2FA PAROL QABUL QILISH
@dp.message(BotStates.auth_password)
async def process_password(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    password = message.text
    
    if user_id not in active_clients:
        await message.answer("❌ Sessiya eskirgan. Qaytadan /start bosing.")
        return

    client = active_clients[user_id]
    
    try:
        await client.sign_in(password=password)
        await save_and_finish_login(message, state, client, user_id)
    except Exception as e:
        # Xatoni ochiq-oydin yozamiz
        await message.answer(f"❌ Xatolik yuz berdi: {e}")


# MUVAFFAQIYATLI LOGINDAN KEYINGI JARAYON
async def save_and_finish_login(message: types.Message, state: FSMContext, client: TelegramClient, user_id: int):
    wait_msg = await message.answer("⏳ Ulanish muvaffaqiyatli! Guruhlar yuklanmoqda...")
    
    session_str = client.session.save()
    db.save_user_session(user_id, session_str) 
    
    dialogs = await client.get_dialogs(limit=200) # Ko'proq dialoglarni ko'rish uchun limitni oshirdik
    for d in dialogs:
        # FAQAT guruhlarni saqlaymiz (Kanallar va shaxsiy chatlar kirmaydi)
        if d.is_group: 
            db.add_group(user_id, d.id, d.title)

    await wait_msg.delete()
    await show_main_menu(message, state)
    await cleanup_client(user_id)

# --- ASOSIY MENYU VA BOSHQARUV ---
async def show_main_menu(message: types.Message, state: FSMContext):
    kb = InlineKeyboardBuilder()
    kb.button(text="👥 Guruhlarni tanlash", callback_data="menu_groups")
    kb.button(text="🚀 Xabar yuborish", callback_data="menu_send")
    kb.button(text="ℹ️ Qo'llanma", callback_data="menu_help")
    kb.adjust(1)
    
    text = "🎯 **Asosiy menyu:**"
    if isinstance(message, types.CallbackQuery):
        await message.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="Markdown")
    else:
        await message.answer(text, reply_markup=kb.as_markup(), parse_mode="Markdown")
    await state.set_state(BotStates.main_menu)

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


@dp.callback_query(F.data == "menu_help")
async def show_help(call: types.CallbackQuery):
    help_text = (
        "📖 **Botdan foydalanish bo'yicha qo'llanma:**\n\n"
        "1️⃣ **Akkaunt ulanishi:** /start buyrug'ini bering va raqamingizni yuboring.\n"
        "2️⃣ **Guruhlarni tanlash:** 'Guruhlarni tanlash' tugmasi orqali xabar yubormoqchi bo'lgan guruhlaringizni ✅ belgilang.\n"
        "3️⃣ **Xabar yuborish:** 'Xabar yuborish' tugmasini bosing, matnni yuboring va vaqt oralig'ini (interval) tanlang.\n"
        "4️⃣ **To'xtatish:** Agar jarayonni to'xtatmoqchi bo'lsangiz, botga qayta /start bosing.\n\n"
        "⚠️ **Eslatma:** Faqat o'zingiz a'zo bo'lgan va xabar yozishga ruxsati bor guruhlar ro'yxatda chiqadi."
    )
    
    kb = InlineKeyboardBuilder()
    kb.button(text="🔙 Ortga", callback_data="back_to_menu")
    
    await call.message.edit_text(help_text, reply_markup=kb.as_markup(), parse_mode="Markdown")


# --- ISHGA TUSHIRISH ---
async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("Bot pollingni boshladi...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot to'xtatildi")
