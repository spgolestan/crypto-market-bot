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
# Indicator Engine
# =========================

# ============================================================
# BOLLINGER BANDS
# ============================================================

def calculate_bollinger_bands(
    closes,
    period=20,
    std_multiplier=2
):
    """Calculate Bollinger Bands."""

    if len(closes) < period:
        return {
            "middle": None,
            "upper": None,
            "lower": None,
            "bandwidth": None,
            "percent_b": None,
        }

    window = closes[-period:]

    middle = sum(window) / period

    variance = sum(
        (price - middle) ** 2
        for price in window
    ) / period

    standard_deviation = variance ** 0.5

    upper = (
        middle
        + std_multiplier * standard_deviation
    )

    lower = (
        middle
        - std_multiplier * standard_deviation
    )

    if middle != 0:
        bandwidth = (
            (upper - lower)
            / middle
        ) * 100
    else:
        bandwidth = 0

    current_price = closes[-1]

    if upper != lower:
        percent_b = (
            (current_price - lower)
            / (upper - lower)
        ) * 100
    else:
        percent_b = 50

    return {
        "middle": middle,
        "upper": upper,
        "lower": lower,
        "bandwidth": bandwidth,
        "percent_b": percent_b,
    }


# ============================================================
# ATR
# ============================================================

def calculate_atr(
    candles,
    period=14
):
    """Calculate Average True Range using Wilder smoothing."""

    if len(candles) < period + 1:
        return None

    true_ranges = []

    for i in range(1, len(candles)):

        current = candles[i]
        previous = candles[i - 1]

        high = current["high"]
        low = current["low"]
        previous_close = previous["close"]

        tr1 = high - low
        tr2 = abs(high - previous_close)
        tr3 = abs(low - previous_close)

        true_range = max(
            tr1,
            tr2,
            tr3
        )

        true_ranges.append(true_range)

    if len(true_ranges) < period:
        return None

    atr = sum(
        true_ranges[:period]
    ) / period

    for i in range(period, len(true_ranges)):

        atr = (
            (atr * (period - 1))
            + true_ranges[i]
        ) / period

    return atr


# ============================================================
# VOLUME ANALYSIS
# ============================================================

def calculate_volume_analysis(
    candles,
    period=20
):
    """Compare current volume with average volume."""

    if len(candles) < period:
        return {
            "current": None,
            "average": None,
            "ratio": None,
            "status": "UNKNOWN",
        }

    volumes = [
        candle["volume"]
        for candle in candles
    ]

    current_volume = volumes[-1]

    average_volume = sum(
        volumes[-period:]
    ) / period

    if average_volume == 0:
        ratio = 0
    else:
        ratio = (
            current_volume
            / average_volume
        )

    if ratio >= 1.5:
        status = "HIGH"
    elif ratio <= 0.7:
        status = "LOW"
    else:
        status = "NORMAL"

    return {
        "current": current_volume,
        "average": average_volume,
        "ratio": ratio,
        "status": status,
    }


# ============================================================
# PRICE / BOLLINGER RELATION
# ============================================================

def get_bollinger_position(
    price,
    lower,
    middle,
    upper
):
    """Determine where current price sits relative to Bollinger Bands."""

    if (
        lower is None
        or middle is None
        or upper is None
    ):
        return "UNKNOWN"

    if price >= upper:
        return "ABOVE_UPPER"

    if price <= lower:
        return "BELOW_LOWER"

    if price > middle:
        return "ABOVE_MIDDLE"

    if price < middle:
        return "BELOW_MIDDLE"

    return "AT_MIDDLE"


# ============================================================
# MARKET REGIME
# ============================================================

def detect_market_regime(
    ema20,
    ema50,
    price,
    bollinger_bandwidth,
    atr_percent,
    volume_ratio,
):
    """Determine the current market regime. Descriptive, not predictive."""

    if (
        ema20 is None
        or ema50 is None
        or price is None
    ):
        return "UNKNOWN"

    if ema20 > ema50 and price > ema20:
        if (
            atr_percent is not None
            and atr_percent >= 1.5
        ):
            return "TRENDING_BULLISH"
        return "BULLISH"

    if ema20 < ema50 and price < ema20:
        if (
            atr_percent is not None
            and atr_percent >= 1.5
        ):
            return "TRENDING_BEARISH"
        return "BEARISH"

    if (
        atr_percent is not None
        and atr_percent < 0.7
    ):
        return "LOW_VOLATILITY"

    if (
        atr_percent is not None
        and atr_percent >= 2.5
    ):
        return "HIGH_VOLATILITY"

    if (
        volume_ratio is not None
        and volume_ratio >= 1.5
    ):
        return "VOLUME_EXPANSION"

    return "RANGING"


# ============================================================
# SIGNAL STRENGTH
# ============================================================

def calculate_signal_strength(
    rsi_value,
    macd_value,
    signal_value,
    ema20,
    ema50,
    price,
    bollinger_position,
    volume_ratio,
    atr_percent,
):
    """Calculate directional confluence as a structured result."""

    bullish = 0
    bearish = 0
    factors = []

    # RSI
    if rsi_value is not None:
        if rsi_value > 55:
            bullish += 1
            factors.append({
                "name": "RSI",
                "direction": "BULLISH",
                "strength": "NORMAL",
            })
        elif rsi_value < 45:
            bearish += 1
            factors.append({
                "name": "RSI",
                "direction": "BEARISH",
                "strength": "NORMAL",
            })
        else:
            factors.append({
                "name": "RSI",
                "direction": "NEUTRAL",
                "strength": "WEAK",
            })

    # MACD
    if (
        macd_value is not None
        and signal_value is not None
    ):
        if macd_value > signal_value:
            bullish += 1
            factors.append({
                "name": "MACD",
                "direction": "BULLISH",
                "strength": "NORMAL",
            })
        elif macd_value < signal_value:
            bearish += 1
            factors.append({
                "name": "MACD",
                "direction": "BEARISH",
                "strength": "NORMAL",
            })
        else:
            factors.append({
                "name": "MACD",
                "direction": "NEUTRAL",
                "strength": "WEAK",
            })

    # EMA Structure
    if (
        ema20 is not None
        and ema50 is not None
        and price is not None
    ):
        if ema20 > ema50 and price > ema20:
            bullish += 2
            factors.append({
                "name": "EMA Structure",
                "direction": "BULLISH",
                "strength": "STRONG",
            })
        elif ema20 < ema50 and price < ema20:
            bearish += 2
            factors.append({
                "name": "EMA Structure",
                "direction": "BEARISH",
                "strength": "STRONG",
            })
        elif ema20 > ema50:
            bullish += 1
            factors.append({
                "name": "EMA Structure",
                "direction": "BULLISH",
                "strength": "NORMAL",
            })
        elif ema20 < ema50:
            bearish += 1
            factors.append({
                "name": "EMA Structure",
                "direction": "BEARISH",
                "strength": "NORMAL",
            })

    # Bollinger
    if bollinger_position == "ABOVE_MIDDLE":
        bullish += 1
        factors.append({
            "name": "Bollinger",
            "direction": "BULLISH",
            "strength": "NORMAL",
        })
    elif bollinger_position == "BELOW_MIDDLE":
        bearish += 1
        factors.append({
            "name": "Bollinger",
            "direction": "BEARISH",
            "strength": "NORMAL",
        })
    elif bollinger_position == "ABOVE_UPPER":
        bullish += 1
        factors.append({
            "name": "Bollinger",
            "direction": "BULLISH",
            "strength": "EXTENDED",
        })
    elif bollinger_position == "BELOW_LOWER":
        bearish += 1
        factors.append({
            "name": "Bollinger",
            "direction": "BEARISH",
            "strength": "EXTENDED",
        })

    # Volume confirmation
    volume_confirmation = "NONE"

    if volume_ratio is not None:
        if volume_ratio >= 1.5:
            volume_confirmation = "STRONG"
        elif volume_ratio >= 1.0:
            volume_confirmation = "NORMAL"
        else:
            volume_confirmation = "WEAK"

    # Final direction
    if bullish > bearish:
        direction = "BULLISH"
    elif bearish > bullish:
        direction = "BEARISH"
    else:
        direction = "MIXED"

    # Confidence
    total_points = bullish + bearish

    if total_points == 0:
        confidence = "LOW"
    else:
        dominant = max(bullish, bearish)
        ratio = dominant / total_points

        if ratio >= 0.75 and dominant >= 5:
            confidence = "HIGH"
        elif ratio >= 0.60:
            confidence = "MODERATE"
        else:
            confidence = "LOW"

    # Volume qualification
    if volume_confirmation == "WEAK":
        confidence_note = "ضعف حجم؛ حرکت تأیید حجمی ضعیفی دارد."
    elif volume_confirmation == "STRONG":
        confidence_note = "حجم بالا؛ حرکت از نظر حجم تأیید بیشتری دارد."
    else:
        confidence_note = "تأیید حجمی معمولی."

    return {
        "bullish_score": bullish,
        "bearish_score": bearish,
        "direction": direction,
        "confidence": confidence,
        "volume_confirmation": volume_confirmation,
        "confidence_note": confidence_note,
        "factors": factors,
    }
# ============================================================

# MARKET STRUCTURE

# Swing Detection + HH / HL / LH / LL

# ============================================================

def detect_swing_points(
candles,
left_bars=2,
right_bars=2
):
"""
Detect swing highs and swing lows.

```
A swing high is a candle whose high is higher
than the highs of the surrounding candles.

A swing low is a candle whose low is lower
than the lows of the surrounding candles.
"""

swing_highs = []
swing_lows = []

if len(candles) < left_bars + right_bars + 1:
    return {
        "swing_highs": [],
        "swing_lows": [],
    }

for i in range(
    left_bars,
    len(candles) - right_bars
):

    current = candles[i]

    current_high = current["high"]
    current_low = current["low"]

    # =========================
    # Swing High
    # =========================

    is_swing_high = True

    for j in range(
        i - left_bars,
        i + right_bars + 1
    ):

        if j == i:
            continue

        if candles[j]["high"] >= current_high:
            is_swing_high = False
            break

    if is_swing_high:

        swing_highs.append({
            "index": i,
            "time": current.get("time"),
            "price": current_high,
        })

    # =========================
    # Swing Low
    # =========================

    is_swing_low = True

    for j in range(
        i - left_bars,
        i + right_bars + 1
    ):

        if j == i:
            continue

        if candles[j]["low"] <= current_low:
            is_swing_low = False
            break

    if is_swing_low:

        swing_lows.append({
            "index": i,
            "time": current.get("time"),
            "price": current_low,
        })

return {
    "swing_highs": swing_highs,
    "swing_lows": swing_lows,
}
```

def classify_swing_structure(swing_points):
"""
Classify swing points as:

```
Highs:
    HH = Higher High
    LH = Lower High
    EH = Equal High

Lows:
    HL = Higher Low
    LL = Lower Low
    EL = Equal Low
"""

swing_highs = swing_points["swing_highs"]
swing_lows = swing_points["swing_lows"]

classified_highs = []
classified_lows = []

# =========================
# Classify Highs
# =========================

previous_high = None

for swing in swing_highs:

    if previous_high is None:

        classification = "FIRST_HIGH"

    elif swing["price"] > previous_high["price"]:

        classification = "HH"

    elif swing["price"] < previous_high["price"]:

        classification = "LH"

    else:

        classification = "EH"

    classified_highs.append({
        **swing,
        "classification": classification,
    })

    previous_high = swing

# =========================
# Classify Lows
# =========================

previous_low = None

for swing in swing_lows:

    if previous_low is None:

        classification = "FIRST_LOW"

    elif swing["price"] > previous_low["price"]:

        classification = "HL"

    elif swing["price"] < previous_low["price"]:

        classification = "LL"

    else:

        classification = "EL"

    classified_lows.append({
        **swing,
        "classification": classification,
    })

    previous_low = swing

return {
    "highs": classified_highs,
    "lows": classified_lows,
}

def analyze_market_structure(
candles,
swing_left=2,
swing_right=2
):
"""
Analyze current market structure using swing points.

```
This stage only detects:
    HH / HL / LH / LL

BOS / CHOCH are intentionally not included yet.
"""

swing_points = detect_swing_points(
    candles,
    left_bars=swing_left,
    right_bars=swing_right
)

structure = classify_swing_structure(
    swing_points
)

highs = structure["highs"]
lows = structure["lows"]

latest_high = (
    highs[-1]
    if highs
    else None
)

previous_high = (
    highs[-2]
    if len(highs) >= 2
    else None
)

latest_low = (
    lows[-1]
    if lows
    else None
)

previous_low = (
    lows[-2]
    if len(lows) >= 2
    else None
)

recent_highs = highs[-3:]
recent_lows = lows[-3:]

bullish_score = 0
bearish_score = 0

# =========================
# Recent High Structure
# =========================

for high in recent_highs:

    if high["classification"] == "HH":
        bullish_score += 1

    elif high["classification"] == "LH":
        bearish_score += 1

# =========================
# Recent Low Structure
# =========================

for low in recent_lows:

    if low["classification"] == "HL":
        bullish_score += 1

    elif low["classification"] == "LL":
        bearish_score += 1

# =========================
# Overall Structure
# =========================

if bullish_score > bearish_score:

    overall_structure = "BULLISH"

elif bearish_score > bullish_score:

    overall_structure = "BEARISH"

else:

    overall_structure = "MIXED"

return {
    "swing_highs": highs,
    "swing_lows": lows,

    "latest_high": latest_high,
    "previous_high": previous_high,

    "latest_low": latest_low,
    "previous_low": previous_low,

    "bullish_score": bullish_score,
    "bearish_score": bearish_score,

    "overall_structure": overall_structure,
}     


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

        # ========================================================
        # Bollinger + ATR + Volume
        # ========================================================

        analysis_candles = [
            {
                "high": float(candle[2]),
                "low": float(candle[1]),
                "close": float(candle[4]),
                "volume": float(candle[5]),
            }
            for candle in data
        ]
        # ========================================================
        # Market Structure
        # Swing Detection + HH / HL / LH / LL
        # ========================================================

        market_structure = analyze_market_structure(
            candles=[
                {
                    "time": int(candle[0]),
                    "open": float(candle[3]),
                    "high": float(candle[2]),
                    "low": float(candle[1]),
                    "close": float(candle[4]),
                    "volume": float(candle[5]),
                }
                for candle in data
            ],
            swing_left=2,
            swing_right=2
        )


        bollinger = calculate_bollinger_bands(
            closes,
            period=20,
            std_multiplier=2
        )

        bollinger_position = get_bollinger_position(
            current_price,
            bollinger["lower"],
            bollinger["middle"],
            bollinger["upper"]
        )

        atr_value = calculate_atr(
            analysis_candles,
            period=14
        )

        if (
            atr_value is not None
            and current_price != 0
        ):
            atr_percent = (
                atr_value
                / current_price
            ) * 100
        else:
            atr_percent = None

        volume = calculate_volume_analysis(
            analysis_candles,
            period=20
        )

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

        # هم‌تراز کردن EMA20 با EMA50
        ema20_aligned = ema20_series[30:]

        ema_cross_status = "⚪ در ۵ کندل اخیر کراس جدیدی مشاهده نشد"

        # فقط ۵ کندل اخیر
        start_index = max(1, len(ema50_series) - 5)

        for i in range(start_index, len(ema50_series)):

            previous_fast = ema20_aligned[i - 1]
            previous_slow = ema50_series[i - 1]

            current_fast = ema20_aligned[i]
            current_slow = ema50_series[i]

            # کراس صعودی
            if (
                previous_fast <= previous_slow
                and current_fast > current_slow
            ):
                ema_cross_status = (
                    f"🟢 کراس صعودی EMA20/EMA50\n"
                    f"⏱ حدود {len(ema50_series) - i} کندل قبل"
                )
                break

            # کراس نزولی
            elif (
                previous_fast >= previous_slow
                and current_fast < current_slow
            ):
                ema_cross_status = (
                    f"🔴 کراس نزولی EMA20/EMA50\n"
                    f"⏱ حدود {len(ema50_series) - i} کندل قبل"
                )
                break


        # =========================
        # تشخیص کراس MACD / Signal
        # =========================

        ema12_series = calculate_ema_series(closes, 12)
        ema26_series = calculate_ema_series(closes, 26)

        # هم‌تراز کردن EMA12 با EMA26
        ema12_aligned = ema12_series[14:]

        macd_series = []

        for i in range(len(ema26_series)):

            macd_series.append(
                ema12_aligned[i]
                - ema26_series[i]
            )

        # Signal = EMA9 روی MACD
        signal_series = calculate_ema_series(
            macd_series,
            9
        )

        # هم‌تراز کردن MACD با Signal
        macd_aligned = macd_series[8:]

        macd_cross_status = "⚪ در ۵ کندل اخیر کراس جدیدی مشاهده نشد"

        # فقط ۵ کندل اخیر
        start_index = max(1, len(signal_series) - 5)

        for i in range(start_index, len(signal_series)):

            previous_macd = macd_aligned[i - 1]
            previous_signal = signal_series[i - 1]

            current_macd = macd_aligned[i]
            current_signal = signal_series[i]

            # کراس صعودی
            if (
                previous_macd <= previous_signal
                and current_macd > current_signal
            ):
                macd_cross_status = (
                    f"🟢 کراس صعودی MACD\n"
                    f"⏱ حدود {len(signal_series) - i} کندل قبل"
                )
                break

            # کراس نزولی
            elif (
                previous_macd >= previous_signal
                and current_macd < current_signal
            ):
                macd_cross_status = (
                    f"🔴 کراس نزولی MACD\n"
                    f"⏱ حدود {len(signal_series) - i} کندل قبل"
                )
                break

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

        # ========================================================
        # تحلیل Bollinger
        # ========================================================

        if bollinger_position == "ABOVE_UPPER":
            bollinger_status = "🔴 قیمت بالای باند بالایی"
        elif bollinger_position == "BELOW_LOWER":
            bollinger_status = "🟢 قیمت پایین باند پایینی"
        elif bollinger_position == "ABOVE_MIDDLE":
            bollinger_status = "🟢 قیمت بالای خط میانی"
        elif bollinger_position == "BELOW_MIDDLE":
            bollinger_status = "🔴 قیمت پایین خط میانی"
        else:
            bollinger_status = "🟡 موقعیت نزدیک خط میانی"

        # ========================================================
        # تحلیل ATR
        # ========================================================

        if atr_percent is not None:
            if atr_percent >= 3:
                atr_status = "🔥 نوسان بالا"
            elif atr_percent <= 1:
                atr_status = "🟡 نوسان پایین"
            else:
                atr_status = "🟢 نوسان متوسط"
        else:
            atr_status = "⚪ ATR در دسترس نیست"

        # ========================================================
        # تحلیل Volume
        # ========================================================

        if volume["status"] == "HIGH":
            volume_text = "🔥 حجم بالاتر از میانگین"
        elif volume["status"] == "LOW":
            volume_text = "🟡 حجم پایین‌تر از میانگین"
        elif volume["status"] == "NORMAL":
            volume_text = "🟢 حجم در محدوده معمول"
        else:
            volume_text = "⚪ حجم نامشخص"

        atr_display = (
            f"{atr_value:.6f}"
            if atr_value is not None
            else "N/A"
        )

        atr_percent_display = (
            f"{atr_percent:.2f}%"
            if atr_percent is not None
            else "N/A"
        )

        bollinger_upper_display = (
            f"{bollinger['upper']:,.2f}"
            if bollinger["upper"] is not None
            else "N/A"
        )

        bollinger_middle_display = (
            f"{bollinger['middle']:,.2f}"
            if bollinger["middle"] is not None
            else "N/A"
        )

        bollinger_lower_display = (
            f"{bollinger['lower']:,.2f}"
            if bollinger["lower"] is not None
            else "N/A"
        )

        bollinger_percent_b_display = (
            f"{bollinger['percent_b']:.2f}"
            if bollinger["percent_b"] is not None
            else "N/A"
        )

        bollinger_bandwidth_display = (
            f"{bollinger['bandwidth']:.2f}%"
            if bollinger["bandwidth"] is not None
            else "N/A"
        )

        current_volume_display = (
            f"{volume['current']:.4f}"
            if volume["current"] is not None
            else "N/A"
        )

        average_volume_display = (
            f"{volume['average']:.4f}"
            if volume["average"] is not None
            else "N/A"
        )

        volume_ratio_display = (
            f"{volume['ratio']:.2f}x"
            if volume["ratio"] is not None
            else "N/A"
        )

        # ========================================================
        # Market Regime / Confluence
        # ========================================================

        market_regime = detect_market_regime(
            ema20=ema20,
            ema50=ema50,
            price=current_price,
            bollinger_bandwidth=bollinger["bandwidth"],
            atr_percent=atr_percent,
            volume_ratio=volume["ratio"],
        )

        confluence = calculate_signal_strength(
            rsi_value=rsi_value,
            macd_value=macd_value,
            signal_value=signal_value,
            ema20=ema20,
            ema50=ema50,
            price=current_price,
            bollinger_position=bollinger_position,
            volume_ratio=volume["ratio"],
            atr_percent=atr_percent,
        )

        bullish_points = confluence["bullish_score"]
        bearish_points = confluence["bearish_score"]
        confluence_direction = confluence["direction"]
        confidence = confluence["confidence"]
        volume_confirmation = confluence["volume_confirmation"]
        confidence_note = confluence["confidence_note"]

        regime_labels = {
            "TRENDING_BULLISH": "🟢 روند صعودی",
            "BULLISH": "🟢 تمایل صعودی",
            "TRENDING_BEARISH": "🔴 روند نزولی",
            "BEARISH": "🔴 تمایل نزولی",
            "LOW_VOLATILITY": "🟡 نوسان پایین",
            "HIGH_VOLATILITY": "🟠 نوسان بالا",
            "VOLUME_EXPANSION": "🟣 افزایش حجم",
            "RANGING": "🟡 بازار رنج",
            "UNKNOWN": "⚪ نامشخص",
        }

        regime_text = regime_labels.get(
            market_regime,
            "⚪ نامشخص"
        )

        confidence_labels = {
            "HIGH": "🟢 بالا",
            "MODERATE": "🟡 متوسط",
            "LOW": "🔴 پایین",
        }

        confidence_text = confidence_labels.get(
            confidence,
            "⚪ نامشخص"
        )

        if confluence_direction == "BULLISH":
            direction_text = "🟢 تمایل صعودی"
        elif confluence_direction == "BEARISH":
            direction_text = "🔴 تمایل نزولی"
        else:
            direction_text = "🟡 وضعیت ترکیبی"
        latest_high = market_structure["latest_high"]
        latest_low = market_structure["latest_low"]
    
        if latest_high:
            latest_high_text = (
                f"{latest_high['classification']} "
                f"@ {latest_high['price']:,.2f}"
            )
        else:
            latest_high_text = "N/A"
    
        if latest_low:
            latest_low_text = (
                f"{latest_low['classification']} "
                f"@ {latest_low['price']:,.2f}"
            )
        else:
            latest_low_text = "N/A"   

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

            f"━━ Bollinger Bands ━━\n"
            f"Upper: {bollinger_upper_display}\n"
            f"Middle: {bollinger_middle_display}\n"
            f"Lower: {bollinger_lower_display}\n"
            f"%B: {bollinger_percent_b_display}\n"
            f"Bandwidth: {bollinger_bandwidth_display}\n"
            f"{bollinger_status}\n\n"

            f"━━ ATR(14) ━━\n"
            f"ATR: {atr_display}\n"
            f"ATR%: {atr_percent_display}\n"
            f"{atr_status}\n\n"

            f"━━ Volume ━━\n"
            f"Current: {current_volume_display}\n"
            f"Average: {average_volume_display}\n"
            f"Ratio: {volume_ratio_display}\n"
            f"{volume_text}\n\n"

            f"━━ EMA ━━\n"
            f"EMA20: ${ema20:,.2f}\n"
            f"EMA50: ${ema50:,.2f}\n"
            f"{ema_status}\n"
            f"{price_status}\n\n"

            f"کراس EMA: {ema_cross_status}\n"
            f"کراس MACD: {macd_cross_status}\n\n"
    
            f"━━ Market Structure ━━\n"
            f"ساختار کلی: {market_structure['overall_structure']}\n"
            f"🟢 امتیاز صعودی ساختار: {market_structure['bullish_score']}\n"
            f"🔴 امتیاز نزولی ساختار: {market_structure['bearish_score']}\n"
            f"High اخیر: {latest_high_text}\n"
            f"Low اخیر: {latest_low_text}\n\n"
    
            f"━━ Market Regime ━━\n"

            f"━━ Confluence ━━\n"
            f"🟢 امتیاز صعودی: {bullish_points}\n"
            f"🔴 امتیاز نزولی: {bearish_points}\n"
            f"جهت: {direction_text}\n"
            f"Confidence: {confidence_text}\n\n"
            f"📦 تأیید حجم: {volume_confirmation}\n"
            f"{confidence_note}"
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
# ============================================================
# Multi-Timeframe Analysis Engine
# ============================================================

SUPPORTED_SYMBOLS = {
    "BTC": "BTC-USD",
    "ETH": "ETH-USD",
}

TIMEFRAME_GRANULARITIES = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "6h": 21600,
    "1d": 86400,
}


def get_granularity(timeframe):
    return TIMEFRAME_GRANULARITIES.get(timeframe)


async def fetch_candles(product_id, granularity):
    url = f"https://api.exchange.coinbase.com/products/{product_id}/candles"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                url,
                params={"granularity": granularity},
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            data = response.json()
        data.sort(key=lambda x: x[0])
        return [
            {"time": int(x[0]), "low": float(x[1]), "high": float(x[2]),
             "open": float(x[3]), "close": float(x[4]), "volume": float(x[5])}
            for x in data
        ]
    except Exception as exc:
        print(f"Fetch candles error: {exc}", flush=True)
        return []


def _ema_series(values, period):
    if len(values) < period:
        return []
    multiplier = 2 / (period + 1)
    ema = sum(values[:period]) / period
    result = [ema]
    for value in values[period:]:
        ema = (value - ema) * multiplier + ema
        result.append(ema)
    return result


def _ema_value(values, period):
    series = _ema_series(values, period)
    return series[-1] if series else None


def _rsi_value(closes, period=14):
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]
        gains.append(change if change > 0 else 0)
        losses.append(abs(change) if change < 0 else 0)
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    return 100 - (100 / (1 + avg_gain / avg_loss))


def _macd_current(closes):
    ema12 = _ema_series(closes, 12)
    ema26 = _ema_series(closes, 26)
    if not ema12 or not ema26:
        return None, None
    ema12_aligned = ema12[14:]
    if len(ema12_aligned) < len(ema26):
        return None, None
    macd = [ema12_aligned[i] - ema26[i] for i in range(len(ema26))]
    signal = _ema_series(macd, 9)
    if not signal:
        return None, None
    return macd[-1], signal[-1]


def analyze_market(candles, symbol, timeframe):
    """تحلیل یک تایم‌فریم برای استفاده در MTF."""
    if len(candles) < 60:
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "confluence": {
                "bullish_score": 0,
                "bearish_score": 0,
                "direction": "MIXED",
                "confidence": "LOW",
                "volume_confirmation": "NONE",
                "confidence_note": "داده کافی نیست.",
                "factors": [],
            },
        }

    closes = [c["close"] for c in candles]
    price = closes[-1]
    ema20 = _ema_value(closes, 20)
    ema50 = _ema_value(closes, 50)
    rsi_value = _rsi_value(closes)
    macd_value, signal_value = _macd_current(closes)
    bollinger = calculate_bollinger_bands(closes, 20, 2)
    bollinger_position = get_bollinger_position(
        price, bollinger["lower"], bollinger["middle"], bollinger["upper"]
    )
    atr_value = calculate_atr(candles, 14)
    atr_percent = (atr_value / price * 100) if atr_value is not None and price else None
    volume = calculate_volume_analysis(candles, 20)

    regime = detect_market_regime(
        ema20, ema50, price, bollinger["bandwidth"], atr_percent, volume["ratio"]
    )
    confluence = calculate_signal_strength(
        rsi_value, macd_value, signal_value, ema20, ema50, price,
        bollinger_position, volume["ratio"], atr_percent
    )

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "price": price,
        "market_regime": regime,
        "confluence": confluence,
    }


def calculate_mtf_confluence(analyses):
    weights = {
        "6h": 3,
        "1h": 2,
        "15m": 1,
    }

    weighted_score = 0
    bullish_score = 0
    bearish_score = 0
    directions = {}

    for timeframe, weight in weights.items():
        if timeframe not in analyses:
            continue

        direction = (
            analyses[timeframe]
            .get("confluence", {})
            .get("direction", "UNKNOWN")
        )

        directions[timeframe] = direction

        if direction == "BULLISH":
            bullish_score += weight
            weighted_score += weight
        elif direction == "BEARISH":
            bearish_score += weight
            weighted_score -= weight

    higher_tf_direction = directions.get("6h", "UNKNOWN")
    main_tf_direction = directions.get("1h", "UNKNOWN")
    short_tf_direction = directions.get("15m", "UNKNOWN")

    if weighted_score > 0:
        overall_direction = "BULLISH"
    elif weighted_score < 0:
        overall_direction = "BEARISH"
    else:
        overall_direction = "MIXED"

    if (
        higher_tf_direction == "BULLISH"
        and main_tf_direction == "BULLISH"
        and short_tf_direction == "BULLISH"
    ):
        alignment = "STRONG_BULLISH"
    elif (
        higher_tf_direction == "BEARISH"
        and main_tf_direction == "BEARISH"
        and short_tf_direction == "BEARISH"
    ):
        alignment = "STRONG_BEARISH"
    elif (
        higher_tf_direction == main_tf_direction
        and main_tf_direction != "UNKNOWN"
    ):
        alignment = "HIGHER_MAIN_ALIGNED"
    elif (
        higher_tf_direction != main_tf_direction
        and higher_tf_direction != "UNKNOWN"
        and main_tf_direction != "UNKNOWN"
    ):
        alignment = "HIGHER_MAIN_CONFLICT"
    else:
        alignment = "MIXED"

    counter_trend = (
        higher_tf_direction != "UNKNOWN"
        and main_tf_direction != "UNKNOWN"
        and higher_tf_direction != main_tf_direction
    )

    short_term_confirmation = "NEUTRAL"
    if (
        short_tf_direction == higher_tf_direction
        and short_tf_direction != "UNKNOWN"
    ):
        short_term_confirmation = "CONFIRMS_HIGHER_TF"
    elif (
        short_tf_direction != higher_tf_direction
        and short_tf_direction != "UNKNOWN"
    ):
        short_term_confirmation = "AGAINST_HIGHER_TF"

    absolute_score = abs(weighted_score)
    if absolute_score >= 5:
        strength = "STRONG"
    elif absolute_score >= 3:
        strength = "MODERATE"
    elif absolute_score >= 1:
        strength = "WEAK"
    else:
        strength = "NEUTRAL"

    if (
        higher_tf_direction == "BEARISH"
        and main_tf_direction == "BULLISH"
        and short_tf_direction == "BEARISH"
    ):
        interpretation = (
            "ساختار 6h نزولی است، 1h حرکت مخالف ساختار بالاتر دارد، "
            "اما 15m دوباره با 6h هم‌جهت شده است."
        )
    elif (
        higher_tf_direction == "BULLISH"
        and main_tf_direction == "BEARISH"
        and short_tf_direction == "BULLISH"
    ):
        interpretation = (
            "ساختار 6h صعودی است، 1h حرکت مخالف ساختار بالاتر دارد، "
            "اما 15m دوباره با 6h هم‌جهت شده است."
        )
    elif alignment == "STRONG_BULLISH":
        interpretation = "هر سه تایم‌فریم هم‌جهت صعودی هستند."
    elif alignment == "STRONG_BEARISH":
        interpretation = "هر سه تایم‌فریم هم‌جهت نزولی هستند."
    elif counter_trend:
        interpretation = "تایم‌فریم اصلی با ساختار بالاتر هم‌جهت نیست."
    else:
        interpretation = "بین تایم‌فریم‌ها هم‌جهتی کامل وجود ندارد."

    return {
        "weighted_score": weighted_score,
        "bullish_score": bullish_score,
        "bearish_score": bearish_score,
        "overall_direction": overall_direction,
        "alignment": alignment,
        "strength": strength,
        "higher_tf_direction": higher_tf_direction,
        "main_tf_direction": main_tf_direction,
        "short_tf_direction": short_tf_direction,
        "counter_trend": counter_trend,
        "short_term_confirmation": short_term_confirmation,
        "interpretation": interpretation,
        "directions": directions,
    }


async def analyze_multi_timeframe(symbol):
    """15m = کوتاه‌مدت، 1h = روند اصلی، 6h = ساختار بالاتر."""
    symbol = symbol.upper()
    timeframes = ["15m", "1h", "6h"]
    analyses = {}

    if symbol not in SUPPORTED_SYMBOLS:
        return {
            "analyses": {},
            "mtf": calculate_mtf_confluence({}),
            "directions": {},
            "alignment": "MIXED",
            "direction": "MIXED",
            "strength": "NEUTRAL",
        }

    for timeframe in timeframes:
        granularity = get_granularity(timeframe)
        candles = await fetch_candles(
            SUPPORTED_SYMBOLS[symbol],
            granularity
        )
        if candles:
            analyses[timeframe] = analyze_market(
                candles=candles,
                symbol=symbol,
                timeframe=timeframe
            )

    mtf = calculate_mtf_confluence(analyses)

    return {
        "analyses": analyses,
        "mtf": mtf,
        "directions": mtf["directions"],
        "alignment": mtf["alignment"],
        "direction": mtf["overall_direction"],
        "strength": mtf["strength"],
    }


async def mtf_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    symbol = "BTC"

    try:
        result = await analyze_multi_timeframe(symbol)
        analyses = result["analyses"]

        if not analyses:
            await update.message.reply_text(
                "❌ داده‌ای برای تحلیل چندتایم‌فریمی دریافت نشد."
            )
            return

        mtf = result["mtf"]

        weighted_score = mtf["weighted_score"]
        bullish_score = mtf["bullish_score"]
        bearish_score = mtf["bearish_score"]
        overall_direction = mtf["overall_direction"]
        alignment = mtf["alignment"]
        strength = mtf["strength"]
        higher_tf_direction = mtf["higher_tf_direction"]
        main_tf_direction = mtf["main_tf_direction"]
        short_tf_direction = mtf["short_tf_direction"]
        counter_trend = mtf["counter_trend"]
        short_confirmation = mtf["short_term_confirmation"]
        interpretation = mtf["interpretation"]

        direction_icons = {
            "BULLISH": "🟢",
            "BEARISH": "🔴",
            "MIXED": "🟡",
            "UNKNOWN": "⚪",
        }

        strength_labels = {
            "STRONG": "🟢 قوی",
            "MODERATE": "🟡 متوسط",
            "WEAK": "🟠 ضعیف",
            "NEUTRAL": "⚪ خنثی",
        }

        alignment_labels = {
            "STRONG_BULLISH": "🟢 هم‌جهتی صعودی کامل",
            "STRONG_BEARISH": "🔴 هم‌جهتی نزولی کامل",
            "HIGHER_MAIN_ALIGNED": "🟢 ساختار بالاتر و تایم‌فریم اصلی هم‌جهت",
            "HIGHER_MAIN_CONFLICT": "⚠️ تعارض بین ساختار بالاتر و تایم‌فریم اصلی",
            "MIXED": "🟡 ساختار ترکیبی",
        }

        lines = [
            "📊 Multi-Timeframe Analysis",
            "",
            f"🪙 {symbol}/USD",
            "",
            "━━ Timeframes ━━",
            "",
        ]

        for timeframe in ["6h", "1h", "15m"]:
            if timeframe not in analyses:
                continue

            analysis = analyses[timeframe]
            direction = analysis["confluence"]["direction"]
            confidence = analysis["confluence"]["confidence"]
            icon = direction_icons.get(direction, "⚪")

            if timeframe == "6h":
                role = "ساختار بالاتر"
            elif timeframe == "1h":
                role = "روند اصلی"
            else:
                role = "مومنتوم کوتاه‌مدت"

            lines.append(
                f"{timeframe} | {role}\n"
                f"{icon} {direction} | Confidence: {confidence}"
            )
            lines.append("")

        lines.extend([
            "━━ MTF Structure ━━",
            "",
            f"6h: {direction_icons.get(higher_tf_direction, '⚪')} {higher_tf_direction}",
            f"1h: {direction_icons.get(main_tf_direction, '⚪')} {main_tf_direction}",
            f"15m: {direction_icons.get(short_tf_direction, '⚪')} {short_tf_direction}",
            "",
            f"Weighted Score: {weighted_score:+d}",
            f"🟢 Bullish Weight: {bullish_score}",
            f"🔴 Bearish Weight: {bearish_score}",
            "",
            "━━ نتیجه ━━",
            "",
            f"جهت غالب: {direction_icons.get(overall_direction, '⚪')} {overall_direction}",
            "",
            f"قدرت: {strength_labels.get(strength, '⚪')}",
            "",
            alignment_labels.get(alignment, "🟡 ساختار ترکیبی"),
        ])

        if counter_trend:
            lines.extend([
                "",
                "⚠️ Higher-Timeframe Conflict",
                "",
                "تایم‌فریم 1h با ساختار 6h هم‌جهت نیست.",
            ])

        if short_confirmation == "CONFIRMS_HIGHER_TF":
            lines.extend([
                "",
                "✅ 15m ساختار 6h را تأیید می‌کند.",
            ])
        elif short_confirmation == "AGAINST_HIGHER_TF":
            lines.extend([
                "",
                "⚠️ 15m خلاف ساختار 6h حرکت می‌کند.",
            ])

        lines.extend([
            "",
            "━━ تفسیر ساختار ━━",
            "",
            interpretation,
        ])

        await update.message.reply_text(
            "\n".join(lines)
        )

    except Exception as exc:
        print(f"MTF API error: {exc}", flush=True)
        await update.message.reply_text(
            f"❌ خطا در تحلیل Multi-Timeframe:\n{exc}"
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
        # تابع محاسبه EMA
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

        # =========================
        # EMA20 / EMA50
        # =========================

        ema20 = calculate_ema_series(
            closes,
            20
        )

        ema50 = calculate_ema_series(
            closes,
            50
        )

        # هم‌تراز کردن EMA20 با EMA50
        ema20_aligned = ema20[30:]

        ema_cross = None
        ema_cross_candle = None

        # فقط 5 کندل اخیر
        start_index = max(
            1,
            len(ema50) - 5
        )

        for i in range(
            start_index,
            len(ema50)
        ):

            previous_fast = ema20_aligned[i - 1]
            previous_slow = ema50[i - 1]

            current_fast = ema20_aligned[i]
            current_slow = ema50[i]

            if (
                previous_fast <= previous_slow
                and current_fast > current_slow
            ):

                ema_cross = (
                    "🟢 کراس صعودی EMA20/EMA50"
                )

                ema_cross_candle = (
                    len(ema50) - i
                )

            elif (
                previous_fast >= previous_slow
                and current_fast < current_slow
            ):

                ema_cross = (
                    "🔴 کراس نزولی EMA20/EMA50"
                )

                ema_cross_candle = (
                    len(ema50) - i
                )

        if ema_cross is None:

            if ema20_aligned[-1] > ema50[-1]:

                ema_status = (
                    "🟢 EMA20 بالاتر از EMA50 است"
                )

            else:

                ema_status = (
                    "🔴 EMA20 پایین‌تر از EMA50 است"
                )

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

        ema12 = calculate_ema_series(
            closes,
            12
        )

        ema26 = calculate_ema_series(
            closes,
            26
        )

        # هم‌تراز کردن EMA12 با EMA26
        ema12_aligned = ema12[14:]

        macd_values = []

        for i in range(len(ema26)):

            macd_values.append(
                ema12_aligned[i]
                - ema26[i]
            )

        # Signal = EMA9 روی MACD
        signal_values = calculate_ema_series(
            macd_values,
            9
        )

        # هم‌تراز کردن MACD با Signal
        macd_aligned = macd_values[8:]

        macd_cross = None
        macd_cross_candle = None

        # فقط 5 کندل اخیر
        start_index = max(
            1,
            len(signal_values) - 5
        )

        for i in range(
            start_index,
            len(signal_values)
        ):

            previous_macd = macd_aligned[i - 1]
            previous_signal = signal_values[i - 1]

            current_macd = macd_aligned[i]
            current_signal = signal_values[i]

            if (
                previous_macd <= previous_signal
                and current_macd > current_signal
            ):

                macd_cross = (
                    "🟢 کراس صعودی MACD"
                )

                macd_cross_candle = (
                    len(signal_values) - i
                )

            elif (
                previous_macd >= previous_signal
                and current_macd < current_signal
            ):

                macd_cross = (
                    "🔴 کراس نزولی MACD"
                )

                macd_cross_candle = (
                    len(signal_values) - i
                )

        if macd_cross is None:

            if macd_aligned[-1] > signal_values[-1]:

                macd_status = (
                    "🟢 MACD بالاتر از Signal است"
                )

            else:

                macd_status = (
                    "🔴 MACD پایین‌تر از Signal است"
                )

            macd_cross = (
                f"⚪ در ۵ کندل اخیر کراس جدیدی مشاهده نشد\n"
                f"{macd_status}"
            )

        else:

            macd_cross = (
                f"{macd_cross}\n"
                f"⏱ حدود {macd_cross_candle} کندل قبل"
            )

        # =========================
        # پیام نهایی
        # =========================

        message = (
            f"🔄 بررسی کراس‌ها\n\n"
            f"🪙 {symbol}/USD\n"
            f"⏱ تایم‌فریم: {timeframe}\n\n"

            f"━━ EMA ━━\n"
            f"{ema_cross}\n\n"

            f"━━ MACD ━━\n"
            f"{macd_cross}"
        )

        await update.message.reply_text(
            message
        )

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
    telegram_application.add_handler(
        CommandHandler("mtf", mtf_command)
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
