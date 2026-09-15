from transformers import pipeline


MODEL_NAME = "ProsusAI/finbert"


classifier = pipeline(
    "text-classification",
    model=MODEL_NAME
)


def analyze_sentiment(text: str) -> dict:
    result = classifier(text)[0]

    return {
        "sentiment": result["label"],
        "score": round(result["score"], 4)
    }


def analyze_news_sentiment(articles: list) -> list:

    results = []

    for article in articles:

        title = article.get("title") or ""
        description = article.get("description") or ""

        text = f"{title}. {description}".strip()

        if not text:
            continue

        sentiment = analyze_sentiment(text)

        results.append({
            "title": title,
            "description": description,
            "url": article.get("url"),
            "source": article.get("source"),
            "published_at": article.get("published_at"),
            "sentiment": sentiment["sentiment"],
            "score": sentiment["score"]
        })

    return results


def calculate_sentiment_score(articles: list) -> dict:

    if not articles:
        return {
            "sentiment_score": 50,
            "condition": "NEUTRAL"
        }

    total = 0

    for article in articles:

        sentiment = article["sentiment"]
        score = article["score"]

        if sentiment == "positive":
            total += score

        elif sentiment == "negative":
            total -= score

    average = total / len(articles)

    sentiment_score = 50 + (average * 50)

    sentiment_score = max(
        0,
        min(100, sentiment_score)
    )

    if sentiment_score >= 60:
        condition = "BULLISH"

    elif sentiment_score >= 40:
        condition = "NEUTRAL"

    else:
        condition = "BEARISH"

    return {
        "sentiment_score": round(sentiment_score, 2),
        "condition": condition
    }