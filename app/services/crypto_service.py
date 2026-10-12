import json
import os
import time

import httpx
from dotenv import load_dotenv

from app.services.cache_service import TTLCache, get_json_with_retry

load_dotenv()

COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY")

BASE_URL = "https://api.coingecko.com/api/v3"

# ================= Cache anti rate-limit (429) =================
# TTL per spesifikasi:
#   get_coin_history : 5 menit
#   get_market_data  : 3 menit
#   get_coin_list    : 10 menit (data jarang berubah; dipakai resolve_coin_id)
CACHE_HISTORY_TTL = 5 * 60
CACHE_MARKET_TTL = 3 * 60
CACHE_COIN_LIST_TTL = 10 * 60

_cache = TTLCache()

# Alias simbol ambigu -> id CoinGecko yang benar. Pencocokan simbol saja
# bisa salah sasaran (mis. "sol" cocok dengan token bridging yang lebih
# dulu muncul di /coins/list, bukan Solana). Dicek sebelum pencarian simbol.
SYMBOL_ALIASES = {
    "btc": "bitcoin",
    "eth": "ethereum",
    "sol": "solana",
    "bnb": "binancecoin",
    "xrp": "ripple",
    "ada": "cardano",
    "doge": "dogecoin",
    "sui": "sui",
    "avax": "avalanche-2",
    "dot": "polkadot",
    "matic": "matic-network",
    "link": "chainlink",
    "ltc": "litecoin",
    "trx": "tron",
    "ton": "the-open-network",
    "atom": "cosmos",
    "algo": "algorand",
    "etc": "ethereum-classic",
    "xlm": "stellar",
    "bch": "bitcoin-cash",
}


async def get_market_data():
    cache_key = ("market_data",)
    cached, hit = _cache.get(cache_key)
    if hit:
        return cached

    url = f"{BASE_URL}/coins/markets"

    params = {
        "vs_currency": "usd",
        "order": "market_cap_desc",
        "per_page": 10,
        "page": 1,
        "sparkline": False,
        "price_change_percentage": "24h",
    }

    headers = {
        "x-cg-demo-api-key": COINGECKO_API_KEY
    }

    data = await get_json_with_retry(
        url, params=params, headers=headers,
        fallback_no_key=bool(COINGECKO_API_KEY),
    )
    _cache.set(cache_key, data, CACHE_MARKET_TTL)
    return data

async def get_coin_detail(coin_id: str):
    url = f"{BASE_URL}/coins/{coin_id}"

    headers = {
        "x-cg-demo-api-key": COINGECKO_API_KEY
    }

    params = {
        "localization": "false",
        "tickers": "false",
        "market_data": "true",
        "community_data": "false",
        "developer_data": "false"
    }

    return await get_json_with_retry(
        url, params=params, headers=headers,
        fallback_no_key=bool(COINGECKO_API_KEY),
    )

async def get_coin_history(coin_id: str, days: str = "90", with_api_key: bool = True):
    cache_key = ("coin_history", coin_id, str(days), with_api_key)
    cached, hit = _cache.get(cache_key)
    if hit:
        return cached

    url = f"{BASE_URL}/coins/{coin_id}/market_chart"

    headers = {}
    if with_api_key and COINGECKO_API_KEY:
        headers = {
            "x-cg-demo-api-key": COINGECKO_API_KEY
        }

    params = {
        "vs_currency": "usd",
        "days": str(days),
        "interval": "daily"
    }

    data = await get_json_with_retry(
        url, params=params, headers=headers,
        # Fallback publik hanya relevan bila key ikut dikirim.
        fallback_no_key=bool(headers),
    )
    _cache.set(cache_key, data, CACHE_HISTORY_TTL)
    return data

async def get_coin_list():
    cache_key = ("coin_list",)
    cached, hit = _cache.get(cache_key)
    if hit:
        return cached

    url = f"{BASE_URL}/coins/list"

    headers = {
        "x-cg-demo-api-key": COINGECKO_API_KEY
    }

    data = await get_json_with_retry(
        url, headers=headers, timeout=30.0,
        fallback_no_key=bool(COINGECKO_API_KEY),
    )
    _cache.set(cache_key, data, CACHE_COIN_LIST_TTL)
    return data

async def resolve_coin_id(query: str):
    coins = await get_coin_list()

    query = query.strip().lower()

    # 1. Cari berdasarkan ID
    for coin in coins:
        if coin["id"].lower() == query:
            return coin["id"]

    # 2. Cari berdasarkan nama
    for coin in coins:
        if coin["name"].lower() == query:
            return coin["id"]

    # 3. Alias simbol umum (menghindari salah sasaran)
    alias = SYMBOL_ALIASES.get(query)
    if alias:
        if any(c["id"] == alias for c in coins):
            return alias

    # 4. Cari berdasarkan symbol
    for coin in coins:
        if coin["symbol"].lower() == query:
            return coin["id"]

    return None


# ============================================================================
# Binance public API — harga live real-time (tanpa API key)
# ============================================================================
#
# Data harian CoinGecko (interval: daily) + cache 3-5 menit membuat harga
# di dashboard tertinggal beberapa menit dari bursa riil. Binance menyediakan
# endpoint publik GRATIS tanpa API key, rate limit longgar (1.200 req/menit)
# dan latensi milidetik — dipakai sebagai harga `current_price` live dengan
# cache sangat pendek (5 detik), sehingga harga di dashboard dan level
# Stop-Loss / Take-Profit / Trailing Stop ikut bergerak detik per detik.
# Bila Binance gagal/offline sesaat, hasil kosong -> pemanggil otomatis
# fallback ke CoinGecko (lihat _watchlist_item / crypto_recommendation).

# Host Binance — utama sesuai spesifikasi (api.binance.com), cadangan host
# market-data resmi Binance (data-api.binance.vision; API & data identik).
# Cadangan ini penting: sebagian ISP meng-hijack DNS api.binance.com ke
# halaman blokir dengan sertifikat self-signed (mis. blockpage.xlaxiata.id).
BINANCE_HOSTS = (
    "https://api.binance.com",
    "https://data-api.binance.vision",
)
BINANCE_TICKER_PATH = "/api/v3/ticker/price"
BINANCE_24H_PATH = "/api/v3/ticker/24hr"

BINANCE_LIVE_TTL = 5.0     # detik — sesuai spesifikasi: hanya 5-10 detik
BINANCE_24H_TTL = 30.0     # % 24 jam bergerak pelan — 30 detik cukup
BINANCE_FAIL_TTL = 5.0     # gagal -> coba lagi 5 detik (bukan tiap request)
BINANCE_TIMEOUT = 4.0      # gagal cepat -> fallback CoinGecko tanpa jeda

# coin_id CoinGecko -> pasangan spot Binance (USDT).
# Hanya koin yang terdaftar di sini yang mendapat harga live; koin lain
# otomatis fallback CoinGecko. Daftar diverifikasi langsung terhadap
# endpoint Binance (satu pasangan tidak ada -> seluruh batch 400 -> semua
# fallback, jadi jangan menambah simbol yang belum dipastikan ada).
BINANCE_SYMBOLS = {
    "bitcoin": "BTCUSDT",
    "ethereum": "ETHUSDT",
    "solana": "SOLUSDT",
    "binancecoin": "BNBUSDT",
    "ripple": "XRPUSDT",
    "dogecoin": "DOGEUSDT",
    "cardano": "ADAUSDT",
    "sui": "SUIUSDT",
    "avalanche-2": "AVAXUSDT",
    "polkadot": "DOTUSDT",
    "chainlink": "LINKUSDT",
    "litecoin": "LTCUSDT",
    "tron": "TRXUSDT",
    "the-open-network": "TONUSDT",
    "cosmos": "ATOMUSDT",
    "algorand": "ALGOUSDT",
    "ethereum-classic": "ETCUSDT",
    "stellar": "XLMUSDT",
    "bitcoin-cash": "BCHUSDT",
    "pepe": "PEPEUSDT",
    "shiba-inu": "SHIBUSDT",
    "hedera-hashgraph": "HBARUSDT",
    "aptos": "APTUSDT",
    "arbitrum": "ARBUSDT",
    "optimism": "OPUSDT",
    "uniswap": "UNIUSDT",
    "polygon-ecosystem-token": "POLUSDT",
    "near": "NEARUSDT",
    "internet-computer": "ICPUSDT",
    "filecoin": "FILUSDT",
    "injective-protocol": "INJUSDT",
    "aave": "AAVEUSDT",
    "render-token": "RENDERUSDT",
    "arweave": "ARUSDT",
    "worldcoin-wld": "WLDUSDT",
}

_binance_cache = TTLCache()
_binance_last_warn = 0.0
_binance_host_ok = None  # host terakhir berhasil -> diprioritaskan


def _warn_binance(where: str, exc: Exception) -> None:
    """Log gagal (dithrottle 1x/menit) — fallback CoinGecko tetap jalan."""
    global _binance_last_warn
    now = time.monotonic()
    if now - _binance_last_warn >= 60.0:
        _binance_last_warn = now
        print(
            f"[Binance] {where} gagal: {type(exc).__name__}: {exc} "
            "— memakai harga CoinGecko (fallback).",
            flush=True,
        )


async def _binance_rows(path: str, tag: str, ttl: float):
    """Ambil daftar ticker Binance — satu request untuk semua pasangan.

    Mencoba `BINANCE_HOSTS` berurutan (host yang terakhir berhasil duluan).
    Return list[dict] atau None bila SEMUA host gagal. Kegagalan ikut
    di-cache singkat (`BINANCE_FAIL_TTL`) agar tidak di-hammer saat
    offline sesaat.
    """
    key = ("binance", tag)
    cached, hit = _binance_cache.get(key)
    if hit:
        return cached

    global _binance_host_ok
    hosts = BINANCE_HOSTS
    if _binance_host_ok in BINANCE_HOSTS:
        hosts = (_binance_host_ok,) + tuple(
            h for h in BINANCE_HOSTS if h != _binance_host_ok
        )

    # Format wajib: JSON array tanpa spasi ("symbols=[...]").
    params = {
        "symbols": json.dumps(
            sorted(set(BINANCE_SYMBOLS.values())), separators=(",", ":")
        )
    }

    rows = None
    last_exc = None
    for host in hosts:
        try:
            async with httpx.AsyncClient(trust_env=False, timeout=BINANCE_TIMEOUT) as client:
                response = await client.get(host + path, params=params)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, list):
                raise RuntimeError(f"respons bukan list ({type(data).__name__})")
            rows = data
            _binance_host_ok = host
            break
        except Exception as exc:  # noqa: BLE001 — harga live bersifat opsional
            last_exc = exc

    if rows is None and last_exc is not None:
        _warn_binance(path, last_exc)

    _binance_cache.set(key, rows, ttl if rows is not None else BINANCE_FAIL_TTL)
    return rows


async def get_binance_live_prices(coin_ids=None) -> dict:
    """Harga live Binance (pasangan USDT) untuk coin_id CoinGecko.

    - Endpoint publik `GET /api/v3/ticker/price` — gratis, tanpa API key,
      rate limit longgar (1.200 req/menit), respons milidetik.
    - Cache sangat pendek: hanya `BINANCE_LIVE_TTL` (5 detik) sehingga
      harga selalu segar / real-time live.
    - Return {coin_id: harga_float}. Koin tanpa pasangan Binance atau saat
      Binance gagal -> tidak muncul di hasil ({}), PEMANGGIL WAJIB fallback
      ke harga CoinGecko — fungsi ini tidak pernah melempar exception.
    """
    rows = await _binance_rows(BINANCE_TICKER_PATH, "price", BINANCE_LIVE_TTL)
    if not rows:
        return {}

    wanted = list(BINANCE_SYMBOLS) if coin_ids is None else coin_ids
    by_symbol = {
        row["symbol"]: row
        for row in rows
        if isinstance(row, dict) and row.get("symbol")
    }

    out = {}
    for coin_id in wanted:
        symbol = BINANCE_SYMBOLS.get(coin_id)
        row = by_symbol.get(symbol)
        if row is None:
            continue
        try:
            out[coin_id] = float(row["price"])
        except (KeyError, TypeError, ValueError):
            continue
    return out


async def get_binance_24h_changes(coin_ids=None) -> dict:
    """Perubahan harga 24 jam (%) dari Binance — pendamping header koin.

    Return {coin_id: persen_float} (cache 30 detik); kosong ({}) bila gagal.
    """
    rows = await _binance_rows(BINANCE_24H_PATH, "24h", BINANCE_24H_TTL)
    if not rows:
        return {}

    wanted = list(BINANCE_SYMBOLS) if coin_ids is None else coin_ids
    by_symbol = {
        row["symbol"]: row
        for row in rows
        if isinstance(row, dict) and row.get("symbol")
    }

    out = {}
    for coin_id in wanted:
        symbol = BINANCE_SYMBOLS.get(coin_id)
        row = by_symbol.get(symbol)
        if row is None:
            continue
        try:
            out[coin_id] = float(row["priceChangePercent"])
        except (KeyError, TypeError, ValueError):
            continue
    return out


# ============================================================================
# Binance klines — candle OHLCV intraday (tanpa API key, publik)
# ============================================================================
#
# Grafik dashboard tadinya hanya harga harian CoinGecko (cache 5 menit).
# Endpoint `/api/v3/klines` Binance menyediakan candle OHLCV nyata
# (15m/1h/4h/1d, ...) gratis tanpa API key sehingga chart bisa bergerak
# seperti terminal trading sungguhan. Gagal -> None (pemanggil fallback
# ke riwayat CoinGecko, tanpa exception).

BINANCE_KLINES_PATH = "/api/v3/klines"

# Interval yang diizinkan (whitelist — mencegah input aneh memicu request).
BINANCE_KLINES_INTERVALS = frozenset({"15m", "30m", "1h", "4h", "1d"})

# TTL per jenis interval: intraday berubah cepat (30 detik), harian pelan
# (5 menit — sama dengan cache history CoinGecko).
KLINES_TTL_INTRADAY = 30.0
KLINES_TTL_DAILY = 5 * 60.0

_klines_cache = TTLCache()
_klines_last_warn = 0.0
_klines_host_ok = None  # host terakhir berhasil -> diprioritaskan


async def get_binance_klines(
    coin_id: str,
    interval: str = "1h",
    limit: int = 200,
) -> dict | None:
    """Candle OHLCV Binance untuk satu koin — siap pakai Lightweight Charts.

    Return None bila koin tanpa pasangan USDT, interval tidak di whitelist,
    atau SEMUA host Binance gagal (tidak pernah melempar exception).

    Payload:
    {
      "symbol": "BTCUSDT", "interval": "1h", "source": "binance",
      "bars": [{"time": 1712345678, "open": .., "high": ..,
                "low": .., "close": .., "volume": ..}, ...],
    }
    "time" = detik (epoch open time) — format native Lightweight Charts.
    """
    if interval not in BINANCE_KLINES_INTERVALS:
        return None
    symbol = BINANCE_SYMBOLS.get(coin_id)
    if not symbol:
        return None

    limit = max(10, min(int(limit), 1000))
    ttl = KLINES_TTL_DAILY if interval == "1d" else KLINES_TTL_INTRADAY

    key = ("klines", symbol, interval, limit)
    cached, hit = _klines_cache.get(key)
    if hit:
        return cached

    params = {"symbol": symbol, "interval": interval, "limit": limit}

    global _klines_host_ok
    hosts = BINANCE_HOSTS
    if _klines_host_ok in BINANCE_HOSTS:
        hosts = (_klines_host_ok,) + tuple(
            h for h in BINANCE_HOSTS if h != _klines_host_ok
        )

    rows = None
    last_exc = None
    for host in hosts:
        try:
            async with httpx.AsyncClient(trust_env=False, timeout=BINANCE_TIMEOUT) as client:
                response = await client.get(
                    host + BINANCE_KLINES_PATH, params=params
                )
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, list):
                raise RuntimeError(f"respons bukan list ({type(data).__name__})")
            rows = data
            _klines_host_ok = host
            break
        except Exception as exc:  # noqa: BLE001 — klines bersifat opsional
            last_exc = exc

    if rows is None:
        global _klines_last_warn
        now = time.monotonic()
        if last_exc is not None and now - _klines_last_warn >= 60.0:
            _klines_last_warn = now
            print(
                f"[Binance] klines {symbol}/{interval} gagal: "
                f"{type(last_exc).__name__}: {last_exc} — fallback CoinGecko.",
                flush=True,
            )
        _klines_cache.set(key, None, BINANCE_FAIL_TTL)
        return None

    bars = []
    for row in rows:
        # Format resmi Binance: [openTime, open, high, low, close, volume,
        # closeTime, quoteVolume, trades, ...] — semua string kecuali waktu.
        try:
            bars.append({
                "time": int(row[0]) // 1000,
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
            })
        except (IndexError, TypeError, ValueError):
            continue

    payload = {
        "symbol": symbol,
        "interval": interval,
        "source": "binance",
        "bars": bars,
    }
    _klines_cache.set(key, payload, ttl)
    return payload