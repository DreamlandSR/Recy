import os
import httpx

from dotenv import load_dotenv

load_dotenv()

GNEWS_API_KEY = os.getenv("GNEWS_API_KEY")

BASE_URL = "https://gnews.io/api/v4"


async def get_crypto_news(
    coin_id: str,
    query: str = None,
    max_results: int = 10,
    from_: str = None,
    to: str = None,
    sortby: str = None,
):
    """Ambil berita dari GNews.

    Parameter opsional `from_`/`to` (ISO 8601) dipakai backtest untuk
    mengambil berita per hari tertentu (arsip free plan ~30 hari).
    """
    url = f"{BASE_URL}/search"

    params = {
        "q": query or coin_id,
        "lang": "en",
        "max": max_results,
        "apikey": GNEWS_API_KEY
    }

    if from_:
        params["from"] = from_
    if to:
        params["to"] = to
    if sortby:
        params["sortby"] = sortby

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