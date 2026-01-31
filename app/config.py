# app/config.py
import os
from dotenv import load_dotenv

load_dotenv()

def _get_int(name: str, default: int = 0) -> int:
    v = (os.getenv(name, "") or "").strip()
    return int(v) if v else default

def _get_set_int(name: str) -> set[int]:
    raw = (os.getenv(name, "") or "").strip()
    if not raw:
        return set()
    return {int(x.strip()) for x in raw.split(",") if x.strip()}

BOT_TOKEN = (os.getenv("BOT_TOKEN", "") or "").strip()

# ADMIN_IDS="123,456"
ADMIN_IDS = _get_set_int("ADMIN_IDS")

GROUP_ID = _get_int("GROUP_ID", 0)
CHANNEL_ID = _get_int("CHANNEL_ID", 0)

CLICK_SECRET = (os.getenv("CLICK_SECRET", "dummy") or "dummy").strip()
PAYME_SECRET = (os.getenv("PAYME_SECRET", "dummy") or "dummy").strip()

PUBLIC_BASE_URL = (os.getenv("PUBLIC_BASE_URL", "") or "").rstrip("/")
WEBHOOK_TOKEN = (os.getenv("WEBHOOK_TOKEN", "change-me") or "change-me").strip()

PAYME_PAY_URL = (os.getenv("PAYME_PAY_URL", "") or "").strip()
CLICK_PAY_URL = (os.getenv("CLICK_PAY_URL", "") or "").strip()

ALLOWED_WEBHOOK_IPS = (os.getenv("ALLOWED_WEBHOOK_IPS", "") or "").strip()

PLAN_PRICES_UZS = {
    7: int(os.getenv("PLAN_7", "20000")),
    30: int(os.getenv("PLAN_30", "50000")),
    90: int(os.getenv("PLAN_90", "120000")),
}

PAYME_AMOUNT_MULTIPLIER = 100  # tiyin -> so‘m
