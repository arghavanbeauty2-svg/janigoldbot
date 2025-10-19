from flask import Flask, request, abort
import telebot
import requests
import json
import os
import schedule
import threading
import time
from datetime import datetime, time as dtime, date
from collections import deque
import logging

app = Flask(__name__)

# تنظیم لاگینگ
logging.basicConfig(filename='goldbot.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

BOT_TOKEN = os.getenv('BOT_TOKEN')
API_KEY = os.getenv('API_KEY')
if not BOT_TOKEN or not API_KEY:
    logging.error("BOT_TOKEN or API_KEY not set")
    raise ValueError("Missing env vars")

bot = telebot.TeleBot(BOT_TOKEN)
prices = deque(maxlen=30)
daily_data = {}
last_price = None
chat_id = None  # برای چند کاربر، به dict تغییر دهید

def load_data():
    global daily_data, prices
    daily_data = {}
    if os.path.exists('daily_data.json'):
        try:
            with open('daily_data.json', 'r', encoding='utf-8') as f:
                daily_data = json.load(f)
        except:
            daily_data = {}
    if os.path.exists('prices.json'):
        try:
            with open('prices.json', 'r', encoding='utf-8') as f:
                price_list = json.load(f)
                prices.extend(price_list)
        except:
            pass

def save_data():
    with open('daily_data.json', 'w', encoding='utf-8') as f:
        json.dump(daily_data, f, ensure_ascii=False)
    with open('prices.json', 'w', encoding='utf-8') as f:
        json.dump(list(prices), f)

def get_gold_price():
    url = f"https://BrsApi.ir/Api/Tsetmc/AllSymbols.php?key={API_KEY}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 OPR/106.0.0.0",
        "Accept": "application/json, text/plain, */*"
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list):
            logging.error("API response is not a list")
            return None
        for item in data:
            if isinstance(item, dict) and item.get("symbol") == "IR_GOLD_MELTED":
                price_str = item.get("price", "0").replace(",", "")
                try:
                    price = int(price_str)
                    logging.info(f"Gold price fetched: {price}")
                    return price
                except ValueError:
                    logging.error("Invalid price format")
                    return None
        logging.warning("Symbol not found in API response")
        return None
    except Exception as e:
        logging.error(f"Error in get_gold_price: {e}")
        return None

def update_daily_data(price):
    today = str(date.today())
    if today not in daily_data:
        daily_data[today] = {"high": price, "low": price, "close": price}
    else:
        daily_data[today]["high"] = max(daily_data[today]["high"], price)
        daily_data[today]["low"] = min(daily_data[today]["low"], price)
        daily_data[today]["close"] = price
    logging.info(f"Daily data updated for {today}")

def calculate_pivot_levels():
    today = str(date.today())
    if today not in daily_data:
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

def is_near_pivot_level(price, levels, threshold=300):
    if not levels:
        return False
    for val in levels.values():
        if abs(price - val) <= threshold:
            return True
    return False

def is_in_active_hours():
    now = datetime.now().time()
    return dtime(11, 0) <= now <= dtime(19, 0) or now >= dtime(22, 30) or now <= dtime(6, 30)

def analyze_and_send(is_manual=False):
    global chat_id, last_price
    if chat_id is None:
        logging.warning("No chat_id set")
        return
    if not is_manual and not is_in_active_hours():
        logging.info("Outside active hours")
        return
    price = get_gold_price()
    if price is None:
        bot.send_message(chat_id, "❌ خطای دریافت قیمت از API")
        return
    update_daily_data(price)
    save_data()
    prices.append(price)
    pivot_levels = calculate_pivot_levels()
    if is_manual:
        msg = f"📊 قیمت دستی: {price:,}\n"
        if pivot_levels:
            msg += (
                f"📌 Pivot: {pivot_levels['pivot']:,.0f}\n"
                f"🟢 R1: {pivot_levels['r1']:,.0f} | R2: {pivot_levels['r2']:,.0f}\n"
                f"🔴 S1: {pivot_levels['s1']:,.0f} | S2: {pivot_levels['s2']:,.0f}"
            )
        else:
            msg += "⏳ داده‌های روزانه کافی نیست."
        bot.send_message(chat_id, msg, parse_mode="Markdown")
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
        bot.send_message(chat_id, msg, parse_mode="Markdown")
        logging.info("Message sent")

# هندلرها
@bot.message_handler(commands=['start'])
def start(message):
    global chat_id
    chat_id = message.chat.id
    bot.reply_to(message, "ربات فرازگلد فعال شد! ✅\nدستور /price برای استعلام دستی.\nدستور /stats برای آمار روزانه.")

@bot.message_handler(commands=['price'])
def manual_price(message):
    analyze_and_send(is_manual=True)

@bot.message_handler(commands=['stats'])
def stats(message):
    today = str(date.today())
    if today in daily_data:
        d = daily_data[today]
        msg = f"📈 آمار امروز:\nبالاترین: {d['high']:,}\nپایین‌ترین: {d['low']:,}\nآخرین: {d['close']:,}"
        bot.reply_to(message, msg)
    else:
        bot.reply_to(message, "⏳ هنوز داده‌ای برای امروز موجود نیست.")

# روت webhook
@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return '', 200
    else:
        abort(403)

# روت health check برای ping و جلوگیری از sleep
@app.route('/')
def health():
    return "Bot is alive!", 200

def run_scheduler():
    schedule.every(2).minutes.do(analyze_and_send)
    while True:
        schedule.run_pending()
        time.sleep(1)

# بارگذاری داده‌ها و ست webhook (اینجا خارج از __main__ برای اجرا در gunicorn)
load_data()
bot.remove_webhook()
bot.set_webhook(url="https://janiGOLDbot.onrender.com/webhook")
logging.info("Webhook set successfully")

# شروع scheduler
threading.Thread(target=run_scheduler, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
