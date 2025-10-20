import os
import json
import logging
from datetime import datetime, time as dtime, date
from collections import deque
from flask import Flask, request, jsonify
import telebot
import requests
import threading
import schedule
import time

# تنظیمات لاگینگ
logging.basicConfig(
    filename='goldbot.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# خواندن متغیرهای محیطی (بدون فاصله اضافه!)
BOT_TOKEN = os.getenv('BOT_TOKEN')
API_KEY = os.getenv('API_KEY')
WEBHOOK_URL = os.getenv('WEBHOOK_URL', 'https://janigoldbot.onrender.com/webhook')  # ✅ بدون فاصله

if not BOT_TOKEN or not API_KEY:
    logging.error("BOT_TOKEN یا API_KEY تنظیم نشده است.")
    raise ValueError("لطفاً متغیرهای محیطی را در Render تنظیم کنید.")

# راه‌اندازی Flask و Telebot
app = Flask(__name__)
bot = telebot.TeleBot(BOT_TOKEN)

# داده‌های جهانی
prices = deque(maxlen=30)
daily_data = {}
last_price = None
active_chats = set()

# === توابع مدیریت داده ===
def load_data():
    global daily_data, prices
    daily_data = {}
    if os.path.exists('daily_data.json'):
        try:
            with open('daily_data.json', 'r', encoding='utf-8') as f:
                daily_data = json.load(f)
            logging.info("داده‌های روزانه بارگذاری شدند.")
        except Exception as e:
            logging.error(f"خطا در بارگذاری daily_data: {e}")

    if os.path.exists('prices.json'):
        try:
            with open('prices.json', 'r', encoding='utf-8') as f:
                price_list = json.load(f)
                prices.extend(price_list)
            logging.info("قیمت‌های قبلی بارگذاری شدند.")
        except Exception as e:
            logging.error(f"خطا در بارگذاری prices: {e}")

def save_data():
    try:
        with open('daily_data.json', 'w', encoding='utf-8') as f:
            json.dump(daily_data, f, ensure_ascii=False)
        with open('prices.json', 'w', encoding='utf-8') as f:
            json.dump(list(prices), f)
        logging.info("داده‌ها ذخیره شدند.")
    except Exception as e:
        logging.error(f"خطا در ذخیره‌سازی داده: {e}")

# === دریافت قیمت از BrsApi.ir ===
def get_gold_price():
    url = f"https://BrsApi.ir/Api/Tsetmc/AllSymbols.php?key={API_KEY}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 OPR/106.0.0.0",
        "Accept": "application/json, text/plain, */*"
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            for item in   # ✅ کامل و صحیح
                if isinstance(item, dict) and item.get("symbol") == "IR_GOLD_MELTED":
                    price_str = item.get("price", "0").replace(",", "")
                    return int(price_str)
        return None
    except Exception as e:
        logging.error(f"خطا در دریافت قیمت: {e}")
        return None

# === به‌روزرسانی داده‌های روزانه ===
def update_daily_data(price):
    today = str(date.today())
    if today not in daily_
        daily_data[today] = {"high": price, "low": price, "close": price}
    else:
        daily_data[today]["high"] = max(daily_data[today]["high"], price)
        daily_data[today]["low"] = min(daily_data[today]["low"], price)
        daily_data[today]["close"] = price

# === محاسبه Pivot Point ===
def calculate_pivot_levels():
    today = str(date.today())
    if today not in daily_
        return None
    d = daily_data[today]
    high, low, close = d["high"], d["low"], d["close"]
    pivot = (high + low + close) / 3
    return {
        "pivot": pivot,
        "r1": 2 * pivot - low,
        "s1": 2 * pivot - high,
        "r2": pivot + (high - low),
        "s2": pivot - (high - low)
    }

# === بررسی نزدیکی به سطوح Pivot ===
def is_near_pivot_level(price, levels, threshold=300):
    if not levels:
        return False
    return any(abs(price - val) <= threshold for val in levels.values())

# === بررسی بازه‌های فعالیت ===
def is_in_active_hours():
    now = datetime.now().time()
    return (dtime(11, 0) <= now <= dtime(19, 0)) or (now >= dtime(22, 30) or now <= dtime(6, 30))

# === تحلیل و ارسال سیگنال ===
def analyze_and_send(is_manual=False, manual_chat_id=None):
    global last_price
    if not active_chats and not is_manual:
        return

    price = get_gold_price()
    if price is None:
        msg = "❌ خطای دریافت قیمت از API"
        target = [manual_chat_id] if is_manual and manual_chat_id else active_chats
        for cid in target:
            bot.send_message(cid, msg)
        return

    update_daily_data(price)
    save_data()
    prices.append(price)
    pivot_levels = calculate_pivot_levels()

    if is_manual and manual_chat_id:
        msg = f"📊 قیمت دستی: {price:,}\n"
        if pivot_levels:
            msg += f"📌 Pivot: {pivot_levels['pivot']:,.0f}"
        bot.send_message(manual_chat_id, msg, parse_mode="Markdown")
        return

    significant_change = False
    near_pivot = is_near_pivot_level(price, pivot_levels, 300)
    if last_price is None:
        significant_change = True
        last_price = price
    else:
        change_percent = abs((price - last_price) / last_price) * 100
        if change_percent >= 0.2:
            significant_change = True
            last_price = price

    if significant_change or near_pivot:
        msg = f"📊 قیمت فعلی: {price:,}\n"
        if pivot_levels:
            msg += f"📌 Pivot: {pivot_levels['pivot']:,.0f}"
        for cid in active_chats:
            try:
                bot.send_message(cid, msg, parse_mode="Markdown")
            except Exception as e:
                logging.error(f"خطا در ارسال به {cid}: {e}")

# === هندلرهای تلگرام ===
@bot.message_handler(commands=['start'])
def start(message):
    active_chats.add(message.chat.id)
    logging.info(f"کاربر جدید: {message.chat.id}")
    bot.reply_to(message, "ربات فرازگلد فعال شد! ✅\nدستور /price برای استعلام دستی.")

@bot.message_handler(commands=['price'])
def manual_price(message):
    logging.info(f"درخواست دستی قیمت از {message.chat.id}")
    analyze_and_send(is_manual=True, manual_chat_id=message.chat.id)

@bot.message_handler(commands=['stats'])
def stats(message):
    today = str(date.today())
    if today in daily_
        d = daily_data[today]
        msg = f"📈 آمار امروز:\nبالاترین: {d['high']:,}\nپایین‌ترین: {d['low']:,}\nآخرین: {d['close']:,}"
    else:
        msg = "⏳ هنوز داده‌ای برای امروز موجود نیست."
    bot.reply_to(message, msg)

# === روت‌های Flask (حیاتی برای Render و UptimeRobot) ===
@app.route('/')
def root_health():
    return "OK", 200

@app.route('/health')  # ✅ این روت برای UptimeRobot ضروری است
def health():
    return "OK", 200

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return '', 200
    return 'Bad Request', 400

# === راه‌اندازی اولیه ===
load_data()
try:
    bot.remove_webhook()
    bot.set_webhook(url=WEBHOOK_URL)
    logging.info(f"Webhook تنظیم شد: {WEBHOOK_URL}")
except Exception as e:
    logging.error(f"خطا در تنظیم webhook: {e}")

# راه‌اندازی scheduler در ترد جداگانه
def run_scheduler():
    schedule.every(2).minutes.do(analyze_and_send)
    while True:
        schedule.run_pending()
        time.sleep(1)

threading.Thread(target=run_scheduler, daemon=True).start()

# === اجرای Flask ===
if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
