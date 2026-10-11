"""Notifikasi Telegram untuk Recy (opsional, dikonfigurasi via .env).

Variabel lingkungan yang dibaca:
    TELEGRAM_BOT_TOKEN  token dari @BotFather
    TELEGRAM_CHAT_ID    chat id pengguna (bisa dari getUpdates BotFather)

Bila keduanya belum di-set, semua fungsi melewati pengiriman secara
graceful (return False / configured=False) TANPA error — fitur alert
sepenuhnya opsional.
"""

import asyncio
import os
from datetime import datetime

import httpx
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

_BASE_URL = "https://api.telegram.org/bot{token}/sendMessage"

# Status yang layak dicoba ulang sekali (rate-limit Telegram 429 dsb.).
_RETRYABLE = frozenset({429, 500, 502, 503, 504})


def is_configured() -> bool:
    """True bila token & chat id sudah di-set di .env."""
    return bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)


# ============================================================================
# Background scheduler (alert otomatis, interval configurable via .env)
# ============================================================================

ALERT_INTERVAL_MINUTES = float(os.getenv("ALERT_INTERVAL_MINUTES", "30") or 30)

# Anti-spam (dedupe) — state in-memory per proses:
#   last_sent_signal[coin_id] = "BUY" / "HOLD" / "SELL"  -> kirim hanya saat
#   sinyal BARU BERUBAH menjadi BUY (bukan berulang tiap siklus).
#   last_trailing[coin_id]    = True  -> kirim trailing sekali per level.
last_sent_signal: dict = {}
_last_trailing_sent: dict = {}


def _interval_seconds() -> float:
    return max(1.0, ALERT_INTERVAL_MINUTES) * 60.0


def should_send_buy_signal(coin_id: str, signal: str) -> bool:
    """True hanya bila sinyal baru berubah menjadi BUY (dedupe anti-spam)."""
    previous = last_sent_signal.get(coin_id)
    last_sent_signal[coin_id] = signal
    return signal == "BUY" and previous != "BUY"


def should_send_trailing(coin_id: str, trigger_key: str) -> bool:
    """True bila level trailing yang sama belum pernah dikirim."""
    if _last_trailing_sent.get(coin_id) == trigger_key:
        return False
    _last_trailing_sent[coin_id] = trigger_key
    return True


def _format_sl_alert(item: dict) -> str:
    """Pesan saat harga menyentuh Stop-Loss posisi berjalan."""
    name = item.get("name") or item.get("coin_id", "?")
    symbol = (item.get("symbol") or "?").upper()
    lines = [
        "🛑 <b>RECY — Stop-Loss Tersentuh</b>",
        f"🪙 <b>{name} ({symbol})</b>",
        f"💰 Harga: <code>{_price(item.get('current_price'))}</code>",
        f"🛑 Level SL: <code>{_price(item.get('sl_price'))}</code>",
        f"📊 PnL mengambang: <code>{item.get('floating_pnl_usd', '—')}</code>",
        "\n<i>Evaluasi posisi — jangan menambah risiko. "
        "Bukan nasihat investasi.</i>",
    ]
    return "\n".join(lines)


async def scan_and_alert(watchlist_items: list, positions: list = None) -> dict:
    """Satu siklus scan: filter sinyal baru (dedupe) lalu kirim pesan.

    - watchlist_items : baris watchlist (coin_id, recommendation, price, ...)
    - positions       : posisi portofolio (sl_status, trailing_stop_status, ...)

    Return ringkasan {scanned, buy_new, trailing_new, sl_new, sent}.
    Tanpa konfigurasi Telegram -> skip penuh tanpa error (dormant).
    """
    result = {
        "scanned": len(watchlist_items),
        "buy_new": 0,
        "trailing_new": 0,
        "sl_new": 0,
        "sent": 0,
        "configured": is_configured(),
    }
    if not is_configured():
        return result

    for item in watchlist_items:
        coin_id = item.get("coin_id")
        if not coin_id or "error" in item:
            continue

        if should_send_buy_signal(coin_id, item.get("recommendation", "HOLD")):
            result["buy_new"] += 1
            if await send_telegram_alert(format_signal_alert(item)):
                result["sent"] += 1

    for pos in positions or []:
        coin_id = pos.get("coin_id")
        if not coin_id or pos.get("error"):
            continue

        if pos.get("sl_status") == "TERSENTUH":
            if should_send_trailing(coin_id, f"sl:{pos.get('sl_price')}"):
                result["sl_new"] += 1
                if await send_telegram_alert(_format_sl_alert(pos)):
                    result["sent"] += 1

        if pos.get("trailing_stop_status") == "TERCAPAI":
            key = f"trailing:{pos.get('trailing_trigger_price')}"
            if should_send_trailing(coin_id, key):
                result["trailing_new"] += 1
                msg = format_trailing_alert(
                    pos.get("name", coin_id),
                    pos.get("symbol", "?"),
                    pos.get("current_price"),
                    pos.get("trailing_trigger_price"),
                    pos.get("sl_price"),
                )
                if await send_telegram_alert(msg):
                    result["sent"] += 1

    return result


async def alert_scheduler_loop(scan_fn) -> None:
    """Loop tak berujung di background: scan watchlist + posisi tiap
    ALERT_INTERVAL_MINUTES. `scan_fn() -> (items, positions)` di-supply
    main.py.

    Bila Telegram belum dikonfigurasi, loop tetap tidur (dormant) tanpa
    memanggil scan_fn sama sekali — nol beban jaringan/CPU.
    """
    interval = _interval_seconds()
    if not is_configured():
        print(
            f"[Recy alerts] Telegram belum dikonfigurasi — scheduler "
            f"dormant (interval {ALERT_INTERVAL_MINUTES:g} menit).",
            flush=True,
        )
    else:
        print(
            f"[Recy alerts] Scheduler aktif — scan tiap "
            f"{ALERT_INTERVAL_MINUTES:g} menit.",
            flush=True,
        )

    while True:
        await asyncio.sleep(interval)

        # Re-check tiap siklus: token bisa saja baru diisi lalu server
        # di-reload oleh uvicorn --reload.
        if not is_configured():
            continue

        try:
            items, positions = await scan_fn()
            stats = await scan_and_alert(items, positions)
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            if stats["buy_new"] or stats["trailing_new"] or stats["sl_new"]:
                print(
                    f"[Recy alerts] {stamp} scan={stats['scanned']} "
                    f"buy_baru={stats['buy_new']} trailing={stats['trailing_new']} "
                    f"sl={stats['sl_new']} terkirim={stats['sent']}",
                    flush=True,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — loop tidak boleh mati
            print(f"[Recy alerts] siklus gagal: {type(exc).__name__}: {exc}", flush=True)


async def send_telegram_alert(message: str) -> bool:
    """Kirim pesan (HTML) ke chat Telegram pengguna.

    Return True bila terkirim; False bila belum dikonfigurasi atau
    gagal (tidak pernah melempar exception ke pemanggil).
    """
    if not is_configured():
        return False

    url = _BASE_URL.format(token=TELEGRAM_BOT_TOKEN)
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    for attempt in range(2):
        try:
            async with httpx.AsyncClient(trust_env=False, timeout=15.0) as client:
                response = await client.post(url, json=payload)

            if response.status_code in _RETRYABLE and attempt == 0:
                continue

            response.raise_for_status()
            return True
        except httpx.HTTPError:
            if attempt == 0:
                continue
            return False

    return False


# ============================================================================
# Format pesan alert yang rapi (HTML Telegram)
# ============================================================================

def _price(value) -> str:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return "—"
    if n >= 1:
        return f"${n:,.2f}"
    if n >= 0.01:
        return f"${n:.6f}"
    return f"${n:.8f}"


def format_signal_alert(item: dict) -> str:
    """Pesan rapi untuk koin dengan sinyal BUY (item = baris watchlist)."""
    name = item.get("name") or item.get("coin_id", "?")
    symbol = (item.get("symbol") or "?").upper()

    lines = [
        "🚨 <b>RECY — Sinyal BUY</b>",
        f"🪙 <b>{name} ({symbol})</b>",
        f"💰 Harga: <code>{_price(item.get('price'))}</code>",
        f"📊 Trend: {item.get('trend', '—')}",
        f"🛑 Stop-Loss: <code>{_price(item.get('sl_price'))}</code>",
        f"✅ Take-Profit: <code>{_price(item.get('tp_price'))}</code>",
        f"⚖️ Risk/Reward: {item.get('risk_reward_ratio') or '—'}",
        f"📦 Alokasi: {item.get('suggested_allocation_pct') or '—'}",
    ]

    trailing = item.get("trailing_stop_trigger")
    if trailing:
        lines.append(f"🔁 Trailing: {trailing}")

    lines.append("\n⚠️ <i>Bukan nasihat investasi — kelola risiko Anda.</i>")
    return "\n".join(lines)


def format_trailing_alert(
    name: str,
    symbol: str,
    price,
    trigger_price,
    trailing_level=None,
) -> str:
    """Pesan rapi saat harga menyentuh level trailing stop trigger.

    Dipakai pemantau posisi (posisi berjalan) — level trailing terbaru
    dikirim bila tersedia.
    """
    lines = [
        "🔁 <b>RECY — Trailing Stop Triggered</b>",
        f"🪙 <b>{name} ({symbol.upper()})</b>",
        f"💰 Harga: <code>{_price(price)}</code>",
        f"🎯 Trigger: <code>{_price(trigger_price)}</code>",
    ]
    if trailing_level is not None:
        lines.append(f"📉 Level trailing: <code>{_price(trailing_level)}</code>")

    lines.append(
        "\n<i>Geser SL mengikuti tertinggi — kunci profit. "
        "Bukan nasihat investasi.</i>"
    )
    return "\n".join(lines)
