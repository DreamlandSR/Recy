# Recy — Intelligent Crypto Market Insight & Recommendation API

Recy adalah platform REST API dan sistem analitik cryptocurrency berbasis AI dan algoritma kustom. Sistem ini menggabungkan data pasar real-time, indikator teknikal, serta analisis sentimen berita untuk menghasilkan rekomendasi aset (*BUY*, *HOLD*, atau *SELL*) secara obyektif dan terukur.

Dokumentasi spesifikasi lengkap dapat dibaca pada [docs/crypto_recommendation_planning.md](file:///c:/Project/Magang/Recy/docs/crypto_recommendation_planning.md).

---

## Table of Contents

- [Overview](#overview)
- [Key Features](#key-features)
- [System Architecture](#system-architecture)
- [Recommendation Engine Algorithm](#recommendation-engine-algorithm)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Installation & Getting Started](#installation--getting-started)
  - [1. Prerequisites](#1-prerequisites)
  - [2. Clone Repository](#2-clone-repository)
  - [3. Environment Setup](#3-environment-setup)
  - [4. Install Dependencies](#4-install-dependencies)
  - [5. Environment Variables](#5-environment-variables)
  - [6. Run Development Server](#6-run-development-server)
- [API Endpoints](#api-endpoints)
- [Development Roadmap](#development-roadmap)
- [Disclaimer](#disclaimer)

---

## Overview

Sistem Recy dirancang untuk mengolah data pasar cryptocurrency secara otomatis dan transparan. Dibandingkan hanya menampilkan grafik harga historis, Recy menganalisis kondisi teknikal pasar beserta sentimen publik dari berita terkini untuk memberikan skor kuantitatif dan rekomendasi aset.

---

## Key Features

- **Market Data Integration:** Agregasi harga real-time, volume 24 jam, market capitalization, dan persentase perubahan harga dari provider pasar crypto (CoinGecko API).
- **Automated Technical Indicators:** Kalkulasi indikator teknikal historis mencakup RSI (Relative Strength Index), MACD, SMA (Simple Moving Average), dan EMA (Exponential Moving Average).
- **News Sentiment Analysis:** Ekstraksi berita crypto dari RSS/API dan pengolahan sentimen (*Positive*, *Neutral*, *Negative*) menggunakan model NLP AI.
- **Multi-Weighted Scoring Engine:** Algoritma pembobotan gabungan antara skor teknikal, skor sentimen, dan skor kondisi pasar.
- **Caching & High Performance:** Penggunaan Redis untuk manajemen cache data transient dan rate-limiting.

---

## System Architecture

Alur pemrosesan data dari pengumpulan hingga penyajian rekomendasi:

```text
                  +--------------------------+
                  |   External Data Sources  |
                  |  CoinGecko / News RSS    |
                  +------------+-------------+
                               |
                               v
                  +--------------------------+
                  |     FastAPI Backend      |
                  |    (Python 3.11+)        |
                  +------------+-------------+
                               |
            +------------------+------------------+
            |                  |                  |
            v                  v                  v
     [Market Data]        [News Data]     [Historical Data]
            |                  |                  |
            +------------------+------------------+
                               |
                        +------+------+
                        | PostgreSQL  |
                        +------+------+
                               |
                +--------------+--------------+
                |                             |
                v                             v
        Technical Analysis             News Sentiment
        (RSI, MACD, MA)                 (AI Sentiment)
                |                             |
                +--------------+--------------+
                               |
                        Scoring Engine
                               |
                               v
                       BUY / HOLD / SELL
                               |
                               v
                     Frontend (React/Next.js)
```

---

## Recommendation Engine Algorithm

Rekomendasi dihitung menggunakan kombinasi pembobotan proporsional berikut:

$$\text{Final Score} = (\text{Technical Score} \times 0.50) + (\text{Sentiment Score} \times 0.30) + (\text{Market Score} \times 0.20)$$

### Classification Matrix

| Final Score Range | Recommendation | Description |
| :--- | :--- | :--- |
| **80 – 100** | **BUY** | Bullish teknikal kuat & sentimen publik sangat positif |
| **60 – 79** | **HOLD / MODERATE BUY** | Kondisi pasar cenderung akumulatif |
| **40 – 59** | **HOLD** | Kondisi pasar netral / konsolidasi |
| **20 – 39** | **MODERATE SELL** | Muncul sinyal teknikal lemah / sentimen negatif |
| **0 – 19** | **SELL** | Tekanan jual tinggi & indikator bearish |

---

## Tech Stack

- **Backend Framework:** FastAPI (Python 3.11+)
- **ASGI Server:** Uvicorn
- **Data Processing:** Pandas, NumPy, `ta` (Technical Analysis Library)
- **HTTP Client:** HTTPX (Async requests)
- **Database:** PostgreSQL (Target)
- **Cache & Queue:** Redis (Target)
- **Frontend:** Next.js / React (Target)

---

## Project Structure

```text
crypto-recommendation/
│
├── app/
│   ├── main.py                  # Entrypoint aplikasi & routing FastAPI
│   ├── services/
│   │   ├── crypto_service.py     # Integrasi CoinGecko API & history
│   │   └── technical_service.py  # Kalkulasi indikator (SMA, EMA, RSI, MACD)
│   ├── api/                     # Router API endpoints
│   ├── models/                  # Database models
│   └── schemas/                 # Pydantic data schemas
│
├── docs/
│   └── crypto_recommendation_planning.md  # Spesifikasi teknis & perencanaan
│
├── tests/                       # Test suite
├── .env.example                 # Template konfigurasi variabel lingkungan
├── .gitignore                   # Ignored files (venv, pycache, secrets)
├── requirements.txt             # Manifest dependensi Python
└── README.md                    # Dokumentasi utama proyek
```

---

## Installation & Getting Started

### 1. Prerequisites

- Python 3.11+
- Git

### 2. Clone Repository

```bash
git clone https://github.com/DreamlandSR/Recy.git
cd Recy
```

### 3. Environment Setup

Buat dan aktifkan virtual environment Python:

- **Windows (PowerShell):**
  ```powershell
  python -m venv .venv
  .\.venv\Scripts\Activate
  ```

- **Linux / macOS:**
  ```bash
  python3 -m venv .venv
  source .venv/bin/activate
  ```

### 4. Install Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 5. Environment Variables

Salin `.env.example` ke `.env` dan atur variabel yang dibutuhkan:

```bash
cp .env.example .env
```

Contoh konfigurasi pada `.env`:

```env
APP_NAME=Recy
APP_ENV=development
APP_VERSION=0.1.0

COINGECKO_API_KEY=your_api_key_here
```

### 6. Run Development Server

Jalankan Uvicorn server:

```bash
uvicorn app.main:app --reload
```

Server akan berjalan pada `http://127.0.0.1:8000`.

Dokumentasi API interaktif dapat diakses melalui:
- **Swagger UI:** [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **ReDoc:** [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)

---

## API Endpoints

| Method | Endpoint | Description | Status |
| :--- | :--- | :--- | :--- |
| `GET` | `/` | Health check & versi API | Active |
| `GET` | `/api/crypto/markets` | Top 10 data pasar cryptocurrency | Active |
| `GET` | `/api/crypto/{coin_id}` | Detail pasar koin tertentu | Active |
| `GET` | `/api/crypto/{coin_id}/history` | Histori harga 90 hari terakhir | Active |
| `GET` | `/api/crypto/{coin_id}/technical` | Hasil kalkulasi indikator teknikal | Active |
| `GET` | `/api/crypto/{coin_id}/news` | Agregasi berita crypto | Planned |
| `GET` | `/api/crypto/{coin_id}/recommendation` | Hasil rekomendasi (BUY/HOLD/SELL) | Planned |

### Sample Response

`GET /api/crypto/bitcoin/technical`

```json
[
  {
    "timestamp": 1700000000000,
    "price": 95420.50,
    "sma_20": 92310.15,
    "ema_20": 93100.80,
    "rsi_14": 64.25,
    "macd": 450.12,
    "macd_signal": 380.05,
    "macd_histogram": 70.07
  }
]
```

---

## Development Roadmap

- [x] Stage 1: Setup struktur proyek & FastAPI foundation
- [x] Stage 2: Integrasi CoinGecko API untuk market data
- [x] Stage 3: Fetching & penyimpanan historical price
- [x] Stage 4: Engine analisis teknikal (RSI, MACD, SMA, EMA)
- [ ] Stage 5: Integrasi sumber berita (Google News RSS / News API)
- [ ] Stage 6: AI News Sentiment Analysis
- [ ] Stage 7: Implementation scoring & recommendation engine
- [ ] Stage 8: Database PostgreSQL & Redis integration
- [ ] Stage 9: Frontend Dashboard (React / Next.js)
- [ ] Stage 10: Real-time update via WebSockets

---

## Disclaimer

Sistem dan algoritma pada proyek ini dikembangkan semata-mata untuk tujuan riset, analisis data, dan edukasi. Hasil analisis maupun rekomendasi (*BUY/HOLD/SELL*) bukan merupakan nasihat keuangan atau ajakan investasi. Pengguna wajib melakukan analisis mandiri (*Do Your Own Research*) sebelum membuat keputusan finansial.
