```python
import os
import asyncio
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes


# ============================================================
# CONFIG
# ============================================================

RENDER_URL = "https://crypto-market-bot-ozg7.onrender.com"
WEBHOOK_PATH = "/telegram-webhook"
WEBHOOK_URL = RENDER_URL + WEBHOOK_PATH

COINBASE_API = "https://api.exchange.coinbase.com"

SUPPORTED_SYMBOLS = {
    "BTC": "BTC-USD",
    "ETH": "ETH-USD",
}

SUPPORTED_TIMEFRAMES = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "6h": 21600,
    "1d": 86400,
}


# ============================================================
# GLOBALS
# ============================================================

telegram_application = None
event_loop = None


# ============================================================
# MARKET DATA ENGINE
# ============================================================

async def fetch_json(url, params=None):
    """
    Generic Coinbase GET request.
    """
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(
            url,
            params=params,
            headers={
                "User-Agent": "crypto-market-bot/1.0"
            },
        )

        response.raise_for_status()
        return response.json()


async def fetch_candles(product_id, granularity):
    """
    Fetch candles from Coinbase and return them sorted
    from oldest -> newest.

    Coinbase candle format:
    [time, low, high, open, close, volume]
    """

    url = f"{COINBASE_API}/products/{product_id}/candles"

    data = await fetch_json(
        url,
        params={
            "granularity": granularity
        },
    )

    if not isinstance(data, list):
        raise ValueError("Invalid candle data received from Coinbase.")

    candles = []

    for candle in data:
        if len(candle) < 6:
            continue

        candles.append({
            "time": int(candle[0]),
            "low": float(candle[1]),
            "high": float(candle[2]),
            "open": float(candle[3]),
            "close": float(candle[4]),
            "volume": float(candle[5]),
        })

    candles.sort(key=lambda x: x["time"])

    return candles


async def fetch_ticker(product_id):
    """
    Fetch current ticker.
    """
    url = f"{COINBASE_API}/products/{product_id}/ticker"
    return await fetch_json(url)


async def fetch_stats(product_id):
    """
    Fetch 24h statistics.
    """
    url = f"{COINBASE_API}/products/{product_id}/stats"
    return await fetch_json(url)


# ============================================================
# BASIC HELPERS
# ============================================================

def get_product_id(symbol):
    return SUPPORTED_SYMBOLS.get(symbol.upper())


def get_granularity(timeframe):
    return SUPPORTED_TIMEFRAMES.get(timeframe.lower())


def format_price(value):
    if value >= 1000:
        return f"${value:,.2f}"

    if value >= 1:
        return f"${value:,.4f}"

    return f"${value:,.6f}"


def format_percent(value):
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}%"


def timeframe_label(timeframe):
    labels = {
        "1m": "1 دقیقه",
        "5m": "5 دقیقه",
        "15m": "15 دقیقه",
        "1h": "1 ساعت",
        "6h": "6 ساعت",
        "1d": "1 روز",
    }

    return labels.get(timeframe, timeframe)


# ============================================================
# INDICATOR ENGINE
# ============================================================

def calculate_ema_series(values, period):
    """
    EMA series with the same length as input.

    Values before enough data exists are None.

    At index period-1:
        SMA is used as the first EMA value.

    After that:
        EMA = price * multiplier + previous_ema * (1 - multiplier)
    """

    if len(values) < period:
        return [None] * len(values)

    result = [None] * len(values)

    sma = sum(values[:period]) / period
    result[period - 1] = sma

    multiplier = 2 / (period + 1)

    previous_ema = sma

    for i in range(period, len(values)):
        current_value = values[i]

        current_ema = (
            current_value * multiplier
            + previous_ema * (1 - multiplier)
        )

        result[i] = current_ema
        previous_ema = current_ema

    return result


def calculate_ema(values, period):
    """
    Return only the latest EMA value.
    """

    series = calculate_ema_series(values, period)

    if not series:
        return None

    return series[-1]


def calculate_rsi(values, period=14):
    """
    Wilder-style RSI.

    Returns the latest RSI value.
    """

    if len(values) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(1, len(values)):
        change = values[i] - values[i - 1]

        if change > 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))

    average_gain = sum(gains[:period]) / period
    average_loss = sum(losses[:period]) / period

    if average_loss == 0:
        rsi = 100.0
    else:
        rs = average_gain / average_loss
        rsi = 100 - (100 / (1 + rs))

    for i in range(period, len(gains)):
        average_gain = (
            (average_gain * (period - 1))
            + gains[i]
        ) / period

        average_loss = (
            (average_loss * (period - 1))
            + losses[i]
        ) / period

        if average_loss == 0:
            rsi = 100.0
        else:
            rs = average_gain / average_loss
            rsi = 100 - (100 / (1 + rs))

    return rsi


def calculate_macd(
    closes,
    fast_period=12,
    slow_period=26,
    signal_period=9,
):
    """
    Calculate MACD, Signal and Histogram.

    All returned series have the same length as closes.

    This makes cross detection much easier because
    everything keeps the original candle index.
    """

    ema_fast = calculate_ema_series(
        closes,
        fast_period
    )

    ema_slow = calculate_ema_series(
        closes,
        slow_period
    )

    macd_series = [None] * len(closes)

    for i in range(len(closes)):
        if (
            ema_fast[i] is not None
            and ema_slow[i] is not None
        ):
            macd_series[i] = (
                ema_fast[i] - ema_slow[i]
            )

    # Signal EMA can only start once enough MACD values exist.
    valid_macd = [
        value
        for value in macd_series
        if value is not None
    ]

    signal_valid = calculate_ema_series(
        valid_macd,
        signal_period
    )

    signal_series = [None] * len(closes)

    valid_index = 0

    for i in range(len(closes)):
        if macd_series[i] is not None:

            if signal_valid[valid_index] is not None:
                signal_series[i] = signal_valid[valid_index]

            valid_index += 1

    histogram_series = [None] * len(closes)

    for i in range(len(closes)):
        if (
            macd_series[i] is not None
            and signal_series[i] is not None
        ):
            histogram_series[i] = (
                macd_series[i] - signal_series[i]
            )

    return {
        "macd": macd_series,
        "signal": signal_series,
        "histogram": histogram_series,
    }


# ============================================================
# CROSS DETECTION ENGINE
# ============================================================

def detect_cross(
    fast_series,
    slow_series,
    lookback=5,
):
    """
    Detect the most recent bullish/bearish cross
    inside the requested lookback window.

    Returns:

    {
        "detected": True,
        "direction": "BULLISH",
        "bars_ago": 2
    }

    or

    {
        "detected": False,
        "direction": None,
        "bars_ago": None
    }
    """

    if len(fast_series) != len(slow_series):
        raise ValueError(
            "Fast and slow series must have the same length."
        )

    latest_index = len(fast_series) - 1

    start_index = max(
        1,
        latest_index - lookback + 1
    )

    latest_cross = None

    for i in range(start_index, latest_index + 1):

        previous_fast = fast_series[i - 1]
        previous_slow = slow_series[i - 1]

        current_fast = fast_series[i]
        current_slow = slow_series[i]

        if (
            previous_fast is None
            or previous_slow is None
            or current_fast is None
            or current_slow is None
        ):
            continue

        # Bullish Cross
        if (
            previous_fast <= previous_slow
            and current_fast > current_slow
        ):
            latest_cross = {
                "detected": True,
                "direction": "BULLISH",
                "bars_ago": latest_index - i,
            }

        # Bearish Cross
        elif (
            previous_fast >= previous_slow
            and current_fast < current_slow
        ):
            latest_cross = {
                "detected": True,
                "direction": "BEARISH",
                "bars_ago": latest_index - i,
            }

    if latest_cross:
        return latest_cross

    return {
        "detected": False,
        "direction": None,
        "bars_ago": None,
    }


def get_current_relation(
    fast_value,
    slow_value,
):
    if fast_value is None or slow_value is None:
        return "UNKNOWN"

    if fast_value > slow_value:
        return "BULLISH"

    if fast_value < slow_value:
        return "BEARISH"

    return "NEUTRAL"


# ============================================================
# MARKET ANALYSIS ENGINE
# ============================================================

def analyze_market(
    candles,
    symbol,
    timeframe,
):
    """
    Main analysis engine.

    This function does NOT send Telegram messages.
    It only calculates and returns structured data.
    """

    if not candles:
        raise ValueError("No candle data available.")

    closes = [
        candle["close"]
        for candle in candles
    ]

    current_price = closes[-1]

    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

    rsi_value = calculate_rsi(
        closes,
        period=14
    )

    if rsi_value is None:
        rsi_zone = "UNKNOWN"
    elif rsi_value >= 70:
        rsi_zone = "OVERBOUGHT"
    elif rsi_value <= 30:
        rsi_zone = "OVERSOLD"
    else:
        rsi_zone = "NEUTRAL"

    # --------------------------------------------------------
    # EMA
    # --------------------------------------------------------

    ema20_series = calculate_ema_series(
        closes,
        20
    )

    ema50_series = calculate_ema_series(
        closes,
        50
    )

    ema20 = ema20_series[-1]
    ema50 = ema50_series[-1]

    ema_relation = get_current_relation(
        ema20,
        ema50
    )

    if (
        ema20 is not None
        and ema50 is not None
    ):
        if ema20 > ema50:
            ema_trend = "BULLISH"
        elif ema20 < ema50:
            ema_trend = "BEARISH"
        else:
            ema_trend = "NEUTRAL"
    else:
        ema_trend = "UNKNOWN"

    # Price relative to EMA20
    if ema20 is None:
        price_vs_ema20 = "UNKNOWN"
    elif current_price > ema20:
        price_vs_ema20 = "ABOVE"
    elif current_price < ema20:
        price_vs_ema20 = "BELOW"
    else:
        price_vs_ema20 = "EQUAL"

    # --------------------------------------------------------
    # EMA CROSS
    # --------------------------------------------------------

    ema_cross = detect_cross(
        ema20_series,
        ema50_series,
        lookback=5
    )

    # --------------------------------------------------------
    # MACD
    # --------------------------------------------------------

    macd_data = calculate_macd(closes)

    macd_series = macd_data["macd"]
    signal_series = macd_data["signal"]
    histogram_series = macd_data["histogram"]

    macd_value = macd_series[-1]
    signal_value = signal_series[-1]
    histogram_value = histogram_series[-1]

    macd_relation = get_current_relation(
        macd_value,
        signal_value
    )

    macd_cross = detect_cross(
        macd_series,
        signal_series,
        lookback=5
    )

    # --------------------------------------------------------
    # Confluence
    # --------------------------------------------------------

    bullish_points = 0
    bearish_points = 0

    # RSI
    if rsi_value is not None:
        if rsi_value > 50:
            bullish_points += 1
        elif rsi_value < 50:
            bearish_points += 1

    # MACD
    if (
        macd_value is not None
        and signal_value is not None
    ):
        if macd_value > signal_value:
            bullish_points += 1
        elif macd_value < signal_value:
            bearish_points += 1

    # EMA
    if (
        ema20 is not None
        and ema50 is not None
    ):
        if ema20 > ema50:
            bullish_points += 1
        elif ema20 < ema50:
            bearish_points += 1

    if bullish_points > bearish_points:
        overall = "BULLISH_BIAS"
    elif bearish_points > bullish_points:
        overall = "BEARISH_BIAS"
    else:
        overall = "MIXED"

    # --------------------------------------------------------
    # Return structured result
    # --------------------------------------------------------

    return {
        "symbol": symbol,
        "timeframe": timeframe,

        "price": current_price,

        "rsi": {
            "value": rsi_value,
            "zone": rsi_zone,
        },

        "ema": {
            "ema20": ema20,
            "ema50": ema50,
            "trend": ema_trend,
            "relation": ema_relation,
            "price_vs_ema20": price_vs_ema20,
        },

        "macd": {
            "value": macd_value,
            "signal": signal_value,
            "histogram": histogram_value,
            "relation": macd_relation,
        },

        "cross": {
            "ema": ema_cross,
            "macd": macd_cross,
        },

        "confluence": {
            "bullish_points": bullish_points,
            "bearish_points": bearish_points,
            "overall": overall,
        },
    }


# ============================================================
# TELEGRAM COMMANDS
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "🤖 Crypto Market Bot فعال است.\n\n"
        "دستورات:\n"
        "/price BTC\n"
        "/price ETH\n"
        "/candles BTC 1h\n"
        "/rsi BTC 1h\n"
        "/ema BTC 1h\n"
        "/macd BTC 1h\n"
        "/cross BTC 1h\n"
        "/analyze BTC 1h"
    )


# ============================================================
# /price
# ============================================================

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not context.args:
        await update.message.reply_text(
            "مثال:\n/price BTC"
        )
        return

    symbol = context.args[0].upper()
    product_id = get_product_id(symbol)

    if not product_id:
        await update.message.reply_text(
            "❌ فقط BTC و ETH پشتیبانی می‌شوند."
        )
        return

    try:
        ticker = await fetch_ticker(product_id)
        stats = await fetch_stats(product_id)

        current_price = float(ticker["price"])
        high_24h = float(stats["high"])
        low_24h = float(stats["low"])
        open_24h = float(stats["open"])

        if open_24h != 0:
            change_24h = (
                (current_price - open_24h)
                / open_24h
            ) * 100
        else:
            change_24h = 0

        message = (
            f"📊 {symbol} Market\n\n"
            f"💰 Price: {format_price(current_price)}\n"
            f"📈 24h High: {format_price(high_24h)}\n"
            f"📉 24h Low: {format_price(low_24h)}\n"
            f"📊 24h Change: {format_percent(change_24h)}"
        )

        await update.message.reply_text(message)

    except Exception as e:
        print("PRICE ERROR:", e)

        await update.message.reply_text(
            "❌ خطا در دریافت اطلاعات قیمت."
        )


# ============================================================
# /candles
# ============================================================

async def candles(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if len(context.args) < 2:
        await update.message.reply_text(
            "مثال:\n/candles BTC 1h"
        )
        return

    symbol = context.args[0].upper()
    timeframe = context.args[1].lower()

    product_id = get_product_id(symbol)
    granularity = get_granularity(timeframe)

    if not product_id:
        await update.message.reply_text(
            "❌ فقط BTC و ETH پشتیبانی می‌شوند."
        )
        return

    if not granularity:
        await update.message.reply_text(
            "❌ تایم‌فریم نامعتبر است.\n"
            "مقادیر مجاز: 1m, 5m, 15m, 1h, 6h, 1d"
        )
        return

    try:
        data = await fetch_candles(
            product_id,
            granularity
        )

        if len(data) < 5:
            await update.message.reply_text(
                "❌ کندل کافی دریافت نشد."
            )
            return

        latest = data[-5:]

        lines = [
            f"🕯 {symbol} — {timeframe}",
            ""
        ]

        for candle in reversed(latest):
            lines.append(
                f"Open: {format_price(candle['open'])}\n"
                f"High: {format_price(candle['high'])}\n"
                f"Low: {format_price(candle['low'])}\n"
                f"Close: {format_price(candle['close'])}\n"
                f"Volume: {candle['volume']:.4f}\n"
                "────────────"
            )

        await update.message.reply_text(
            "\n".join(lines)
        )

    except Exception as e:
        print("CANDLES ERROR:", e)

        await update.message.reply_text(
            "❌ خطا در دریافت کندل‌ها."
        )


# ============================================================
# /rsi
# ============================================================

async def rsi(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if len(context.args) < 2:
        await update.message.reply_text(
            "مثال:\n/rsi BTC 1h"
        )
        return

    symbol = context.args[0].upper()
    timeframe = context.args[1].lower()

    product_id = get_product_id(symbol)
    granularity = get_granularity(timeframe)

    if not product_id or not granularity:
        await update.message.reply_text(
            "❌ Symbol یا timeframe نامعتبر است."
        )
        return

    try:
        data = await fetch_candles(
            product_id,
            granularity
        )

        closes = [
            candle["close"]
            for candle in data
        ]

        rsi_value = calculate_rsi(
            closes,
            14
        )

        if rsi_value is None:
            await update.message.reply_text(
                "❌ کندل کافی برای RSI وجود ندارد."
            )
            return

        if rsi_value >= 70:
            status = "🔴 اشباع خرید"
        elif rsi_value <= 30:
            status = "🟢 اشباع فروش"
        else:
            status = "🟡 محدوده میانی"

        message = (
            f"📊 RSI — {symbol} — {timeframe}\n\n"
            f"RSI(14): {rsi_value:.2f}\n"
            f"Status: {status}"
        )

        await update.message.reply_text(message)

    except Exception as e:
        print("RSI ERROR:", e)

        await update.message.reply_text(
            "❌ خطا در محاسبه RSI."
        )


# ============================================================
# /ema
# ============================================================

async def ema(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if len(context.args) < 2:
        await update.message.reply_text(
            "مثال:\n/ema BTC 1h"
        )
        return

    symbol = context.args[0].upper()
    timeframe = context.args[1].lower()

    product_id = get_product_id(symbol)
    granularity = get_granularity(timeframe)

    if not product_id or not granularity:
        await update.message.reply_text(
            "❌ Symbol یا timeframe نامعتبر است."
        )
        return

    try:
        data = await fetch_candles(
            product_id,
            granularity
        )

        closes = [
            candle["close"]
            for candle in data
        ]

        if len(closes) < 50:
            await update.message.reply_text(
                "❌ حداقل 50 کندل لازم است."
            )
            return

        ema20 = calculate_ema(
            closes,
            20
        )

        ema50 = calculate_ema(
            closes,
            50
        )

        current_price = closes[-1]

        if ema20 > ema50:
            trend = "🟢 روند EMA صعودی"
        elif ema20 < ema50:
            trend = "🔴 روند EMA نزولی"
        else:
            trend = "🟡 EMAها برابر"

        if current_price > ema20:
            price_status = "🟢 قیمت بالاتر از EMA20"
        else:
            price_status = "🔴 قیمت پایین‌تر از EMA20"

        message = (
            f"📈 EMA — {symbol} — {timeframe}\n\n"
            f"Price: {format_price(current_price)}\n"
            f"EMA20: {format_price(ema20)}\n"
            f"EMA50: {format_price(ema50)}\n\n"
            f"{trend}\n"
            f"{price_status}"
        )

        await update.message.reply_text(message)

    except Exception as e:
        print("EMA ERROR:", e)

        await update.message.reply_text(
            "❌ خطا در محاسبه EMA."
        )


# ============================================================
# /macd
# ============================================================

async def macd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if len(context.args) < 2:
        await update.message.reply_text(
            "مثال:\n/macd BTC 1h"
        )
        return

    symbol = context.args[0].upper()
    timeframe = context.args[1].lower()

    product_id = get_product_id(symbol)
    granularity = get_granularity(timeframe)

    if not product_id or not granularity:
        await update.message.reply_text(
            "❌ Symbol یا timeframe نامعتبر است."
        )
        return

    try:
        data = await fetch_candles(
            product_id,
            granularity
        )

        closes = [
            candle["close"]
            for candle in data
        ]

        if len(closes) < 35:
            await update.message.reply_text(
                "❌ حداقل 35 کندل لازم است."
            )
            return

        macd_data = calculate_macd(closes)

        macd_value = macd_data["macd"][-1]
        signal_value = macd_data["signal"][-1]
        histogram = macd_data["histogram"][-1]

        if macd_value > signal_value:
            status = "🟢 MACD بالاتر از Signal"
        elif macd_value < signal_value:
            status = "🔴 MACD پایین‌تر از Signal"
        else:
            status = "🟡 MACD و Signal برابر"

        message = (
            f"📊 MACD — {symbol} — {timeframe}\n\n"
            f"MACD: {macd_value:.6f}\n"
            f"Signal: {signal_value:.6f}\n"
            f"Histogram: {histogram:.6f}\n\n"
            f"{status}"
        )

        await update.message.reply_text(message)

    except Exception as e:
        print("MACD ERROR:", e)

        await update.message.reply_text(
            "❌ خطا در محاسبه MACD."
        )


# ============================================================
# /cross
# ============================================================

async def cross(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if len(context.args) < 2:
        await update.message.reply_text(
            "مثال:\n/cross BTC 1h"
        )
        return

    symbol = context.args[0].upper()
    timeframe = context.args[1].lower()

    product_id = get_product_id(symbol)
    granularity = get_granularity(timeframe)

    if not product_id or not granularity:
        await update.message.reply_text(
            "❌ Symbol یا timeframe نامعتبر است."
        )
        return

    try:
        data = await fetch_candles(
            product_id,
            granularity
        )

        if len(data) < 60:
            await update.message.reply_text(
                "❌ حداقل 60 کندل لازم است."
            )
            return

        result = analyze_market(
            data,
            symbol,
            timeframe
        )

        ema_cross = result["cross"]["ema"]
        macd_cross = result["cross"]["macd"]

        # ----------------------------------------------------
        # EMA Cross
        # ----------------------------------------------------

        if ema_cross["detected"]:

            if ema_cross["direction"] == "BULLISH":
                ema_message = (
                    "🟢 EMA20/EMA50 Bullish Cross"
                )
            else:
                ema_message = (
                    "🔴 EMA20/EMA50 Bearish Cross"
                )

            ema_message += (
                f"\n⏱ {ema_cross['bars_ago']} کندل قبل"
            )

        else:

            ema_relation = result["ema"]["relation"]

            if ema_relation == "BULLISH":
                ema_message = (
                    "ℹ️ کراس EMA20/EMA50 در 5 کندل اخیر "
                    "دیده نشد.\n"
                    "EMA20 بالاتر از EMA50 است."
                )

            elif ema_relation == "BEARISH":
                ema_message = (
                    "ℹ️ کراس EMA20/EMA50 در 5 کندل اخیر "
                    "دیده نشد.\n"
                    "EMA20 پایین‌تر از EMA50 است."
                )

            else:
                ema_message = (
                    "ℹ️ کراس EMA20/EMA50 در 5 کندل اخیر "
                    "دیده نشد."
                )

        # ----------------------------------------------------
        # MACD Cross
        # ----------------------------------------------------

        if macd_cross["detected"]:

            if macd_cross["direction"] == "BULLISH":
                macd_message = (
                    "🟢 MACD Bullish Cross"
                )
            else:
                macd_message = (
                    "🔴 MACD Bearish Cross"
                )

            macd_message += (
                f"\n⏱ {macd_cross['bars_ago']} کندل قبل"
            )

        else:

            macd_relation = result["macd"]["relation"]

            if macd_relation == "BULLISH":
                macd_message = (
                    "ℹ️ کراس MACD در 5 کندل اخیر "
                    "دیده نشد.\n"
                    "MACD بالاتر از Signal است."
                )

            elif macd_relation == "BEARISH":
                macd_message = (
                    "ℹ️ کراس MACD در 5 کندل اخیر "
                    "دیده نشد.\n"
                    "MACD پایین‌تر از Signal است."
                )

            else:
                macd_message = (
                    "ℹ️ کراس MACD در 5 کندل اخیر "
                    "دیده نشد."
                )

        message = (
            f"🔄 Cross Analysis\n"
            f"{symbol} — {timeframe}\n\n"
            f"{ema_message}\n\n"
            f"{macd_message}"
        )

        await update.message.reply_text(message)

    except Exception as e:
        print("CROSS ERROR:", e)

        await update.message.reply_text(
            "❌ خطا در تشخیص Cross."
        )


# ============================================================
# /analyze
# ============================================================

async def analyze(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if len(context.args) < 2:
        await update.message.reply_text(
            "مثال:\n/analyze BTC 1h"
        )
        return

    symbol = context.args[0].upper()
    timeframe = context.args[1].lower()

    product_id = get_product_id(symbol)
    granularity = get_granularity(timeframe)

    if not product_id:
        await update.message.reply_text(
            "❌ فقط BTC و ETH پشتیبانی می‌شوند."
        )
        return

    if not granularity:
        await update.message.reply_text(
            "❌ تایم‌فریم نامعتبر است.\n"
            "مقادیر مجاز: 1m, 5m, 15m, 1h, 6h, 1d"
        )
        return

    try:
        data = await fetch_candles(
            product_id,
            granularity
        )

        if len(data) < 60:
            await update.message.reply_text(
                "❌ حداقل 60 کندل برای تحلیل لازم است."
            )
            return

        result = analyze_market(
            data,
            symbol,
            timeframe
        )

        # ----------------------------------------------------
        # Values
        # ----------------------------------------------------

        current_price = result["price"]

        rsi_value = result["rsi"]["value"]
        rsi_zone = result["rsi"]["zone"]

        ema20 = result["ema"]["ema20"]
        ema50 = result["ema"]["ema50"]

        ema_trend = result["ema"]["trend"]
        price_vs_ema20 = result["ema"]["price_vs_ema20"]

        macd_value = result["macd"]["value"]
        signal_value = result["macd"]["signal"]
        histogram = result["macd"]["histogram"]

        macd_relation = result["macd"]["relation"]

        ema_cross = result["cross"]["ema"]
        macd_cross = result["cross"]["macd"]

        bullish_points = result["confluence"]["bullish_points"]
        bearish_points = result["confluence"]["bearish_points"]
        overall = result["confluence"]["overall"]

        # ----------------------------------------------------
        # RSI Text
        # ----------------------------------------------------

        if rsi_zone == "OVERBOUGHT":
            rsi_status = "🔴 اشباع خرید"
        elif rsi_zone == "OVERSOLD":
            rsi_status = "🟢 اشباع فروش"
        else:
            rsi_status = "🟡 محدوده میانی"

        # ----------------------------------------------------
        # EMA Text
        # ----------------------------------------------------

        if ema_trend == "BULLISH":
            ema_status = "🟢 EMA20 بالاتر از EMA50"
        elif ema_trend == "BEARISH":
            ema_status = "🔴 EMA20 پایین‌تر از EMA50"
        else:
            ema_status = "🟡 EMA وضعیت خنثی"

        if price_vs_ema20 == "ABOVE":
            price_status = "🟢 قیمت بالاتر از EMA20"
        elif price_vs_ema20 == "BELOW":
            price_status = "🔴 قیمت پایین‌تر از EMA20"
        else:
            price_status = "🟡 قیمت نزدیک EMA20"

        # ----------------------------------------------------
        # MACD Text
        # ----------------------------------------------------

        if macd_relation == "BULLISH":
            macd_status = "🟢 MACD بالاتر از Signal"
        elif macd_relation == "BEARISH":
            macd_status = "🔴 MACD پایین‌تر از Signal"
        else:
            macd_status = "🟡 MACD و Signal برابر"

        # ----------------------------------------------------
        # Cross Text
        # ----------------------------------------------------

        if ema_cross["detected"]:

            if ema_cross["direction"] == "BULLISH":
                ema_cross_text = "🟢 EMA Bullish Cross"
            else:
                ema_cross_text = "🔴 EMA Bearish Cross"

            ema_cross_text += (
                f" — {ema_cross['bars_ago']} کندل قبل"
            )

        else:
            ema_cross_text = (
                "⚪ EMA Cross در 5 کندل اخیر ندارد"
            )

        if macd_cross["detected"]:

            if macd_cross["direction"] == "BULLISH":
                macd_cross_text = "🟢 MACD Bullish Cross"
            else:
                macd_cross_text = "🔴 MACD Bearish Cross"

            macd_cross_text += (
                f" — {macd_cross['bars_ago']} کندل قبل"
            )

        else:
            macd_cross_text = (
                "⚪ MACD Cross در 5 کندل اخیر ندارد"
            )

        # ----------------------------------------------------
        # Overall
        # ----------------------------------------------------

        if overall == "BULLISH_BIAS":
            overall_text = "🟢 تمایل کلی صعودی"
        elif overall == "BEARISH_BIAS":
            overall_text = "🔴 تمایل کلی نزولی"
        else:
            overall_text = "🟡 وضعیت ترکیبی"

        # ----------------------------------------------------
        # Final Message
        # ----------------------------------------------------

        message = (
            f"🧠 Market Analysis\n"
            f"{symbol} — {timeframe}\n\n"

            f"💰 Price\n"
            f"{format_price(current_price)}\n\n"

            f"📊 RSI(14)\n"
            f"{rsi_value:.2f}\n"
            f"{rsi_status}\n\n"

            f"📈 EMA\n"
            f"EMA20: {format_price(ema20)}\n"
            f"EMA50: {format_price(ema50)}\n"
            f"{ema_status}\n"
            f"{price_status}\n\n"

            f"📉 MACD\n"
            f"MACD: {macd_value:.6f}\n"
            f"Signal: {signal_value:.6f}\n"
            f"Histogram: {histogram:.6f}\n"
            f"{macd_status}\n\n"

            f"🔄 Cross\n"
            f"{ema_cross_text}\n"
            f"{macd_cross_text}\n\n"

            f"🎯 Confluence\n"
            f"🟢 Bullish Points: {bullish_points}\n"
            f"🔴 Bearish Points: {bearish_points}\n\n"

            f"{overall_text}"
        )

        await update.message.reply_text(message)

    except Exception as e:
        print("ANALYZE ERROR:", e)

        await update.message.reply_text(
            "❌ خطا در تحلیل بازار."
        )


# ============================================================
# HTTP SERVER
# ============================================================

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

        else:

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

            data = body.decode("utf-8")

            print("Webhook received")

            update_data = __import__(
                "json"
            ).loads(data)

            update = Update.de_json(
                update_data,
                telegram_application.bot
            )

            future = asyncio.run_coroutine_threadsafe(
                telegram_application.process_update(update),
                event_loop
            )

            def handle_result(f):

                try:
                    exception = f.exception()

                    if exception:
                        print(
                            "Update processing error:",
                            exception
                        )
                    else:
                        print(
                            "Update processed successfully"
                        )

                except Exception as callback_error:
                    print(
                        "Callback error:",
                        callback_error
                    )

            future.add_done_callback(
                handle_result
            )

            self.send_response(200)
            self.send_header(
                "Content-Type",
                "text/plain; charset=utf-8"
            )
            self.end_headers()

            self.wfile.write(b"OK")

        except Exception as e:

            print(
                "WEBHOOK ERROR:",
                e
            )

            self.send_response(500)
            self.end_headers()

    def log_message(self, format, *args):
        return


def start_web_server():

    port = int(
        os.environ.get(
            "PORT",
            "10000"
        )
    )

    server = HTTPServer(
        ("0.0.0.0", port),
        HealthHandler
    )

    print(
        f"HTTP server running on port {port}"
    )

    server.serve_forever()


# ============================================================
# TELEGRAM
# ============================================================

async def start_telegram():

    global telegram_application

    token = os.environ.get(
        "TELEGRAM_BOT_TOKEN"
    )

    if not token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN environment variable is missing."
        )

    telegram_application = (
        Application.builder()
        .token(token)
        .build()
    )

    # --------------------------------------------------------
    # Handlers
    # --------------------------------------------------------

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
        CommandHandler(
            "ema",
            ema
        )
    )

    telegram_application.add_handler(
        CommandHandler(
            "macd",
            macd
        )
    )

    telegram_application.add_handler(
        CommandHandler(
            "cross",
            cross
        )
    )

    telegram_application.add_handler(
        CommandHandler(
            "analyze",
            analyze
        )
    )

    # --------------------------------------------------------
    # Start Telegram Application
    # --------------------------------------------------------

    await telegram_application.initialize()

    await telegram_application.start()

    await telegram_application.bot.set_webhook(
        url=WEBHOOK_URL,
        drop_pending_updates=True
    )

    print(
        "Telegram webhook set:",
        WEBHOOK_URL
    )


# ============================================================
# MAIN
# ============================================================

def main():

    global event_loop

    event_loop = asyncio.new_event_loop()

    asyncio.set_event_loop(
        event_loop
    )

    # Start HTTP server in background
    web_thread = threading.Thread(
        target=start_web_server,
        daemon=True
    )

    web_thread.start()

    # Start Telegram
    event_loop.run_until_complete(
        start_telegram()
    )

    print(
        "Crypto Market Bot started successfully."
    )

    try:
        event_loop.run_forever()

    except KeyboardInterrupt:
        print(
            "Bot stopped."
        )

    finally:

        try:
            event_loop.run_until_complete(
                telegram_application.stop()
            )

            event_loop.run_until_complete(
                telegram_application.shutdown()
            )

        except Exception as e:
            print(
                "Shutdown error:",
                e
            )

        event_loop.close()


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()
```
