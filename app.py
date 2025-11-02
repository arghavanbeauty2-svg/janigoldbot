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
webhook_set = False

# --- بارگذاری قیمت ---
def load_price():
    if os.path.exists(PRICE_FILE):
        try:
            with open(PRICE_FILE, 'r') as f:
                data = json.load(f)
                return data.get("price", 45555000), data.get("previous", 45555000)
        except:
            pass
    return 45555000, 45555000

# --- ذخیره قیمت ---
def save_price(price, previous):
    with open(PRICE_FILE, 'w') as f:
        json.dump({"price": price, "previous": previous}, f)

price, previous_price = load_price()

# --- دکمه‌ها ---
def get_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "+۱,۰۰۰,۰۰۰", "callback_data": "add_1000000"},
             {"text": "+۱۰۰,۰۰۰", "callback_data": "add_100000"},
             {"text": "+۱۰,۰۰۰", "callback_data": "add_10000"}],
            [{"text": "-۱۰,۰۰۰", "callback_data": "sub_10000"},
             {"text": "-۱۰۰,۰۰۰", "callback_data": "sub_100000"},
             {"text": "-۱,۰۰۰,۰۰۰", "callback_data": "sub_1000000"}],
            [{"text": "🔄 بروزرسانی", "callback_data": "refresh"},
             {"text": "📊 سیگنال", "callback_data": "signal"}]
        ]
    }

# --- سیگنال ---
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
def send_price(chat_id, message_id=None):
    global price, previous_price
    change = price - previous_price
    change_percent = (change / previous_price * 100) if previous_price else 0
    message = f"💰 **قیمت طلای آب‌شده**\n`{price:,} تومان`\n\n"
    if change != 0:
        message += f"{'📈' if change > 0 else '📉'} تغییر: `{change:+,} تومان` ({change_percent:+.2f}%)\n\n"
    message += check_signal() + "\n\n"
    message += "تنظیم قیمت با دکمه 👇"

    payload = {
        'chat_id': chat_id,
        'text': message,
        'parse_mode': 'Markdown',
        'reply_markup': json.dumps(get_keyboard())
    }
    if message_id:
        payload['message_id'] = message_id
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText"
    else:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    
    try:
        resp = requests.post(url, data=payload, timeout=10).json()
        if resp.get('ok'):
            logger.info(f"پیام به {chat_id}")
    except Exception as e:
        logger.error(f"ارسال شکست: {e}")

# --- Webhook ---
@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        update = request.get_json()
        
        # /start یا اولین پیام
        if 'message' in update:
            chat_id = update['message']['chat']['id']
            send_price(chat_id)

        # دکمه‌ها
        elif 'callback_query' in update:
            cb = update['callback_query']
            chat_id = cb['message']['chat']['id']
            message_id = cb['message']['message_id']
            data = cb['data']
            global price, previous_price

            if data.startswith("add_") or data.startswith("sub_"):
                amount = int(data.split("_")[1])
                if data.startswith("sub_"):
                    amount = -amount
                previous_price = price
                price += amount
                save_price(price, previous_price)
                send_price(chat_id, message_id)
            
            elif data == "refresh":
                send_price(chat_id, message_id)
            
            elif data == "signal":
                signal = check_signal()
                requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                              data={'chat_id': chat_id, 'text': signal, 'parse_mode': 'Markdown'})

            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery",
                          data={'callback_query_id': cb['id']})
        
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
    return "ربات دکمه‌ای قیمت + سیگنال"

if __name__ == '__main__':
    app.run()
