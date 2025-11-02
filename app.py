from flask import Flask, request, abort
import requests
import json
import logging
import os
import pytesseract
from PIL import Image
import cv2
import numpy as np
import talib
import io

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

TELEGRAM_TOKEN = "8296855766:AAEAOO_NA2Q0GROFMKACAVV2ZnkxvDBroWM"
WEBHOOK_URL = "https://abshodeh.onrender.com/webhook"
PRICE_FILE = "price.json"
webhook_set = False

# --- بارگذاری قیمت (بدون پیش‌فرض) ---
def load_price():
    if os.path.exists(PRICE_FILE):
        try:
            with open(PRICE_FILE, 'r') as f:
                data = json.load(f)
                return data.get("price")
        except:
            pass
    return None  # بدون قیمت اولیه

price = load_price()

# --- ذخیره قیمت ---
def save_price(p):
    global price
    price = p
    with open(PRICE_FILE, 'w') as f:
        json.dump({"price": price}, f)

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
            [{"text": "📊 سیگنال", "callback_data": "signal"},
             {"text": "🔄 بروزرسانی", "callback_data": "refresh"}]
        ]
    }

# --- سیگنال ---
def generate_signal(current_price, rsi=None):
    tp = int(current_price * 1.02)
    sl = int(current_price * 0.99)
    rr = "1:2"
    rsi_text = f"\n📈 RSI: {rsi:.1f}" if rsi else ""
    
    if rsi and rsi > 70:
        return f"📉 **سیگنال فروش**{rsi_text}\n\n💰 قیمت: `{current_price:,}`\n\n✅ ورود: `{current_price:,}`\n🎯 TP: `{tp:,}`\n🛑 SL: `{sl:,}`\n\n📊 ریسک/ریوارد: {rr}"
    elif rsi and rsi < 30:
        return f"📈 **سیگنال خرید**{rsi_text}\n\n💰 قیمت: `{current_price:,}`\n\n✅ ورود: `{current_price:,}`\n🎯 TP: `{tp:,}`\n🛑 SL: `{sl:,}`\n\n📊 ریسک/ریوارد: {rr}"
    else:
        return f"➖ **بدون سیگنال قوی**\n\n💰 قیمت: `{current_price:,}`\n\nورود: `{current_price:,}`\n🎯 TP: `{tp:,}`\n🛑 SL: `{sl:,}`\n\n📊 ریسک/ریوارد: {rr}"

# --- OCR چارت ---
def ocr_chart(image_bytes):
    try:
        image = Image.open(io.BytesIO(image_bytes))
        img = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        text = pytesseract.image_to_string(thresh, config='--psm 6 -c tessedit_char_whitelist=0123456789.,')
        numbers = [float(x.replace(',', '')) for x in text.split() if x.replace('.', '').replace(',', '').isdigit()]
        if len(numbers) >= 4:
            closes = numbers[-20:]
            rsi = talib.RSI(np.array(closes), timeperiod=14)[-1]
            return int(closes[-1]), rsi
    except Exception as e:
        logger.error(f"OCR خطا: {e}")
    return None, None

# --- دانلود فایل ---
def download_file(file_id):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile"
    resp = requests.post(url, data={'file_id': file_id}).json()
    if resp.get('ok'):
        file_path = resp['result']['file_path']
        download_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
        return requests.get(download_url).content
    return None

# --- ارسال پیام ---
def send_message(chat_id, text, reply_markup=None):
    payload = {'chat_id': chat_id, 'text': text, 'parse_mode': 'Markdown'}
    if reply_markup:
        payload['reply_markup'] = json.dumps(reply_markup)
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", data=payload, timeout=10)
    except Exception as e:
        logger.error(f"ارسال شکست: {e}")

# --- Webhook ---
@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') != 'application/json':
        abort(403)
    
    update = request.get_json()
    
    if 'message' in update:
        msg = update['message']
        chat_id = msg['chat']['id']
        
        # اسکرین‌شات
        if 'photo' in msg:
            file_id = msg['photo'][-1]['file_id']
            image_bytes = download_file(file_id)
            if image_bytes:
                new_price, rsi = ocr_chart(image_bytes)
                if new_price:
                    save_price(new_price)
                    signal = generate_signal(new_price, rsi)
                    send_message(chat_id, signal, get_keyboard())
                else:
                    send_message(chat_id, "❌ چارت قابل خواندن نیست. عدد بنویسید یا دکمه بزنید.")
            return '', 200
        
        # قیمت دستی (عدد)
        text = msg.get('text', '').strip()
        if text.isdigit() and len(text) >= 5:
            new_price = int(text)
            save_price(new_price)
            signal = generate_signal(new_price)
            send_message(chat_id, signal, get_keyboard())
            return '', 200
        
        if text == '/start':
            send_message(chat_id, 
                "📸 **اسکرین‌شات چارت بفرستید** یا **قیمت بنویسید**\n\n"
                "تنظیم با دکمه 👇", get_keyboard())

    elif 'callback_query' in update:
        cb = update['callback_query']
        chat_id = cb['message']['chat']['id']
        data = cb['data']
        global price

        if price is None:
            send_message(chat_id, "⚠️ ابتدا قیمت تنظیم کنید.")
            return '', 200

        if data.startswith("add_") or data.startswith("sub_"):
            amount = int(data.split("_")[1])
            if data.startswith("sub_"): amount = -amount
            price += amount
            save_price(price)
            signal = generate_signal(price)
            send_message(chat_id, signal, get_keyboard())
        
        elif data == "signal":
            signal = generate_signal(price)
            send_message(chat_id, signal)
        
        elif data == "refresh":
            signal = generate_signal(price)
            send_message(chat_id, signal, get_keyboard())
        
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery",
                      data={'callback_query_id': cb['id']})
    
    return '', 200

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
    return "ربات تحلیل چارت + سیگنال (بدون قیمت پیش‌فرض)"

if __name__ == '__main__':
    app.run()
