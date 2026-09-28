import os
import asyncio
import threading
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes


# =========================
# Settings
# =========================

RENDER_URL = "https://crypto-market-bot-ozg7.onrender.com"

WEBHOOK_PATH = "/telegram-webhook"

WEBHOOK_URL = RENDER_URL + WEBHOOK_PATH


# =========================
# Global objects
# =========================

telegram_application = None
event_loop = None


# =========================
# Telegram Commands
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "سلام 👋\n"
        "ربات تحلیل بازار فعال است.\n\n"
        "دریافت قیمت:\n"
        "/price BTC\n"
        "/price ETH"
    )


async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not context.args:

        await update.message.reply_text(
            "لطفاً نام ارز را وارد کن.\n\n"
            "مثال:\n"
            "/price BTC"
        )

        return

    symbol = context.args[0].upper()

    symbols = {
        "BTC": "BTCUSDT",
        "ETH": "ETHUSDT"
    }

    if symbol not in symbols:

        await update.message.reply_text(
            "فعلاً فقط این ارزها برای تست فعال هستند:\n\n"
            "/price BTC\n"
            "/price ETH"
        )

        return

    trading_symbol = symbols[symbol]

    url = "https://api.binance.com/api/v3/ticker/24hr"

    params = {
        "symbol": trading_symbol
    }

    try:

        async with httpx.AsyncClient(timeout=10) as client:

            response = await client.get(
                url,
                params=params
            )

            response.raise_for_status()

            data = response.json()

        price_value = float(
            data["lastPrice"]
        )

        change_24h = float(
            data["priceChangePercent"]
        )

        message = (
            f"📊 {symbol}/USDT\n\n"
            f"💰 قیمت: ${price_value:,.2f}\n"
            f"📈 تغییر ۲۴ ساعت: {change_24h:+.2f}%"
        )

        await update.message.reply_text(
            message
        )

    except Exception as e:

        print(
            f"Price API error: {e}",
            flush=True
        )

        await update.message.reply_text(
            "❌ دریافت اطلاعات بازار با خطا مواجه شد."
        )


# =========================
# HTTP Server
# =========================

class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):

        if self.path == "/":

            self.send_response(200)

            self.send_header(
                "Content-Type",
                "text/plain; charset=utf-8"
            )

            self.end_headers()

            self.wfile.write(
                b"Crypto Market Bot is running!"
            )

            return

        self.send_response(404)

        self.end_headers()


    def do_POST(self):

        if self.path != WEBHOOK_PATH:

            self.send_response(404)

            self.end_headers()

            return

        try:

            content_length = int(
                self.headers.get(
                    "Content-Length",
                    0
                )
            )

            body = self.rfile.read(
                content_length
            )

            print(
                "Telegram webhook received",
                flush=True
            )

            data = json.loads(
                body.decode("utf-8")
            )

            update = Update.de_json(
                data,
                telegram_application.bot
            )

            future = asyncio.run_coroutine_threadsafe(
                telegram_application.process_update(update),
                event_loop
            )

            future.add_done_callback(
                lambda f: print(
                    f"Update processing finished: {f.exception()}"
                    if f.exception()
                    else "Update processed successfully",
                    flush=True
                )
            )

            self.send_response(200)

            self.send_header(
                "Content-Type",
                "text/plain"
            )

            self.end_headers()

            self.wfile.write(
                b"OK"
            )

        except Exception as e:

            print(
                f"Webhook error: {e}",
                flush=True
            )

            self.send_response(500)

            self.end_headers()


    def log_message(self, format, *args):
        return


# =========================
# HTTP Server
# =========================

def start_web_server():

    port = int(
        os.environ.get(
            "PORT",
            "10000"
        )
    )

    print(
        f"Starting HTTP server on port {port}...",
        flush=True
    )

    server = HTTPServer(
        ("0.0.0.0", port),
        HealthHandler
    )

    print(
        f"HTTP server is listening on port {port}",
        flush=True
    )

    server.serve_forever()


# =========================
# Telegram
# =========================

async def start_telegram():

    global telegram_application

    token = os.environ.get(
        "TELEGRAM_BOT_TOKEN"
    )

    if not token:

        print(
            "ERROR: TELEGRAM_BOT_TOKEN is not set!",
            flush=True
        )

        return

    print(
        "Starting Telegram application...",
        flush=True
    )

    telegram_application = (
        Application
        .builder()
        .token(token)
        .build()
    )

    telegram_application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    telegram_application.add_handler(
        CommandHandler(
            "price",
            price
        )
    )

    await telegram_application.initialize()

    await telegram_application.start()

    print(
        "Setting Telegram webhook...",
        flush=True
    )

    await telegram_application.bot.set_webhook(
        url=WEBHOOK_URL,
        drop_pending_updates=True
    )

    print(
        f"Webhook set: {WEBHOOK_URL}",
        flush=True
    )

    print(
        "Telegram bot is running with WEBHOOK!",
        flush=True
    )


# =========================
# Main
# =========================

def main():

    global event_loop

    print(
        "Starting main application...",
        flush=True
    )

    event_loop = asyncio.new_event_loop()

    asyncio.set_event_loop(
        event_loop
    )

    # اول HTTP Server را بالا می‌آوریم
    web_thread = threading.Thread(
        target=start_web_server,
        daemon=True
    )

    web_thread.start()

    # سپس Telegram را راه‌اندازی می‌کنیم
    event_loop.run_until_complete(
        start_telegram()
    )

    print(
        "Event loop is now running...",
        flush=True
    )

    # بسیار مهم:
    # Event Loop باید همیشه در حال اجرا بماند
    event_loop.run_forever()


if __name__ == "__main__":

    main()
