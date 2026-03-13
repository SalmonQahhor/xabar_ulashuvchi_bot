import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from pyrogram import Client
from database import DB
from config import BOT_TOKEN, API_ID, API_HASH, ADMIN_ID

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
db = DB()
active_userbots = {}

class LoginSteps(StatesGroup):
    phone = State()
    code = State()

@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    user = db.get_user(message.from_user.id)
    if not user or not user['is_active']:
        return await message.answer(f"❌ Ruxsat yo'q. ID: {message.from_user.id}")
    
    kb = InlineKeyboardBuilder()
    kb.button(text="📱 Akkauntni ulash", callback_data="connect")
    kb.button(text="🕒 Interval", callback_data="time_menu")
    kb.button(text="👥 Guruhlar", callback_data="groups_menu")
    kb.button(text="📝 Xabarni belgilash", callback_data="set_msg")
    kb.button(text="🚀 Start/Stop", callback_data="toggle_bot")
    kb.adjust(2)
    await message.answer("Boshqaruv paneli:", reply_markup=kb.as_markup())

# Guruhlarni ✅/❌ rejimida chiqarish
@dp.callback_query(F.data == "groups_menu")
async def groups_menu(call: types.CallbackQuery):
    user_id = call.from_user.id
    kb = InlineKeyboardBuilder()
    # Bazadan guruhlarni olish logikasi...
    # (Bu yerda db.get_user_groups ishlatiladi)
    kb.button(text="🔄 Guruhlarni yangilash", callback_data="refresh_groups")
    kb.button(text="⬅️ Orqaga", callback_data="back_home")
    await call.message.edit_text("Guruhlarni sozlang:", reply_markup=kb.as_markup())

async def main():
    # Bu yerda scheduler ham ishga tushiriladi
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())