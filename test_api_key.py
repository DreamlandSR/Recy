import os
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("COINGECKO_API_KEY")

if api_key:
    print("API key ditemukan")
    print("Panjang:", len(api_key))
    print("Awal:", api_key[:5])
else:
    print("API key TIDAK ditemukan")