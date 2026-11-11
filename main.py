import os
import flet as ft
import threading
import time
from datetime import datetime, date
from scanner_engine import get_top_gainers, verify_15m_and_1h_signal, get_coin_full_analysis
from notifier import send_notification
from updater import check_app_update, CURRENT_VERSION

def main(page: ft.Page):
    page.title = "Binance Long Scanner Pro"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = "#0B0E11"
    page.padding = 0
    page.window_width = 980
    page.window_height = 740
    page.window_min_width = 360
    page.window_min_height = 640

    BG_DARK = "#0B0E11"
    CARD_BG = "#161A1E"
    ELEVATED_BG = "#1E2329"
    BORDER_COLOR = "#2B3139"
    GOLD = "#FCD535"
    GREEN = "#0ECB81"
    RED = "#F6465D"
    TEXT_PRIMARY = "#EAECEF"
    TEXT_MUTED = "#848E9C"

    config = {
        "ntfy_topic": page.client_storage.get("ntfy_topic") or "mn_long_scanner_80",
        "min_gain": float(page.client_storage.get("min_gain") or 5.0),
        "scan_interval": int(page.client_storage.get("scan_interval") or 15),
        "daily_limit": int(page.client_storage.get("daily_limit") or 25),
    }

    is_running = False
    cached_gainers = {}
    selected_coin_report = None
    quota_lock = threading.Lock()

    today_str = date.today().isoformat()
    saved_date = page.client_storage.get("quota_date")
    if saved_date == today_str:
        daily_sent_coins = set(page.client_storage.get("daily_sent_coins") or [])
        message_logs = list(page.client_storage.get("saved_msg_logs") or [])
    else:
        daily_sent_coins = set()
        message_logs = []
        page.client_storage.set("quota_date", today_str)
        page.client_storage.set("daily_sent_coins", [])
        page.client_storage.set("saved_msg_logs", [])
    def check_and_reset_day():
        nonlocal today_str, daily_sent_coins, message_logs
        current_day = date.today().isoformat()
        if current_day != today_str:
            today_str = current_day
            daily_sent_coins.clear()
            message_logs.clear()
            page.client_storage.set("quota_date", today_str)
            page.client_storage.set("daily_sent_coins", [])
            page.client_storage.set("saved_msg_logs", [])
            daily_quota_txt.value = f"0 / {config['daily_limit']}"
            page.update()

    def show_snack(msg, color=GREEN):
        page.snack_bar = ft.SnackBar(
            content=ft.Text(msg, color=ft.Colors.WHITE, weight=ft.FontWeight.W_500),
            bgcolor=color,
            behavior=ft.SnackBarBehavior.FLOATING,
            shape=ft.RoundedRectangleBorder(radius=10)
        )
        page.snack_bar.open = True
        page.update()

    def copy_text(text):
        page.set_clipboard(text)
        show_snack("Copied to clipboard!")

    def check_updates_bg():
        upd = check_app_update()
        if upd:
            dlg = ft.AlertDialog(
                bgcolor=CARD_BG,
                title=ft.Text(f"Update Available: v{upd['version']}", color=GOLD, weight=ft.FontWeight.BOLD),
                content=ft.Text(upd["notes"], size=12, color=TEXT_PRIMARY),
                actions=[
                    ft.TextButton("Later", on_click=lambda e: page.close(dlg)),
                    ft.ElevatedButton("Download", bgcolor=GREEN, color=ft.Colors.BLACK, on_click=lambda e: page.launch_url(upd["windows_url"]))
                ]
            )
            page.open(dlg)

    threading.Thread(target=check_updates_bg, daemon=True).start()

    status_dot = ft.Container(width=8, height=8, border_radius=4, bgcolor=TEXT_MUTED)
    status_label = ft.Text("IDLE", size=11, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY)
    status_pill = ft.Container(
        content=ft.Row([status_dot, status_label], spacing=6, tight=True),
        bgcolor=ELEVATED_BG,
        border=ft.border.all(1, BORDER_COLOR),
        padding=ft.padding.symmetric(horizontal=12, vertical=6),
        border_radius=20
    )

    active_coins_txt = ft.Text("0", size=20, weight=ft.FontWeight.BOLD, color=GOLD)
    daily_quota_txt = ft.Text(f"{len(daily_sent_coins)} / {config['daily_limit']}", size=20, weight=ft.FontWeight.BOLD, color=GREEN)
    timeframe_badge_txt = ft.Text("15m + 1h", size=16, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY)

    live_log_txt = ft.Text("Tap 'Run' to start live Binance Futures scanning...", size=12, color=TEXT_MUTED)
    progress_bar = ft.ProgressBar(value=0, color=GOLD, bgcolor=ELEVATED_BG, height=4, border_radius=2, visible=False)
    empty_state = ft.Container(
        padding=30,
        alignment=ft.alignment.center,
        content=ft.Column([
            ft.Icon(ft.Icons.RADAR, size=48, color=BORDER_COLOR),
            ft.Text("No Signals Detected Yet", size=15, weight=ft.FontWeight.BOLD, color=TEXT_MUTED),
            ft.Text("Confirmed bottom reversal coins (up to 25/day) will appear here.", size=12, color=TEXT_MUTED, text_align=ft.TextAlign.CENTER),
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=6)
    )

    signals_list = ft.ListView(expand=True, spacing=12, padding=ft.padding.only(bottom=20))
    signals_list.controls.append(empty_state)

    selected_coin_card_holder = ft.Container(visible=False)
    msg_header_counter = ft.Text(f"Alert History ({len(message_logs)} Saved):", size=12, weight=ft.FontWeight.BOLD, color=GOLD)
    msg_list_view = ft.ListView(height=240, spacing=8)

    def delete_single_message(index):
        if 0 <= index < len(message_logs):
            message_logs.pop(index)
            page.client_storage.set("saved_msg_logs", message_logs[:50])
            update_message_dialog_list()
            show_snack("Message deleted!", RED)

    def delete_all_messages(e=None):
        message_logs.clear()
        page.client_storage.set("saved_msg_logs", [])
        update_message_dialog_list()
        show_snack("All messages deleted!", RED)

    def clear_selected_coin_report(e=None):
        nonlocal selected_coin_report
        selected_coin_report = None
        selected_coin_card_holder.visible = False
        page.update()

    def update_message_dialog_list():
        msg_header_counter.value = f"Alert History ({len(message_logs)} Saved):"
        msg_list_view.controls.clear()
        if not message_logs:
            msg_list_view.controls.append(
                ft.Container(
                    padding=20, alignment=ft.alignment.center,
                    content=ft.Text("No saved notifications yet.", color=TEXT_MUTED, size=12)
                )
            )
        else:
            for idx, log_item in enumerate(message_logs):
                msg_list_view.controls.append(
                    ft.Container(
                        bgcolor=ELEVATED_BG, padding=10, border_radius=8,
                        border=ft.border.all(1, BORDER_COLOR),
                        content=ft.Row([
                            ft.Text(log_item, size=11, color=TEXT_PRIMARY, expand=True),
                            ft.IconButton(
                                ft.Icons.DELETE_OUTLINE, icon_size=16, icon_color=RED,
                                on_click=lambda e, i=idx: delete_single_message(i)
                            )
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
                    )
                )
        page.update()
    def send_selected_coin_alert(e):
        if not selected_coin_report:
            return
        d = selected_coin_report
        ok = send_notification(
            config["ntfy_topic"], d["symbol"], d["timeframe"], d["gain"],
            d["entry"], d["sl"], d["tp1"], d["tp2"], d["tp3"]
        )
        now_str = datetime.now().strftime('%I:%M:%S %p')
        status_str = "Sent ✅" if ok else "Failed ❌"
        entry_log = f"[{now_str}] Manual: {d['symbol']} | Entry: {d['entry']} | SL: {d['sl']} -> {status_str}"
        message_logs.insert(0, entry_log)
        page.client_storage.set("saved_msg_logs", message_logs[:50])
        update_message_dialog_list()
        show_snack(f"{d['symbol']} sent to phone ({status_str})", GREEN if ok else RED)

    def render_selected_coin_box(data):
        nonlocal selected_coin_report
        selected_coin_report = data
        if not data:
            selected_coin_card_holder.visible = False
            return

        full_text = (
            f"Pair: {data['symbol']} ({data['timeframe']})\n"
            f"Status: {data['status']}\n"
            f"24h Gain: +{data['gain']}% | Vol: ${data['volume']}M\n"
            f"Entry: {data['entry']} | Safe SL: {data['sl']} (-{data['risk_pct']}%)\n"
            f"TP1: {data['tp1']} | TP2: {data['tp2']} | TP3: {data['tp3']}"
        )

        selected_coin_card_holder.visible = True
        selected_coin_card_holder.content = ft.Container(
            bgcolor=ELEVATED_BG, padding=12, border_radius=12,
            border=ft.border.all(1, GREEN if data["matched"] else GOLD),
            content=ft.Column([
                ft.Row([
                    ft.Row([
                        ft.Icon(ft.Icons.ANALYTICS, color=GOLD, size=18),
                        ft.Text(f"{data['symbol']} Report", size=14, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY),
                    ], spacing=6),
                    ft.Row([
                        ft.Container(
                            content=ft.Text(f"+{data['gain']}%", size=11, weight=ft.FontWeight.BOLD, color=GREEN),
                            bgcolor="#0ECB8120", padding=ft.padding.symmetric(horizontal=7, vertical=2), border_radius=6
                        ),
                        ft.IconButton(ft.Icons.CLOSE, icon_size=16, icon_color=RED, on_click=clear_selected_coin_report)
                    ], spacing=2)
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),

                ft.Text(f"Status: {data['status']}", size=11, weight=ft.FontWeight.BOLD, color=GREEN if data["matched"] else GOLD),
                ft.Text(f"TF: {data['timeframe']}  •  24h Vol: ${data['volume']}M", size=11, color=TEXT_MUTED),
                ft.Divider(height=4, color=BORDER_COLOR),

                ft.Row([
                    ft.Column([ft.Text("ENTRY", size=9, color=TEXT_MUTED), ft.Text(f"{data['entry']}", size=12, weight=ft.FontWeight.BOLD)]),
                    ft.Column([ft.Text(f"SAFE SL (-{data['risk_pct']}%)", size=9, color=RED), ft.Text(f"{data['sl']}", size=12, weight=ft.FontWeight.BOLD, color=RED)]),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),

                ft.Row([
                    ft.Column([ft.Text("TP 1 (1:1.5)", size=9, color=TEXT_MUTED), ft.Text(f"{data['tp1']}", size=11, weight=ft.FontWeight.BOLD, color=GREEN)]),
                    ft.Column([ft.Text("TP 2 (1:2.5)", size=9, color=TEXT_MUTED), ft.Text(f"{data['tp2']}", size=11, weight=ft.FontWeight.BOLD, color=GREEN)]),
                    ft.Column([ft.Text("TP 3 (1:4.0)", size=9, color=TEXT_MUTED), ft.Text(f"{data['tp3']}", size=11, weight=ft.FontWeight.BOLD, color=GOLD)]),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),

                ft.Row([
                    ft.ElevatedButton("Send Alert", icon=ft.Icons.SEND, bgcolor=GREEN, color=ft.Colors.BLACK, height=32, on_click=send_selected_coin_alert),
                    ft.OutlinedButton("Copy", icon=ft.Icons.COPY, height=32, on_click=lambda e, t=full_text: copy_text(t)),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
            ], spacing=6)
        )
    def create_signal_card(symbol, tf, gain, vol, entry, sl, tp1, tp2, tp3, timestamp_str):
        risk_pct = round(((entry - sl) / entry) * 100, 2)
        copy_payload = (
            f"🚀 LONG SIGNAL: {symbol} ({tf})\n"
            f"Entry: {entry} | SL: {sl} (-{risk_pct}%)\n"
            f"TP1: {tp1} | TP2: {tp2} | TP3: {tp3}"
        )
        return ft.Container(
            bgcolor=CARD_BG,
            padding=14,
            border_radius=12,
            border=ft.border.all(1, BORDER_COLOR),
            content=ft.Column([
                ft.Row([
                    ft.Row([
                        ft.Container(
                            content=ft.Text("LONG", size=10, weight=ft.FontWeight.BOLD, color=ft.Colors.BLACK),
                            bgcolor=GREEN, padding=ft.padding.symmetric(horizontal=6, vertical=2), border_radius=4
                        ),
                        ft.Text(symbol, size=16, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY),
                        ft.Container(
                            content=ft.Text(tf, size=10, color=GOLD, weight=ft.FontWeight.BOLD),
                            bgcolor="#FCD53515", padding=ft.padding.symmetric(horizontal=6, vertical=2), border_radius=4
                        )
                    ], spacing=6),
                    ft.Row([
                        ft.Text(f"+{gain}%", size=13, weight=ft.FontWeight.BOLD, color=GREEN),
                        ft.IconButton(ft.Icons.COPY, icon_size=16, icon_color=TEXT_MUTED, on_click=lambda e: copy_text(copy_payload))
                    ], spacing=2)
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),

                ft.Text(f"Detected: {timestamp_str}  •  24h Vol: ${vol}M", size=11, color=TEXT_MUTED),
                ft.Divider(height=6, color=BORDER_COLOR),

                ft.Row([
                    ft.Column([ft.Text("ENTRY PRICE", size=10, color=TEXT_MUTED), ft.Text(f"{entry}", size=13, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY)]),
                    ft.Column([ft.Text(f"SAFE SL (-{risk_pct}%)", size=10, color=RED), ft.Text(f"{sl}", size=13, weight=ft.FontWeight.BOLD, color=RED)]),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),

                ft.Container(
                    bgcolor=ELEVATED_BG, padding=10, border_radius=8,
                    content=ft.Row([
                        ft.Column([ft.Text("TP 1 (1:1.5)", size=9, color=TEXT_MUTED), ft.Text(f"{tp1}", size=12, weight=ft.FontWeight.BOLD, color=GREEN)]),
                        ft.Column([ft.Text("TP 2 (1:2.5)", size=9, color=TEXT_MUTED), ft.Text(f"{tp2}", size=12, weight=ft.FontWeight.BOLD, color=GREEN)]),
                        ft.Column([ft.Text("TP 3 (1:4.0)", size=9, color=TEXT_MUTED), ft.Text(f"{tp3}", size=12, weight=ft.FontWeight.BOLD, color=GOLD)]),
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
                )
            ], spacing=8)
        )
    def scanner_loop():
        nonlocal is_running, cached_gainers
        while is_running:
            try:
                check_and_reset_day()
                if len(daily_sent_coins) >= config["daily_limit"]:
                    live_log_txt.value = f"Daily limit ({config['daily_limit']}) reached. Waiting for tomorrow..."
                    progress_bar.visible = False
                    page.update()
                    time.sleep(30)
                    continue

                live_log_txt.value = "Fetching top Binance Futures gainers..."
                progress_bar.visible = True
                progress_bar.value = None
                page.update()

                gainers = get_top_gainers(min_gain=config["min_gain"])
                cached_gainers = gainers
                symbols = list(gainers.keys())
                active_coins_txt.value = str(len(symbols))
                page.update()

                if not symbols:
                    live_log_txt.value = f"No pairs >= +{config['min_gain']}%. Retrying in {config['scan_interval']}s..."
                    progress_bar.visible = False
                    page.update()
                else:
                    total = len(symbols)
                    for idx, sym in enumerate(symbols):
                        if not is_running:
                            break
                        if sym in daily_sent_coins:
                            continue
                        if len(daily_sent_coins) >= config["daily_limit"]:
                            break

                        progress_bar.value = (idx + 1) / total
                        live_log_txt.value = f"Analyzing [{idx+1}/{total}]: {sym} (15m & 1h)..."
                        page.update()

                        matched, tf, entry, sl, tp1, tp2, tp3, _ = verify_15m_and_1h_signal(sym)
                        if matched:
                            with quota_lock:
                                if sym not in daily_sent_coins and len(daily_sent_coins) < config["daily_limit"]:
                                    daily_sent_coins.add(sym)
                                    page.client_storage.set("daily_sent_coins", list(daily_sent_coins))
                                    daily_quota_txt.value = f"{len(daily_sent_coins)} / {config['daily_limit']}"

                                    info = gainers.get(sym, {"gain": 0, "volume": 0})
                                    now_str = datetime.now().strftime('%I:%M:%S %p')

                                    ok = send_notification(
                                        config["ntfy_topic"], sym, tf, info["gain"],
                                        entry, sl, tp1, tp2, tp3
                                    )
                                    status_str = "Sent ✅" if ok else "Failed ❌"
                                    log_msg = f"[{now_str}] {sym} ({tf}) | Entry: {entry} -> {status_str}"
                                    message_logs.insert(0, log_msg)
                                    page.client_storage.set("saved_msg_logs", message_logs[:50])

                                    if empty_state in signals_list.controls:
                                        signals_list.controls.remove(empty_state)

                                    card = create_signal_card(sym, tf, info["gain"], info["volume"], entry, sl, tp1, tp2, tp3, now_str)
                                    signals_list.controls.insert(0, card)
                                    live_log_txt.value = f"🔥 SIGNAL FOUND: {sym} ({tf})!"
                                    page.update()

                    progress_bar.visible = False
                    if is_running:
                        live_log_txt.value = f"Scan complete. Next cycle in {config['scan_interval']}s..."
                        page.update()

            except Exception as ex:
                live_log_txt.value = f"Network warning: {str(ex)[:45]}..."
                progress_bar.visible = False
                page.update()

            for _ in range(config["scan_interval"]):
                if not is_running:
                    break
                time.sleep(1)
    def toggle_scanner(e):
        nonlocal is_running
        is_running = not is_running
        if is_running:
            run_btn.text = "Stop"
            run_btn.icon = ft.Icons.STOP_CIRCLE
            run_btn.bgcolor = RED
            status_dot.bgcolor = GREEN
            status_label.value = "SCANNING"
            threading.Thread(target=scanner_loop, daemon=True).start()
        else:
            run_btn.text = "Run"
            run_btn.icon = ft.Icons.PLAY_ARROW
            run_btn.bgcolor = GREEN
            status_dot.bgcolor = TEXT_MUTED
            status_label.value = "IDLE"
            progress_bar.visible = False
            live_log_txt.value = "Scanner paused."
        page.update()

    search_input = ft.TextField(
        label="Coin Symbol (e.g. BTCUSDT, SOLUSDT)",
        border_color=BORDER_COLOR, focused_border_color=GOLD,
        text_size=13, height=45, capitalizations=ft.TextCapitalization.CHARACTERS
    )

    def analyze_manual_coin(e):
        sym = search_input.value.strip().upper()
        if not sym:
            return
        if not sym.endswith("USDT"):
            sym += "USDT"
        show_snack(f"Analyzing {sym}...", GOLD)
        def worker():
            try:
                t_info = cached_gainers.get(sym)
                report = get_coin_full_analysis(sym, t_info)
                render_selected_coin_box(report)
                page.update()
            except Exception:
                show_snack(f"Could not fetch {sym}. Check symbol name.", RED)
        threading.Thread(target=worker, daemon=True).start()

    def open_message_box(e):
        update_message_dialog_list()
        dlg = ft.AlertDialog(
            bgcolor=CARD_BG,
            title=ft.Row([
                ft.Text("Analyzer & Alert Logs", size=16, weight=ft.FontWeight.BOLD),
                ft.IconButton(ft.Icons.DELETE_SWEEP, icon_color=RED, tooltip="Clear All Logs", on_click=delete_all_messages)
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            content=ft.Container(
                width=420,
                content=ft.Column([
                    ft.Row([
                        ft.Container(content=search_input, expand=True),
                        ft.ElevatedButton("Check", bgcolor=GOLD, color=ft.Colors.BLACK, height=45, on_click=analyze_manual_coin)
                    ], spacing=8),
                    selected_coin_card_holder,
                    ft.Divider(color=BORDER_COLOR),
                    msg_header_counter,
                    msg_list_view
                ], tight=True, spacing=10)
            ),
            actions=[ft.TextButton("Close", on_click=lambda e: page.close(dlg))]
        )
        page.open(dlg)

    def open_settings(e):
        ntfy_field = ft.TextField(label="Ntfy.sh Topic Name", value=config["ntfy_topic"], border_color=BORDER_COLOR)
        gain_field = ft.TextField(label="Min 24h Gain (%)", value=str(config["min_gain"]), keyboard_type=ft.KeyboardType.NUMBER, border_color=BORDER_COLOR)
        interval_field = ft.TextField(label="Scan Interval (Seconds)", value=str(config["scan_interval"]), keyboard_type=ft.KeyboardType.NUMBER, border_color=BORDER_COLOR)
        limit_field = ft.TextField(label="Daily Signal Limit", value=str(config["daily_limit"]), keyboard_type=ft.KeyboardType.NUMBER, border_color=BORDER_COLOR)

        def save_settings(ev):
            try:
                config["ntfy_topic"] = ntfy_field.value.strip()
                config["min_gain"] = max(1.0, float(gain_field.value))
                config["scan_interval"] = max(5, int(interval_field.value))
                config["daily_limit"] = max(1, int(limit_field.value))

                page.client_storage.set("ntfy_topic", config["ntfy_topic"])
                page.client_storage.set("min_gain", config["min_gain"])
                page.client_storage.set("scan_interval", config["scan_interval"])
                page.client_storage.set("daily_limit", config["daily_limit"])

                daily_quota_txt.value = f"{len(daily_sent_coins)} / {config['daily_limit']}"
                page.close(dlg)
                show_snack("Settings saved successfully!")
            except ValueError:
                show_snack("Please enter valid numbers!", RED)

        dlg = ft.AlertDialog(
            bgcolor=CARD_BG,
            title=ft.Text("Scanner Settings", size=16, weight=ft.FontWeight.BOLD),
            content=ft.Container(
                width=360,
                content=ft.Column([
                    ntfy_field, gain_field, interval_field, limit_field,
                    ft.Text(f"App Version: v{CURRENT_VERSION}", size=11, color=TEXT_MUTED)
                ], tight=True, spacing=12)
            ),
            actions=[
                ft.TextButton("Cancel", on_click=lambda ev: page.close(dlg)),
                ft.ElevatedButton("Save", bgcolor=GOLD, color=ft.Colors.BLACK, on_click=save_settings)
            ]
        )
        page.open(dlg)

    run_btn = ft.ElevatedButton(
        "Run", icon=ft.Icons.PLAY_ARROW, bgcolor=GREEN, color=ft.Colors.BLACK,
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10)),
        on_click=toggle_scanner
    )

    header = ft.Container(
        bgcolor=CARD_BG,
        padding=ft.padding.symmetric(horizontal=16, vertical=12),
        border=ft.border.only(bottom=ft.BorderSide(1, BORDER_COLOR)),
        content=ft.Row([
            ft.Row([
                ft.Icon(ft.Icons.CANDLESTICK_CHART, color=GOLD, size=24),
                ft.Column([
                    ft.Text("Binance Long Pro", size=16, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY),
                    status_pill
                ], spacing=4)
            ], spacing=10),
            ft.Row([
                ft.IconButton(ft.Icons.MAIL_OUTLINE, icon_color=GOLD, tooltip="Analyzer & Logs", on_click=open_message_box),
                ft.IconButton(ft.Icons.SETTINGS_OUTLINED, icon_color=TEXT_PRIMARY, tooltip="Settings", on_click=open_settings),
                run_btn
            ], spacing=4)
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
    )

    stats_row = ft.Row([
        ft.Container(
            expand=True, bgcolor=CARD_BG, padding=12, border_radius=12,
            border=ft.border.all(1, BORDER_COLOR),
            content=ft.Column([
                ft.Text("ACTIVE GAINERS", size=10, color=TEXT_MUTED),
                active_coins_txt
            ], spacing=4)
        ),
        ft.Container(
            expand=True, bgcolor=CARD_BG, padding=12, border_radius=12,
            border=ft.border.all(1, BORDER_COLOR),
            content=ft.Column([
                ft.Text("DAILY QUOTA", size=10, color=TEXT_MUTED),
                daily_quota_txt
            ], spacing=4)
        ),
        ft.Container(
            expand=True, bgcolor=CARD_BG, padding=12, border_radius=12,
            border=ft.border.all(1, BORDER_COLOR),
            content=ft.Column([
                ft.Text("STRATEGY", size=10, color=TEXT_MUTED),
                timeframe_badge_txt
            ], spacing=4)
        ),
    ], spacing=10)

    status_banner = ft.Container(
        bgcolor=ELEVATED_BG, padding=10, border_radius=10,
        border=ft.border.all(1, BORDER_COLOR),
        content=ft.Column([
            ft.Row([
                ft.Icon(ft.Icons.TERMINAL, size=14, color=GOLD),
                ft.Container(content=live_log_txt, expand=True)
            ], spacing=8),
            progress_bar
        ], spacing=6)
    )

    body = ft.Container(
        expand=True,
        padding=ft.padding.symmetric(horizontal=16, vertical=12),
        content=ft.Column([
            stats_row,
            status_banner,
            ft.Text("LIVE CONFIRMED SIGNALS", size=12, weight=ft.FontWeight.BOLD, color=TEXT_MUTED),
            signals_list
        ], spacing=12, expand=True)
    )

    page.add(ft.Column([header, body], spacing=0, expand=True))

if __name__ == "__main__":
    ft.app(target=main)
