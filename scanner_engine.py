import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_URL = "https://binance.com"

session = requests.Session()
retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504])
session.mount("https://", HTTPAdapter(max_retries=retries, pool_connections=20, pool_maxsize=20))

def get_decimal_places(price):
    price_str = f"{price:.10f}".rstrip('0')
    if '.' in price_str:
        parts = price_str.split('.')
        return len(parts[1]) if len(parts) > 1 else 2
    return 2

def calculate_ema(prices, period):
    if len(prices) < period:
        return [prices[-1]] * len(prices)
    k = 2 / (period + 1)
    ema = [sum(prices[:period]) / period]
    for price in prices[period:]:
        ema.append(price * k + ema[-1] * (1 - k))
    pad = [ema[0]] * (len(prices) - len(ema))
    return pad + ema

def calculate_macd(prices):
    ema12 = calculate_ema(prices, 12)
    ema26 = calculate_ema(prices, 26)
    dif = [e12 - e26 for e12, e26 in zip(ema12, ema26)]
    dea = calculate_ema(dif, 9)
    hist = [d - s for d, s in zip(dif, dea)]
    return dif, dea, hist

def calculate_atr(candles, period=14):
    if len(candles) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(candles)):
        h = candles[i]['high']
        l = candles[i]['low']
        pc = candles[i - 1]['close']
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
    return sum(trs[-period:]) / period

def get_top_gainers(min_gain=5.0):
    url = f"{BASE_URL}/fapi/v1/ticker/24hr"
    resp = session.get(url, timeout=15).json()
    if not isinstance(resp, list):
        return {}
    gainers = {}
    for item in resp:
        symbol = item.get("symbol", "")
        if symbol.endswith("USDT") and not symbol.endswith("_PERP"):
            try:
                price_change_pct = float(item.get("priceChangePercent", 0))
                last_price = float(item.get("lastPrice", 0))
                volume_usdt = float(item.get("quoteVolume", 0))
                high_price = float(item.get("highPrice", 0))
                low_price = float(item.get("lowPrice", 0))
                if price_change_pct >= min_gain and volume_usdt >= 2_000_000:
                    gainers[symbol] = {
                        "gain": round(price_change_pct, 2),
                        "price": last_price,
                        "volume": round(volume_usdt / 1_000_000, 2),
                        "high_24h": high_price,
                        "low_24h": low_price
                    }
            except (ValueError, TypeError):
                continue
    return dict(sorted(gainers.items(), key=lambda x: x[1]["gain"], reverse=True))

def fetch_klines(symbol, interval):
    url = f"{BASE_URL}/fapi/v1/klines"
    params = {"symbol": symbol, "interval": interval, "limit": 120}
    return session.get(url, params=params, timeout=10).json()
def check_bottom_bullish_pattern(klines_data):
    if not klines_data or not isinstance(klines_data, list) or len(klines_data) < 105:
        return False, 0, 0, 0, 0, 0, 0

    candles = []
    closes = []
    for k in klines_data:
        c_close = float(k[4])
        closes.append(c_close)
        candles.append({
            'time': k[0],
            'open': float(k[1]),
            'high': float(k[2]),
            'low': float(k[3]),
            'close': c_close,
            'volume': float(k[5])
        })

    curr = candles[-2]
    prev = candles[-3]

    support_zone_low = min(c['low'] for c in candles[-42:-2])
    is_absolute_bottom = prev['low'] <= support_zone_low * 1.0015 and curr['low'] >= prev['low'] * 0.998
    if not is_absolute_bottom:
        return False, 0, 0, 0, 0, 0, 0

    if not (prev['close'] < prev['open'] and curr['close'] > curr['open']):
        return False, 0, 0, 0, 0, 0, 0

    past_10 = candles[-13:-3]
    past_5 = candles[-8:-3]
    past_3 = candles[-6:-3]

    high_10 = max(c['high'] for c in past_10)
    high_5 = max(c['high'] for c in past_5)
    downtrend_structure = (high_10 >= high_5) and (high_5 > prev['high'])

    red_in_10 = sum(1 for c in past_10 if c['close'] < c['open']) >= 5
    red_in_5 = sum(1 for c in past_5 if c['close'] < c['open']) >= 3
    downtrend_3 = past_3[-1]['close'] < past_3[0]['open']

    if not (downtrend_structure and red_in_10 and red_in_5 and downtrend_3):
        return False, 0, 0, 0, 0, 0, 0

    curr_body = curr['close'] - curr['open']
    prev_body = prev['open'] - prev['close']
    curr_total_range = curr['high'] - curr['low']
    upper_wick = curr['high'] - curr['close']

    if curr_body <= 0 or prev_body <= 0 or curr_total_range <= 0:
        return False, 0, 0, 0, 0, 0, 0

    bullish_engulfing = (curr['close'] >= prev['open']) and (curr_body >= prev_body * 0.85)
    clean_strong_candle = (curr_body / curr_total_range) >= 0.55 and upper_wick <= (curr_body * 0.35)
    volume_spike = curr['volume'] >= (prev['volume'] * 1.0)

    if not (bullish_engulfing and clean_strong_candle and volume_spike):
        return False, 0, 0, 0, 0, 0, 0

    ema7 = calculate_ema(closes, 7)
    dif, dea, hist = calculate_macd(closes)

    if not (curr['close'] > ema7[-2] and hist[-2] > hist[-3] and dif[-2] >= dif[-3]):
        return False, 0, 0, 0, 0, 0, 0

    decimals = get_decimal_places(curr['close'])
    entry = curr['close']
    atr = calculate_atr(candles[:-1], period=14)

    bottom_low = min(prev['low'], curr['low'])
    safe_buffer = max(bottom_low * 0.0015, atr * 0.25)
    sl = round(bottom_low - safe_buffer, decimals)

    risk = entry - sl
    risk_pct = (risk / entry) * 100

    if risk <= 0 or risk_pct < 0.35 or risk_pct > 2.2:
        return False, 0, 0, 0, 0, 0, 0

    tp1 = round(entry + (risk * 1.5), decimals)
    tp2 = round(entry + (risk * 2.5), decimals)
    tp3 = round(entry + (risk * 4.0), decimals)

    return True, entry, sl, tp1, tp2, tp3, curr['time']

def verify_15m_and_1h_signal(symbol):
    klines_1h = fetch_klines(symbol, "1h")
    matched_1h, entry_1h, sl_1h, tp1_1h, tp2_1h, tp3_1h, time_1h = check_bottom_bullish_pattern(klines_1h)
    if matched_1h:
        return True, "1h", entry_1h, sl_1h, tp1_1h, tp2_1h, tp3_1h, time_1h

    klines_15m = fetch_klines(symbol, "15m")
    matched_15m, entry_15m, sl_15m, tp1_15m, tp2_15m, tp3_15m, time_15m = check_bottom_bullish_pattern(klines_15m)
    if matched_15m:
        if isinstance(klines_1h, list) and len(klines_1h) >= 5:
            h1_curr_close = float(klines_1h[-1][4])
            h1_curr_open = float(klines_1h[-1][1])
            h1_prev_close = float(klines_1h[-2][4])
            h1_prev_open = float(klines_1h[-2][1])
            if (h1_curr_close >= h1_curr_open) or (h1_prev_close > h1_prev_open):
                return True, "15m + 1h Confirmed", entry_15m, sl_15m, tp1_15m, tp2_15m, tp3_15m, time_15m

    return False, "", 0, 0, 0, 0, 0, 0

def get_coin_full_analysis(symbol, ticker_info=None):
    klines_15m = fetch_klines(symbol, "15m")
    matched, tf_label, entry, sl, tp1, tp2, tp3, _ = verify_15m_and_1h_signal(symbol)

    live_price = ticker_info["price"] if ticker_info else float(klines_15m[-1][4])
    gain_24h = ticker_info["gain"] if ticker_info else 0.0
    vol_24h = ticker_info["volume"] if ticker_info else 0.0
    high_24h = ticker_info.get("high_24h", live_price) if ticker_info else live_price
    low_24h = ticker_info.get("low_24h", live_price) if ticker_info else live_price

    decimals = get_decimal_places(live_price)

    if not matched:
        candles_15m = [{
            'high': float(k[2]), 'low': float(k[3]), 'close': float(k[4])
        } for k in klines_15m[-30:]]
        atr = calculate_atr(candles_15m, 14)
        support_low = min(c['low'] for c in candles_15m[-20:])
        entry = live_price
        sl = round(support_low - max(support_low * 0.0015, atr * 0.25), decimals)
        risk = max(entry - sl, entry * 0.005)
        if sl >= entry:
            sl = round(entry - risk, decimals)
        tp1 = round(entry + (risk * 1.5), decimals)
        tp2 = round(entry + (risk * 2.5), decimals)
        tp3 = round(entry + (risk * 4.0), decimals)
        status_text = "WAITING (Bottom Reversal Pending)"
        tf_display = "15m / 1h Watching"
    else:
        status_text = "CONFIRMED LONG SIGNAL ✅"
        tf_display = tf_label

    risk_pct = round(((entry - sl) / entry) * 100, 2)

    return {
        "symbol": symbol,
        "matched": matched,
        "status": status_text,
        "timeframe": tf_display,
        "gain": gain_24h,
        "price": live_price,
        "volume": vol_24h,
        "high_24h": high_24h,
        "low_24h": low_24h,
        "entry": entry,
        "sl": sl,
        "risk_pct": risk_pct,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3
    }
