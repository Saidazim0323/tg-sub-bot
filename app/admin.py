from aiogram import F
from aiogram.types import Message
from .config import ADMIN_ID
from .services import ensure_user, upsert_subscription, add_payment
from .services import expected_amount_uzs
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
def register_admin(dp):
    @dp.message(F.text == "/admin")
async def admin_menu(msg: Message):
    if msg.from_user.id != ADMIN_ID:
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 To‘lovlar", callback_data="admin:payments")],
        [InlineKeyboardButton(text="🎁 Obuna berish", callback_data="admin:give")],
        [InlineKeyboardButton(text="ℹ️ Buyruqlar", callback_data="admin:help")]
    ])

    await msg.answer("👑 <b>Admin panel</b>", reply_markup=kb)
    @dp.message(F.text.startswith("/give"))
    async def give(msg: Message):
        if msg.from_user.id != ADMIN_ID:
            return
        parts = msg.text.split()
        if len(parts) != 3:
            return await msg.answer("Format: /give <user_id> <days>")
        uid = int(parts[1]); days = int(parts[2])
        u = await ensure_user(uid)
        exp = await upsert_subscription(uid, days)
        await add_payment(uid, "admin", 0, "success", days, ext_id=f"manual:{msg.from_user.id}")
        await msg.answer(f"✅ Obuna berildi.\nUser:{uid}\nPAY CODE:{u.pay_code}\nTugash:{exp} (UTC)")
