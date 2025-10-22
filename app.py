import os
import json
import logging
import requests
from datetime import datetime, time as dtime, date
from collections import deque
from flask import Flask, request, jsonify
import telebot
import threading
import schedule
import time
import urllib3

# غیرفعال کردن هشدارهای SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# تنظیمات لاگینگ به stdout/stderr (برای Render Logs)
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# خواندن متغیرهای محیطی
TOKEN = os.getenv("BOT_TOKEN")
API_KEY = os.getenv("API_KEY")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://janigoldbot.onrender.com/webhook")

if not TOKEN or not API_KEY:
    logging.error("BOT_TOKEN یا API_KEY تنظیم نشده است.")
    raise ValueError("لطفاً متغیرهای محیطی BOT_TOKEN و API_KEY را در Render تنظیم کنید.")

# راه‌اندازی Flask و Telebot
app = Flask(__name__)
bot = telebot.TeleBot(TOKEN)

# داده‌های جهانی
prices = deque(maxlen=30)
daily_data = {}
last_price = None
active_users = set()

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
    url = f"https://brsapi.ir/Api/Market/Gold_Currency.php?key={API_KEY}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*"
    }
    try:
        logging.debug("📡 ارسال درخواست به BrsApi.ir...")
        response = requests.get(url, headers=headers, timeout=10, verify=False)
        response.raise_for_status()
        data = response.json()
        logging.debug(f"پاسخ API: {json.dumps(data, ensure_ascii=False)}")
        if isinstance(data, dict) and 'gold' in data:
            for item in data['gold']:
                if item.get("symbol") == "IR_GOLD_MELTED":
                    price_str = str(item.get("price", "0")).replace(",", "")
                    price = int(price_str)
                    logging.info(f"💰 قیمت دریافتی: {price:,}")
                    return price
            logging.warning("نماد طلای آبشده یافت نشد.")
        else:
            logging.error("پاسخ API حاوی کلید 'gold' نیست.")
        return None
    except Exception as e:
        logging.error(f"خطا در دریافت قیمت: {e}")
        return None

# === به‌روزرسانی داده‌های روزانه ===
def update_daily_data(price):
    today = str(date.today())
    if today not in daily_data:
        daily_data[today] = {"high": price, "low": price, "close": price}
        logging.info(f"📅 داده‌های روز جدید ایجاد شد: {today}")
    else:
        daily_data[today]["high"] = max(daily_data[today]["high"], price)
        daily_data[today]["low"] = min(daily_data[today]["low"], price)
        daily_data[today]["close"] = price
        logging.info(f"📈 داده‌های روز {today} به‌روزرسانی شد.")

# === محاسبه Pivot Point ===
def calculate_pivot_levels():
    today = str(date.today())
    if today not in daily_data:
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
def check_and_notify(is_manual=False, manual_chat_id=None):
    global last_price
    logging.debug(f"check_and_notify: is_manual={is_manual}, manual_chat_id={manual_chat_id}, active_users={active_users}")
    if not active_users and not is_manual:
        logging.info("هیچ کاربر فعالی وجود ندارد و درخواست دستی نیست.")
        return

    price = get_gold_price()
    if price is None:
        msg = "❌ خطای دریافت قیمت از API"
        target_chats = [manual_chat_id] if is_manual and manual_chat_id else active_users
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
        for cid in active_users.copy():
            try:
                bot.send_message(cid, msg, parse_mode="Markdown")
                logging.info(f"سیگنال به {cid} ارسال شد: {msg}")
            except Exception as e:
                logging.error(f"خطا در ارسال سیگنال به {cid}: {e}")

# === هندلرهای تلگرام ===
@bot.message_handler(commands=['start'])
def start(message):
    active_users.add(message.chat.id)
    logging.info(f"👤 کاربر جدید: {message.chat.id}")
    try:
        bot.reply_to(message, "سلام! ربات فعال شد ✅\nدستور /price برای استعلام دستی.\nدستور /stats برای آمار روزانه.")
        logging.info(f"پاسخ /start به {message.chat.id} ارسال شد.")
    except Exception as e:
        logging.error(f"خطا در پاسخ به /start برای {message.chat.id}: {e}")

@bot.message_handler(commands=['price'])
def manual_price(message):
    logging.info(f"📥 درخواست دستی قیمت از {message.chat.id}")
    check_and_notify(is_manual=True, manual_chat_id=message.chat.id)

@bot.message_handler(commands=['stats'])
def stats(message):
    logging.info(f"📥 درخواست آمار از {message.chat.id}")
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
def index():
    logging.debug("Health check / درخواست شد.")
    return "OK", 200

@app.route('/health')
def health():
    logging.debug("Health check /health درخواست شد.")
    return "OK", 200

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        logging.debug(f"Webhook دریافت شد: {json_string}")
        try:
            update = telebot.types.Update.de_json(json_string)
            if update:
                logging.debug(f"Update پردازش شد: {update}")
                bot.process_new_updates([update])
            else:
                logging.warning("Update نامعتبر دریافت شد.")
        except Exception as e:
            logging.error(f"خطا در پردازش webhook: {e}")
        return '', 200
    else:
        logging.warning("درخواست webhook با content-type نامعتبر")
        return 'Bad Request', 400

@app.route('/status')
def status():
    logging.debug("درخواست وضعیت ربات")
    return jsonify({
        "active_users_count": len(active_users),
        "last_price": last_price,
        "today_data": daily_data.get(str(date.today()), None)
    })

# === زمان‌بندی چک خودکار ===
def run_scheduler():
    logging.info("Scheduler شروع شد.")
    schedule.every(2).minutes.do(check_and_notify)
    while True:
        schedule.run_pending()
        time.sleep(1)

# === اجرای اولیه ===
if __name__ == "__main__":
    logging.info("🚀 راه‌اندازی ربات...")
    load_data()
    try:
        bot.remove_webhook()
        time.sleep(1)
        bot.set_webhook(url=WEBHOOK_URL)
        logging.info(f"Webhook تنظیم شد: {WEBHOOK_URL}")
    except Exception as e:
        logging.error(f"خطا در تنظیم webhook: {e}")

    threading.Thread(target=run_scheduler, daemon=True).start()

    port = int(os.getenv("PORT", 10000))
    logging.info(f"🌐 سرور روی پورت {port} شروع می‌شود...")
    app.run(host="0.0.0.0", port=port)
