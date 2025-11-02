from flask import Flask, request, abort
import requests
import json
import logging
import time
import threading
import random

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

TELEGRAM_TOKEN = "8296855766:AAEAOO_NA2Q0GROFMKACAVV2ZnkxvDBroWM"
WEBHOOK_URL = "https://abshodeh.onrender.com/webhook"
BRS_API_URL = "https://brsapi.ir/Api/Market/Gold_Currency.php?key=BFnYYJjKvtuvPhtIZ2WfyFNhE54TG6ly"
PROXY_API_URL = "https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&country=IR&anonymity=elite&timeout=2000"
NOBITEX_URL = "https://api.nobitex.ir/v2/orderbook/XAUTUSDT"

keyboard = {"inline_keyboard": [[{"text": "🔄 استعلام مجدد", "callback_data": "get_price"}]]}
webhook_set = False
cached_price = {"price": 45555000, "change": 948000, "percent": 2.13, "timestamp": 0}
CACHE_TIME = 90
live_proxies = []
proxy_lock = threading.Lock()

def update_proxies():
    global live_proxies
    while True:
        try:
            resp = requests.get(PROXY_API_URL, timeout=8).text.strip()
            candidates = [f"http://{p}" for p in resp.split('\n') if p.strip()][:12]
            logger.info(f"دریافت {len(candidates)} پروکسی تازه")

            tested = []
            for proxy_url in candidates:
                proxy = {"http": proxy_url, "https": proxy_url}
                try:
                    r = requests.get(BRS_API_URL, proxies=proxy, timeout=4)
                    if r.status_code == 200 and 'IR_GOLD_MELTED' in r.text:
                        tested.append(proxy)
                        logger.info(f"پروکسی زنده: {proxy_url}")
                except:
                    pass
            with proxy_lock:
                live_proxies = tested[:3]
            logger.info(f"تعداد پروکسی‌های زنده: {len(live_proxies)}")
        except Exception as e:
            logger.error(f"خطا در بروزرسانی پروکسی: {e}")
        time.sleep(90)

threading.Thread(target=update_proxies, daemon=True).start()

def fetch_gold_price():
    global cached_price
    now = time.time()
    if now - cached_price["timestamp"] < CACHE_TIME:
        return cached_price["price"], cached_price["change"], cached_price["percent"]

    with proxy_lock:
        proxies = live_proxies.copy()
    if proxies:
        random.shuffle(proxies)
        for proxy in proxies:
            try:
                resp = requests.get(BRS_API_URL, proxies=proxy, timeout=8).json()
                for item in resp.get('gold', []):
                    if item.get('symbol') == 'IR_GOLD_MELTED':
                        price = int(item['price'])
                        change = item.get('change_value', 0)
                        percent = item.get('change_percent', 0)
                        cached_price.update({"price": price, "change": change, "percent": percent, "timestamp": now})
                        logger.info(f"قیمت واقعی brsapi.ir: {price:,} تومان")
                        return price, change, percent
            except Exception as e:
                logger.warning(f"پروکسی شکست: {e}")

    try:
        resp = requests.get(NOBITEX_URL, timeout=8).json()
        if resp.get('status') == 'ok':
            bids = float(resp['bids'][0][0]) if resp['bids'] else 0
            asks = float(resp['asks'][0][0]) if resp['asks'] else 0
            price_tether = (bids + asks) / 2
            price_gram = int(price_tether * 600000 / 31.1035 * 4.608)
            logger.info(f"Nobitex fallback: {price_gram:,} تومان")
            return price_gram, 0, 0
    except Exception as e:
        logger.error(f"Nobitex خطا: {e}")

    return 45555000, 948000, 2.13

def send_price(chat_id):
    price, change, percent = fetch_gold_price()
    message = f"💰 **قیمت طلای آب‌شده**\n`{price:,} تومان`\n\n{'📈' if change > 0 else '📉'} تغییر: `{change:+,} تومان` ({percent:+.2f}%)\n\nکلیک برای بروزرسانی 👇"
    payload = {'chat_id': chat_id, 'text': message, 'parse_mode': 'Markdown', 'reply_markup': json.dumps(keyboard)}
    try:
        resp = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", data=payload, timeout=10).json()
        if resp.get('ok'):
            logger.info(f"پیام ارسال شد به {chat_id}")
    except Exception as e:
        logger.error(f"ارسال شکست: {e}")

def edit_price(chat_id, message_id):
    price, change, percent = fetch_gold_price()
    new_text = f"💰 **قیمت طلای آب‌شده**\n`{price:,} تومان`\n\n{'📈' if change > 0 else '📉'} تغییر: `{change:+,} تومان` ({percent:+.2f}%)\n\nکلیک برای بروزرسانی 👇"
    payload = {'chat_id': chat_id, 'message_id': message_id, 'text': new_text, 'parse_mode': 'Markdown', 'reply_markup': json.dumps(keyboard)}
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText", data=payload, timeout=10)
    except Exception as e:
        logger.error(f"ویرایش شکست: {e}")

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        update = request.get_json()
        if 'message' in update and update['message'].get('text', '').strip() == '/start':
            send_price(update['message']['chat']['id'])
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
    return "ربات طلای آب‌شده — پروکسی اتومات"

if __name__ == '__main__':
    app.run()
