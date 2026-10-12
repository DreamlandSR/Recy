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

# Batas aturan aktif (mencegah file tumbuh tak terkendali).
MAX_ACTIVE_ALERTS = 50

_lock = threading.Lock()


def _load() -> dict:
    if not DATA_PATH.exists():
        return {"alerts": []}
    try:
        data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"alerts": []}
    if not isinstance(data, dict) or not isinstance(data.get("alerts"), list):
        return {"alerts": []}
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
        if len(active) >= MAX_ACTIVE_ALERTS:
            raise ValueError(
                f"Jumlah alert aktif mencapai batas ({MAX_ACTIVE_ALERTS}). "
                "Hapus sebagian dulu."
            )
        data["alerts"].append(alert)
        _save(data)

    return alert


def delete_alert(alert_id: str):
    """Hapus satu aturan (aktif maupun sudah terpicu); return atau None."""
    with _lock:
        data = _load()
        remaining = [a for a in data["alerts"] if a.get("id") != alert_id]
        if len(remaining) == len(data["alerts"]):
            return None
        removed = next(a for a in data["alerts"] if a.get("id") == alert_id)
        data["alerts"] = remaining
        _save(data)
    return removed


def list_alerts() -> dict:
    """Daftar aturan: aktif dulu (baru ditambah di atas), lalu riwayat
    terpicu (terbaru di atas)."""
    with _lock:
        alerts = [a for a in _load()["alerts"]]

    active = [a for a in alerts if a.get("active")]
    triggered = [
        a for a in alerts
        if not a.get("active") and a.get("triggered_at")
    ]
    active.sort(key=lambda a: a.get("created_at") or "", reverse=True)
    triggered.sort(key=lambda a: a.get("triggered_at") or "", reverse=True)

    return {
        "active": active,
        "triggered": triggered[:20],  # riwayat cukup 20 terakhir
        "active_count": len(active),
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
