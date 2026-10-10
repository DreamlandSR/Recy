import asyncio

from app.services.crypto_service import get_coin_history
from app.services.backtest_service import run_technical_backtest


async def main():

    print("Mengambil data Solana...")

    history = await get_coin_history("solana")

    prices = history["prices"]

    print(f"Jumlah data harga: {len(prices)}")

    print("\nMenjalankan backtesting...")

    results = run_technical_backtest(prices)

    print(f"Jumlah hasil backtest: {len(results)}")

    print("\n5 hasil pertama:")

    for result in results[:5]:
        print(result)


if __name__ == "__main__":
    asyncio.run(main())