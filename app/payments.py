import hashlib

# CLICK SIGNATURE TEKSHIRISH
def verify_click(data, secret):
    s = (
        f"{data['click_trans_id']}{data['service_id']}"
        f"{secret}{data['merchant_trans_id']}"
        f"{data['amount']}{data['action']}{data['sign_time']}"
    )
    return hashlib.md5(s.encode()).hexdigest() == data["sign_string"]

# PAYME JSON-RPC VALIDATION
async def verify_payme(data, secret):
    # Test / production: PAYME_SECRET bilan tekshir
    # Bu yerga real check qo‘yiladi
    return True
