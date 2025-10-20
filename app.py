import os
import json
import time
import requests
from datetime import datetime, date
from collections import deque
from flask import Flask, request
import telebot

# === تنظیمات اولیه ===
TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
API_KEY = os.getenv("API_KEY", "YOUR_API_KEY")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://your-app-url.onrender.com/webhook")

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# داده‌های جهانی
prices = deque(maxlen=30)
daily_data = {}
last_price = None
active_users = set()

# === دریافت قیمت از BrsApi.ir ===
def get_price():
    url = f"https://BrsApi.ir/Api/Tsetmc/AllSymbols.php?key={API_KEY}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "*/*"
    }
    try:
        res = requests.get(url, headers=headers, timeout=10, verify=False)
        if res.status_code == 200:
            data = res.json()
            for item in data:
                if isinstance(item, dict) and item.get("symbol") == "IR_GOLD_MELTED":
                    price_str = item.get("price", "0").replace(",", "")
                    return int(price_str)
    except:
        pass
    return None

# === به‌روزرسانی داده روزانه ===
def update_daily(price):
    today = str(date.today())
    if today not in daily_data:
        daily_data[today] = {"high": price, "low": price, "close": price}
    else:
        daily_data[today]["high"] = max(daily_data[today]["high"], price)
        daily_data[today]["low"] = min(daily_data[today]["low"], price)
        daily_data[today]["close"] = price

# === محاسبه Pivot Point ===
def pivot():
    today = str(date.today())
    if today in daily_data:
        d = daily_data[today]
        p = (d["high"] + d["low"] + d["close"]) / 3
        return {"pivot": round(p), "r1": round(2*p - d["low"]), "s1": round(2*p - d["high"])}
    return None

# === ارسال سیگنال ===
def send_signal(chat_id, price):
    p = pivot()
    msg = f"📊 قیمت: {price:,}\n"
    if p:
        msg += f"📌 Pivot: {p['pivot']:,}"
    try:
        bot.send_message(chat_id, msg)
    except:
        pass

# === بررسی تغییر قیمت ===
def check_price():
    global last_price
    price = get_price()
    if price is None:
        return
    prices.append(price)
    update_daily(price)
    
    if last_price is None:
        last_price = price
        return
        
    change = abs(price - last_price) / last_price * 100
    if change >= 0.2:
        last_price = price
        for uid in active_users:
            send_signal(uid, price)

# === هندلرهای تلگرام ===
@bot.message_handler(commands=['start'])
def start(m):
    active_users.add(m.chat.id)
    bot.reply_to(m, "✅ ربات فعال شد.\nدستور /price برای دریافت قیمت.")

@bot.message_handler(commands=['price'])
def price(m):
    p = get_price()
    if p:
        msg = f"📊 قیمت دستی: {p:,}\n"
        pv = pivot()
        if pv:
            msg += f"📌 Pivot: {pv['pivot']:,}"
        bot.reply_to(m, msg)
    else:
        bot.reply_to(m, "❌ خطا در دریافت قیمت.")

# === روت‌های Flask ===
@app.route('/')
def home():
    return "OK", 200

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return '', 200
    return 'Bad Request', 400

# === اجرای اولیه ===
if __name__ == "__main__":
    import threading
    bot.remove_webhook()
    time.sleep(1)
    bot.set_webhook(url=WEBHOOK_URL)
    
    # چک هر 2 دقیقه
    def job():
        while True:
            time.sleep(120)
            check_price()
            
    threading.Thread(target=job, daemon=True).start()
    
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
