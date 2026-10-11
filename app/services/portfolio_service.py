"""Jurnal portofolio pribadi Recy — penyimpanan lokal ringan.

Posisi disimpan mentah di ``data/portfolio.json`` (coin_id, buy_price,
amount, notes). ``list_positions()`` memperkaya tiap posisi dengan data
live dari pipeline teknikal yang sama dengan watchlist:

    current_price        harga pasar terkini (CoinGecko, cache 5 menit)
    floating_pnl_usd     keuntungan/kerugian mengambang dalam USD
    floating_pnl_pct     persentase PnL terhadap modal masuk
    sl_status            AMAN / DEKAT / TERSENTUH (harga vs Stop-Loss plan)
    trailing_stop_status MENUNGGU / TERCAPAI (harga vs level trigger trailing)

Kegagalan enrichment per-posisi (429/404 dsb.) tidak menjatuhkan daftar
seluruhnya — posisi tetap tampil dengan ``error`` dan tanpa angka live.
"""

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.services.crypto_service import get_coin_history, get_coin_list
from app.services.technical_service import calculate_sma_ema
from app.services.scoring_service import calculate_technical_score
from app.services.recommendation_service import generate_recommendation

DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "portfolio.json"

# Dekat SL = harga < 1.5% di atas level SL (peringatan dini).
NEAR_SL_PCT = 1.5

_lock = threading.Lock()


# =====================================================================
# Persistence (JSON lokal, atomik, thread-safe)
# =====================================================================

def _load() -> dict:
    if not DATA_PATH.exists():
        return {"positions": []}
    try:
        data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"positions": []}
    if not isinstance(data, dict) or not isinstance(data.get("positions"), list):
        return {"positions": []}
    return data


def _save(data: dict) -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = DATA_PATH.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(DATA_PATH)


def add_position(coin_id: str, buy_price: float, amount: float, notes: str = "") -> dict:
    """Tambah satu posisi beli; mengembalikan posisi yang tersimpan."""
    if buy_price <= 0:
        raise ValueError("buy_price harus lebih besar dari 0.")
    if amount <= 0:
        raise ValueError("amount harus lebih besar dari 0.")

    position = {
        "id": uuid.uuid4().hex[:12],
        "coin_id": coin_id.strip().lower(),
        "buy_price": float(buy_price),
        "amount": float(amount),
        "notes": (notes or "").strip(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    with _lock:
        data = _load()
        data["positions"].append(position)
        _save(data)

    return position


def delete_position(position_id: str):
    """Hapus posisi berdasar id; return posisi terhapus atau None."""
    with _lock:
        data = _load()
        remaining = [p for p in data["positions"] if p.get("id") != position_id]
        if len(remaining) == len(data["positions"]):
            return None
        removed = next(p for p in data["positions"] if p.get("id") == position_id)
        data["positions"] = remaining
        _save(data)
    return removed


def list_raw() -> list:
    with _lock:
        return list(_load()["positions"])


# =====================================================================
# Enrichment live (harga, PnL, status SL & trailing)
# =====================================================================

async def _live_snapshot(coin_id: str) -> dict:
    """Satu snapshot live per koin: harga, SL/TP plan, trend, sinyal.

    Memakai pipeline identik dengan watchlist (history 365 hari) sehingga
    cache 5 menit CoinGecko ikut terpakai — panggilan berulang murah.
    """
    history = await get_coin_history(coin_id, days=365)
    prices = history["prices"]
    volumes = history.get("total_volumes") or []

    technical = calculate_sma_ema(prices, volumes)[-1]
    score = calculate_technical_score(technical)

    recommendation = generate_recommendation(
        score["technical_score"],
        score["condition"],
        trend_filter_ok=score["trend_filter_ok"],
        coin_id=coin_id,
        current_price=technical["price"],
        atr_14=technical.get("atr_14"),
    )
    execution = recommendation["execution"]

    return {
        "current_price": float(execution["current_price"]),
        "sl_price": float(execution["stop_loss_price"]),
        "tp_price": float(execution["take_profit_price"]),
        "sl_distance_pct": float(execution.get("sl_distance_pct") or 0.0),
        "trend": score["condition"],
        "recommendation": recommendation["recommendation"],
    }


async def _coin_names(coin_ids: set) -> dict:
    """Map coin_id -> {name, symbol} dari /coins/list (cache 10 menit)."""
    try:
        coins = await get_coin_list()
        wanted = {c for c in coin_ids}
        return {
            c["id"]: {"name": c.get("name", c["id"]),
                      "symbol": (c.get("symbol") or c["id"]).upper()}
            for c in coins
            if c["id"] in wanted
        }
    except Exception:
        return {}


async def _enrich(position: dict, meta: dict) -> dict:
    out = dict(position)
    info = meta.get(position["coin_id"], {})
    out["name"] = info.get("name", position["coin_id"])
    out["symbol"] = info.get("symbol", position["coin_id"][:6].upper())

    buy = float(position["buy_price"])
    amount = float(position["amount"])
    cost = buy * amount

    out["cost_usd"] = cost

    try:
        snap = await _live_snapshot(position["coin_id"])
    except Exception as exc:  # 429/404 dsb. — posisi tetap tampil
        out["error"] = f"{type(exc).__name__}: {exc}"
        out["current_price"] = None
        out["floating_pnl_usd"] = None
        out["floating_pnl_pct"] = None
        out["sl_status"] = "—"
        out["trailing_stop_status"] = "—"
        return out

    price = snap["current_price"]
    value = price * amount

    out["current_price"] = price
    out["floating_pnl_usd"] = value - cost
    out["floating_pnl_pct"] = ((price / buy) - 1) * 100 if buy > 0 else 0.0
    out["sl_price"] = snap["sl_price"]
    out["tp_price"] = snap["tp_price"]
    out["trend"] = snap["trend"]
    out["recommendation"] = snap["recommendation"]

    # --- Status SL (harga vs level SL rencana) ---
    if price <= snap["sl_price"]:
        out["sl_status"] = "TERSENTUH"
    elif snap["sl_distance_pct"] > 0 and price <= snap["sl_price"] * (1 + NEAR_SL_PCT / 100):
        out["sl_status"] = "DEKAT"
    else:
        out["sl_status"] = "AMAN"

    # --- Status trailing stop ---
    # Trigger mengikuti aturan plan: harga naik sejauh jarak risiko (SL)
    # di atas harga MASUK -> trailing mulai menggeser SL.
    risk_pct = snap["sl_distance_pct"]
    if risk_pct > 0:
        trigger = buy * (1 + risk_pct / 100)
        out["trailing_trigger_price"] = round(trigger, 8)
        out["trailing_stop_status"] = "TERCAPAI" if price >= trigger else "MENUNGGU"
    else:
        out["trailing_trigger_price"] = None
        out["trailing_stop_status"] = "—"

    return out


async def list_positions() -> dict:
    """Seluruh posisi + ringkasan total, diperkaya data live."""
    raw = list_raw()
    meta = await _coin_names({p["coin_id"] for p in raw})

    positions = [await _enrich(p, meta) for p in raw]

    def _sum(key):
        vals = [p[key] for p in positions if p.get(key) is not None]
        return sum(vals) if vals else None

    total_cost = sum(p["cost_usd"] for p in positions)
    total_value = None
    if positions and all(p.get("current_price") is not None for p in positions):
        total_value = sum(p["cost_usd"] + p["floating_pnl_usd"] for p in positions)

    total_pnl = (total_value - total_cost) if total_value is not None else None

    return {
        "count": len(positions),
        "totals": {
            "total_cost_usd": round(total_cost, 2),
            "total_value_usd": round(total_value, 2) if total_value is not None else None,
            "total_pnl_usd": round(total_pnl, 2) if total_pnl is not None else None,
            "total_pnl_pct": (
                round(total_pnl / total_cost * 100, 2)
                if total_pnl is not None and total_cost > 0 else None
            ),
        },
        "positions": positions,
    }
