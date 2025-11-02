from flask import Flask, request, abort
import requests
import json
import logging
import time
import re
import threading

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

TELEGRAM_TOKEN = "8296855766:AAEAOO_NA2Q0GROFMKACAVV2ZnkxvDBroWM"
WEBHOOK_URL = "https://abshodeh.onrender.com/webhook"
TRADINGVIEW_SYMBOL_URL = "https://www.tradingview.com/symbols/FARAZGOLD-MAZANE-GOLD/"
webhook_set = False
price_cache = {"price": None, "change": None, "percent": None, "timestamp": 0}
CACHE_TIME = 60  # ۱ دقیقه

# --- دکمه‌ها ---
def get_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "💰 قیمت لحظه‌ای", "callback_data": "price"}],
            [{"text": "📊 تحلیل روند", "callback_data": "analysis"}],
            [{"text": "📈 سیگنال خرید/فروش", "callback_data": "signal"}]
        ]
    }

# --- استخراج قیمت از TradingView ---
def scrape_tradingview():
    now = time.time()
    if now - price_cache["timestamp"] < CACHE_TIME and price_cache["price"]:
        return price_cache["price"], price_cache["change"], price_cache["percent"]

    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(TRADINGVIEW_SYMBOL_URL, headers=headers, timeout=10).text
        
        # استخراج قیمت فعلی
        price_match = re.search(r'"last":\s*"?(\d+(?:\.\d+)?)"?', resp)
        change_match = re.search(r'"change":\s*"?([+-]?\d+(?:\.\d+)?)"?', resp)
        percent_match = re.search(r'"change_percent":\s*"?([+-]?\d+(?:\.\d+)?)"?', resp)
        
        if price_match:
            price = int(float(price_match.group(1)))
            change = int(float(change_match.group(1))) if change_match else 0
            percent = float(percent_match.group(1)) if percent_match else 0.0
            
            price_cache.update({"price": price, "change": change, "percent": percent, "timestamp": now})
            logger.info(f"TradingView قیمت: {price:,} تومان | تغییر: {change:+,} ({percent:+.2f}%)")
            return price, change, percent
    except Exception as e:
        logger.error(f"Scraping خطا: {e}")
    
    return None, None, None

# --- قیمت لحظه‌ای ---
def get_price_text():
    price, change, percent = scrape_tradingview()
    if price is None:
        return "❌ دریافت قیمت موقتاً ممکن نیست. دوباره تلاش کنید."
    
    return f"💰 **قیمت طلای آب‌شده (MAZANE/GOLD)**\n\n" \
           f"`{price:,} تومان`\n\n" \
           f"{'📈' if change >= 0 else '📉'} تغییر: `{change:+,} تومان` ({percent:+.2f}%)"

# --- تحلیل روند ---
def get_analysis_text():
    price, change, percent = scrape_tradingview()
    if price is None:
        return "❌ دریافت داده برای تحلیل ممکن نیست."
    
    rsi_status = "نزدیک اشباع خرید (احتمال اصلاح)" if percent > 2 else "در محدوده خنثی" if abs(percent) <= 1 else "در روند قوی"
    trend = "📈 **صعودی**" if change > 0 else "📉 **نزولی**" if change < 0 else "➖ **خنثی**"
    
    return f"📊 **تحلیل روند فعلی**\n\n" \
           f"💰 قیمت: `{price:,} تومان`\n" \
           f"{trend} | تغییر ۲۴ساعته: `{change:+,} تومان` ({percent:+.2f}%)\n\n" \
           f"🔍 **وضعیت RSI**: {rsi_status}\n" \
           f"📌 **حمایت**: ~{int(price * 0.98):,} تومان\n" \
           f"📌 **مقاومت**: ~{int(price * 1.02):,} تومان\n\n" \
           f"_داده‌ها از TradingView (MAZANE/GOLD)_"

# --- سیگنال خرید/فروش ---
def get_signal_text():
    price, change, percent = scrape_tradingview()
    if price is None:
        return "❌ دریافت داده برای سیگنال ممکن نیست."
    
    tp = int(price * 1.02)
    sl = int(price * 0.99)
    rr = "1:2"
    
    if percent >= 1.5:
        signal = "📈 **سیگنال خرید**"
        entry = price
    elif percent <= -1.5:
        signal = "📉 **سیگنال فروش**"
        entry = price
    else:
        signal = "➖ **بدون سیگنال قوی**"
        entry = price
    
    return f"{signal}\n\n" \
           f"💰 **قیمت فعلی**: `{price:,} تومان`\n\n" \
           f"✅ **ورود**: `{entry:,}`\n" \
           f"🎯 **حد سود (TP)**: `{tp:,}` (+2%)\n" \
           f"🛑 **حد زیان (SL)**: `{sl:,}` (-1%)\n\n" \
           f"📊 **ریسک/ریوارد**: {rr}\n" \
           f"_بر اساس تغییر ۲۴ساعته و روند فعلی_"

# --- ارسال پیام ---
def send_message(chat_id, text):
    payload = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': 'Markdown',
        'reply_markup': json.dumps(get_keyboard())
    }
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
    
    if 'message' in update and update['message'].get('text', '').strip() == '/start':
        chat_id = update['message']['chat']['id']
        send_message(chat_id, 
            "🤖 **ربات قیمت طلای آب‌شده (TradingView)**\n\n"
            "از دکمه‌های زیر استفاده کنید:\n\n"
            "داده‌ها از نماد **MAZANE/GOLD** در TradingView")
    
    elif 'callback_query' in update:
        cb = update['callback_query']
        chat_id = cb['message']['chat']['id']
        data = cb['data']
        
        if data == "price":
            text = get_price_text()
        elif data == "analysis":
            text = get_analysis_text()
        elif data == "signal":
            text = get_signal_text()
        else:
            text = "دکمه نامعتبر."
        
        send_message(chat_id, text)
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
    return "ربات قیمت طلا — TradingView MAZANE/GOLD"

if __name__ == '__main__':
    app.run()
