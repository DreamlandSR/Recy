import os
import httpx
from dotenv import load_dotenv

load_dotenv()

COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY")

BASE_URL = "https://api.coingecko.com/api/v3"


async def get_market_data():
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

    async with httpx.AsyncClient(trust_env=False) as client:
        response = await client.get(
            url,
            params=params,
            headers=headers
        )

    response.raise_for_status()

    return response.json()

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

    async with httpx.AsyncClient(trust_env=False) as client:
        response = await client.get(
            url,
            params=params,
            headers=headers
        )

    response.raise_for_status()

    return response.json()

async def get_coin_history(coin_id: str, days: str = "90", with_api_key: bool = True):
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

    async with httpx.AsyncClient(trust_env=False) as client:
        response = await client.get(
            url,
            params=params,
            headers=headers
        )

    response.raise_for_status()

    return response.json()

async def get_coin_list():
    url = f"{BASE_URL}/coins/list"

    headers = {
        "x-cg-demo-api-key": COINGECKO_API_KEY
    }

    async with httpx.AsyncClient(
        trust_env=False,
        timeout=30.0
    ) as client:

        response = await client.get(
            url,
            headers=headers
        )

    response.raise_for_status()

    return response.json()

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

    # 3. Cari berdasarkan symbol
    for coin in coins:
        if coin["symbol"].lower() == query:
            return coin["id"]

    return None