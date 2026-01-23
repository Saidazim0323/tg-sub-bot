from datetime import datetime, timedelta
from .database import Session
from .models import Subscription

async def activate_subscription(tg_id, days=30):
    async with Session() as s:
        sub = Subscription(
            tg_id=tg_id,
            expires_at=datetime.utcnow() + timedelta(days=days),
            active=True
        )
        await s.merge(sub)
        await s.commit()
