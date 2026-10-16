"""Alert harga custom (price alert rules) — Phase 9.

Aturan pengguna disimpan di ``data/price_alerts.json``:

    {"alerts": [{"id", "coin_id", "direction": "ABOVE"|"BELOW",
                 "target_price", "active", "created_at",
                 "triggered_at", "trigger_price"}, ...]}

Evaluasi dipanggil ``main.py`` dari endpoint ``/api/crypto/live-prices``
(yang di-poll UI tiap 5 detik) memakai harga live Binance — reaksi dalam
hitungan detik tanpa menambah timer baru. Aturan bersifat SEKALI TEMBAK:
saat harga menyentuh target, alert dinonaktifkan dan harga pemicu
dicatat; pengiriman Telegram / notifikasi desktop dilakukan pemanggil
(main.py / frontend) dari daftar ``triggered``.

Thread-safe & atomik mengikuti pola ``portfolio_service``.
"""

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "price_alerts.json"

# Arah trigger: ABOVE = harga >= target; BELOW = harga <= target.
DIRECTIONS = frozenset({"ABOVE", "BELOW"})

# Alert indikator (Phase 10): nama -> kolom baris teknikal (technical_service).
# Dievaluasi dari history CoinGecko 365 hari yang sudah di-cache 5 menit,
# sehingga cek 10-an detik tetap ringan.
INDICATORS = {"RSI14": "rsi_14", "ADX": "adx_14"}

# Batas aturan aktif (mencegah file tumbuh tak terkendali).
MAX_ACTIVE_ALERTS = 50

_lock = threading.Lock()


def _load() -> dict:
    if not DATA_PATH.exists():
        return {"alerts": [], "indicator_alerts": []}
    try:
        data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"alerts": [], "indicator_alerts": []}
    if not isinstance(data, dict) or not isinstance(data.get("alerts"), list):
        return {"alerts": [], "indicator_alerts": []}
    # File lama mungkin belum punya kunci indicator_alerts (Phase 10).
    if not isinstance(data.get("indicator_alerts"), list):
        data["indicator_alerts"] = []
    return data


def _save(data: dict) -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = DATA_PATH.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    tmp.replace(DATA_PATH)


def add_alert(coin_id: str, direction: str, target_price: float) -> dict:
    """Tambah satu aturan alert aktif; return aturan yang tersimpan.

    Raises ValueError bila arah tidak valid, harga tidak positif, atau
    jumlah aturan aktif mencapai batas.
    """
    direction = (direction or "").strip().upper()
    if direction not in DIRECTIONS:
        raise ValueError(
            f"direction harus salah satu dari {sorted(DIRECTIONS)}."
        )
    target_price = float(target_price)
    if target_price <= 0:
        raise ValueError("target_price harus lebih besar dari 0.")

    alert = {
        "id": uuid.uuid4().hex[:12],
        "coin_id": coin_id.strip().lower(),
        "direction": direction,
        "target_price": target_price,
        "active": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "triggered_at": None,
        "trigger_price": None,
    }

    with _lock:
        data = _load()
        active = [a for a in data["alerts"] if a.get("active")]
        active += [a for a in data["indicator_alerts"] if a.get("active")]
        if len(active) >= MAX_ACTIVE_ALERTS:
            raise ValueError(
                f"Jumlah alert aktif mencapai batas ({MAX_ACTIVE_ALERTS}). "
                "Hapus sebagian dulu."
            )
        data["alerts"].append(alert)
        _save(data)

    return alert


def add_indicator_alert(
    coin_id: str, indicator: str, direction: str, target: float
) -> dict:
    """Tambah aturan alert INDIKATOR (RSI14 / ADX) — sekali tembak.

    Contoh: RSI14 BELOW 30 -> kabari saat RSI harian menyentuh 30 ke bawah.
    """
    indicator = (indicator or "").strip().upper()
    if indicator not in INDICATORS:
        raise ValueError(
            f"indicator harus salah satu dari {sorted(INDICATORS)}."
        )
    direction = (direction or "").strip().upper()
    if direction not in DIRECTIONS:
        raise ValueError(
            f"direction harus salah satu dari {sorted(DIRECTIONS)}."
        )
    target = float(target)
    if target <= 0:
        raise ValueError("target harus lebih besar dari 0.")

    alert = {
        "id": uuid.uuid4().hex[:12],
        "coin_id": coin_id.strip().lower(),
        "indicator": indicator,
        "direction": direction,
        "target": target,
        "active": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "triggered_at": None,
        "trigger_value": None,
    }

    with _lock:
        data = _load()
        active = [a for a in data["alerts"] if a.get("active")]
        active += [a for a in data["indicator_alerts"] if a.get("active")]
        if len(active) >= MAX_ACTIVE_ALERTS:
            raise ValueError(
                f"Jumlah alert aktif mencapai batas ({MAX_ACTIVE_ALERTS}). "
                "Hapus sebagian dulu."
            )
        data["indicator_alerts"].append(alert)
        _save(data)

    return alert


def delete_alert(alert_id: str):
    """Hapus satu aturan (harga maupun indikator; aktif/terpicu)."""
    with _lock:
        data = _load()
        for key in ("alerts", "indicator_alerts"):
            remaining = [a for a in data[key] if a.get("id") != alert_id]
            if len(remaining) == len(data[key]):
                continue
            removed = next(a for a in data[key] if a.get("id") == alert_id)
            data[key] = remaining
            _save(data)
            return removed
    return None


def list_alerts() -> dict:
    """Daftar aturan: aktif dulu (baru ditambah di atas), lalu riwayat
    terpicu (terbaru di atas) — untuk harga & indikator."""
    with _lock:
        data = _load()
        alerts = list(data["alerts"])
        indicators = list(data["indicator_alerts"])

    def _split(items):
        active = [a for a in items if a.get("active")]
        triggered = [
            a for a in items
            if not a.get("active") and a.get("triggered_at")
        ]
        active.sort(key=lambda a: a.get("created_at") or "", reverse=True)
        triggered.sort(key=lambda a: a.get("triggered_at") or "", reverse=True)
        return active, triggered

    active, triggered = _split(alerts)
    ind_active, ind_triggered = _split(indicators)

    return {
        "active": active,
        "triggered": triggered[:20],  # riwayat cukup 20 terakhir
        "active_count": len(active),
        "indicator_active": ind_active,
        "indicator_triggered": ind_triggered[:20],
        "indicator_active_count": len(ind_active),
    }


def evaluate_alerts(prices_by_coin: dict) -> list:
    """Cek semua aturan aktif terhadap {coin_id: harga_live}.

    Aturan yang tersentuh dinonaktifkan (sekali tembak) dengan
    ``trigger_price`` = harga saat picu, lalu disimpan ke disk.
    Return daftar aturan yang baru terpicu (untuk Telegram / notif UI).
    """
    if not prices_by_coin:
        return []

    with _lock:
        data = _load()
        triggered = []
        for alert in data["alerts"]:
            if not alert.get("active"):
                continue
            price = prices_by_coin.get(alert.get("coin_id"))
            if price is None:
                continue
            direction = alert.get("direction")
            target = alert.get("target_price")
            hit = (
                price >= target if direction == "ABOVE"
                else price <= target if direction == "BELOW"
                else False
            )
            if hit:
                alert["active"] = False
                alert["triggered_at"] = datetime.now(timezone.utc).isoformat()
                alert["trigger_price"] = float(price)
                triggered.append(dict(alert))

        if triggered:
            _save(data)

    return triggered


def evaluate_indicator_alerts(values_by_coin: dict) -> list:
    """Cek aturan indikator terhadap {coin_id: {"RSI14": x, "ADX": y}}.

    Sekali tembak seperti harga: aturan terpicu dinonaktifkan + nilai
    pemicu dicatat. Return daftar yang baru terpicu.
    """
    if not values_by_coin:
        return []

    with _lock:
        data = _load()
        triggered = []
        for alert in data["indicator_alerts"]:
            if not alert.get("active"):
                continue
            values = values_by_coin.get(alert.get("coin_id"))
            if not values:
                continue
            value = values.get(alert.get("indicator"))
            if value is None:
                continue
            direction = alert.get("direction")
            target = alert.get("target")
            hit = (
                value >= target if direction == "ABOVE"
                else value <= target if direction == "BELOW"
                else False
            )
            if hit:
                alert["active"] = False
                alert["triggered_at"] = datetime.now(timezone.utc).isoformat()
                alert["trigger_value"] = round(float(value), 4)
                triggered.append(dict(alert))

        if triggered:
            _save(data)

    return triggered


# ============================================================================
# Backup / Restore (Phase 10 — proteksi data jurnal pribadi)
# ============================================================================

def backup_payload() -> dict:
    """Snapshot seluruh aturan alert (harga + indikator) utk file backup."""
    with _lock:
        data = _load()
        return {
            "alerts": [dict(a) for a in data["alerts"]],
            "indicator_alerts": [dict(a) for a in data["indicator_alerts"]],
        }


def restore_payload(payload: dict, mode: str = "merge") -> dict:
    """Pulihkan aturan alert dari backup. `merge` = union by id (data lama
    menang); `replace` = timpa file. Return ringkasan jumlah.

    Raises ValueError bila bentuk payload tidak valid.
    """
    if not isinstance(payload, dict):
        raise ValueError("payload backup tidak valid (bukan objek).")
    price = payload.get("alerts", [])
    indicator = payload.get("indicator_alerts", [])
    if not isinstance(price, list) or not isinstance(indicator, list):
        raise ValueError("payload backup tidak valid (field alerts/indicator_alerts).")

    with _lock:
        data = _load()
        if mode == "replace":
            data["alerts"] = [dict(a) for a in price]
            data["indicator_alerts"] = [dict(a) for a in indicator]
        else:
            for key, incoming in (("alerts", price), ("indicator_alerts", indicator)):
                existing_ids = {a.get("id") for a in data[key]}
                for a in incoming:
                    if isinstance(a, dict) and a.get("id") not in existing_ids:
                        data[key].append(dict(a))
                        existing_ids.add(a.get("id"))
        _save(data)

    return {
        "mode": mode,
        "price_alerts": len(data["alerts"]),
        "indicator_alerts": len(data["indicator_alerts"]),
    }
