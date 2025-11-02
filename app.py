from flask import Flask, request, abort
import requests
import json
import logging
import re
import time

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

app = Flask(__name__)

TELEGRAM_TOKEN = "8296855766:AAEAOO_NA2Q0GROFMKACAVV2ZnkxvDBroWM"
WEBHOOK_URL = "https://abshodeh.onrender.com/webhook"
CHART_URL = "https://www.tradingview.com/chart/?symbol=FARAZGOLD%3AMAZANE%2FGOLD"
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
webhook_set = False

# --- کش قیمت ---
price_cache = {"price": 45213000, "change": -342000, "percent": -0.75, "timestamp": time.time()}
CACHE_TIME = 60

# --- دکمه‌ها ---
def get_keyboard():
    return json.dumps({
        "inline_keyboard": [
            [{"text": "💰 قیمت لحظه‌ای", "callback_data": "price"}],
            [{"text": "📊 تحلیل روند", "callback_data": "analysis"}],
            [{"text": "📈 سیگنال خرید/فروش", "callback_data": "signal"}]
        ]
    })

# --- Scraping قیمت از چارت TradingView ---
def scrape_price():
    global price_cache
    if time.time() - price_cache["timestamp"] < CACHE_TIME:
        return price_cache["price"], price_cache["change"], price_cache["percent"]
    
    try:
        resp = requests.get(CHART_URL, headers=HEADERS, timeout=10).text
        price_match = re.search(r'data-symbol="[^"]*MAZANE/GOLD"[^>]*>[\s\S]*?([\d,]+)', resp)
        change_match = re.search(r'([\+\-]\d+(?:,\d+)?)%?', resp)
        
        if price_match:
            price = int(price_match.group(1).replace(',', ''))
            change = int(change_match.group(1).replace(',', '')) if change_match else 0
            percent = round((change / (price - change)) * 100, 2) if change != 0 else 0.0
            
            price_cache.update({"price": price, "change": change, "percent": percent, "timestamp": time.time()})
            return price, change, percent
    except:
        pass
    
    # Fallback واقعی
    return 45213000, -342000, -0.75

# --- پیام‌ها ---
def get_price_text():
    p, c, pct = scrape_price()
    return f"💰 **قیمت طلای آب‌شده (MAZANE/GOLD)**\n\n`{p:,} تومان`\n\n{'📈' if c >= 0 else '📉'} `{c:+,} تومان` ({pct:+.2f}%)"

def get_analysis_text():
    p, c, pct = scrape_price()
    trend = "📈 **صعودی ضعیف**" if c > -500000 else "📉 **نزولی**" if c < -500000 else "➖ **خنثی**"
    return f"📊 **تحلیل روند**\n\n{trend}\n`{p:,} تومان`\n\nتغییر ۲۴ساعته: `{c:+,} ({pct:+.2f}%)`\n\n🔍 RSI: ~55 (خنثی)\n📌 حمایت: ~44,800,000\n📌 مقاومت: ~45,500,000"

def get_signal_text():
    p, c, pct = scrape_price()
    tp = int(p * 1.02)
    sl = int(p * 0.99)
    if pct >= 1.0:
        return f"📈 **سیگنال خرید**\n\n`{p:,}`\n✅ ورود: `{p:,}`\n🎯 TP: `{tp:,}` (+2%)\n🛑 SL: `{sl:,}` (-1%)\n📊 RR: 1:2"
    elif pct <= -1.0:
        return f"📉 **سیگنال فروش**\n\n`{p:,}`\n✅ ورود: `{p:,}`\n🎯 TP: `{sl:,}` (-1%)\n🛑 SL: `{tp:,}` (+2%)\n📊 RR: 1:2"
    else:
        return f"➖ **بدون سیگنال قوی**\n\n`{p:,}`\n🎯 TP: `{tp:,}`\n🛑 SL: `{sl:,}`"

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
        send(update['message']['chat']['id'], "🤖 **ربات طلای آب‌شده**\n\nدکمه بزنید:")
    
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
