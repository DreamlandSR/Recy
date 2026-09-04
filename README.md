# 🚀 Recy — Intelligent Crypto Market Insight & Recommendation API

![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi)
![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-316192?style=for-the-badge&logo=postgresql&logoColor=white)
![Redis](https://img.shields.io/badge/Redis-DC382D?style=for-the-badge&logo=redis&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green.style=for-the-badge)

**Recy** adalah platform REST API dan sistem analitik cryptocurrency berbasis AI & algoritma yang menggabungkan **data pasar crypto real-time, analisis indikator teknikal, serta analisis sentimen berita terbaru** untuk menghasilkan skor rekomendasi aset yang terukur (**BUY**, **HOLD**, atau **SELL**).

> 📌 **Dokumen Perencanaan Lengkap:** Detail spesifikasi dan arsitektur dapat dilihat pada [docs/crypto_recommendation_planning.md](file:///c:/Project/Magang/Recy/docs/crypto_recommendation_planning.md).

---

## 📑 Daftar Isi

- [✨ Fitur Utama](#-fitur-utama)
- [🏗️ Arsitektur & Alur Data](#️-arsitektur--alur-data)
- [🧮 Algoritma Recommendation Engine](#-algoritma-recommendation-engine)
- [🛠️ Teknologi yang Digunakan](#️-teknologi-yang-digunakan)
- [📂 Struktur Proyek](#-struktur-proyek)
- [🚀 Panduan Penggunaan & Instalasi](#-panduan-penggunaan--instalasi)
  - [1. Prasyarat](#1-prasyarat)
  - [2. Kloning Repository](#2-kloning-repository)
  - [3. Setup Virtual Environment](#3-setup-virtual-environment)
  - [4. Instalasi Dependency](#4-instalasi-dependency)
  - [5. Konfigurasi Environment](#5-konfigurasi-environment)
  - [6. Menjalankan Server API](#6-menjalankan-server-api)
- [📡 Endpoint API Utama](#-endpoint-api-utama)
- [🗺️ Tahapan Pengembangan (Roadmap MVP)](#️-tahapan-pengembangan-roadmap-mvp)
- [⚠️ Disclaimer](#️-disclaimer)

---

## ✨ Fitur Utama

- **📊 Integration Data Pasar (Market Data):** Mengambil harga terbaru, volume, market cap, dan perubahan harga 24 jam dari provider terpercaya (CoinGecko API / Exchange API).
- **📈 Analisis Teknikal Otomatis:** Menghitung indikator teknikal populer seperti **RSI**, **MACD**, **SMA (Simple Moving Average)**, dan **EMA (Exponential Moving Average)** dari data historis.
- **📰 News Data & AI Sentiment Analysis:** Mengagregasi berita crypto (Google News RSS / News API) dan menganalisis sentimen publik (*Positive*, *Neutral*, *Negative*) menggunakan AI NLP model.
- **⚡ Recommendation Engine:** Penggabungan pembobotan multi-faktor (*Technical Score*, *Sentiment Score*, *Market Score*) untuk menghasilkan klasifikasi rekomendasi objektif.
- **⏱️ Near Real-time Updates & Caching:** Optimasi query dan caching data menggunakan Redis.

---

## 🏗️ Arsitektur & Alur Data

Sistem bekerja secara modular dari pengumpulan data hingga penghasilan rekomendasi:

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

## 🧮 Algoritma Recommendation Engine

Rekomendasi dihitung menggunakan kombinasi pembobotan proporsional:

$$\text{Final Score} = (\text{Technical Score} \times 0.50) + (\text{Sentiment Score} \times 0.30) + (\text{Market Score} \times 0.20)$$

### Matriks Klasifikasi Rekomendasi

| Rentang Skor | Klasifikasi Rekomendasi | Keterangan Singkat |
| :--- | :--- | :--- |
| **80 – 100** | **BUY** | Sinyal teknikal kuat & sentimen pasar positif |
| **60 – 79** | **HOLD / MODERATE BUY** | Kondisi pasar cenderung akumulatif |
| **40 – 59** | **HOLD** | Kondisi netral / konsolidasi |
| **20 – 39** | **MODERATE SELL** | Muncul sinyal teknikal lemah / sentimen negatif |
| **0 – 19** | **SELL** | Tekanan jual tinggi & indikator bearish |

---

## 🛠️ Teknologi yang Digunakan

- **Backend Web Framework:** [FastAPI](https://fastapi.tiangolo.com/) (Python 3.11+)
- **Server ASGI:** [Uvicorn](https://www.uvicorn.org/)
- **Data Analysis & Indicators:** [Pandas](https://pandas.pydata.org/), [ta](https://github.com/bukosabino/ta) (Technical Analysis Library)
- **HTTP Client:** [HTTPX](https://www.python-httpx.org/) (Async HTTP Requests)
- **Database (Target):** PostgreSQL
- **Cache & Message Broker (Target):** Redis
- **Frontend (Target Roadmap):** React / Next.js

---

## 📂 Struktur Proyek

```text
crypto-recommendation/
│
├── app/
│   ├── main.py                  # Entrypoint aplikasi FastAPI & routing utama
│   ├── services/
│   │   ├── crypto_service.py     # Integrasi CoinGecko API & market history
│   │   └── technical_service.py  # Kalkulasi indikator teknikal (SMA, EMA, RSI, MACD)
│   ├── api/                     # Sub-module router API (Target)
│   ├── models/                  # Database models SQLAlchemy/SQLModel (Target)
│   └── schemas/                 # Pydantic schemas (Target)
│
├── docs/
│   └── crypto_recommendation_planning.md  # Dokumen perencanaan arsitektur lengkap
│
├── tests/                       # Unit testing & integration testing
├── .env.example                 # Template variabel lingkungan
├── .gitignore                   # Aturan pengabaian file Git (venv, cache, secret)
├── requirements.txt             # Daftar dependensi Python
└── README.md                    # Dokumentasi utama proyek
```

---

## 🚀 Panduan Penggunaan & Instalasi

Ikuti langkah-langkah di bawah ini untuk menjalankan sistem **Recy** di lingkungan lokal Anda.

### 1. Prasyarat

Pastikan perangkat Anda telah terinstal:
- **Python 3.11** atau versi lebih baru.
- **Git** untuk kontrol versi.

### 2. Kloning Repository

```bash
git clone https://github.com/DreamlandSR/Recy.git
cd Recy
```

### 3. Setup Virtual Environment

Buat dan aktifkan *virtual environment* Python:

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

### 4. Instalasi Dependency

Install seluruh kebutuhan library dengan perintah berikut:

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 5. Konfigurasi Environment

Salin file `.env.example` menjadi `.env` dan lengkapi konfigurasi API Key Anda:

- **Windows (PowerShell):**
  ```powershell
  Copy-Item .env.example .env
  ```
- **Linux / macOS:**
  ```bash
  cp .env.example .env
  ```

Isi variabel pada file `.env`:
```env
APP_NAME=Recy
APP_ENV=development
APP_VERSION=0.1.0

# API Keys
COINGECKO_API_KEY=your_coingecko_api_key_here
```

### 6. Menjalankan Server API

Jalankan server FastAPI menggunakan Uvicorn:

```bash
uvicorn app.main:app --reload
```

Jika server berhasil berjalan, Anda akan melihat output terminal berikut:

```text
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [...]
INFO:     Application startup complete.
```

Dokumentasi OpenAPI Interaktif (Swagger UI) dapat diakses secara otomatis melalui browser:
👉 **Swagger UI:** [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)  
👉 **ReDoc:** [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)

---

## 📡 Endpoint API Utama

| Method | Endpoint | Deskripsi | Status |
| :--- | :--- | :--- | :--- |
| `GET` | `/` | Health check & info versi API | ✅ Available |
| `GET` | `/api/crypto/markets` | Mengambil data top 10 pasar cryptocurrency terbaru | ✅ Available |
| `GET` | `/api/crypto/{coin_id}` | Detail pasar koin tertentu (contoh: `bitcoin`) | ✅ Available |
| `GET` | `/api/crypto/{coin_id}/history` | Histori harga pasar 90 hari terakhir | ✅ Available |
| `GET` | `/api/crypto/{coin_id}/technical` | Hasil kalkulasi indikator teknikal (SMA, EMA, RSI, MACD) | ✅ Available |
| `GET` | `/api/crypto/{coin_id}/news` | Berita crypto terbaru terkait aset | 🚧 In Development |
| `GET` | `/api/crypto/{coin_id}/recommendation` | Skor rekomendasi akhir (BUY/HOLD/SELL) | 🚧 In Development |

### Contoh Respon API

**Request:** `GET /api/crypto/bitcoin/technical`

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

## 🗺️ Tahapan Pengembangan (Roadmap MVP)

- [x] **Tahap 1:** Persiapan Struktur & Fondasi Project FastAPI
- [x] **Tahap 2:** Integrasi Data Pasar Real-Time (CoinGecko API)
- [x] **Tahap 3:** Pengambilan & Penyimpanan Historical Price
- [x] **Tahap 4:** Engine Kalkulasi Analisis Teknikal (RSI, MACD, SMA, EMA)
- [ ] **Tahap 5:** Integrasi Source Berita (Google News RSS / News API)
- [ ] **Tahap 6:** AI News Sentiment Analysis Model
- [ ] **Tahap 7:** Implementation Scoring & Recommendation Engine
- [ ] **Tahap 8:** Integrasi Database PostgreSQL & Caching Redis
- [ ] **Tahap 9:** Dashboard UI Frontend (React / Next.js)
- [ ] **Tahap 10:** Real-Time Push Notification & WebSocket Support

---

## ⚠️ Disclaimer

Sistem rekomendasi pada proyek ini dibuat untuk tujuan **analitis, riset, dan edukatif**. Hasil rekomendasi yang dihasilkan oleh sistem (*BUY/HOLD/SELL*) bukan merupakan nasihat keuangan (financial advice) atau jaminan kepastian investasi. Pengguna diharapkan selalu melakukan *Do Your Own Research* (DYOR) sebelum melakukan transaksi aset cryptocurrency.

---

<p center>
Crafted with ❤️ for Intelligent Crypto Market Analytics
</p>
