from app.services.sentiment_service import analyze_sentiment


texts = [
    "Bitcoin price surged after strong institutional demand.",
    "Bitcoin suffers a major decline as investors panic.",
    "Bitcoin price remained stable with little market movement."
]


for text in texts:
    result = analyze_sentiment(text)

    print("Text:", text)
    print("Sentiment:", result["sentiment"])
    print("Score:", result["score"])
    print("-" * 50)