"""In-memory cache dengan TTL per entry (anti rate-limit 429).

CoinGecko (free ~30-50 req/menit) dan GNews (free 100 req/hari) mudah
kena HTTP 429 saat banyak endpoint dibuka bersamaan. Cache sederhana
berbasis dictionary + timestamp ini menyimpan hasil request dalam memori
proses selama TTL tertentu sehingga request berulang tidak memanggil API
lagi.

Catatan:
- Tidak ada dependensi baru (murni stdlib `time`).
- `time.monotonic()` dipakai agar tidak terpengaruh perubahan jam sistem.
- Cache bersifat per-proses (uvicorn reload / restart = kosong lagi) —
  cukup untuk pola akses personal production.
"""

import asyncio
import time
from typing import Any, Hashable, Optional, Tuple

import httpx

# Status yang layak dicoba ulang (burst pertama sebelum cache terisi
# sering kena 429/5xx sesaat dari CoinGecko; 401 juga teramati transient).
RETRYABLE_STATUS = frozenset({401, 429, 500, 502, 503, 504})


async def get_json_with_retry(
    url: str,
    params: dict = None,
    headers: dict = None,
    timeout: float = 30.0,
    retries: int = 3,
    backoff: float = 1.5,
    fallback_no_key: bool = False,
) -> Any:
    """GET JSON dengan retry + fallback jalur publik tanpa API key.

    Melengkapi cache: request PERTAMA (miss) tetap bisa kena error dari
    CoinGecko:
    - 429/5xx -> retry dengan backoff tumbuh (1.5s, 3s, ...).
    - 401 saat mengirim key (CoinGecko error 10002 "API Key Missing" —
      kuota demo key pada jendela pendek habis dan key diabaikan) ->
      otomatis ulangi TANPA key (jalur publik), yang terbukti masih 200
      saat key ditolak. Peralihan strategi tidak menghitung sebagai retry.
    """
    key_headers = headers
    use_key = True
    attempt = 0

    while True:
        try:
            async with httpx.AsyncClient(trust_env=False, timeout=timeout) as client:
                response = await client.get(
                    url,
                    params=params,
                    headers=(key_headers if use_key else None),
                )
        except httpx.TransportError:
            if attempt >= retries:
                raise
            attempt += 1
            await asyncio.sleep(backoff * attempt)
            continue

        # Key ditolak CoinGecko -> pindah ke jalur publik tanpa key.
        if (
            response.status_code == 401
            and fallback_no_key
            and use_key
            and key_headers
        ):
            use_key = False
            await asyncio.sleep(backoff)
            continue

        if response.status_code in RETRYABLE_STATUS and attempt < retries:
            attempt += 1
            await asyncio.sleep(backoff * attempt)
            continue

        response.raise_for_status()
        return response.json()


class TTLCache:
    """Dictionary cache dengan waktu kedaluwarsa per entry."""

    def __init__(self, max_entries: int = 512):
        self._store: dict = {}
        self._max_entries = max_entries

    def get(self, key: Hashable) -> Tuple[Optional[Any], bool]:
        """Return (value, True) bila cache hit, (None, False) bila miss/kadaluarsa."""
        entry = self._store.get(key)
        if entry is None:
            return None, False

        value, expires_at = entry
        if time.monotonic() >= expires_at:
            # Kadaluarsa -> buang agar tidak menumpuk.
            del self._store[key]
            return None, False
        return value, True

    def set(self, key: Hashable, value: Any, ttl: float) -> None:
        """Simpan value dengan TTL (detik). Evict entry kadaluarsa bila penuh."""
        if key not in self._store and len(self._store) >= self._max_entries:
            self._evict_expired()
            if len(self._store) >= self._max_entries:
                # Masih penuh -> buang yang paling lama disimpan (FIFO).
                oldest_key = next(iter(self._store))
                del self._store[oldest_key]

        self._store[key] = (value, time.monotonic() + ttl)

    def clear(self) -> None:
        self._store.clear()

    def _evict_expired(self) -> None:
        now = time.monotonic()
        expired = [
            key for key, (_, expires_at) in self._store.items()
            if now >= expires_at
        ]
        for key in expired:
            del self._store[key]

    def __len__(self) -> int:
        return len(self._store)
