import requests
from datetime import datetime

def send_notification(ntfy_topic, symbol, timeframe, gain_24h, price, sl, tp1, tp2, tp3):
    if not ntfy_topic:
        return False
    url = f"https://ntfy.sh{ntfy_topic.strip()}"
    title = f"SAFE LONG SIGNAL: {symbol} (+{gain_24h}%)"
    risk_pct = round(((price - sl) / price) * 100, 2)
    tp1_pct = round(((tp1 - price) / price) * 100, 2)
    tp2_pct = round(((tp2 - price) / price) * 100, 2)
    tp3_pct = round(((tp3 - price) / price) * 100, 2)
    
    message = (
        f"Pair: {symbol} ({timeframe})\n"
        f"24h Gain: +{gain_24h}%\n"
        f"==========================\n"
        f"Entry Price : {price}\n"
        f"Stop Loss   : {sl} (-{risk_pct}% Safe SL)\n"
        f"--------------------------\n"
        f"TP 1 (1:1.5): {tp1} (+{tp1_pct}%) [Move SL to Entry]\n"
        f"TP 2 (1:2.5): {tp2} (+{tp2_pct}%)\n"
        f"TP 3 (1:4.0): {tp3} (+{tp3_pct}%)\n"
        f"==========================\n"
        f"Verified: 15m/1h Bottom Red -> Confirm Bullish\n"
        f"Time: {datetime.now().strftime('%I:%M:%S %p')}"
    )
    headers = {
        "Title": title,
        "Priority": "high",
        "Tags": "rocket,shield,chart_with_upwards_trend"
    }
    try:
        res = requests.post(url, data=message.encode("utf-8"), headers=headers, timeout=10)
        return res.status_code == 200
    except Exception:
        return False
