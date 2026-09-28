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
# کندل
# =========================
async def rsi(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if len(context.args) < 2:
        await update.message.reply_text(
            "فرمت دستور:\n\n"
            "/rsi BTC 1h\n\n"
            "مثال:\n"
            "/rsi BTC 1h"
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

        if len(data) < 15:
            await update.message.reply_text(
                "❌ برای محاسبه RSI داده کافی دریافت نشد."
            )
            return

        # Coinbase:
        # [time, low, high, open, close, volume]

        # مرتب‌سازی از قدیمی به جدید
        data = sorted(
            data,
            key=lambda x: x[0]
        )

        closes = [
            float(candle[4])
            for candle in data
        ]

        period = 14

        gains = []
        losses = []

        for i in range(1, len(closes)):

            change = closes[i] - closes[i - 1]

            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))

        avg_gain = sum(
            gains[:period]
        ) / period

        avg_loss = sum(
            losses[:period]
        ) / period

        for i in range(period, len(gains)):

            avg_gain = (
                (avg_gain * (period - 1))
                + gains[i]
            ) / period

            avg_loss = (
                (avg_loss * (period - 1))
                + losses[i]
            ) / period

        if avg_loss == 0:

            rsi_value = 100

        else:

            rs = avg_gain / avg_loss

            rsi_value = (
                100
                - (100 / (1 + rs))
            )

        if rsi_value >= 70:

            status = "🔴 محدوده اشباع خرید"

        elif rsi_value <= 30:

            status = "🟢 محدوده اشباع فروش"

        else:

            status = "🟡 محدوده میانی"

        message = (
            f"📊 RSI Analysis\n\n"
            f"🪙 {symbol}/USD\n"
            f"⏱ تایم‌فریم: {timeframe}\n\n"
            f"RSI(14): {rsi_value:.2f}\n\n"
            f"وضعیت: {status}"
        )

        await update.message.reply_text(
            message
        )

    except Exception as e:

        print(
            f"RSI API error: {e}",
            flush=True
        )

        await update.message.reply_text(
            "❌ محاسبه RSI با خطا مواجه شد."
        )
# ===================
# RSI
# ==================
async def macd(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if len(context.args) < 2:
        await update.message.reply_text(
            "لطفاً ارز و تایم‌فریم را وارد کن.\n\n"
            "مثال:\n"
            "/macd BTC 1h"
        )
        return

    symbol = context.args[0].upper()
    timeframe = context.args[1].lower()

    symbols = {
        "BTC": "BTC-USD",
        "ETH": "ETH-USD"
    }

    timeframes = {
        "1m": 60,
        "5m": 300,
        "15m": 900,
        "1h": 3600,
        "6h": 21600,
        "1d": 86400
    }

    if symbol not in symbols:
        await update.message.reply_text(
            "فعلاً فقط BTC و ETH فعال هستند."
        )
        return

    if timeframe not in timeframes:
        await update.message.reply_text(
            "تایم‌فریم نامعتبر است.\n\n"
            "تایم‌فریم‌های مجاز:\n"
            "1m\n"
            "5m\n"
            "15m\n"
            "1h\n"
            "6h\n"
            "1d"
        )
        return

    product_id = symbols[symbol]
    granularity = timeframes[timeframe]

    url = (
        f"https://api.exchange.coinbase.com/"
        f"products/{product_id}/candles"
    )

    try:
        async with httpx.AsyncClient(timeout=10) as client:

            response = await client.get(
                url,
                params={"granularity": granularity},
                headers={"Accept": "application/json"}
            )

            response.raise_for_status()
            data = response.json()

        if len(data) < 35:
            await update.message.reply_text(
                "❌ اطلاعات کافی برای محاسبه MACD دریافت نشد."
            )
            return

        # مرتب‌سازی از قدیمی به جدید
        data.sort(key=lambda x: x[0])

        closes = [float(candle[4]) for candle in data]

        # EMA
        def calculate_ema(values, period):

            multiplier = 2 / (period + 1)

            ema = sum(values[:period]) / period
            ema_values = [ema]

            for price in values[period:]:
                ema = (
                    (price - ema) * multiplier
                    + ema
                )

                ema_values.append(ema)

            return ema_values

        # EMA 12
        ema12 = calculate_ema(closes, 12)

        # EMA 26
        ema26 = calculate_ema(closes, 26)

        # برای هم‌تراز شدن EMA12 با EMA26
        ema12_aligned = ema12[14:]

        macd_values = []

        for i in range(len(ema26)):
            macd_value = (
                ema12_aligned[i]
                - ema26[i]
            )

            macd_values.append(macd_value)

        # Signal = EMA 9 روی MACD
        if len(macd_values) < 9:
            await update.message.reply_text(
                "❌ اطلاعات کافی برای محاسبه Signal وجود ندارد."
            )
            return

        signal_values = calculate_ema(
            macd_values,
            9
        )

        macd_current = macd_values[-1]
        signal_current = signal_values[-1]

        histogram = (
            macd_current
            - signal_current
        )

        if macd_current > signal_current:
            status = "🟢 MACD بالاتر از Signal است"
        elif macd_current < signal_current:
            status = "🔴 MACD پایین‌تر از Signal است"
        else:
            status = "🟡 MACD و Signal برابر هستند"

        message = (
            f"📊 MACD Analysis\n\n"
            f"🪙 {symbol}/USD\n"
            f"⏱ تایم‌فریم: {timeframe}\n\n"
            f"MACD: {macd_current:.4f}\n"
            f"Signal: {signal_current:.4f}\n"
            f"Histogram: {histogram:.4f}\n\n"
            f"وضعیت: {status}"
        )

        await update.message.reply_text(message)

    except Exception as e:

        print(
            f"MACD API error: {e}",
            flush=True
        )

        await update.message.reply_text(
            "❌ دریافت اطلاعات MACD با خطا مواجه شد."
        )
# ===============
# MACD
# ===============
async def ema(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if len(context.args) < 2:
        await update.message.reply_text(
            "لطفاً ارز و تایم‌فریم را وارد کن.\n\n"
            "مثال:\n"
            "/ema BTC 1h"
        )
        return

    symbol = context.args[0].upper()
    timeframe = context.args[1].lower()

    symbols = {
        "BTC": "BTC-USD",
        "ETH": "ETH-USD"
    }

    timeframes = {
        "1m": 60,
        "5m": 300,
        "15m": 900,
        "1h": 3600,
        "6h": 21600,
        "1d": 86400
    }

    if symbol not in symbols:
        await update.message.reply_text(
            "فعلاً فقط BTC و ETH فعال هستند."
        )
        return

    if timeframe not in timeframes:
        await update.message.reply_text(
            "تایم‌فریم نامعتبر است.\n\n"
            "تایم‌فریم‌های مجاز:\n"
            "1m\n"
            "5m\n"
            "15m\n"
            "1h\n"
            "6h\n"
            "1d"
        )
        return

    product_id = symbols[symbol]
    granularity = timeframes[timeframe]

    url = (
        f"https://api.exchange.coinbase.com/"
        f"products/{product_id}/candles"
    )

    try:
        async with httpx.AsyncClient(timeout=10) as client:

            response = await client.get(
                url,
                params={"granularity": granularity},
                headers={"Accept": "application/json"}
            )

            response.raise_for_status()
            data = response.json()

        if len(data) < 50:
            await update.message.reply_text(
                "❌ اطلاعات کافی برای محاسبه EMA دریافت نشد."
            )
            return

        # قدیمی به جدید
        data.sort(key=lambda x: x[0])

        closes = [float(candle[4]) for candle in data]

        def calculate_ema(values, period):

            multiplier = 2 / (period + 1)

            ema_value = sum(values[:period]) / period

            for price in values[period:]:
                ema_value = (
                    (price - ema_value) * multiplier
                    + ema_value
                )

            return ema_value

        ema20 = calculate_ema(closes, 20)
        ema50 = calculate_ema(closes, 50)

        current_price = closes[-1]

        if ema20 > ema50:
            trend = "🟢 روند کوتاه‌مدت بالاتر از میان‌مدت"
        elif ema20 < ema50:
            trend = "🔴 روند کوتاه‌مدت پایین‌تر از میان‌مدت"
        else:
            trend = "🟡 EMA20 و EMA50 برابر هستند"

        if current_price > ema20 and current_price > ema50:
            position = "🟢 قیمت بالاتر از هر دو EMA قرار دارد"
        elif current_price < ema20 and current_price < ema50:
            position = "🔴 قیمت پایین‌تر از هر دو EMA قرار دارد"
        else:
            position = "🟡 قیمت بین EMA20 و EMA50 قرار دارد"

        message = (
            f"📊 EMA Analysis\n\n"
            f"🪙 {symbol}/USD\n"
            f"⏱ تایم‌فریم: {timeframe}\n\n"
            f"💰 قیمت فعلی: ${current_price:,.2f}\n\n"
            f"EMA 20: ${ema20:,.2f}\n"
            f"EMA 50: ${ema50:,.2f}\n\n"
            f"روند: {trend}\n"
            f"موقعیت قیمت: {position}"
        )

        await update.message.reply_text(message)

    except Exception as e:

        print(
            f"EMA API error: {e}",
            flush=True
        )

        await update.message.reply_text(
            "❌ دریافت اطلاعات EMA با خطا مواجه شد."
        )
# ===================
# EMA
# ===================
async def analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if len(context.args) < 2:
        await update.message.reply_text(
            "لطفاً ارز و تایم‌فریم را وارد کن.\n\n"
            "مثال:\n"
            "/analyze BTC 1h"
        )
        return

    symbol = context.args[0].upper()
    timeframe = context.args[1].lower()

    symbols = {
        "BTC": "BTC-USD",
        "ETH": "ETH-USD"
    }

    timeframes = {
        "1m": 60,
        "5m": 300,
        "15m": 900,
        "1h": 3600,
        "6h": 21600,
        "1d": 86400
    }

    if symbol not in symbols:
        await update.message.reply_text(
            "فعلاً فقط BTC و ETH فعال هستند."
        )
        return

    if timeframe not in timeframes:
        await update.message.reply_text(
            "تایم‌فریم نامعتبر است.\n\n"
            "مجاز:\n"
            "1m | 5m | 15m | 1h | 6h | 1d"
        )
        return

    product_id = symbols[symbol]
    granularity = timeframes[timeframe]

    url = (
        f"https://api.exchange.coinbase.com/"
        f"products/{product_id}/candles"
    )

    try:

        async with httpx.AsyncClient(timeout=10) as client:

            response = await client.get(
                url,
                params={"granularity": granularity},
                headers={"Accept": "application/json"}
            )

            response.raise_for_status()
            data = response.json()

        if len(data) < 50:
            await update.message.reply_text(
                "❌ اطلاعات کافی برای تحلیل دریافت نشد."
            )
            return

        data.sort(key=lambda x: x[0])

        closes = [
            float(candle[4])
            for candle in data
        ]

        current_price = closes[-1]

        # =========================
        # EMA
        # =========================

        def calculate_ema(values, period):

            multiplier = 2 / (period + 1)

            ema_value = sum(values[:period]) / period

            for price in values[period:]:
                ema_value = (
                    (price - ema_value) * multiplier
                    + ema_value
                )

            return ema_value    


        def calculate_ema_series(values, period):

            multiplier = 2 / (period + 1)

            ema = sum(values[:period]) / period

            result = [ema]

            for price in values[period:]:

                ema = (
                    (price - ema) * multiplier
                    + ema
                )

                result.append(ema)

            return result
        ema20 = calculate_ema(closes, 20)
        ema50 = calculate_ema(closes, 50)
        # =========================
        # تشخیص کراس EMA20 / EMA50
        # =========================

        ema20_series = calculate_ema_series(closes, 20)
        ema50_series = calculate_ema_series(closes, 50)

        ema20_aligned = ema20_series[30:]

        ema_cross_status = "⚪ کراس جدیدی مشاهده نشد"

        for i in range(1, len(ema50_series)):

            previous_fast = ema20_aligned[i - 1]
            previous_slow = ema50_series[i - 1]

            current_fast = ema20_aligned[i]
            current_slow = ema50_series[i]

            if (
                previous_fast <= previous_slow
                and current_fast > current_slow
            ):
                ema_cross_status = "🟢 کراس صعودی EMA20/EMA50"

            elif (
                previous_fast >= previous_slow
                and current_fast < current_slow
            ):
                ema_cross_status = "🔴 کراس نزولی EMA20/EMA50"


        # =========================
        # تشخیص کراس MACD / Signal
        # =========================

        ema12_series = calculate_ema_series(closes, 12)
        ema26_series = calculate_ema_series(closes, 26)

        ema12_aligned = ema12_series[14:]

        macd_series = []

        for i in range(len(ema26_series)):

            macd_series.append(
                ema12_aligned[i]
                - ema26_series[i]
            )

        signal_series = calculate_ema_series(
            macd_series,
            9
        )

        macd_aligned = macd_series[8:]

        macd_cross_status = "⚪ کراس جدیدی مشاهده نشد"

        for i in range(1, len(signal_series)):

            previous_macd = macd_aligned[i - 1]
            previous_signal = signal_series[i - 1]

            current_macd = macd_aligned[i]
            current_signal = signal_series[i]

            if (
                previous_macd <= previous_signal
                and current_macd > current_signal
            ):
                macd_cross_status = "🟢 کراس صعودی MACD"

            elif (
                previous_macd >= previous_signal
                and current_macd < current_signal
            ):
                macd_cross_status = "🔴 کراس نزولی MACD"

        # =========================
        # RSI
        # =========================

        gains = []
        losses = []

        for i in range(1, len(closes)):

            change = closes[i] - closes[i - 1]

            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))

        period = 14

        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period

        for i in range(period, len(gains)):

            avg_gain = (
                (avg_gain * (period - 1))
                + gains[i]
            ) / period

            avg_loss = (
                (avg_loss * (period - 1))
                + losses[i]
            ) / period

        if avg_loss == 0:
            rsi_value = 100
        else:
            rs = avg_gain / avg_loss
            rsi_value = 100 - (
                100 / (1 + rs)
            )

        # =========================
        # MACD
        # =========================

        ema12_values = []

        multiplier12 = 2 / 13

        ema12 = sum(closes[:12]) / 12
        ema12_values.append(ema12)

        for price in closes[12:]:

            ema12 = (
                (price - ema12) * multiplier12
                + ema12
            )

            ema12_values.append(ema12)

        ema26_values = []

        multiplier26 = 2 / 27

        ema26 = sum(closes[:26]) / 26
        ema26_values.append(ema26)

        for price in closes[26:]:

            ema26 = (
                (price - ema26) * multiplier26
                + ema26
            )

            ema26_values.append(ema26)

        ema12_aligned = ema12_values[14:]

        macd_values = []

        for i in range(len(ema26_values)):

            macd_values.append(
                ema12_aligned[i]
                - ema26_values[i]
            )

        signal_period = 9
        signal_multiplier = 2 / 10

        signal = (
            sum(macd_values[:signal_period])
            / signal_period
        )

        for value in macd_values[signal_period:]:

            signal = (
                (value - signal)
                * signal_multiplier
                + signal
            )

        macd_value = macd_values[-1]
        signal_value = signal
        histogram = macd_value - signal_value

        # =========================
        # تحلیل RSI
        # =========================

        if rsi_value >= 70:
            rsi_status = "🔴 اشباع خرید"
        elif rsi_value <= 30:
            rsi_status = "🟢 اشباع فروش"
        else:
            rsi_status = "🟡 محدوده میانی"

        # =========================
        # تحلیل MACD
        # =========================

        if macd_value > signal_value:
            macd_status = "🟢 MACD بالاتر از Signal"
        elif macd_value < signal_value:
            macd_status = "🔴 MACD پایین‌تر از Signal"
        else:
            macd_status = "🟡 MACD و Signal برابر"

        # =========================
        # تحلیل EMA
        # =========================

        if ema20 > ema50:
            ema_status = "🟢 EMA20 بالاتر از EMA50"
        else:
            ema_status = "🔴 EMA20 پایین‌تر از EMA50"

        if current_price > ema20:
            price_status = "🟢 قیمت بالاتر از EMA20"
        else:
            price_status = "🔴 قیمت پایین‌تر از EMA20"

        # =========================
        # جمع‌بندی
        # =========================

        bullish_points = 0
        bearish_points = 0

        if rsi_value > 50:
            bullish_points += 1
        elif rsi_value < 50:
            bearish_points += 1

        if macd_value > signal_value:
            bullish_points += 1
        elif macd_value < signal_value:
            bearish_points += 1

        if ema20 > ema50:
            bullish_points += 1
        elif ema20 < ema50:
            bearish_points += 1

        if bullish_points > bearish_points:
            overall = "🟢 تمایل صعودی"
        elif bearish_points > bullish_points:
            overall = "🔴 تمایل نزولی"
        else:
            overall = "🟡 وضعیت ترکیبی"

        message = (
            f"📊 تحلیل ترکیبی بازار\n\n"
            f"🪙 {symbol}/USD\n"
            f"⏱ تایم‌فریم: {timeframe}\n\n"

            f"💰 قیمت: ${current_price:,.2f}\n\n"

            f"━━ RSI ━━\n"
            f"RSI(14): {rsi_value:.2f}\n"
            f"{rsi_status}\n\n"

            f"━━ MACD ━━\n"
            f"MACD: {macd_value:.4f}\n"
            f"Signal: {signal_value:.4f}\n"
            f"Histogram: {histogram:.4f}\n"
            f"{macd_status}\n\n"

            f"━━ EMA ━━\n"
            f"EMA20: ${ema20:,.2f}\n"
            f"EMA50: ${ema50:,.2f}\n"
            f"{ema_status}\n"
            f"{price_status}\n\n"
            
            f"کراس EMA: {ema_cross_status}\n"
            f"کراس MACD: {macd_cross_status}\n\n"

            f"━━ جمع‌بندی ━━\n"
            f"🟢 عوامل صعودی: {bullish_points}\n"
            f"🔴 عوامل نزولی: {bearish_points}\n\n"
            f"وضعیت کلی: {overall}"
        )

        await update.message.reply_text(message)

    except Exception as e:

        print(
            f"Analyze API error: {e}",
            flush=True
        )

        await update.message.reply_text(
            "❌ در تحلیل بازار خطایی رخ داد."
        )
# ====================
# ANALYS
# ====================
async def cross(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if len(context.args) < 2:
        await update.message.reply_text(
            "لطفاً ارز و تایم‌فریم را وارد کن.\n\n"
            "مثال:\n"
            "/cross BTC 1h"
        )
        return

    symbol = context.args[0].upper()
    timeframe = context.args[1].lower()

    symbols = {
        "BTC": "BTC-USD",
        "ETH": "ETH-USD"
    }

    timeframes = {
        "1m": 60,
        "5m": 300,
        "15m": 900,
        "1h": 3600,
        "6h": 21600,
        "1d": 86400
    }

    if symbol not in symbols:
        await update.message.reply_text(
            "فعلاً فقط BTC و ETH فعال هستند."
        )
        return

    if timeframe not in timeframes:
        await update.message.reply_text(
            "تایم‌فریم نامعتبر است.\n\n"
            "مجاز:\n"
            "1m | 5m | 15m | 1h | 6h | 1d"
        )
        return

    product_id = symbols[symbol]
    granularity = timeframes[timeframe]

    url = (
        f"https://api.exchange.coinbase.com/"
        f"products/{product_id}/candles"
    )

    try:

        async with httpx.AsyncClient(timeout=10) as client:

            response = await client.get(
                url,
                params={"granularity": granularity},
                headers={"Accept": "application/json"}
            )

            response.raise_for_status()
            data = response.json()

        if len(data) < 60:
            await update.message.reply_text(
                "❌ اطلاعات کافی برای تشخیص کراس دریافت نشد."
            )
            return

        data.sort(key=lambda x: x[0])

        closes = [
            float(candle[4])
            for candle in data
        ]

        # =========================
        # EMA
        # =========================

        def calculate_ema_series(values, period):

            multiplier = 2 / (period + 1)

            ema = sum(values[:period]) / period

            result = [ema]

            for price in values[period:]:
                ema = (
                    (price - ema) * multiplier
                    + ema
                )
                result.append(ema)

            return result

        ema20 = calculate_ema_series(closes, 20)
        ema50 = calculate_ema_series(closes, 50)

        # هم‌تراز کردن EMA20 با EMA50
        ema20_aligned = ema20[30:]

        ema_cross = None
        ema_cross_candle = None

        start_index = max(1, len(ema50) - 5)

        for i in range(start_index, len(ema50)):

            previous_fast = ema20_aligned[i - 1]
            previous_slow = ema50[i - 1]

            current_fast = ema20_aligned[i]
            current_slow = ema50[i]

            if (
                previous_fast <= previous_slow
                and current_fast > current_slow
            ):
                ema_cross = "🟢 کراس صعودی EMA20/EMA50"
                ema_cross_candle = len(ema50) - i

            elif (
                previous_fast >= previous_slow
                and current_fast < current_slow
            ):
                ema_cross = "🔴 کراس نزولی EMA20/EMA50"
                ema_cross_candle = len(ema50) - i

        if ema_cross is None:

            if ema20_aligned[-1] > ema50[-1]:
                ema_status = "🟢 EMA20 بالاتر از EMA50 است"
            else:
                ema_status = "🔴 EMA20 پایین‌تر از EMA50 است"

            ema_cross = (
                f"⚪ در ۵ کندل اخیر کراس جدیدی مشاهده نشد\n"
                f"{ema_status}"
            )

        else:

            ema_cross = (
                f"{ema_cross}\n"
                f"⏱ حدود {ema_cross_candle} کندل قبل"
            )

        # =========================
        # MACD
        # =========================

        ema12 = calculate_ema_series(closes, 12)
        ema26 = calculate_ema_series(closes, 26)

        ema12_aligned = ema12[14:]

        macd_values = []

        for i in range(len(ema26)):

            macd_values.append(
                ema12_aligned[i]
                - ema26[i]
            )

        signal_values = calculate_ema_series(
            macd_values,
            9
        )

        # هم‌تراز کردن MACD با Signal
        macd_aligned = macd_values[8:]

macd_cross = None
macd_cross_candle = None

start_index = max(1, len(signal_values) - 5)

for i in range(start_index, len(signal_values)):

    previous_macd = macd_aligned[i - 1]
    previous_signal = signal_values[i - 1]

    current_macd = macd_aligned[i]
    current_signal = signal_values[i]

    if (
        previous_macd <= previous_signal
        and current_macd > current_signal
    ):
        macd_cross = "🟢 کراس صعودی MACD"
        macd_cross_candle = len(signal_values) - i

    elif (
        previous_macd >= previous_signal
        and current_macd < current_signal
    ):
        macd_cross = "🔴 کراس نزولی MACD"
        macd_cross_candle = len(signal_values) - i

        if macd_cross is None:

            if macd_aligned[-1] > signal_values[-1]:
                macd_status = "🟢 MACD بالاتر از Signal است"
            else:
                macd_status = "🔴 MACD پایین‌تر از Signal است"

            macd_cross = (
                f"⚪ در ۵ کندل اخیر کراس جدیدی مشاهده نشد\n"
                f"{macd_status}"
            )

        else:
            macd_cross = (
                f"{macd_cross}\n"
                f"⏱ حدود {macd_cross_candle} کندل قبل"
            )

        message = (
            f"🔄 بررسی کراس‌ها\n\n"
            f"🪙 {symbol}/USD\n"
            f"⏱ تایم‌فریم: {timeframe}\n\n"

            f"━━ EMA ━━\n"
            f"{ema_cross}\n\n"

            f"━━ MACD ━━\n"
            f"{macd_cross}"
        )

        await update.message.reply_text(message)

    except Exception as e:

        print(
            f"Cross API error: {e}",
            flush=True
        )

        await update.message.reply_text(
            "❌ در بررسی کراس‌ها خطایی رخ داد."
        )
# ==========================
# CROSS
# =========================
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
    telegram_application.add_handler(
        CommandHandler(
            "rsi",
            rsi
        )
    )
    telegram_application.add_handler(
        CommandHandler("macd", macd)
    )
    telegram_application.add_handler(
        CommandHandler("ema", ema)
    )
    telegram_application.add_handler(
        CommandHandler("analyze", analyze)
    )
    telegram_application.add_handler(
        CommandHandler("cross", cross)
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
