import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

ADMIN_IDS = set(
    int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()
)
GROUP_ID = int(os.getenv("GROUP_ID", "0"))
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))

CLICK_SECRET = os.getenv("CLICK_SECRET", "dummy").strip()
PAYME_SECRET = os.getenv("PAYME_SECRET", "dummy").strip()  # basic auth: "login:password"

PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
WEBHOOK_TOKEN = os.getenv("WEBHOOK_TOKEN", "change-me").strip()

# Optional: yo‘naltirish tugmalari uchun (agar sizda link bo‘lsa)
PAYME_PAY_URL = os.getenv("PAYME_PAY_URL", "").strip()   # masalan: https://payme.uz/....
CLICK_PAY_URL = os.getenv("CLICK_PAY_URL", "").strip()   # masalan: https://click.uz/....

ALLOWED_WEBHOOK_IPS = os.getenv("ALLOWED_WEBHOOK_IPS", "").strip()

PLAN_PRICES_UZS = {
    7: int(os.getenv("PLAN_7", "20000")),
    30: int(os.getenv("PLAN_30", "50000")),
    90: int(os.getenv("PLAN_90", "120000")),
}

PAYME_AMOUNT_MULTIPLIER = 100  # tiyin
