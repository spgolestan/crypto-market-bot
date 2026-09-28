import os
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "سلام 👋\n"
        "ربات تحلیل بازار فعال است."
    )


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")

    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN تنظیم نشده است.")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))

    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
