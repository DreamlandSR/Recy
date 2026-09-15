from transformers import pipeline

MODEL_NAME = "ProsusAI/finbert"

classifier = pipeline(
    "text-classification",
    model=MODEL_NAME
)

texts = [
    "Ethereum price surged after strong institutional demand.",
    "Ethereum suffers a major decline as investors panic.",
    "Ethereum price remained stable with little market movement."
]

for text in texts:
    result = classifier(text)[0]

    print("Text:", text)
    print("Sentiment:", result["label"])
    print("Score:", round(result["score"], 4))
    print("-" * 50)