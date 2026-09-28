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
        "BTC": "BTC-USD",
        "ETH": "ETH-USD"
    }

    if symbol not in symbols:
        await update.message.reply_text(
            "فعلاً فقط این ارزها برای تست فعال هستند:\n\n"
            "/price BTC\n"
            "/price ETH"
        )
        return

    product_id = symbols[symbol]

    url = (
        f"https://api.exchange.coinbase.com/"
        f"products/{product_id}/ticker"
    )

    stats_url = (
        f"https://api.exchange.coinbase.com/"
        f"products/{product_id}/stats"
    )

    try:

        async with httpx.AsyncClient(timeout=10) as client:

            ticker_response = await client.get(
                url,
                headers={
                    "Accept": "application/json"
                }
            )

            ticker_response.raise_for_status()

            ticker_data = ticker_response.json()

            stats_response = await client.get(
                stats_url,
                headers={
                    "Accept": "application/json"
                }
            )

            stats_response.raise_for_status()

            stats_data = stats_response.json()

        price_value = float(
            ticker_data["price"]
        )

        open_24h = float(
            stats_data["open"]
        )

        high_24h = float(
            stats_data["high"]
        )

        low_24h = float(
            stats_data["low"]
        )

        change_24h = (
            (price_value - open_24h)
            / open_24h
            * 100
        )

        if change_24h >= 0:
            change_icon = "📈"
        else:
            change_icon = "📉"

        message = (
            f"📊 {symbol}/USD\n\n"
            f"💰 قیمت: ${price_value:,.2f}\n"
            f"{change_icon} تغییر ۲۴ ساعت: {change_24h:+.2f}%\n\n"
            f"🔺 سقف ۲۴ ساعت: ${high_24h:,.2f}\n"
            f"🔻 کف ۲۴ ساعت: ${low_24h:,.2f}"
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
# ==========
async def candles(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if len(context.args) < 2:
        await update.message.reply_text(
            "فرمت دستور:\n\n"
            "/candles BTC 1h\n\n"
            "مثال:\n"
            "/candles BTC 1h"
        )
        return

    symbol = context.args[0].upper()
    timeframe = context.args[1].lower()

    symbols = {
        "BTC": "BTC-USD",
        "ETH": "ETH-USD"
    }

    if symbol not in symbols:
        await update.message.reply_text(
            "فعلاً فقط BTC و ETH فعال هستند."
        )
        return

    timeframes = {
        "1m": 60,
        "5m": 300,
        "15m": 900,
        "1h": 3600,
        "6h": 21600,
        "1d": 86400
    }

    if timeframe not in timeframes:
        await update.message.reply_text(
            "تایم‌فریم‌های قابل استفاده:\n\n"
            "1m\n"
            "5m\n"
            "15m\n"
            "1h\n"
            "6h\n"
            "1d"
        )
        return

    product_id = symbols[symbol]

    url = (
        f"https://api.exchange.coinbase.com/"
        f"products/{product_id}/candles"
    )

    params = {
        "granularity": timeframes[timeframe]
    }

    try:

        async with httpx.AsyncClient(timeout=10) as client:

            response = await client.get(
                url,
                params=params,
                headers={
                    "Accept": "application/json"
                }
            )

            response.raise_for_status()

            data = response.json()

        if not data:
            await update.message.reply_text(
                "❌ اطلاعات کندلی دریافت نشد."
            )
            return

        # Coinbase کندل‌ها را به صورت:
        # [time, low, high, open, close, volume]
        # برمی‌گرداند.

        candles_data = data[:5]

        message = (
            f"🕯 {symbol}/USD\n"
            f"⏱ تایم‌فریم: {timeframe}\n\n"
        )

        for candle in candles_data:

            timestamp = candle[0]
            low = float(candle[1])
            high = float(candle[2])
            open_price = float(candle[3])
            close = float(candle[4])
            volume = float(candle[5])

            message += (
                f"━━━━━━━━━━━━\n"
                f"Open:  ${open_price:,.2f}\n"
                f"High:  ${high:,.2f}\n"
                f"Low:   ${low:,.2f}\n"
                f"Close: ${close:,.2f}\n"
                f"Volume: {volume:,.4f}\n"
            )

        await update.message.reply_text(
            message
        )

    except Exception as e:

        print(
            f"Candles API error: {e}",
            flush=True
        )

        await update.message.reply_text(
            "❌ دریافت اطلاعات کندلی با خطا مواجه شد."
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
    telegram_application.add_handler(
        CommandHandler(
            "candles",
            candles
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
