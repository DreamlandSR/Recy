import asyncio
import os

from dotenv import load_dotenv

load_dotenv()

print("MAIN API KEY:")
print("Exists:", os.getenv("COINGECKO_API_KEY") is not None)
print("Length:", len(os.getenv("COINGECKO_API_KEY")))

from app.services.crypto_service import get_coin_history

print("\nAFTER IMPORT crypto_service:")
print("Exists:", os.getenv("COINGECKO_API_KEY") is not None)
print("Length:", len(os.getenv("COINGECKO_API_KEY")))


async def main():

    print("\nTesting get_coin_history()...")

    try:

        history = await get_coin_history("solana")

        print("SUCCESS")
        print("Jumlah prices:", len(history["prices"]))

    except Exception as e:

        print("ERROR")
        print(type(e).__name__)
        print(e)


if __name__ == "__main__":
    asyncio.run(main())