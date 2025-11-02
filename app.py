from flask import Flask, request, abort
import requests
import json
import logging
import time
import threading

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

app = Flask(__name__)

TELEGRAM_TOKEN = "8296855766:AAEAOO_NA2Q0GROFMKACAVV2ZnkxvDBroWM"
WEBHOOK_URL = "https://abshodeh.onrender.com/webhook"
# API غیررسمی TradingView برای نماد MAZANE/GOLD
TV_API_URL = "https://symbol-search.tradingview.com/symbol_search/?text=MAZANE/GOLD&exchange=FARAZGOLD"
HEADERS = {'User-Agent': 'Mozilla/5.0'}
webhook_set = False

price_data = {"price": None, "change": 0, "percent": 0.0, "timestamp": 0}
CACHE_TIME = 90
lock = threading.Lock()

# --- دکمه‌ها ---
def get_keyboard():
    return json.dumps({
        "inline_keyboard": [
            [{"text": "💰 قیمت لحظه‌ای", "callback_data": "price"}],
            [{"text": "📊 تحلیل روند", "callback_data": "analysis"}],
            [{"text": "📈 سیگنال خرید/فروش", "callback_data": "signal"}]
        ]
    })

# --- دریافت قیمت از TradingView API ---
def fetch_price():
    global price_data
    try:
        # مرحله ۱: جستجوی نماد
        search = requests.get(TV_API_URL, headers=HEADERS, timeout=8).json()
        symbol_id = next((s['id'] for s in search if s['symbol'] == 'MAZANE/GOLD'), None)
        if not symbol_id:
            return
        
        # مرحله ۲: داده‌های لحظه‌ای (غیررسمی اما پایدار)
        data_url = f"https://scanner.tradingview.com/symbol?symbol=FARAZGOLD:MAZANE/GOLD"
        resp = requests.get(data_url, headers=HEADERS, timeout=8).json()
        
        if 'close' in resp:
            with lock:
                price_data["price"] = int(resp['close'])
                price_data["change"] = int(resp.get('change', 0))
                price_data["percent"] = float(resp.get('change_percent', 0.0))
                price_data["timestamp"] = time.time()
    except Exception as e:
        logger.error(f"API خطا: {e}")

# --- شروع Thread ---
threading.Thread(target=fetch_price, daemon=True).start()

# --- پیام‌ها ---
def get_price_text():
    with lock:
        p, c, pct = price_data["price"], price_data["change"], price_data["percent"]
    if p is None:
        return "⚠️ در حال دریافت قیمت از TradingView..."
    return f"💰 **قیمت طلای آب‌شده**\n\n`{p:,} تومان`\n\n{'📈' if c >= 0 else '📉'} `{c:+,} تومان` ({pct:+.2f}%)"

def get_analysis_text():
    with lock:
        p, c, pct = price_data["price"], price_data["change"], price_data["percent"]
    if p is None:
        return "⚠️ داده در دسترس نیست."
    trend = "📈 **صعودی**" if c > 0 else "📉 **نزولی**" if c < 0 else "➖ **خنثی**"
    rsi_note = "نزدیک اشباع خرید" if pct > 2 else "نزدیک اشباع فروش" if pct < -2 else "متعادل"
    return f"📊 **تحلیل روند**\n\n{trend}\n`{p:,} تومان` | `{c:+,} ({pct:+.2f}%)`\n\n🔍 RSI: {rsi_note}\n📌 حمایت: ~{int(p*0.98):,}\n📌 مقاومت: ~{int(p*1.02):,}"

def get_signal_text():
    with lock:
        p, pct = price_data["price"], price_data["percent"]
    if p is None:
        return "⚠️ داده در دسترس نیست."
    tp = int(p * 1.02)
    sl = int(p * 0.99)
    if pct >= 1.5:
        return f"📈 **سیگنال خرید**\n\n`{p:,}`\n✅ ورود: `{p:,}`\n🎯 TP: `{tp:,}`\n🛑 SL: `{sl:,}`\n📊 RR: 1:2"
    elif pct <= -1.5:
        return f"📉 **سیگنال فروش**\n\n`{p:,}`\n✅ ورود: `{p:,}`\n🎯 TP: `{sl:,}`\n🛑 SL: `{tp:,}`\n📊 RR: 1:2"
    else:
        return f"➖ **بدون سیگنال**\n\n`{p:,}`\n🎯 TP: `{tp:,}`\n🛑 SL: `{sl:,}`"

# --- ارسال ---
def send(chat_id, text):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={'chat_id': chat_id, 'text': text, 'parse_mode': 'Markdown', 'reply_markup': get_keyboard()},
            timeout=5
        )
    except: pass

# --- Webhook ---
@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') != 'application/json':
        abort(403)
    
    update = request.get_json()
    
    if 'message' in update and update['message'].get('text', '').strip() == '/start':
        send(update['message']['chat']['id'], "🤖 **ربات طلا — TradingView**\n\nدکمه بزنید:")
    
    elif 'callback_query' in update:
        cb = update['callback_query']
        chat_id = cb['message']['chat']['id']
        data = cb['data']
        
        if data == "price": text = get_price_text()
        elif data == "analysis": text = get_analysis_text()
        elif data == "signal": text = get_signal_text()
        else: text = "دکمه نامعتبر."
        
        send(chat_id, text)
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery", 
                      data={'callback_query_id': cb['id']}, timeout=3)
    
    # بروزرسانی هر ۹۰ ثانیه
    if time.time() - price_data["timestamp"] > CACHE_TIME:
        threading.Thread(target=fetch_price, daemon=True).start()
    
    return '', 200

@app.before_request
def setup():
    global webhook_set
    if not webhook_set:
        try:
            r = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook", 
                              data={'url': WEBHOOK_URL}, timeout=5).json()
            if r.get('ok'): webhook_set = True
        except: pass

@app.route('/')
def home():
    return "ربات طلا — زنده"

if __name__ == '__main__':
    app.run()
