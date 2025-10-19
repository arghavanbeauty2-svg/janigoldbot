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
bot = telebot.TeleBot(BOT_TOKEN)
prices = deque(maxlen=30)
daily_data = {}
last_price = None
chat_id = None  # اگر چند کاربر، این رو به dict تغییر بده

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

# بقیه توابع مثل get_gold_price, update_daily_data, calculate_pivot_levels, etc. رو از کد اصلی کپی کن

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

# روت health check برای ping
@app.route('/')
def health():
    return "Bot is alive!", 200

def run_scheduler():
    schedule.every(2).minutes.do(analyze_and_send)
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    load_data()
    # ست webhook
    bot.remove_webhook()
    bot.set_webhook(url=f"https://janigoldbot.onrender.com/webhook")
    
    threading.Thread(target=run_scheduler, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
