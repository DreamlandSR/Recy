import os
import asyncio
import httpx

from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("COINGECKO_API_KEY")


async def main():

    url = "https://api.coingecko.com/api/v3/coins/solana/market_chart"

    params = {
        "vs_currency": "usd",
        "days": "90",
        "interval": "daily"
    }

    headers = {
        "x-cg-demo-api-key": API_KEY
    }

    async with httpx.AsyncClient(
        trust_env=False,
        timeout=30.0
    ) as client:

        response = await client.get(
            url,
            params=params,
            headers=headers
        )

        print("Status:", response.status_code)
        print("Response:")

        print(response.text[:1000])


if __name__ == "__main__":
    asyncio.run(main())