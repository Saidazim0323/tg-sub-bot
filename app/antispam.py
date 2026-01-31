# app/antispam.py
import time
from collections import defaultdict

# user_id -> last_time
_last_click = defaultdict(float)
_last_msg = defaultdict(float)

def allow_click(user_id: int, delay: float = 2.0) -> bool:
    """Inline tugmalar (callback) uchun anti-spam"""
    now = time.time()
    if now - _last_click[user_id] < delay:
        return False
    _last_click[user_id] = now
    return True

def allow_message(user_id: int, delay: float = 1.0) -> bool:
    """Oddiy message bosishlar uchun (menu) anti-spam"""
    now = time.time()
    if now - _last_msg[user_id] < delay:
        return False
    _last_msg[user_id] = now
    return True
