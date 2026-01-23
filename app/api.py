from fastapi import FastAPI, Request
from .payments import verify_click, verify_payme
from .utils import activate_subscription
from .config import CLICK_SECRET, PAYME_SECRET

app = FastAPI()

@app.post("/click")
async def click(req: Request):
    data = await req.json()
    if not verify_click(data, CLICK_SECRET):
        return {"error": -1}
    await activate_subscription(int(data["merchant_trans_id"]))
    return {"error": 0}

@app.post("/payme")
async def payme(req: Request):
    data = await req.json()
    if not await verify_payme(data, PAYME_SECRET):
        return {"error": -1}
    await activate_subscription(int(data["merchant_id"]))
    return {"error": 0}
