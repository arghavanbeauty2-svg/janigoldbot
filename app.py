import os
import logging
from flask import Flask, request
import telebot
import time
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://janigoldbot.onrender.com/webhook")

if not TOKEN:
    logging.error("BOT_TOKEN تنظیم نشده است.")
    raise ValueError("BOT_TOKEN را در Render تنظیم کنید.")

app = Flask(__name__)
bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=['start'])
def start(message):
    logging.info(f"👤 /start از {message.chat.id}: {message.text}")
    try:
        bot.reply_to(message, "سلام! ربات فعال شد ✅")
        logging.info(f"پاسخ /start به {message.chat.id} ارسال شد.")
    except Exception as e:
        logging.error(f"خطا در /start: {e}")

@bot.message_handler(commands=['price'])
def price(message):
    logging.info(f"📥 /price از {message.chat.id}")
    try:
        bot.reply_to(message, "قیمت: 46,735,000 تومان (تست)")
        logging.info(f"پاسخ /price به {message.chat.id} ارسال شد.")
    except Exception as e:
        logging.error(f"خطا در /price: {e}")

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        logging.debug(f"Webhook: {json_string}")
        try:
            update = telebot.types.Update.de_json(json_string)
            bot.process_new_updates([update])
            logging.info("Webhook پردازش شد.")
        except Exception as e:
            logging.error(f"خطا در webhook: {e}")
        return '', 200
    return 'Bad Request', 400

@app.route('/')
def health():
    logging.debug("Health check / درخواست شد.")
    return "OK", 200

@app.route('/health')
def health_alt():
    logging.debug("Health check /health درخواست شد.")
    return "OK", 200

if __name__ == "__main__":
    logging.info("🚀 ربات شروع شد...")
    try:
        bot.remove_webhook()
        time.sleep(1)
        bot.set_webhook(url=WEBHOOK_URL)
        logging.info(f"Webhook ست شد: {WEBHOOK_URL}")
    except Exception as e:
        logging.error(f"خطا در webhook: {e}")

    port = int(os.getenv("PORT", 10000))
    logging.info(f"سرور روی پورت {port} شروع می‌شود...")
    app.run(host="0.0.0.0", port=port)
