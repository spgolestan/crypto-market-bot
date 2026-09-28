import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes


# -----------------------------
# Telegram Bot
# -----------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "سلام 👋\n"
        "ربات تحلیل بازار فعال است."
    )


# -----------------------------
# HTTP Server for Render
# -----------------------------

class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Crypto Market Bot is running!")

    def log_message(self, format, *args):
        return


def start_web_server():
    port = int(os.environ.get("PORT", 10000))

    server = HTTPServer(("0.0.0.0", port), HealthHandler)

    print(f"Web server running on port {port}")

    server.serve_forever()


# -----------------------------
# Main
# -----------------------------

def main():

    token = os.environ.get("TELEGRAM_BOT_TOKEN")

    if not token:
        raise ValueError(
            "TELEGRAM_BOT_TOKEN environment variable is not set."
        )

    # Start HTTP server in background
    web_thread = threading.Thread(
        target=start_web_server,
        daemon=True
    )

    web_thread.start()

    # Create Telegram application
    app = Application.builder().token(token).build()

    # Telegram commands
    app.add_handler(
        CommandHandler("start", start)
    )

    print("Telegram bot is running...")

    # Start Telegram polling
    app.run_polling()


if __name__ == "__main__":
    main()
