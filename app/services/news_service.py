import os
import httpx

from dotenv import load_dotenv

load_dotenv()

GNEWS_API_KEY = os.getenv("GNEWS_API_KEY")

BASE_URL = "https://gnews.io/api/v4"


async def get_crypto_news(coin_id: str):
    url = f"{BASE_URL}/search"

    params = {
        "q": coin_id,
        "lang": "en",
        "max": 10,
        "apikey": GNEWS_API_KEY
    }

    async with httpx.AsyncClient(
        trust_env=False,
        timeout=30.0
    ) as client:

        response = await client.get(
            url,
            params=params
        )

    response.raise_for_status()

    data = response.json()

    articles = []

    for article in data.get("articles", []):
        articles.append({
            "title": article.get("title"),
            "description": article.get("description"),
            "url": article.get("url"),
            "source": article.get("source", {}).get("name"),
            "published_at": article.get("publishedAt"),
            "image": article.get("image")
        })

    return {
        "coin_id": coin_id,
        "query": coin_id,
        "total_articles": len(articles),
        "articles": articles
    }