from flask import Flask, request, abort
import requests
import json
import logging
import time

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

app = Flask(__name__)

TELEGRAM_TOKEN = "8296855766:AAEAOO_NA2Q0GROFMKACAVV2ZnkxvDBroWM"
WEBHOOK_URL = "https://abshodeh.onrender.com/webhook"
webhook_set = False

# --- API TradingView (MAZANE/GOLD) ---
def fetch_mazane_gold():
    try:
        # درخواست به TradingView symbol search
        search_url = "https://symbol-search.tradingview.com/symbol_search/?text=MAZANE/GOLD&exchange=FARAZGOLD"
        resp = requests.get(search_url, timeout=5).json()
        symbol = next((s for s in resp if s['symbol'] == 'MAZANE/GOLD'), None)
        if symbol:
            # داده‌های لحظه‌ای
            data_url = f"https://api.tradingview.com/symbols/{symbol['exchange']}/{symbol['symbol']}/"
            data = requests.get(data_url, timeout=5).json()
            price = int(data.get('last', 0))
            change = data.get('change', 0)
            percent = data.get('change_percent', 0.0)
            return price, change, percent
    except:
        pass
    return 0, 0, 0.0

# --- دکمه‌ها ---
def get_keyboard():
    return json.dumps({
        "inline_keyboard": [
            [{"text": "💰 قیمت لحظه‌ای", "callback_data": "price"}],
            [{"text": "📊 تحلیل روند", "callback_data": "analysis"}],
            [{"text": "📈 سیگنال خرید/فروش", "callback_data": "signal"}]
        ]
    })

# --- پیام‌ها ---
def get_price_text():
    p, c, pct = fetch_mazane_gold()
    if p == 0:
        return "⚠️ دریافت قیمت موقتاً ممکن نیست."
    return f"💰 **قیمت طلای آب‌شده (MAZANE/GOLD)**\n\n`{p:,} تومان`\n\n{'📈' if c >= 0 else '📉'} `{c:+,} تومان` ({pct:+.2f}%)"

def get_analysis_text():
    p, c, pct = fetch_mazane_gold()
    if p == 0:
        return "⚠️ داده برای تحلیل در دسترس نیست."
    trend = "📈 **صعودی**" if c > 0 else "📉 **نزولی**" if c < 0 else "➖ **خنثی**"
    rsi_note = "نزدیک اشباع خرید" if pct > 2 else "نزدیک اشباع فروش" if pct < -2 else "متعادل"
    return f"📊 **تحلیل روند**\n\n{trend}\n`{p:,} تومان`\n\nتغییر ۲۴ساعته: `{c:+,} تومان` ({pct:+.2f}%)`\n\n🔍 RSI: {rsi_note}\n📌 حمایت: ~{int(p*0.98):,}\n📌 مقاومت: ~{int(p*1.02):,}"

def get_signal_text():
    p, c, pct = fetch_mazane_gold()
    if p == 0:
        return "⚠️ داده برای سیگنال در دسترس نیست."
    tp = int(p * 1.02)
    sl = int(p * 0.99)
    if pct >= 1.5:
        return f"📈 **سیگنال خرید**\n\n`{p:,}`\n✅ ورود: `{p:,}`\n🎯 TP: `{tp:,}` (+2%)\n🛑 SL: `{sl:,}` (-1%)\n📊 RR: 1:2"
    elif pct <= -1.5:
        return f"📉 **سیگنال فروش**\n\n`{p:,}`\n✅ ورود: `{p:,}`\n🎯 TP: `{sl:,}` (-1%)\n🛑 SL: `{tp:,}` (+2%)\n📊 RR: 1:2"
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
    return "ربات طلا — TradingView"

if __name__ == '__main__':
    app.run()
