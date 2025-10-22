import os
import json
import logging
import requests
from datetime import datetime, date
from flask import Flask, request, jsonify
import telebot
import threading
import schedule
import time
import urllib3

# غیرفعال کردن هشدارهای SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# تنظیمات لاگینگ به stdout/stderr
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# خواندن متغیرهای محیطی
TOKEN = os.getenv("BOT_TOKEN")
API_KEY = os.getenv("API_KEY")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://janigoldbot.onrender.com/webhook")
TEST_CHAT_ID = "249634530"  # chat_id خودت برای تست

if not TOKEN or not API_KEY:
    logging.error("BOT_TOKEN یا API_KEY تنظیم نشده است.")
    raise ValueError("لطفاً متغیرهای محیطی BOT_TOKEN و API_KEY را در Render تنظیم کنید.")

# راه‌اندازی Flask و Telebot
app = Flask(__name__)
bot = telebot.TeleBot(TOKEN)

# === تست اولیه BOT_TOKEN و ارسال پیام تست ===
def test_bot_token():
    try:
        response = requests.get(f"https://api.telegram.org/bot{TOKEN}/getMe")
        data = response.json()
        if data.get("ok"):
            logging.info(f"✅ BOT_TOKEN معتبر است: {data['result']['username']}")
            # ارسال پیام تست به TEST_CHAT_ID
            bot.send_message(TEST_CHAT_ID, "🟢 ربات با موفقیت استارت شد!")
            logging.info(f"پیام تست به {TEST_CHAT_ID} ارسال شد.")
        else:
            logging.error(f"❌ BOT_TOKEN نامعتبر: {data}")
    except Exception as e:
        logging.error(f"❌ خطا در تست BOT_TOKEN: {e}")

# === دریافت قیمت از BrsApi.ir ===
def get_gold_price():
    url = f"https://brsapi.ir/Api/Market/Gold_Currency.php?key={API_KEY}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*"
    }
    try:
        logging.debug("📡 ارسال درخواست به BrsApi.ir...")
        response = requests.get(url, headers=headers, timeout=10, verify=False)
        response.raise_for_status()
        data = response.json()
        logging.debug(f"پاسخ API: {json.dumps(data, ensure_ascii=False)}")
        if isinstance(data, dict) and 'gold' in data:
            for item in data['gold']:
                if item.get("symbol") == "IR_GOLD_MELTED":
                    price_str = str(item.get("price", "0")).replace(",", "")
                    price = int(price_str)
                    logging.info(f"💰 قیمت دریافتی: {price:,}")
                    return price
            logging.warning("نماد طلای آبشده یافت نشد.")
        else:
            logging.error("پاسخ API حاوی کلید 'gold' نیست.")
        return None
    except Exception as e:
        logging.error(f"خطا در دریافت قیمت: {e}")
        return None

# === هندلرهای تلگرام ===
@bot.message_handler(commands=['start'])
def start(message):
    logging.info(f"👤 کاربر جدید: {message.chat.id}")
    try:
        bot.reply_to(message, "سلام! ربات فعال شد ✅\nدستور /price برای استعلام دستی.")
        logging.info(f"پاسخ /start به {message.chat.id} ارسال شد.")
    except Exception as e:
        logging.error(f"خطا در پاسخ به /start برای {message.chat.id}: {e}")

@bot.message_handler(commands=['price'])
def manual_price(message):
    logging.info(f"📥 درخواست دستی قیمت از {message.chat.id}")
    try:
        price = get_gold_price()
        if price is None:
            bot.reply_to(message, "❌ خطای دریافت قیمت از API")
            logging.error(f"خطا در دریافت قیمت برای {message.chat.id}")
        else:
            msg = f"📊 قیمت دستی: {price:,}"
            bot.reply_to(message, msg, parse_mode="Markdown")
            logging.info(f"پاسخ /price به {message.chat.id} ارسال شد.")
    except Exception as e:
        logging.error(f"خطا در پاسخ به /price برای {message.chat.id}: {e}")
        bot.reply_to(message, "❌ خطا در پردازش درخواست")

# === روت‌های Flask ===
@app.route('/')
def index():
    logging.debug("Health check / درخواست شد.")
    return "OK", 200

@app.route('/health')
def health():
    logging.debug("Health check /health درخواست شد.")
    return "OK", 200

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        logging.debug(f"Webhook دریافت شد: {json_string}")
        try:
            update = telebot.types.Update.de_json(json_string)
            if update:
                logging.debug(f"Update پردازش شد: {update}")
                bot.process_new_updates([update])
            else:
                logging.warning("Update نامعتبر دریافت شد.")
        except Exception as e:
            logging.error(f"خطا در پردازش webhook: {e}")
        return '', 200
    else:
        logging.warning("درخواست webhook با content-type نامعتبر")
        return 'Bad Request', 400

@app.route('/status')
def status():
    logging.debug("درخواست وضعیت ربات")
    return jsonify({
        "active_users_count": 0,
        "last_price": get_gold_price(),
        "status": "running"
    })

# === زمان‌بندی چک خودکار ===
def run_scheduler():
    logging.info("Scheduler شروع شد.")
    schedule.every(2).minutes.do(lambda: logging.info("چک قیمت دوره‌ای اجرا شد."))
    while True:
        schedule.run_pending()
        time.sleep(1)

# === اجرای اولیه ===
if __name__ == "__main__":
    logging.info("🚀 راه‌اندازی ربات...")
    test_bot_token()  # تست BOT_TOKEN
    try:
        bot.remove_webhook()
        time.sleep(1)
        bot.set_webhook(url=WEBHOOK_URL)
        logging.info(f"Webhook تنظیم شد: {WEBHOOK_URL}")
    except Exception as e:
        logging.error(f"خطا در تنظیم webhook: {e}")

    threading.Thread(target=run_scheduler, daemon=True).start()

    port = int(os.getenv("PORT", 10000))
    logging.info(f"🌐 سرور روی پورت {port} شروع می‌شود...")
    app.run(host="0.0.0.0", port=port)
