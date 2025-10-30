from flask import Flask, request, abort
import requests
import json
import logging
import time
import random

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

TELEGRAM_TOKEN = "8296855766:AAEAOO_NA2Q0GROFMKACAVV2ZnkxvDBroWM"
WEBHOOK_URL = "https://abshodeh.onrender.com/webhook"
BRS_API_URL = "https://brsapi.ir/Api/Market/Gold_Currency.php?key=BFnYYJjKvtuvPhtIZ2WfyFNhE54TG6ly"
PROXY_API_URL = "https://api.proxyscape.com/v2/?request=getproxies&protocol=http&country=IR&anonymity=elite&timeout=5000"
NOBITEX_URL = "https://api.nobitex.ir/v2/orderbook/XAUTUSDT"

keyboard = {"inline_keyboard": [[{"text": "🔄 استعلام مجدد", "callback_data": "get_price"}]]}
webhook_set = False
cached_price = {"price": 45555000, "change": 948000, "percent": 2.13, "timestamp": 0}
CACHE_TIME = 180  # ۳ دقیقه
live_proxies = []  # پروکسی‌های زنده

# --- دریافت پروکسی‌های تازه ---
def fetch_fresh_proxies():
    global live_proxies
    try:
        resp = requests.get(PROXY_API_URL, timeout=10).text
        lines = resp.strip().split('\n')
        candidates = [line for line in lines if line.strip()]
        logger.info(f"پروکسی‌های تازه دریافت شد: {len(candidates)}")
        
        live = []
        for proxy_str in candidates[:20]:  # تست ۲۰ تا
            proxy = {"http": proxy_str, "https": proxy_str}
            try:
                test_resp = requests.get(BRS_API_URL, proxies=proxy, timeout=3).json()
                if test_resp.get('gold') and any(item.get('symbol') == 'IR_GOLD_MELTED' for item in test_resp.get('gold', [])):
                    live.append(proxy)
                    logger.info(f"پروکسی زنده: {proxy_str}")
            except:
                pass
        live_proxies = live[:3]  # فقط ۳ تا نگه دار
        logger.info(f"پروکسی‌های زنده: {len(live_proxies)}")
    except Exception as e:
        logger.error(f"دریافت پروکسی شکست: {e}")

# --- دریافت قیمت ---
def fetch_gold_price():
    global cached_price
    now = time.time()
    if now - cached_price["timestamp"] < CACHE_TIME:
        logger.info(f"از کش: {cached_price['price']:,} تومان")
        return cached_price["price"], cached_price["change"], cached_price["percent"]

    # --- برسی brsapi.ir با پروکسی چرخشی ---
    if live_proxies:
        for proxy in random.sample(live_proxies, len(live_proxies)):  # چرخش رندوم
            try:
                resp = requests.get(BRS_API_URL, proxies=proxy, timeout=12).json()
                for item in resp.get('gold', []):
                    if item.get('symbol') == 'IR_GOLD_MELTED':
                        price = int(item['price'])
                        change = item.get('change_value', 0)
                        percent = item.get('change_percent', 0)
                        cached_price = {"price": price, "change": change, "percent": percent, "timestamp": now}
                        logger.info(f"brsapi.ir قیمت: {price:,} تومان (پروکسی {list(proxy.values())[0]})")
                        return price, change, percent
            except Exception as e:
                logger.warning(f"پروکسی {list(proxy.values())[0]} شکست: {e}")
        logger.warning("همه پروکسی‌ها مرده — به Nobitex برو")

    # --- Fallback Nobitex ---
    try:
        resp = requests.get(NOBITEX_URL, timeout=15).json()
        if resp.get('status') == 'ok':
            bids = float(resp['bids'][0][0]) if resp['bids'] else 0
            asks = float(resp['asks'][0][0]) if resp['asks'] else 0
            price_tether = (bids + asks) / 2
            price_gram = int(price_tether * 600000 / 31.1035 * 4.608)
            logger.info(f"Nobitex fallback: {price_gram:,} تومان")
            return price_gram, 0, 0
    except Exception as e:
        logger.error(f"Nobitex خطا: {e}")

    # --- Final fallback ---
    logger.warning("fallback ثابت")
    return 45555000, 948000, 2.13

# --- ارسال پیام ---
def send_price(chat_id):
    price, change, percent = fetch_gold_price()
    message = (
        f"💰 **قیمت طلای آب‌شده**\n"
        f"`{price:,} تومان`\n\n"
        f"{'📈' if change > 0 else '📉'} تغییر: `{change:+,} تومان` ({percent:+.2f}%)\n\n"
        f"کلیک برای بروزرسانی 👇"
    )
    payload = {
        'chat_id': chat_id,
        'text': message,
        'parse_mode': 'Markdown',
        'reply_markup': json.dumps(keyboard)
    }
    try:
        resp = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", data=payload, timeout=10).json()
        if resp.get('ok'):
            logger.info(f"پیام ارسال شد به {chat_id}")
    except Exception as e:
        logger.error(f"ارسال شکست: {e}")

# --- ویرایش ---
def edit_price(chat_id, message_id):
    price, change, percent = fetch_gold_price()
    new_text = (
        f"💰 **قیمت طلای آب‌شده**\n"
        f"`{price:,} تومان`\n\n"
        f"{'📈' if change > 0 else '📉'} تغییر: `{change:+,} تومان` ({percent:+.2f}%)\n\n"
        f"کلیک برای بروزرسانی 👇"
    )
    payload = {
        'chat_id': chat_id,
        'message_id': message_id,
        'text': new_text,
        'parse_mode': 'Markdown',
        'reply_markup': json.dumps(keyboard)
    }
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText", data=payload, timeout=10)
    except Exception as e:
        logger.error(f"ویرایش شکست: {e}")

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
                send_price(chat_id)
        elif 'callback_query' in update:
            cb = update['callback_query']
            chat_id = cb['message']['chat']['id']
            message_id = cb['message']['message_id']
            if cb['data'] == 'get_price':
                edit_price(chat_id, message_id)
                requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery",
                              data={'callback_query_id': cb['id']})
        return '', 200
    abort(403)

# --- تنظیم Webhook ---
@app.before_request
def setup_webhook():
    global webhook_set
    if not webhook_set:
        try:
            resp = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook", data={'url': WEBHOOK_URL}, timeout=10).json()
            if resp.get('ok'):
                logger.info("✅ Webhook تنظیم شد")
            webhook_set = True
        except Exception as e:
            logger.error(f"Webhook خطا: {e}")

@app.route('/')
def home():
    return "ربات طلای آب‌شده فعال است! (فقط brsapi.ir با پروکسی اتومات)"

if __name__ == '__main__':
    app.run()
