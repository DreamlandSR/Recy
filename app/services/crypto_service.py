import os
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