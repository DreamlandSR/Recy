# Rasionil & Justifikasi Parameter Indikator Teknikal Recy

Dokumen ini menjelaskan secara komprehensif latar belakang teoritis, matematis, dan empiris di balik pemilihan parameter teknikal yang digunakan dalam sistem analisis dan rekomendasi kuantitatif **Recy** (`app/services/technical_service.py`, `app/services/scoring_service.py`, dan `app/services/recommendation_service.py`).

---

## 📌 Ringkasan Parameter & Fungsi Utama

| Indikator | Parameter Default | Domain Analisis | Peran Utama dalam Recy |
| :--- | :--- | :--- | :--- |
| **RSI** | Periode: `14` | Momentum | Deteksi overbought/oversold, bullish expansion zone, dan konfirmasi breakout. |
| **SMA** | Periode: `20, 50, 200` | Trend | Penentu tren jangka pendek, menengah, dan makro (Golden/Death Cross & Trend Filter). |
| **EMA** | Periode: `20, 50` | Trend Reaktif | Deteksi akselerasi momentum dan filter tren dinamis untuk mode *Scalping*. |
| **MACD** | Fast: `12`, Slow: `26`, Signal: `9` | Momentum & Trend | Konfirmasi arah tren dan akselerasi momentum via garis sinyal dan histogram. |
| **Bollinger Bands** | Periode: `20`, Deviasi: `2.0` | Volatilitas | Pengukur jarak ekstrem harga terhadap standar deviasi normal (`bb_position`). |
| **ADX** | Periode: `14` (Ambang: `20`, `25`) | Rezim Pasar | **Regime Classifier**: Menentukan bobot dinamis antara strategi *Trend* vs *Oscillator*. |
| **ATR** | Periode: `14` (Multipliers: `1.5×`, `2.0×`) | Volatilitas & Risiko | Menentukan level Stop-Loss, Take-Profit, dan Trailing Stop berbasis volatilitas riil aset. |
| **Volume SMA** | Periode: `20` (Rasio: `0.8`, `1.2`) | Konfirmasi Aliran Dana | Validasi kekuatan breakout dan penyaring *fake pump / low-liquidity squeeze*. |

---

## 1. Relative Strength Index (RSI)

### A. Mengapa Periode 14?
- **Pencipta**: J. Welles Wilder Jr. (*New Concepts in Technical Trading Systems*, 1978).
- **Dasar Siklus**: Wilder merancang periode 14 berdasarkan setengah siklus kalender lunar (~28 hari). Dalam analisis teknikal klasik, setengah siklus pasar adalah periode paling efektif untuk mengukur osilasi harga dari titik terendah ke tertinggi tanpa mengalami lag berlebih.
- **Efisiensi Noise vs Lag**: 
  - Periode lebih pendek (misal 7 atau 9) menghasilkan terlalu banyak *whipsaw* (sinyal palsu) pada volatilitas crypto yang tinggi.
  - Periode lebih panjang (misal 21 atau 25) terlalu lambat merespons pembalikan momentum tajam di pasar aset digital.
  - Periode 14 terbukti menjadi *gold standard* universal yang paling banyak dipantau oleh algoritma dan pelaku pasar institusional.

### B. Justifikasi Zonasi Skor di Recy
Di [scoring_service.py](file:///c:/Project/Magang/Recy/app/services/scoring_service.py#L260-L274), RSI diklasifikasikan ke dalam 4 zona:

```python
if rsi < 30:
    rsi_score = 65      # Oversold / Potensi Rebound
elif rsi < 50:
    rsi_score = 45      # Zona Lemah / Di bawah netral
elif rsi <= 70:
    rsi_score = 70      # Bullish Expansion Zone (Zona Sehat)
else:
    rsi_score = 35      # Overbought / Rawan Koreksi
```

1. **RSI < 30 (Skor 65 - Akumulasi)**:
   - Kondisi *oversold* ekstrem. Tekanan jual penjual mulai jenuh (*seller exhaustion*), menciptakan probabilitas matematis tinggi terjadinya *technical rebound* (mean-reversion).
2. **30 ≤ RSI < 50 (Skor 45 - Lemah)**:
   - Momentum berada di bawah titik ekuilibrium (50). Mengindikasikan bear masih memegang kendali jangka pendek.
3. **50 ≤ RSI ≤ 70 (Skor 70 - Zona Paling Ideal untuk Beli)**:
   - Kesalahan umum trader pemula adalah menganggap RSI naik sebagai tanda bahaya. Dalam tren bullish yang sehat, harga justru bergerak kuat di atas level 50 tanpa menyentuh batas overbought. Level 50–70 menunjukkan *momentum buyer* aktif dan ekspansi tren yang berkelanjutan.
4. **RSI > 70 (Skor 35 - Kehati-hatian)**:
   - Kondisi *overbought*. Probabilitas koreksi jangka pendek atau aksi *profit taking* meningkat drastis, sehingga pembukaan posisi baru dibatasi.

### C. Relaksasi Breakout (RSI 50–78)
Pada fungsi `momentum_breakout()`, syarat RSI ditetapkan pada rentang **50.0 hingga 78.0**. Pada momentum ledakan volume (*breakout*), RSI sering kali menembus level 70 sejenak. Rentang hingga 78 mengizinkan sistem menangkap *runaway trend* tanpa terjebak pada puncak parabola (>80).

---

## 2. Moving Averages: SMA (20, 50, 200) & EMA (20, 50)

### A. Perbedaan Filosofis SMA vs EMA
- **SMA (Simple Moving Average)**: Memberikan bobot setara pada setiap data point. Sangat stabil dan tidak mudah terdistorsi oleh satu candle anomali.
- **EMA (Exponential Moving Average)**: Memberikan bobot eksponensial lebih besar pada harga terbaru. Mengurangi lag dan mendeteksi perubahan arah harga lebih dini.

### B. Pemilihan Periode & Perannya
1. **SMA 20 & EMA 20 (Siklus 1 Bulan / Rata-rata 3 Minggu Crypto)**:
   - Pasar saham konvensional memiliki 20–22 hari bursa per bulan. Di pasar crypto yang berjalan 24/7, periode 20 tetap dipertahankan sebagai tolok ukur pergerakan harga bulanan.
   - **Cross EMA 20 > SMA 20**: Digunakan di [scoring_service.py](file:///c:/Project/Magang/Recy/app/services/scoring_service.py#L82) sebagai indikator akselerasi momentum jangka pendek. Jika rata-rata tertimbang terbaru (EMA) menyalip rata-rata umum (SMA), artinya pembeli sedang agresif mendongkrak harga.
2. **SMA 50 (Tren Menengah ~1.5 s/d 2 Bulan)**:
   - Penentu arah tren kuartalan. Banyak pengelola dana (*hedge funds*) menggunakan SMA 50 sebagai level batas dinamis antara fase akumulasi dan fase distribusi.
3. **SMA 200 (Tren Makro Jangka Panjang / Institutional Boundary)**:
   - Standar global pasar modal dunia. 
   - **Golden Cross** (`SMA 50 > SMA 200`): Mengonfirmasi transisi dari bear market ke bull market struktural.
   - **Trend Filter**: Recy mewajibkan `Price > SMA 200` untuk sinyal BUY standar guna mencegah *"catching falling knives"* (membeli aset yang sedang dalam tren turun struktural).
4. **EMA 50 (Khusus Mode Scalping / Day Trading)**:
   - Pada perdagangan jangka pendek (timeframe 15m–1h), SMA 200 harian terlalu lambat untuk memberikan perlindungan tren. Mode *Scalp* mengalihkan filter tren ke pasangan **EMA 20 & EMA 50** pada timeframe aktif untuk menjaga reaksi cepat terhadap struktur harga intraday.

---

## 3. MACD (Moving Average Convergence Divergence)

### A. Parameter Standar 12, 26, 9
- **Pencipta**: Gerald Appel (1979).
- **Dasar**:
  - `Fast EMA = 12`: Merepresentasikan momentum 2 minggu kerja.
  - `Slow EMA = 26`: Merepresentasikan siklus 1 bulan kerja.
  - `Signal Line = 9`: Exponential smoothing 9 hari terhadap selisih MACD line.
- **Mengapa tidak diubah untuk Crypto?**
  Meskipun pasar crypto tidak pernah libur, parameter (12, 26, 9) telah menjadi *self-fulfilling prophecy*. Mayoritas algoritma HFT (High-Frequency Trading), bot market maker, dan indikator terminal institusional (Bloomberg, TradingView) mengacu pada angka ini. Mengubah parameter ke angka unik sering kali justru menurunkan korelasi sinyal terhadap likuiditas pasar nyata.

### B. Evaluasi Skor di Recy
Di [scoring_service.py](file:///c:/Project/Magang/Recy/app/services/scoring_service.py#L279-L290), skor momentum menggabungkan dua dimensi MACD:
1. **Trend Direction (MACD Line vs Signal Line)**:
   - `MACD > Signal`: Skor 70 (Kecepatan kenaikan harga jangka pendek melampaui rata-rata historisnya).
   - `MACD ≤ Signal`: Skor 30 (Sinyal pelemahan tren).
2. **Momentum Acceleration (Histogram > 0)**:
   - Histogram mengukur selisih antara garis MACD dan garis sinyal. Histogram positif mengonfirmasi bahwa momentum sedang membesar (*diverging*), bukan melambat.

---

## 4. Bollinger Bands (20, 2.0 Deviasi Standar)

### A. Landasan Statistik Gaussian
- **Pencipta**: John Bollinger (1980-an).
- **Dasar Matematika**: Dalam distribusi normal (kurva lonceng Gauss):
  - $\pm 1\sigma$ mencakup ~68.2% data.
  - $\pm 2\sigma$ mencakup **~95.4%** data.
  - $\pm 3\sigma$ mencakup ~99.7% data.
- **Mengapa $2\sigma$?**
  Deviasi 2.0 memastikan bahwa sekitar 95% pergerakan harga terjadi di dalam pita. Ketika harga menyentuh pita luar, itu adalah peristiwa statistik ekstrem (~5% probabilitas), menandakan kondisi *overextended* (terlalu murah di lower band atau terlalu mahal di upper band).

### B. Normalisasi Posisi Harga (`bb_position`)
Recy mengonversi harga ke dalam skala relatif 0.0 s/d 1.0:
$$\text{bb\_position} = \frac{\text{Price} - \text{Lower Band}}{\text{Upper Band} - \text{Lower Band}}$$

- **`bb_position < 0.20` (Skor 70)**: Harga berada di 20% terbawah band (dekat Lower Band). Mengindikasikan diskon harga ekstrem dengan potensi tinggi memantul kembali ke nilai tengah (*mean-reversion*).
- **`0.20 ≤ bb_position ≤ 0.80` (Skor 50)**: Harga berada dalam rentang wajar (ekuilibrium).
- **`bb_position > 0.80` (Skor 30)**: Harga menyentuh pita atas, mengindikasikan resistensi volatilitas dan risiko koreksi.

---

## 5. Average Directional Index (ADX 14) & Rezim Pasar

### A. Paradoks Indikator Teknikal
Masalah terbesar dalam analisis teknikal kuantitatif adalah:
- **Osilator (RSI, Bollinger Bands)** bekerja sangat baik saat pasar bergerak *Sideways* (membeli di support, menjual di resisten), namun **gagal total** saat pasar *Trending* kuat (terus memberi sinyal overbought saat harga terbang tinggi).
- **Trend Follower (Moving Average, MACD)** sangat menguntungkan saat pasar *Trending*, namun mengalami banyak kerugian (*whipsaw/choppy*) saat pasar *Sideways*.

### B. Solusi Recy: Dynamic Regime Weighting
Recy menggunakan ADX 14 bukan untuk menentukan arah (naik/turun), melainkan untuk **mengukur kekuatan tren** dan mengklasifikasikan rezim pasar secara otomatis:

```text
ADX >= 25       ──> TRENDING    ──> Bobot Trend & MACD dinaikkan
ADX < 20        ──> SIDEWAYS    ──> Bobot Osilator (RSI & Bollinger) dinaikkan
20 <= ADX < 25  ──> TRANSITION  ──> Bobot Seimbang Netral
```

#### Matriks Bobot Rezim Pasar ([scoring_service.py](file:///c:/Project/Magang/Recy/app/services/scoring_service.py#L64-L69)):
| Rezim | Ambang ADX | Trend ($w_{trend}$) | Momentum ($w_{mom}$) | Volatilitas ($w_{vol}$) | Volume ($w_{volm}$) |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **TRENDING** | $\ge 25$ | **40%** | **35%** | **10%** | **15%** |
| **SIDEWAYS** | $< 20$ | **15%** | **30%** | **40%** | **15%** |
| **TRANSITION**| $20 - 25$ | **30%** | **35%** | **20%** | **15%** |

### C. Override Mean-Reversion
Pada rezim **SIDEWAYS** ($ADX < 20$) dengan **$RSI < 35$**, Recy melonggarkan syarat SMA 50. Hal ini secara matematis mengizinkan pembelian di harga diskon bawah range konsolidasi, tanpa harus menunggu konfirmasi tren naik yang lambat.

---

## 6. Average True Range (ATR 14) & Risk Management

### A. Mengapa ATR Lebih Unggul dari Stop-Loss Persentase Kaku?
Banyak trader menggunakan aturan kaku seperti "Stop-Loss selalu 3%". Pendekatan ini memiliki kelemahan fatal di pasar crypto:
- Pada aset stabil seperti **Bitcoin**, pergerakan 3% adalah pergerakan besar.
- Pada aset dengan volatilitas tinggi seperti **Solana** atau koin berkapitalisasi menengah, fluktuasi normal 30 menit saja bisa mencapai 4–5%. Stop-Loss 3% akan terkena *stop-out prematur* (terkena sumbu candle sebelum harga naik kembali).

ATR mengukur rentang volatilitas harian riil aset tersebut, sehingga batas risiko **beradaptasi secara organik**:
$$\text{True Range (TR)} = \max(|High - Low|, |High - Close_{prev}|, |Low - Close_{prev}|)$$

### B. Rasio Multiplier ($1.5\times$ SL dan $2.0\times$ TP)
Di [recommendation_service.py](file:///c:/Project/Magang/Recy/app/services/recommendation_service.py#L10-L13):

$$\text{Stop-Loss Price} = \text{Entry} - (1.5 \times ATR_{14})$$
$$\text{Take-Profit Price} = \text{Entry} + (2.0 \times ATR_{14})$$
$$\text{Risk : Reward Ratio} = \frac{2.0 \times ATR}{1.5 \times ATR} = 1 : 1.33$$

1. **Jarak $1.5 \times ATR$**:
   - Memberikan ruang napas sebesar 1.5 kali rata-rata fluktuasi harian di bawah harga beli. Jarak ini berada di luar rentang *market noise* acak normal, sehingga stop-out hanya terjadi jika terjadi perubahan tren yang valid.
2. **Rasio Risk:Reward $1 : 1.33$**:
   - Menjamin ekspektansi matematika bernilai positif. Dengan rasio ini, sistem hanya membutuhkan win rate minimal ~43% untuk mencapai titik impas (*breakeven*), jauh lebih aman dibandingkan strategi rasio 1:1.
3. **ATR Trailing Stop**:
   - Level dihitung dari puncak harga tertinggi sejak entri:
     $$\text{Trailing Level} = \text{Highest Price} - (1.5 \times ATR_{14})$$
   - Mengunci keuntungan saat tren berjalan, mencegah posisi yang sudah profit berbalik menjadi rugi besar.

---

## 7. Konfirmasi Volume & Volume SMA 20

### A. Mengapa Perlu Konfirmasi Volume?
Volume adalah *"bahan bakar"* di balik pergerakan harga. Pergerakan harga yang naik tanpa didukung volume yang signifikan rentan menjadi *manipulasi pasar* atau *fake pump* akibat likuiditas tipis.

### B. Rumus & Ambang Rasio
$$\text{volume\_ratio} = \frac{\text{Volume Harian}}{\text{SMA 20 (Volume)}}$$

1. **`volume_ratio ≥ 1.2` saat harga naik (Skor 75)**:
   - Volume transaksi 20% di atas rata-rata bulanan mengonfirmasi adanya akumulasi nyata oleh investor institusional (*smart money*).
2. **`volume_ratio < 0.8` saat harga naik (Skor 35)**:
   - Kenaikan harga terjadi di atas volume tipis (-20% dari rata-rata). Ini adalah peringatan dini *low-liquidity trap*.
3. **`volume_ratio ≥ 1.2` saat harga turun (Skor 30)**:
   - Tekanan jual besar (*institutional distribution / panic selling*).

---

## 8. Ambang Sinyal Mode Trading & Penalti Breakout

Di [scoring_service.py](file:///c:/Project/Magang/Recy/app/services/scoring_service.py#L10-L28):

```python
SIGNAL_MODES = {
    "scalp": {"buy": 60.0, "sell": 40.0},
    "swing": {"buy": 68.0, "sell": 32.0},
}
```

### A. Mode Scalping (BUY ≥ 60, SELL < 40)
- **Karakteristik**: Siklus transaksi menit hingga jam (intraday).
- **Rasional**: Keuntungan scalping diambil dari riak pergerakan kecil. Jika harus menunggu skor mencapai 70 (sangat selektif), sebagian besar pergerakan harga sudah selesai. Ambang 60/40 memberikan sensitivitas tinggi untuk eksekusi cepat.

### B. Mode Swing (BUY ≥ 68, SELL < 32)
- **Karakteristik**: Siklus transaksi berhari-hari hingga berminggu-minggu.
- **Rasional**: Memerlukan konfirmasi multivariat yang ketat agar tidak mudah terombang-ambing oleh volatilitas harian. Ambang 68/32 memastikan bahwa posisi hanya diambil ketika sebagian besar indikator (trend, momentum, volume) berada dalam konvergensi bullish yang solid.

### C. Penalti Breakout (`TREND_BREAKOUT_PENALTY = 12.0`)
- **Masalah**: Aturan Trend Filter tradisional (`Price > SMA 200`) sering kali membuat trader ketinggalan fase awal siklus bull baru, karena pembalikan tren dari dasar *bear market* selalu dimulai saat harga masih di bawah SMA 200.
- **Solusi**: Jika `momentum_breakout()` mendeteksi ledakan momentum yang kuat (Fresh MACD Golden Cross + RSI 50–78 menguat), sistem tidak memblokir sinyal ke `HOLD` secara mutlak, melainkan menerapkan pemotongan skor sebesar **12 poin**. Hal ini memungkinkan sinyal BUY tetap muncul jika skor awalnya sangat tinggi (>80), namun menyaring koin yang kenaikannya masih ragu-ragu.

---

## 📚 Referensi Ilmiah & Bacaan Lanjutan

1. **Wilder, J. Welles Jr.** (1978). *New Concepts in Technical Trading Systems*. Trend Research. (RSI, ATR, ADX).
2. **Appel, Gerald** (2005). *Technical Analysis: Power Tools for Active Investors*. Financial Times Prentice Hall. (MACD).
3. **Bollinger, John** (2001). *Bollinger on Bollinger Bands*. McGraw-Hill. (Volatility Bands).
4. **Murphy, John J.** (1999). *Technical Analysis of the Financial Markets*. New York Institute of Finance. (Moving Averages & Multi-Timeframe Trends).
5. **Kaufman, Perry J.** (2013). *Trading Systems and Methods* (5th ed.). John Wiley & Sons. (Adaptive Volatility & Noise Reduction).
