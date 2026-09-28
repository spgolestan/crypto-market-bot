import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes


# =========================
# Telegram
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "سلام 👋\n"
        "ربات تحلیل بازار فعال است.\n\n"
        "برای دریافت قیمت:\n"
        "/price BTC"
    )


# =========================
# Price
# =========================

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not context.args:
        await update.message.reply_text(
            "نمونه استفاده:\n"
            "/price BTC"
        )
        return

    symbol = context.args[0].upper()

    # فعلاً فقط BTC و ETH را برای تست می‌پذیریم
    symbols = {
        "BTC": "bitcoin",
        "ETH": "ethereum"
    }

    if symbol not in symbols:
        await update.message.reply_text(
            "فعلاً این ارز برای تست پشتیبانی نمی‌شود.\n\n"
            "نمونه:\n"
            "/price BTC\n"
            "/price ETH"
        )
        return

    coin_id = symbols[symbol]

    url = "https://api.coingecko.com/api/v3/simple/price"

    params = {
        "ids": coin_id,
        "vs_currencies": "usd",
        "include_24hr_change": "true"
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:

            response = await client.get(
                url,
                params=params
            )

            response.raise_for_status()

            data = response.json()

        coin_data = data[coin_id]

        price_value = coin_data["usd"]
        change_24h = coin_data.get("usd_24h_change", 0)

        message = (
            f"📊 {symbol}/USDT\n\n"
            f"💰 قیمت: ${price_value:,.2f}\n"
            f"📈 تغییر ۲۴ ساعت: {change_24h:+.2f}%"
        )

        await update.message.reply_text(message)

    except Exception as e:

        print(f"Price API error: {e}")

        await update.message.reply_text(
            "❌ دریافت اطلاعات بازار با خطا مواجه شد.\n"
            "لطفاً چند لحظه بعد دوباره امتحان کن."
        )


# =========================
# Render Web Server
# =========================

class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):

        self.send_response(200)

        self.send_header(
            "Content-Type",
            "text/plain; charset=utf-8"
        )

        self.end_headers()

        self.wfile.write(
            b"Crypto Market Bot is running!"
        )

    def log_message(self, format, *args):
        return


def start_web_server():

    port = int(
        os.environ.get("PORT", 10000)
    )

    server = HTTPServer(
        ("0.0.0.0", port),
        HealthHandler
    )

    print(
        f"Web server running on port {port}"
    )

    server.serve_forever()


# =========================
# Main
# =========================

def main():

    token = os.environ.get(
        "TELEGRAM_BOT_TOKEN"
    )

    if not token:
        raise ValueError(
            "TELEGRAM_BOT_TOKEN environment variable is not set."
        )

    # Render HTTP server
    web_thread = threading.Thread(
        target=start_web_server,
        daemon=True
    )

    web_thread.start()

    # Telegram application
    app = (
        Application
        .builder()
        .token(token)
        .build()
    )

    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    app.add_handler(
        CommandHandler(
            "price",
            price
        )
    )

    print("Telegram bot is running...")

    app.run_polling()


if __name__ == "__main__":
    main()
