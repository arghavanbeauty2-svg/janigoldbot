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
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# خواندن متغیرهای محیطی
BOT_TOKEN = os.getenv('BOT_TOKEN')
API_KEY = os.getenv('API_KEY')
WEBHOOK_URL = os.getenv('WEBHOOK_URL', 'https://janigoldbot.onrender.com/webhook')

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
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*"
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        logging.debug(f"پاسخ API: {data}")
        if not isinstance(data, list):
            logging.error("پاسخ API لیست نیست.")
            return None
        for item in data:
            if isinstance(item, dict) and item.get("symbol") == "IR_GOLD_MELTED":
                price_str = item.get("price", "0").replace(",", "")
                price = int(price_str)
                logging.info(f"قیمت طلا دریافت شد: {price}")
                return price
        logging.warning("نماد طلای آبشده یافت نشد.")
        return None
    except Exception as e:
        logging.error(f"خطا در دریافت قیمت: {e}")
        return None

# === به‌روزرسانی داده‌های روزانه ===
def update_daily_data(price):
    today = str(date.today())
    if today not in daily_data:
        daily_data[today] = {"high": price, "low": price, "close": price}
    else:
        daily_data[today]["high"] = max(daily_data[today]["high"], price)
        daily_data[today]["low"] = min(daily_data[today]["low"], price)
        daily_data[today]["close"] = price
    logging.debug(f"داده‌های روزانه به‌روزرسانی شدند: {daily_data[today]}")

# === محاسبه Pivot Point ===
def calculate_pivot_levels():
    today = str(date.today())
    if today not in daily_data:
        logging.warning("داده‌ای برای امروز موجود نیست.")
        return None
    d = daily_data[today]
    high, low, close = d["high"], d["low"], d["close"]
    pivot = (high + low + close) / 3
    levels = {
        "pivot": pivot,
        "r1": 2 * pivot - low,
        "s1": 2 * pivot - high,
        "r2": pivot + (high - low),
        "s2": pivot - (high - low)
    }
    logging.debug(f"سطوح Pivot: {levels}")
    return levels

# === بررسی نزدیکی به سطوح Pivot ===
def is_near_pivot_level(price, levels, threshold=300):
    if not levels:
        return False
    near = any(abs(price - val) <= threshold for val in levels.values())
    logging.debug(f"بررسی نزدیکی به Pivot: قیمت={price}, نزدیک={near}")
    return near

# === بررسی بازه‌های فعالیت ===
def is_in_active_hours():
    now = datetime.now().time()
    active = (dtime(11, 0) <= now <= dtime(19, 0)) or (now >= dtime(22, 30) or now <= dtime(6, 30))
    logging.debug(f"ساعت فعال: {active}, زمان فعلی: {now}")
    return active

# === تحلیل و ارسال سیگنال ===
def analyze_and_send(is_manual=False, manual_chat_id=None):
    global last_price
    logging.debug(f"analyze_and_send: is_manual={is_manual}, manual_chat_id={manual_chat_id}, active_chats={active_chats}")
    if not active_chats and not is_manual:
        logging.info("هیچ چت فعالی وجود ندارد و درخواست دستی نیست.")
        return

    price = get_gold_price()
    if price is None:
        msg = "❌ خطای دریافت قیمت از API"
        target_chats = [manual_chat_id] if is_manual and manual_chat_id else active_chats
        for cid in target_chats:
            try:
                bot.send_message(cid, msg)
                logging.info(f"پیام خطا به {cid} ارسال شد.")
            except Exception as e:
                logging.error(f"خطا در ارسال پیام خطا به {cid}: {e}")
        return

    update_daily_data(price)
    save_data()
    prices.append(price)
    pivot_levels = calculate_pivot_levels()

    if is_manual and manual_chat_id:
        msg = f"📊 قیمت دستی: {price:,}\n"
        if pivot_levels:
            msg += (
                f"📌 Pivot: {pivot_levels['pivot']:,.0f}\n"
                f"🟢 R1: {pivot_levels['r1']:,.0f} | R2: {pivot_levels['r2']:,.0f}\n"
                f"🔴 S1: {pivot_levels['s1']:,.0f} | S2: {pivot_levels['s2']:,.0f}"
            )
        else:
            msg += "⏳ داده‌های روزانه کافی نیست."
        try:
            bot.send_message(manual_chat_id, msg, parse_mode="Markdown")
            logging.info(f"پیام قیمت دستی به {manual_chat_id} ارسال شد.")
        except Exception as e:
            logging.error(f"خطا در ارسال پیام دستی به {manual_chat_id}: {e}")
        return

    if not is_in_active_hours():
        logging.info("خارج از ساعات فعال، سیگنال ارسال نشد.")
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
                logging.info(f"سیگنال به {cid} ارسال شد: {msg}")
            except Exception as e:
                logging.error(f"خطا در ارسال سیگنال به {cid}: {e}")

# === هندلرهای تلگرام ===
@bot.message_handler(commands=['start'])
def start(message):
    active_chats.add(message.chat.id)
    logging.info(f"کاربر جدید: {message.chat.id}")
    try:
        bot.reply_to(message, "ربات فرازگلد فعال شد! ✅\nدستور /price برای استعلام دستی.\nدستور /stats برای آمار روزانه.")
        logging.info(f"پاسخ /start به {message.chat.id} ارسال شد.")
    except Exception as e:
        logging.error(f"خطا در پاسخ به /start برای {message.chat.id}: {e}")

@bot.message_handler(commands=['price'])
def manual_price(message):
    logging.info(f"درخواست دستی قیمت از {message.chat.id}")
    analyze_and_send(is_manual=True, manual_chat_id=message.chat.id)

@bot.message_handler(commands=['stats'])
def stats(message):
    logging.info(f"درخواست آمار از {message.chat.id}")
    today = str(date.today())
    if today in daily_data:
        d = daily_data[today]
        msg = f"📈 آمار امروز:\nبالاترین: {d['high']:,}\nپایین‌ترین: {d['low']:,}\nآخرین: {d['close']:,}"
    else:
        msg = "⏳ هنوز داده‌ای برای امروز موجود نیست."
    try:
        bot.reply_to(message, msg)
        logging.info(f"پاسخ /stats به {message.chat.id} ارسال شد.")
    except Exception as e:
        logging.error(f"خطا در پاسخ به /stats برای {message.chat.id}: {e}")

# === روت‌های Flask ===
@app.route('/')
def health():
    """Health check برای Render و UptimeRobot"""
    logging.debug("Health check درخواست شد.")
    return "OK", 200

@app.route('/health')
def health_alt():
    """Health check اضافی برای UptimeRobot"""
    logging.debug("Health check /health درخواست شد.")
    return "OK", 200

@app.route('/webhook', methods=['POST'])
def webhook():
    """پردازش درخواست‌های webhook از تلگرام"""
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        logging.debug(f"Webhook دریافت شد: {json_string}")
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return '', 200
    else:
        logging.warning("درخواست webhook با content-type نامعتبر")
        return 'Bad Request', 400

@app.route('/status')
def status():
    """وضعیت داخلی ربات"""
    logging.debug("درخواست وضعیت ربات")
    return jsonify({
        "active_chats_count": len(active_chats),
        "last_price": last_price,
        "today_data": daily_data.get(str(date.today()), None)
    })

# === زمان‌بندی چک خودکار ===
def run_scheduler():
    logging.info("Scheduler شروع شد.")
    schedule.every(2).minutes.do(analyze_and_send)
    while True:
        schedule.run_pending()
        time.sleep(1)

# === راه‌اندازی اولیه ===
load_data()
try:
    bot.remove_webhook()
    time.sleep(0.1)  # تاخیر برای اطمینان از حذف
    bot.set_webhook(url=WEBHOOK_URL)
    logging.info(f"Webhook تنظیم شد: {WEBHOOK_URL}")
except Exception as e:
    logging.error(f"خطا در تنظیم webhook: {e}")

threading.Thread(target=run_scheduler, daemon=True).start()

if __name__ == "__main__":
    logging.info("اپلیکیشن به صورت محلی اجرا شد.")
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
