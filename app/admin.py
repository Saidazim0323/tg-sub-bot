from aiogram import F
from aiogram.types import Message
from datetime import datetime, timedelta
from .database import Session
from .models import Subscription
from .config import ADMIN_ID

def register_admin(dp):
    @dp.message(F.text.startswith("/give"))
    async def give(msg: Message):
        if msg.from_user.id != ADMIN_ID:
            return
        _, uid, days = msg.text.split()
        async with Session() as s:
            s.add(Subscription(
                tg_id=int(uid),
                expires_at=datetime.utcnow()+timedelta(days=int(days)),
                active=True
            ))
            await s.commit()
        await msg.answer("✅ Obuna berildi")

    @dp.message(F.text.startswith("/payments"))
    async def payments(msg: Message):
        if msg.from_user.id != ADMIN_ID:
            return
        from .models import Payment
        async with Session() as s:
            rows = await s.execute(Payment.__table__.select())
            text = "\n".join(
                f"{p.tg_id} | {p.amount} | {p.provider} | {p.status}"
                for p in rows.fetchall()
            )
        await msg.answer(text or "To‘lovlar yo‘q")
