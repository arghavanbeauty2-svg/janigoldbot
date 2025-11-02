from flask import Flask, request, abort
import requests
import json
import logging
import os

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

TELEGRAM_TOKEN = "8296855766:AAEAOO_NA2Q0GROFMKACAVV2ZnkxvDBroWM"
WEBHOOK_URL = "https://abshodeh.onrender.com/webhook"
PRICE_FILE = "price.json"
keyboard = {"inline_keyboard": [[{"text": "🔄 بروزرسانی", "callback_data": "get_price"}]]}
webhook_set = False

# --- بارگذاری قیمت از فایل ---
def load_price():
    if os.path.exists(PRICE_FILE):
        try:
            with open(PRICE_FILE, 'r') as f:
                data = json.load(f)
                return data.get("price", 45555000), data.get("previous", 45555000)
        except:
            pass
    return 45555000, 45555000  # پیش‌فرض

# --- ذخیره قیمت ---
def save_price(price, previous):
    with open(PRICE_FILE, 'w') as f:
        json.dump({"price": price, "previous": previous}, f)

price, previous_price = load_price()

# --- بررسی سیگنال ---
def check_signal():
    if previous_price == 0:
        return "بدون تغییر قبلی"
    change_percent = (price - previous_price) / previous_price * 100
    if change_percent >= 2:
        return f"📈 **سیگنال خرید** (+{change_percent:.2f}%)"
    elif change_percent <= -2:
        return f"📉 **سیگنال فروش** ({change_percent:.2f}%)"
    else:
        return f"➖ بدون سیگنال ({change_percent:+.2f}%)"

# --- ارسال قیمت ---
def send_price(chat_id, show_signal=False):
    global price, previous_price
    change = price - previous_price
    change_percent = (change / previous_price * 100) if previous_price else 0
    message = f"💰 **قیمت طلای آب‌شده**\n`{price:,} تومان`\n\n"
    if change != 0:
        message += f"{'📈' if change > 0 else '📉'} تغییر: `{change:+,} تومان` ({change_percent:+.2f}%)\n\n"
    if show_signal:
        message += check_signal() + "\n\n"
    message += "کلیک برای بروزرسانی 👇"
    payload = {'chat_id': chat_id, 'text': message, 'parse_mode': 'Markdown', 'reply_markup': json.dumps(keyboard)}
    try:
        resp = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", data=payload, timeout=10).json()
        if resp.get('ok'):
            logger.info(f"پیام ارسال شد به {chat_id}")
    except Exception as e:
        logger.error(f"ارسال شکست: {e}")

# --- ویرایش پیام ---
def edit_price(chat_id, message_id):
    send_price(chat_id)  # همان تابع، اما edit
    payload = {'chat_id': chat_id, 'message_id': message_id, 'text': "در حال بروزرسانی...", 'parse_mode': 'Markdown'}
    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText", data=payload, timeout=10)
    send_price(chat_id)  # ارسال جدید

# --- Webhook ---
@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        update = request.get_json()
        if 'message' in update:
            msg = update['message']
            chat_id = msg['chat']['id']
            text = msg.get('text', '').strip()
            if text == '/start':
                send_price(chat_id, show_signal=True)
            elif text.startswith('/setprice '):
                try:
                    new_price = int(text.split()[1])
                    global price, previous_price
                    previous_price = price
                    price = new_price
                    save_price(price, previous_price)
                    send_price(chat_id, show_signal=True)
                    logger.info(f"قیمت دستی تنظیم شد: {price:,}")
                except:
                    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                                  data={'chat_id': chat_id, 'text': "❌ فرمت: /setprice 45600000"})
            elif text == '/signal':
                signal = check_signal()
                requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                              data={'chat_id': chat_id, 'text': signal, 'parse_mode': 'Markdown'})
        elif 'callback_query' in update and update['callback_query']['data'] == 'get_price':
            cb = update['callback_query']
            edit_price(cb['message']['chat']['id'], cb['message']['message_id'])
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery", data={'callback_query_id': cb['id']})
        return '', 200
    abort(403)

@app.before_request
def setup_webhook():
    global webhook_set
    if not webhook_set:
        try:
            resp = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook", data={'url': WEBHOOK_URL}, timeout=10).json()
            if resp.get('ok'):
                logger.info("Webhook تنظیم شد")
            webhook_set = True
        except:
            pass

@app.route('/')
def home():
    return "ربات قیمت دستی + سیگنال فعال"

if __name__ == '__main__':
    app.run()
