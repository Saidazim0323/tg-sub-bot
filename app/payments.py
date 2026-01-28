import hashlib
import base64

def verify_click_signature(data: dict, secret: str) -> bool:
    try:
        s = (
            f"{data['click_trans_id']}{data['service_id']}"
            f"{secret}{data['merchant_trans_id']}"
            f"{data['amount']}{data['action']}{data['sign_time']}"
        )
        expected = hashlib.md5(s.encode()).hexdigest()
        return expected == data.get("sign_string")
    except Exception:
        return False

def verify_payme_basic_auth(headers, secret: str) -> bool:
    auth = headers.get("authorization")
    if not auth or not auth.lower().startswith("basic "):
        return False
    try:
        token = auth.split(" ", 1)[1].strip()
        decoded = base64.b64decode(token).decode()
        return decoded == secret
    except Exception:
        return False
