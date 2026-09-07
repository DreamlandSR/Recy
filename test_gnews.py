import os
import httpx
from dotenv import load_dotenv

load_dotenv()

GNEWS_API_KEY = os.getenv("GNEWS_API_KEY")

URL = "https://gnews.io/api/v4/search"

params = {
    "q": "Ethereum",
    "lang": "en",
    "max": 10,
    "apikey": GNEWS_API_KEY
}


async def test():
    print("Testing GNews API...")

    async with httpx.AsyncClient(
        trust_env=False,
        timeout=30.0
    ) as client:

        response = await client.get(
            URL,
            params=params
        )

        print("Status:", response.status_code)
        print("URL:", response.url)

        response.raise_for_status()

        data = response.json()

        print("Total articles:", data.get("totalArticles"))
        print()

        for article in data.get("articles", []):
            print("Title:", article.get("title"))
            print("Source:", article.get("source", {}).get("name"))
            print("Published:", article.get("publishedAt"))
            print("-" * 50)


import asyncio

asyncio.run(test())