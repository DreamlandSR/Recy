import os

from dotenv import load_dotenv

from app.services.cache_service import TTLCache, get_json_with_retry

load_dotenv()

GNEWS_API_KEY = os.getenv("GNEWS_API_KEY")

BASE_URL = "https://gnews.io/api/v4"

# Cache in-memory anti rate-limit 429 GNews (free plan: 100 req/hari).
# Berita jarang berubah dalam menit -> TTL 10 menit.
CACHE_NEWS_TTL = 10 * 60

_cache = TTLCache()


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

    Hasil di-cache in-memory 10 menit (per kombinasi parameter) untuk
    menghindari HTTP 429 saat banyak endpoint dibuka bersamaan.
    """
    cache_key = (
        "news", coin_id, query, max_results, from_, to, sortby,
    )
    cached, hit = _cache.get(cache_key)
    if hit:
        return cached

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

    data = await get_json_with_retry(url, params=params, timeout=30.0)

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

    result = {
        "coin_id": coin_id,
        "query": coin_id,
        "total_articles": len(articles),
        "articles": articles
    }

    # Cache hasil berbentuk akhir (bukan JSON mentah) agar respons
    # cache-hit identik dengan respons miss.
    _cache.set(cache_key, result, CACHE_NEWS_TTL)

    return result