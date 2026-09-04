# Planning — Website Crypto Recommendation

## 1. Pengenalan Sistem

Website ini merupakan platform analisis cryptocurrency yang menggabungkan **data pasar crypto, berita terbaru, analisis teknikal, dan sentiment analysis** untuk menghasilkan rekomendasi aset.

Sistem tidak hanya menampilkan harga crypto, tetapi mencoba menjawab:

> Berdasarkan kondisi pasar, indikator teknikal, dan sentimen berita terbaru, bagaimana kondisi suatu cryptocurrency saat ini?

Hasil akhirnya berupa:

- **BUY**
- **HOLD**
- **SELL**

Beserta **score** dan alasan yang mendukung rekomendasi tersebut.

> **Catatan:** Rekomendasi sistem bersifat analitis dan edukatif, bukan jaminan keuntungan atau nasihat investasi.

---

## 2. Tujuan Sistem

Tujuan utama sistem:

1. Mengambil data cryptocurrency secara otomatis.
2. Menampilkan harga crypto terbaru.
3. Mengambil berita terbaru yang berkaitan dengan crypto.
4. Menganalisis sentimen berita.
5. Menghitung indikator teknikal.
6. Menggabungkan hasil analisis menjadi sebuah skor.
7. Menghasilkan rekomendasi BUY/HOLD/SELL.
8. Menampilkan perubahan data secara real-time atau near-real-time.
9. Menyediakan dasar analisis yang dapat diuji menggunakan data historis.

---

## 3. Teknologi yang Digunakan

### 3.1 Backend

**Python + FastAPI**

Digunakan untuk:

- REST API
- WebSocket
- Integrasi external API
- Business logic
- Technical analysis
- Sentiment analysis
- Recommendation engine

### 3.2 Database

**PostgreSQL**

Digunakan untuk menyimpan:

- Data cryptocurrency
- Harga historis
- Volume
- Berita
- Sentiment
- Technical indicators
- Hasil rekomendasi

### 3.3 Cache dan Queue

**Redis**

Digunakan untuk:

- Caching data
- Menyimpan data sementara
- Rate limiting
- Queue processing
- Proses asynchronous

### 3.4 Frontend

**React / Next.js**

Digunakan untuk:

- Dashboard
- Chart harga
- Daftar cryptocurrency
- Berita terbaru
- Recommendation score
- Real-time price update

---

# 4. Sumber Data

Sistem membutuhkan beberapa sumber data utama.

```text
                    Data Sources
                         |
          +--------------+--------------+
          |              |              |
          v              v              v
     Market Data       News            AI
          |              |              |
     Crypto API       RSS/API       AI API
```

## 4.1 Market Data

Digunakan untuk memperoleh:

- Harga
- Volume
- Market capitalization
- Perubahan harga
- Historical price

Untuk prototype dapat menggunakan:

- CoinGecko API
- Binance API
- Coinbase API
- Kraken API

Pemilihan provider final dilakukan setelah membandingkan:

- Rate limit
- Ketersediaan endpoint
- Dukungan WebSocket
- Kebutuhan autentikasi
- Ketentuan penggunaan
- Kesesuaian untuk penggunaan publik/komersial

## 4.2 News Data

Digunakan untuk memperoleh:

- Judul berita
- Sumber berita
- URL
- Waktu publikasi
- Deskripsi/ringkasan jika tersedia

Untuk prototype dapat menggunakan:

- Google News RSS
- News API/provider lain

## 4.3 AI

AI digunakan terutama untuk:

- Sentiment analysis
- Klasifikasi berita
- Ekstraksi topik
- Identifikasi cryptocurrency yang berkaitan dengan berita

Contoh:

```text
Berita
   |
   v
Sentiment Analysis
   |
   +--> Positive
   +--> Neutral
   +--> Negative
```

---

# 5. Konsep Utama Sistem

Sistem memiliki beberapa komponen analisis.

## 5.1 Market Analysis

Menganalisis kondisi pasar berdasarkan:

```text
Price
Volume
Market Cap
24H Change
```

## 5.2 Technical Analysis

Indikator awal:

```text
RSI
MACD
SMA
EMA
Bollinger Bands
Volume
```

Contoh:

```text
RSI = 28

        |
        v

Oversold
```

## 5.3 News Sentiment

Berita dianalisis oleh AI.

Contoh:

```text
"Bitcoin gains after institutional demand rises"

        |
        v

Sentiment Analysis

        |
        v

Positive
Score = 0.86
```

## 5.4 Recommendation Engine

Semua hasil analisis digabungkan:

```text
Technical Score
       +
Sentiment Score
       +
Market Score
       |
       v
Recommendation Engine
       |
       v
BUY / HOLD / SELL
```

---

# 6. Arsitektur Sistem

```text
                    +---------------------+
                    |   Crypto Data API   |
                    | CoinGecko /         |
                    | Exchange API        |
                    +----------+----------+
                               |
                               v
                    +---------------------+
                    |      FastAPI        |
                    |       Python        |
                    +----------+----------+
                               |
             +-----------------+-----------------+
             |                 |                 |
             v                 v                 v
       Market Data          News Data       Historical Data
             |                 |                 |
             +-----------------+-----------------+
                               |
                        +------+------+
                        | PostgreSQL  |
                        +------+------+
                               |
                +--------------+--------------+
                |                             |
                v                             v
        Technical Analysis             News Sentiment
        RSI / MACD / MA                AI Analysis
                |                             |
                +--------------+--------------+
                               |
                      Recommendation Engine
                               |
                               v
                       BUY / HOLD / SELL
                               |
                               v
                      React / Next.js
```

---

# 7. Tahapan Pengembangan

Pengembangan dilakukan secara bertahap agar setiap bagian dapat diuji sebelum masuk ke tahap berikutnya.

---

## Tahap 1 — Persiapan Project

### Tujuan

Membuat fondasi aplikasi.

### Yang dilakukan

```text
Python
FastAPI
PostgreSQL
Redis
Git
Environment configuration
```

Struktur awal:

```text
crypto-recommendation/
│
├── app/
├── tests/
├── .env
├── requirements.txt
└── README.md
```

### Output

FastAPI berhasil berjalan.

Contoh:

```text
GET /
   |
   v
FastAPI
   |
   v
"Crypto Recommendation API"
```

---

# Tahap 2 — Integrasi Crypto API

### Tujuan

Mendapatkan data cryptocurrency.

Untuk tahap pertama, jangan langsung menggunakan banyak cryptocurrency.

Gunakan:

```text
BTC
```

sebagai cryptocurrency pertama.

### Data yang diambil

```text
Bitcoin
BTC
Price
Market Cap
Volume
24H Change
```

### Alur

```text
Crypto API
     |
     v
FastAPI
     |
     v
Process Data
     |
     v
PostgreSQL
```

### Output

Endpoint:

```text
GET /api/crypto/BTC
```

menghasilkan informasi Bitcoin.

---

# Tahap 3 — Historical Price

### Tujuan

Menyimpan data historis yang nantinya digunakan untuk technical analysis.

Contoh:

```text
BTC

10:00 -> $112,000
10:01 -> $112,100
10:02 -> $112,050
10:03 -> $112,300
...
```

Historical data diperlukan untuk menghitung:

```text
RSI
MACD
SMA
EMA
Bollinger Bands
```

### Output

Endpoint:

```text
GET /api/crypto/BTC/history
```

---

# Tahap 4 — Technical Analysis

Setelah historical price tersedia:

```text
Historical Price
       |
       v
Technical Analysis
       |
       +--> RSI
       +--> MACD
       +--> SMA
       +--> EMA
       |
       v
Technical Score
```

Contoh:

```text
RSI    = 42
MACD   = Bullish
SMA 50 = Bullish
EMA 20 = Bullish

Technical Score
= 78 / 100
```

Pada tahap ini analisis dibuat menggunakan algoritma yang jelas dan dapat dijelaskan, bukan langsung menggunakan AI.

---

# Tahap 5 — Integrasi Berita

Setelah market analysis berjalan, tambahkan sumber berita.

```text
Bitcoin
   |
   v
Google News RSS
   |
   v
Berita
   |
   v
Database
```

Data yang disimpan:

```text
Title
Source
URL
Published At
Description
```

Endpoint:

```text
GET /api/crypto/BTC/news
```

Website kemudian dapat menampilkan:

```text
Latest Bitcoin News

1. Berita A
2. Berita B
3. Berita C
```

---

# Tahap 6 — Sentiment Analysis

Setiap berita dianalisis.

```text
News
 |
 v
AI
 |
 v
Sentiment
 |
 +--> Positive
 +--> Neutral
 +--> Negative
 |
 v
Sentiment Score
```

Contoh:

```text
Berita A
Positive
0.91

Berita B
Positive
0.76

Berita C
Negative
0.64
```

Kemudian dihitung:

```text
Overall Sentiment
        |
        v
78 / 100
```

Output:

```text
Sentiment Score = 78
```

---

# Tahap 7 — Recommendation Engine

Ini merupakan salah satu komponen inti sistem.

Data yang digunakan:

```text
Technical Score
       +
Sentiment Score
       +
Market Score
```

Contoh bobot awal:

```text
Technical     50%
Sentiment     30%
Market        20%
```

Rumus:

```text
Final Score =
(Technical Score × 0.50)
+
(Sentiment Score × 0.30)
+
(Market Score × 0.20)
```

Contoh:

```text
Technical = 82
Sentiment = 78
Market    = 75
```

Maka:

```text
Final Score =
(82 × 0.50)
+
(78 × 0.30)
+
(75 × 0.20)

= 41 + 23.4 + 15

= 79.4
```

---

# Tahap 8 — Recommendation Classification

Score kemudian diklasifikasikan.

Contoh baseline:

```text
80 - 100
BUY

60 - 79
HOLD / MODERATE BUY

40 - 59
HOLD

20 - 39
MODERATE SELL

0 - 19
SELL
```

Contoh:

```text
Final Score = 79.4

       |
       v

HOLD / MODERATE BUY
```

> Threshold dan bobot tersebut hanya baseline. Nantinya perlu diuji menggunakan historical data dan backtesting.

---

# Tahap 9 — Frontend Dashboard

Setelah backend utama selesai, buat dashboard.

Contoh:

```text
+-------------------------------------------+
|          CRYPTO RECOMMENDATION            |
+-------------------------------------------+
|                                           |
| BTC/USDT                    $112,450       |
| +3.21%                                     |
|                                           |
| Technical       82 / 100                  |
| Sentiment       78 / 100                  |
| Market          75 / 100                  |
|                                           |
| Final Score     79.4 / 100                |
|                                           |
|             HOLD / BUY                    |
|                                           |
+-------------------------------------------+
```

Dashboard dapat berisi:

- Harga crypto
- Perubahan 24 jam
- Volume
- Market cap
- Price chart
- RSI
- MACD
- Moving Average
- Berita terbaru
- Sentiment
- Final score
- Recommendation

---

# Tahap 10 — Real-Time Update

Real-time dapat dilakukan dalam dua tahap.

## 10.1 Polling

Tahap awal:

```text
Frontend
    |
    v
FastAPI
    |
    v
Crypto API
```

Frontend melakukan request secara berkala.

Contoh:

```text
Setiap 30 detik
       |
       v
GET /api/crypto/BTC
```

Metode ini lebih sederhana untuk MVP.

## 10.2 WebSocket

Setelah sistem stabil:

```text
Crypto Exchange
       |
       v
WebSocket
       |
       v
FastAPI
       |
       v
WebSocket
       |
       v
React
```

Dengan demikian perubahan harga dapat dikirim ke browser tanpa reload halaman.

---

# Tahap 11 — Scheduler dan Background Processing

Proses yang tidak perlu dilakukan langsung oleh user dapat dipindahkan ke background worker.

Contoh:

```text
Fetch Crypto Price
Fetch News
Analyze Sentiment
Calculate Indicators
Generate Recommendation
```

Alur:

```text
Scheduler
    |
    +--> Fetch Market Data
    |
    +--> Fetch News
    |
    +--> Sentiment Analysis
    |
    +--> Technical Analysis
    |
    +--> Recommendation
```

Redis dapat digunakan bersama worker/queue untuk membantu proses asynchronous.

---

# Tahap 12 — Backtesting

Tahap ini sangat penting sebelum sistem dianggap menghasilkan rekomendasi yang dapat diandalkan.

Sistem diuji menggunakan data historis:

```text
Historical Data
       |
       v
Recommendation Engine
       |
       v
BUY / HOLD / SELL
       |
       v
Bandingkan dengan kondisi harga berikutnya
```

Yang dapat dievaluasi:

- Accuracy
- Return
- Maximum drawdown
- Win rate
- Risk/reward
- False signal
- Sharpe ratio jika diperlukan

Tujuannya bukan mencari sistem yang selalu benar, tetapi mengetahui apakah strategi mempunyai performa yang masuk akal dan risiko yang dapat dipahami.

---

# Tahap 13 — Testing

Testing dibagi menjadi:

### Unit Test

Menguji:

```text
RSI calculation
MACD calculation
Score calculation
Recommendation classification
```

### Integration Test

Menguji:

```text
FastAPI
   |
External API
   |
Database
```

### API Test

Menguji endpoint:

```text
GET /api/crypto
GET /api/crypto/{symbol}
GET /api/crypto/{symbol}/news
GET /api/crypto/{symbol}/analysis
GET /api/crypto/{symbol}/recommendation
```

### Frontend Test

Menguji:

- Dashboard
- Chart
- News
- Real-time update
- Recommendation display

---

# 8. Urutan Pengerjaan Keseluruhan

```text
                    PROJECT START
                          |
                          v
                +-------------------+
                | 1. Setup Project  |
                +---------+---------+
                          |
                          v
                +-------------------+
                | 2. Crypto API     |
                +---------+---------+
                          |
                          v
                +-------------------+
                | 3. Historical     |
                |    Price          |
                +---------+---------+
                          |
                          v
                +-------------------+
                | 4. Technical      |
                |    Analysis       |
                +---------+---------+
                          |
                          v
                +-------------------+
                | 5. News API/RSS   |
                +---------+---------+
                          |
                          v
                +-------------------+
                | 6. Sentiment AI   |
                +---------+---------+
                          |
                          v
                +-------------------+
                | 7. Recommendation |
                +---------+---------+
                          |
                          v
                +-------------------+
                | 8. Dashboard      |
                +---------+---------+
                          |
                          v
                +-------------------+
                | 9. Real-Time      |
                +---------+---------+
                          |
                          v
                +-------------------+
                | 10. Scheduler &   |
                |     Queue         |
                +---------+---------+
                          |
                          v
                +-------------------+
                | 11. Backtesting   |
                +---------+---------+
                          |
                          v
                +-------------------+
                | 12. Testing       |
                +---------+---------+
                          |
                          v
                    PROJECT MVP
```

---

# 9. Target MVP

Versi pertama tidak perlu langsung kompleks.

### Backend

```text
Python
FastAPI
PostgreSQL
Redis
```

### Data

```text
Crypto Market Data
+
Google News RSS
```

### Analysis

```text
RSI
MACD
SMA
EMA
News Sentiment
```

### Output

```text
Price
+
News
+
Technical Score
+
Sentiment Score
+
Final Score
+
BUY / HOLD / SELL
```

---

# 10. Pengembangan Cryptocurrency

Tahap awal:

```text
BTC
```

Jika BTC berhasil:

```text
BTC
ETH
```

Kemudian:

```text
BTC
ETH
SOL
BNB
XRP
```

Baru setelah sistem stabil, cryptocurrency dapat diperluas.

---

# 11. Struktur Project Target

```text
crypto-recommendation/
│
├── app/
│   ├── main.py
│   │
│   ├── api/
│   │   ├── crypto.py
│   │   ├── news.py
│   │   ├── analysis.py
│   │   └── recommendation.py
│   │
│   ├── services/
│   │   ├── crypto_service.py
│   │   ├── news_service.py
│   │   ├── technical_service.py
│   │   ├── sentiment_service.py
│   │   └── recommendation_service.py
│   │
│   ├── models/
│   │   ├── cryptocurrency.py
│   │   ├── price.py
│   │   ├── news.py
│   │   ├── indicator.py
│   │   └── recommendation.py
│   │
│   ├── schemas/
│   │   ├── crypto.py
│   │   ├── news.py
│   │   └── recommendation.py
│   │
│   ├── workers/
│   │   ├── price_worker.py
│   │   ├── news_worker.py
│   │   └── analysis_worker.py
│   │
│   └── core/
│       ├── config.py
│       └── database.py
│
├── tests/
│
├── .env
├── requirements.txt
├── README.md
└── docker-compose.yml
```

---

# 12. Prinsip Recommendation Engine

Sistem **tidak sebaiknya** menggunakan:

```text
Berita
   |
   v
AI
   |
   v
BUY
```

Lebih baik:

```text
                 Market Data
                     |
          +----------+----------+
          |                     |
          v                     v
 Technical Analysis       Market Condition
          |                     |
          +----------+----------+
                     |
                     +
                     |
                 News Data
                     |
                     v
               Sentiment AI
                     |
                     v
               Scoring Engine
                     |
                     v
              BUY / HOLD / SELL
```

Dengan pendekatan tersebut, alasan di balik rekomendasi lebih mudah dijelaskan dan setiap komponen dapat diuji secara terpisah.

---

# 13. Target Akhir Sistem

Target akhir website:

```text
+------------------------------------------------------+
|              CRYPTO RECOMMENDATION                   |
+------------------------------------------------------+
|                                                      |
| BTC                     $112,450       +3.21%        |
|                                                      |
| Technical Score          82 / 100                    |
| Sentiment Score          78 / 100                    |
| Market Score             75 / 100                    |
|                                                      |
| Final Score              79.4 / 100                  |
|                                                      |
| Recommendation:          HOLD / MODERATE BUY         |
|                                                      |
+------------------------------------------------------+
| Latest News                                          |
|                                                      |
| Positive  | Bitcoin institutional demand increases   |
| Positive  | Crypto market gains momentum             |
| Negative  | Regulatory concerns remain               |
+------------------------------------------------------+
|                                                      |
|                  BTC PRICE CHART                     |
|                                                      |
+------------------------------------------------------+
```

---

# 14. Kesimpulan Planning

Pengembangan dilakukan dari sistem sederhana menuju sistem real-time:

```text
Crypto API
    ↓
FastAPI
    ↓
PostgreSQL
    ↓
Historical Data
    ↓
Technical Analysis
    ↓
News
    ↓
Sentiment Analysis
    ↓
Recommendation Engine
    ↓
React Dashboard
    ↓
WebSocket
    ↓
Real-Time Crypto Recommendation
```

**Prioritas utama:** jangan langsung membuat semua fitur sekaligus. Mulai dari **BTC + market data**, pastikan data berhasil masuk ke database, kemudian lanjut ke historical data dan technical analysis. Setelah fondasi tersebut stabil, baru tambahkan berita, AI, recommendation engine, frontend, dan real-time.

Dengan tahapan ini, setiap bagian dapat diuji secara terpisah sehingga apabila terjadi kesalahan, sumber masalah lebih mudah ditemukan.
