import os
import json
import logging
import time
import threading
import random
import requests
from flask import Flask, request, abort

# --- تنظیمات لاگ ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- متغیرهای محیطی (حتماً در Render یا محیط اجرا ست کنید) ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    raise ValueError("متغیر محیطی TELEGRAM_TOKEN تنظیم نشده است.")

WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://abshodeh.onrender.com/webhook").rstrip('/')
BRS_API_KEY = os.getenv("BRS_API_KEY", "BFnYYJjKvtuvPhtIZ2WfyFNhE54TG6ly")

# --- ثابت‌ها ---
BRS_API_URL = f"https://brsapi.ir/Api/Market/Gold_Currency.php?key={BRS_API_KEY}"
PROXY_API_URL = "https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&country=IR&anonymity=elite&timeout=2000"
NOBITEX_URL = "https://api.nobitex.ir/v2/orderbook/XAUTUSDT"

KEYBOARD = {"inline_keyboard": [[{"text": "🔄 استعلام مجدد", "callback_data": "get_price"}]]}

# --- وضعیت‌های جهانی ---
webhook_set = False
cached_price = {
    "price": 45555000,
    "change": 948000,
    "percent": 2.13,
    "timestamp": 0,
    "source": "fallback"
}
CACHE_TIME = 90  # seconds

live_proxies = []
proxy_lock = threading.Lock()

# --- تابع به‌روزرسانی پروکسی‌ها ---
def update_proxies():
    global live_proxies
    while True:
        try:
            logger.info("در حال دریافت لیست پروکسی‌ها...")
            resp = requests.get(PROXY_API_URL, timeout=8)
            resp.raise_for_status()
            candidates = [f"http://{p.strip()}" for p in resp.text.split('\n') if p.strip()][:12]
            logger.info(f"دریافت {len(candidates)} پروکسی تازه")

            tested = []
            for proxy_url in candidates:
                proxy = {"http": proxy_url, "https": proxy_url}
                try:
                    r = requests.get(BRS_API_URL, proxies=proxy, timeout=4)
                    if r.status_code == 200 and 'IR_GOLD_MELTED' in r.text:
                        tested.append(proxy)
                        logger.info(f"پروکسی زنده: {proxy_url}")
                except Exception as e:
                    logger.debug(f"پروکسی رد شد ({proxy_url}): {e}")

            with proxy_lock:
                live_proxies = tested[:3]
            logger.info(f"تعداد پروکسی‌های زنده: {len(live_proxies)}")
        except Exception as e:
            logger.error(f"خطا در بروزرسانی پروکسی: {e}")
        time.sleep(90)

# --- راه‌اندازی thread پروکسی ---
threading.Thread(target=update_proxies, daemon=True).start()

# --- دریافت قیمت طلا ---
def fetch_gold_price():
    global cached_price
    now = time.time()
    if now - cached_price["timestamp"] < CACHE_TIME:
        logger.debug("استفاده از داده‌های کش‌شده")
        return cached_price["price"], cached_price["change"], cached_price["percent"]

    # اولویت: BRS با پروکسی
    with proxy_lock:
        proxies_list = live_proxies.copy()
    if proxies_list:
        random.shuffle(proxies_list)
        for proxy in proxies_list:
            try:
                resp = requests.get(BRS_API_URL, proxies=proxy, timeout=8)
                resp.raise_for_status()
                data = resp.json()
                for item in data.get('gold', []):
                    if item.get('symbol') == 'IR_GOLD_MELTED':
                        price = int(item['price'])
                        change = item.get('change_value', 0)
                        percent = item.get('change_percent', 0)
                        cached_price.update({
                            "price": price,
                            "change": change,
                            "percent": percent,
                            "timestamp": now,
                            "source": "brsapi"
                        })
                        logger.info(f"قیمت brsapi.ir: {price:,} تومان")
                        return price, change, percent
            except Exception as e:
                logger.warning(f"پروکسی شکست خورد: {e}")

    # fallback: Nobitex
    try:
        resp = requests.get(NOBITEX_URL, timeout=8)
        resp.raise_for_status()
        data = resp.json()
        if data.get('status') == 'ok':
            bids = float(data['bids'][0][0]) if data.get('bids') else 0
            asks = float(data['asks'][0][0]) if data.get('asks') else 0
            if bids > 0 and asks > 0:
                price_tether = (bids + asks) / 2
                # تبدیل XAUT/USDT → تومان بر اساس فرضیات فعلی
                price_gram = int(price_tether * 600000 / 31.1035 * 4.608)
                cached_price.update({
                    "price": price_gram,
                    "change": 0,
                    "percent": 0,
                    "timestamp": now,
                    "source": "nobitex"
                })
                logger.info(f"Nobitex fallback: {price_gram:,} تومان")
                return price_gram, 0, 0
    except Exception as e:
        logger.error(f"Nobitex خطا: {e}")

    # fallback نهایی
    logger.warning("همه منابع شکست خوردند — بازگشت به مقدار پیش‌فرض")
    return cached_price["price"], cached_price["change"], cached_price["percent"]

# --- ارسال پیام جدید ---
def send_price(chat_id):
    price, change, percent = fetch_gold_price()
    arrow = "📈" if change > 0 else "📉" if change < 0 else "➖"
    message = (
        f"💰 **قیمت طلای آب‌شده**\n"
        f"`{price:,} تومان`\n\n"
        f"{arrow} تغییر: `{change:+,} تومان` ({percent:+.2f}%)\n\n"
        f"کلیک برای بروزرسانی 👇"
    )
    payload = {
        'chat_id': chat_id,
        'text': message,
        'parse_mode': 'Markdown',
        'reply_markup': json.dumps(KEYBOARD, ensure_ascii=False)
    }
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        resp = requests.post(url, data=payload, timeout=10)
        resp.raise_for_status()
        result = resp.json()
        if result.get('ok'):
            logger.info(f"پیام ارسال شد به {chat_id}")
        else:
            logger.error(f"خطا در ارسال پیام: {result}")
    except Exception as e:
        logger.error(f"ارسال پیام شکست خورد: {e}")

# --- ویرایش پیام موجود ---
def edit_price(chat_id, message_id):
    price, change, percent = fetch_gold_price()
    arrow = "📈" if change > 0 else "📉" if change < 0 else "➖"
    new_text = (
        f"💰 **قیمت طلای آب‌شده**\n"
        f"`{price:,} تومان`\n\n"
        f"{arrow} تغییر: `{change:+,} تومان` ({percent:+.2f}%)\n\n"
        f"کلیک برای بروزرسانی 👇"
    )
    payload = {
        'chat_id': chat_id,
        'message_id': message_id,
        'text': new_text,
        'parse_mode': 'Markdown',
        'reply_markup': json.dumps(KEYBOARD, ensure_ascii=False)
    }
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText"
        requests.post(url, data=payload, timeout=10)
    except Exception as e:
        logger.error(f"ویرایش پیام شکست خورد: {e}")

# --- Flask App ---
app = Flask(__name__)

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') != 'application/json':
        abort(403)
    update = request.get_json()
    if not update:
        abort(400)

    if 'message' in update:
        text = update['message'].get('text', '').strip()
        chat_id = update['message']['chat']['id']
        if text == '/start':
            send_price(chat_id)

    elif 'callback_query' in update:
        cb = update['callback_query']
        if cb['data'] == 'get_price':
            try:
                edit_price(cb['message']['chat']['id'], cb['message']['message_id'])
            except KeyError:
                # پیام قدیمی یا حذف‌شده
                send_price(cb['from']['id'])
            # پاسخ به callback
            try:
                url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery"
                requests.post(url, data={'callback_query_id': cb['id']}, timeout=5)
            except Exception as e:
                logger.debug(f"خطا در پاسخ به callback: {e}")

    return '', 200

@app.route('/')
def home():
    return "ربات طلای آب‌شده — پروکسی اتوماتیک"

# --- تنظیم webhook در زمان راه‌اندازی ---
def set_webhook():
    global webhook_set
    if webhook_set:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook"
        resp = requests.post(url, data={'url': WEBHOOK_URL}, timeout=10)
        resp.raise_for_status()
        result = resp.json()
        if result.get('ok'):
            logger.info(f"Webhook با موفقیت تنظیم شد روی: {WEBHOOK_URL}")
            webhook_set = True
        else:
            logger.error(f"تنظیم webhook شکست خورد: {result}")
    except Exception as e:
        logger.error(f"خطا در تنظیم webhook: {e}")

# --- راه‌اندازی ---
if __name__ == '__main__':
    set_webhook()
    # در محیط Render، debug=False و host='0.0.0.0' ضروری است
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)), debug=False)
