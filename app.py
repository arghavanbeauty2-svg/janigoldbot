# app.py
import os
import json
import time
import requests
import logging
from datetime import datetime, date
from collections import deque
from flask import Flask, request
import telebot
import urllib3

# === تنظیمات اولیه ===
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

TOKEN = os.getenv("BOT_TOKEN")
API_KEY = os.getenv("API_KEY")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://janigoldbot.onrender.com/webhook")

if not TOKEN or not API_KEY:
    raise ValueError("لطفاً متغیرهای محیطی BOT_TOKEN و API_KEY را در Render تنظیم کنید.")

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# === داده‌های جهانی ===
prices = deque(maxlen=30)
daily_data = {}
last_price = None
active_users = set()

# === توابع کمکی ===
def get_gold_price():
    url = f"https://BrsApi.ir/Api/Tsetmc/AllSymbols.php?key={API_KEY}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "*/*"
    }
    try:
        logging.info("📡 ارسال درخواست به BrsApi.ir...")
        response = requests.get(url, headers=headers, timeout=10, verify=False)
        if response.status_code == 200:
            data = response.json()
            logging.info("✅ پاسخ موفق از BrsApi.ir دریافت شد.")
            # ✅ خط اصلاح‌شده: for item in data
            for item in 
                if isinstance(item, dict) and item.get("symbol") == "IR_GOLD_MELTED":
                    price_str = item.get("price", "0").replace(",", "")
                    price = int(price_str)
                    logging.info(f"💰 قیمت دریافتی: {price:,}")
                    return price
        else:
            logging.error(f"❌ خطا در دریافت قیمت: کد وضعیت {response.status_code}")
        return None
    except Exception as e:
        logging.error(f"❌ خطا در دریافت قیمت از BrsApi.ir: {e}")
        return None

def update_daily_data(price):
    today = str(date.today())
    if today not in daily_
        daily_data[today] = {"high": price, "low": price, "close": price}
        logging.info(f"📅 داده‌های روز جدید ایجاد شد: {today}")
    else:
        daily_data[today]["high"] = max(daily_data[today]["high"], price)
        daily_data[today]["low"] = min(daily_data[today]["low"], price)
        daily_data[today]["close"] = price
        logging.info(f"📈 داده‌های روز {today} به‌روزرسانی شد.")

def calculate_pivot_levels():
    today = str(date.today())
    if today not in daily_
        logging.warning("📉 داده‌های روزانه برای محاسبه Pivot Point یافت نشد.")
        return None
    d = daily_data[today]
    high, low, close = d["high"], d["low"], d["close"]
    pivot = (high + low + close) / 3
    levels = {
        "pivot": round(pivot),
        "r1": round(2 * pivot - low),
        "s1": round(2 * pivot - high),
        "r2": round(pivot + (high - low)),
        "s2": round(pivot - (high - low))
    }
    logging.info(f"🧮 محاسبه Pivot Point: {levels}")
    return levels

def send_signal(chat_id, price):
    pivot_levels = calculate_pivot_levels()
    msg = f"📊 قیمت فعلی: {price:,}\n"
    if pivot_levels:
        msg += f"📌 Pivot: {pivot_levels['pivot']:,.0f}"
    try:
        bot.send_message(chat_id, msg)
        logging.info(f"📤 سیگنال به {chat_id} ارسال شد.")
    except Exception as e:
        logging.error(f"❌ خطا در ارسال سیگنال به {chat_id}: {e}")

def check_and_notify():
    global last_price
    price = get_gold_price()
    if price is None:
        return

    update_daily_data(price)
    prices.append(price)

    if last_price is None:
        last_price = price
        logging.info("🆕 اولین قیمت ثبت شد.")
        return

    change_percent = abs((price - last_price) / last_price) * 100
    if change_percent >= 0.2:
        logging.info(f"📈 تغییر قیمت > 0.2%: {change_percent:.2f}%")
        last_price = price
        for uid in active_users.copy():
            send_signal(uid, price)

# === هندلرهای تلگرام ===
@bot.message_handler(commands=['start'])
def start(message):
    active_users.add(message.chat.id)
    logging.info(f"👤 کاربر جدید: {message.chat.id}")
    bot.reply_to(message, "سلام! ربات فعال شد ✅\nدستور /price برای استعلام دستی.")

@bot.message_handler(commands=['price'])
def manual_price(message):
    logging.info(f"📥 درخواست دستی قیمت از {message.chat.id}")
    price = get_gold_price()
    if price:
        pivot_levels = calculate_pivot_levels()
        msg = f"📊 قیمت دستی: {price:,}\n"
        if pivot_levels:
            msg += f"📌 Pivot: {pivot_levels['pivot']:,.0f}"
        bot.reply_to(message, msg)
    else:
        bot.reply_to(message, "❌ خطا در دریافت قیمت.")

# === روت‌های Flask ===
@app.route('/')
def index():
    return "OK", 200

@app.route('/health')
def health():
    return "OK", 200

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return '', 200
    else:
        return 'Bad Request', 400

# === اجرای اولیه ===
if __name__ == "__main__":
    import threading
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    logging.info("🚀 راه‌اندازی ربات...")

    try:
        bot.remove_webhook()
        time.sleep(1)
        bot.set_webhook(url=WEBHOOK_URL)
        logging.info(f"🔗 Webhook تنظیم شد: {WEBHOOK_URL}")
    except Exception as e:
        logging.error(f"❌ خطا در تنظیم webhook: {e}")

    def run_scheduler():
        while True:
            time.sleep(120) # 2 دقیقه
            check_and_notify()

    threading.Thread(target=run_scheduler, daemon=True).start()

    port = int(os.getenv("PORT", 10000))
    logging.info(f"🌐 سرور روی پورت {port} شروع می‌شود...")
    app.run(host="0.0.0.0", port=port)
