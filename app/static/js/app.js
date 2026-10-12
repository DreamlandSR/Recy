/* ==========================================================================
   Recy Crypto Intelligence Terminal — frontend (vanilla JS, zero build)
   - Watchlist  : GET /api/crypto/dashboard/watchlist      (poll 45 dtk)
   - Live price : GET /api/crypto/live-prices              (poll 5 dtk — harga
     Binance real-time + SL/TP terhitung ulang dari harga live)
   - Chart      : GET /api/crypto/{id}/history             (cache BE 5 mnt)
   - Gauges     : GET /api/crypto/{id}/technical/score
   - Exec+News  : GET /api/crypto/{id}/analysis            (FinBERT)
   - Ticker FNG : GET /api/market/fng                      (cache BE 15 mnt)
   ========================================================================== */

"use strict";

const POLL_WATCHLIST_MS = 45_000;
const POLL_DETAIL_MS = 60_000;      // history + technical (murah, di-cache)
const POLL_ANALYSIS_MS = 300_000;   // execution + news (FinBERT)
const POLL_LIVE_MS = 5_000;         // fallback HTTP polling bila WebSocket offline
const POLL_ALERTS_MS = 10_000;      // cek alert harga (ringan, cache BE 5 dtk)

const BINANCE_WS_URLS = [
  "wss://data-stream.binance.vision/ws/!miniTicker@arr",
  "wss://stream.binance.com:9443/ws/!miniTicker@arr",
];

const BINANCE_SYMBOLS = {
  bitcoin: "BTCUSDT",
  ethereum: "ETHUSDT",
  solana: "SOLUSDT",
  binancecoin: "BNBUSDT",
  ripple: "XRPUSDT",
  dogecoin: "DOGEUSDT",
  cardano: "ADAUSDT",
  sui: "SUIUSDT",
  "avalanche-2": "AVAXUSDT",
  polkadot: "DOTUSDT",
  chainlink: "LINKUSDT",
  litecoin: "LTCUSDT",
  tron: "TRXUSDT",
  "the-open-network": "TONUSDT",
  cosmos: "ATOMUSDT",
  algorand: "ALGOUSDT",
  "ethereum-classic": "ETCUSDT",
  stellar: "XLMUSDT",
  "bitcoin-cash": "BCHUSDT",
  pepe: "PEPEUSDT",
  "shiba-inu": "SHIBUSDT",
  "hedera-hashgraph": "HBARUSDT",
  aptos: "APTUSDT",
  arbitrum: "ARBUSDT",
  optimism: "OPUSDT",
  uniswap: "UNIUSDT",
  "polygon-ecosystem-token": "POLUSDT",
  near: "NEARUSDT",
  "internet-computer": "ICPUSDT",
  filecoin: "FILUSDT",
  "injective-protocol": "INJUSDT",
  aave: "AAVEUSDT",
  "render-token": "RENDERUSDT",
  arweave: "ARUSDT",
  "worldcoin-wld": "WLDUSDT",
};

let binanceWs = null;
let wsReconnectTimer = null;
let wsUrlIdx = 0;
let wsActive = false;

/* Timeframe (Phase 9): 15m-1D memakai candle OHLCV Binance (klines,
   update tick OHLC real-time); 7D-1Y area CoinGecko (jangka panjang). */
const TF_CONFIG = {
  "15m": { src: "binance", interval: "15m", limit: 180 },
  "1h": { src: "binance", interval: "1h", limit: 240 },
  "4h": { src: "binance", interval: "4h", limit: 210 },
  "1D": { src: "binance", interval: "1d", limit: 180 },
  "7D": { src: "coingecko", days: 7 },
  "30D": { src: "coingecko", days: 30 },
  "90D": { src: "coingecko", days: 90 },
  "1Y": { src: "coingecko", days: 365 },
};
const DEFAULT_COINS = ["bitcoin", "ethereum", "solana", "binancecoin", "ripple"];
const LS_KEY = "recy.watchlist.coins";

const state = {
  coins: [],            // watchlist rows
  selected: null,       // coin_id terpilih
  chart: null,
  series: {},
  timers: {},
  loadingDetail: false,
  tf: "90D",            // timeframe chart aktif
  custom: loadCustomCoins(), // koin tambahan pengguna (localStorage)
  exec: null,           // blok execution terakhir (untuk kalkulator)
  pendingAdd: null,     // koin baru yang sedang divalidasi
  // Phase 8
  lastBarTime: null,    // (legacy) waktu bar terakhir — lihat lastBar
  filter: "all",        // quick filter watchlist aktif
  prevRec: {},          // rekomendasi sebelumnya (deteksi transisi BUY)
  notifFired: {},       // status peringatan risiko terakhir (dedupe)
  // Phase 9
  sort: "default",      // urutan watchlist (chip sortir)
  seriesType: null,     // "candles" | "area" — jenis series utama chart
  lastBar: null,        // bar terakhir (OHLC utk candle / value utk area)
  priceLines: {},       // ref garis SL/TP/trailing pada series aktif
  lastClosed: [],       // riwayat trade tertutup terakhir (equity/CSV)
  equityChart: null,    // chart mini equity curve (tab Riwayat)
  equitySeries: null,
};

const $ = (sel) => document.querySelector(sel);

/* ---------------- helpers ---------------- */

async function api(path) {
  const res = await fetch(path, { cache: "no-store" });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(`${res.status} — ${detail}`);
  }
  return res.json();
}

function fmtPrice(p) {
  const n = Number(p);
  if (p == null || Number.isNaN(n)) return "—";
  if (n >= 1000) return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  if (n >= 1) return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 4 });
  if (n >= 0.01) return n.toFixed(6);
  return n.toFixed(8);
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function coinIcon(sym, cls = "coin-icon") {
  const s = esc(String(sym).toLowerCase());
  return (
    `<span class="relative inline-flex">` +
    `<i class="fa-solid fa-coins absolute inset-0 m-auto text-muted/50"></i>` +
    `<img class="${cls}" loading="lazy" alt="${s}" ` +
    `src="https://cdn.jsdelivr.net/gh/spothq/cryptocurrency-icons@master/128/color/${s}.png" ` +
    `onerror="this.style.visibility='hidden'"/>` +
    `</span>`
  );
}

const TREND_BADGE = {
  BULLISH: '<span class="badge badge-bull"><i class="fa-solid fa-arrow-trend-up"></i>BULLISH</span>',
  BEARISH: '<span class="badge badge-bear"><i class="fa-solid fa-arrow-trend-down"></i>BEARISH</span>',
  NEUTRAL: '<span class="badge badge-neutral"><i class="fa-solid fa-minus"></i>NEUTRAL</span>',
};

const REC_BADGE = {
  BUY: '<span class="badge badge-buy"><i class="fa-solid fa-circle-check"></i>BUY</span>',
  HOLD: '<span class="badge badge-hold"><i class="fa-solid fa-hourglass-half"></i>HOLD</span>',
  SELL: '<span class="badge badge-sell"><i class="fa-solid fa-triangle-exclamation"></i>SELL</span>',
};

function scoreColor(v) {
  if (v >= 60) return "var(--bull)";
  if (v >= 40) return "var(--amber)";
  return "var(--bear)";
}

/* --------- Watchlist kustom (localStorage) --------- */
function loadCustomCoins() {
  try {
    const list = JSON.parse(localStorage.getItem(LS_KEY));
    return Array.isArray(list) ? list.filter((x) => typeof x === "string" && x) : [];
  } catch (_) {
    return [];
  }
}

function saveCustomCoins() {
  localStorage.setItem(LS_KEY, JSON.stringify(state.custom));
}

function watchParams() {
  const all = [...DEFAULT_COINS];
  for (const c of state.custom) if (!all.includes(c)) all.push(c);
  return all.join(",");
}

/* --------- Toast --------- */
let toastTimer = null;
function toast(msg, kind = "ok") {
  const el = $("#toast");
  el.textContent = msg;
  el.className = `toast show ${kind}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.className = "toast"; }, 4200);
}

/* ---------------- 1. FNG ---------------- */

async function loadFng() {
  try {
    const fng = await api("/api/market/fng");
    const s = Number(fng.score);
    const color = s >= 60 ? "var(--bull)" : s >= 40 ? "var(--amber)" : "var(--bear)";
    $("#fng-value").textContent = `${Math.round(s)} — ${fng.classification || ""}`;
    $("#fng-value").style.color = color;
  } catch (err) {
    $("#fng-value").textContent = "N/A";
    console.warn("FNG:", err.message);
  }
}

/* ---------------- 2. Watchlist ---------------- */

async function loadWatchlist() {
  try {
    const q = watchParams();
    const data = await api(`/api/crypto/dashboard/watchlist?coins=${encodeURIComponent(q)}`);
    state.coins = data.coins || [];

    // Validasi koin baru: bila coin_id tidak dikenal CoinGecko (ada field
    // error), keluarkan dari daftar kustom dan beri tahu pengguna.
    if (state.pendingAdd) {
      const added = state.coins.find((c) => c.coin_id === state.pendingAdd);
      if (!added || added.error) {
        state.custom = state.custom.filter((x) => x !== state.pendingAdd);
        saveCustomCoins();
        toast(`Koin "${state.pendingAdd}" tidak ditemukan di CoinGecko.`, "err");
      } else {
        toast(`${added.name} (${(added.symbol || "").toUpperCase()}) ditambahkan ke watchlist.`);
      }
      state.pendingAdd = null;
    }
    // Self-healing: buang koin kustom yang tidak valid dari penyimpanan.
    const errored = new Set(state.coins.filter((c) => c.error).map((c) => c.coin_id));
    state.custom = state.coins
      .map((c) => c.coin_id)
      .filter((id) => !DEFAULT_COINS.includes(id) && !errored.has(id));
    saveCustomCoins();

    // (Phase 8) Deteksi transisi sinyal -> BUY utk notifikasi desktop.
    state.coins.forEach(checkBuySignal);
    // (Phase 9) Alert harga terpicu dari siklus watchlist (scheduler TG).
    if (data.alerts_triggered && data.alerts_triggered.length) {
      handleAlertTriggers(data.alerts_triggered);
    }

    renderWatchlist();
    $("#wl-updated").textContent = `updated ${new Date().toLocaleTimeString("id-ID")}`;

    // Auto-pilih koin pertama saat belum ada yang dipilih — tampilan
    // terminal selalu penuh, pengguna tinggal klik koin lain untuk berganti.
    if (!state.selected) {
      const first = state.coins.find((c) => !c.error);
      if (first) selectCoin(first.coin_id);
    }
  } catch (err) {
    $("#watchlist-body").innerHTML =
      `<tr><td colspan="6" class="p-6 text-center text-bear">
         <i class="fa-solid fa-circle-exclamation mr-2"></i>Gagal memuat watchlist: ${esc(err.message)}
       </td></tr>`;
    console.error("watchlist:", err);
  }
}

/* --------- Quick filter watchlist (market scanner, client-side) --------- */
function watchFilterMatch(c) {
  if (state.filter === "buy") return c.recommendation === "BUY";
  if (state.filter === "near_sl") {
    if (c.price == null || c.sl_price == null) return false;
    const price = Number(c.price);
    const sl = Number(c.sl_price);
    // Dekat/tersentuh SL: harga <= SL + 1.5% (sama dgn aturan backend).
    return sl > 0 && price <= sl * (1 + 1.5 / 100);
  }
  if (state.filter === "trending") return c.adx_14 != null && Number(c.adx_14) >= 25;
  return true;
}

/* --------- Sortir watchlist (client-side instan) --------- */
function sortWatchlistRows(rows) {
  const s = state.sort;
  if (s === "default") return rows;
  const out = [...rows];
  const num = (v, d) => (v == null || Number.isNaN(Number(v)) ? d : Number(v));
  if (s === "change_desc") {
    out.sort((a, b) => num(b.change_24h_pct, -Infinity) - num(a.change_24h_pct, -Infinity));
  } else if (s === "price_desc") {
    out.sort((a, b) => num(b.price, -Infinity) - num(a.price, -Infinity));
  } else if (s === "adx_desc") {
    out.sort((a, b) => num(b.adx_14, -Infinity) - num(a.adx_14, -Infinity));
  } else if (s === "signal") {
    const rank = { BUY: 0, HOLD: 1, SELL: 2 };
    out.sort((a, b) => (rank[a.recommendation] ?? 3) - (rank[b.recommendation] ?? 3));
  }
  return out;
}

function renderWatchlist() {
  const body = $("#watchlist-body");
  const rows = sortWatchlistRows(state.coins.filter(watchFilterMatch));
  const countEl = $("#wl-filter-count");
  if (countEl) countEl.textContent = `${rows.length}/${state.coins.length} koin`;

  if (!state.coins.length) {
    body.innerHTML = `<tr><td colspan="6" class="p-6 text-center text-muted">Tidak ada data koin.</td></tr>`;
    return;
  }
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="6" class="p-6 text-center text-muted">Tidak ada koin yang cocok dengan filter <b class="text-cyan">${esc(state.filter)}</b>.</td></tr>`;
    return;
  }

  // Tabel kompak kolom kiri: Coin | Price (live) | Signal | SL | TP | Aksi.
  body.innerHTML = rows
    .map((c) => `
      <tr class="wl-row ${c.coin_id === state.selected ? "selected" : ""}" data-coin="${esc(c.coin_id)}">
        <td>
          <div class="flex items-center gap-2.5">
            ${coinIcon(c.symbol)}
            <div class="min-w-0">
              <div class="truncate font-semibold">${esc(c.name)}</div>
              <div class="text-[10px] uppercase text-muted">${esc(c.symbol)}</div>
            </div>
          </div>
        </td>
        <td class="num text-right font-semibold cell-price">$${fmtPrice(c.price)}${c.error ? `<div class="text-[9.5px] text-bear">error</div>` : ""}</td>
        <td class="cell-signal">${REC_BADGE[c.recommendation] || `<span class="badge badge-neutral">${esc(c.recommendation || "—")}</span>`}</td>
        <td class="num text-right text-bear cell-sl">$${fmtPrice(c.sl_price)}</td>
        <td class="num text-right text-bull cell-tp">$${fmtPrice(c.tp_price)}</td>
        <td class="text-center">${state.custom.includes(c.coin_id)
          ? `<span class="wl-remove" data-remove="${esc(c.coin_id)}" title="Hapus dari watchlist"><i class="fa-solid fa-xmark"></i></span>`
          : ""}</td>
      </tr>`)
    .join("");

  body.querySelectorAll(".wl-row").forEach((row) =>
    row.addEventListener("click", () => selectCoin(row.dataset.coin))
  );
  body.querySelectorAll("[data-remove]").forEach((el) =>
    el.addEventListener("click", (ev) => {
      ev.stopPropagation();
      const id = el.dataset.remove;
      state.custom = state.custom.filter((x) => x !== id);
      saveCustomCoins();
      if (state.selected === id) {
        state.selected = null;
        $("#detail").classList.add("hidden");
        $("#detail-empty").classList.remove("hidden");
      }
      loadWatchlist();
    })
  );
}

/* ---------------- 3. Detail: chart + gauges ---------------- */

function ensureChart() {
  if (state.chart) return;
  const el = $("#chart");
  state.chart = LightweightCharts.createChart(el, {
    width: el.clientWidth,
    height: el.clientHeight || 340,
    layout: {
      background: { type: "solid", color: "#121824" },
      textColor: "#8A94A8",
      fontFamily: "Inter, sans-serif",
    },
    grid: {
      vertLines: { color: "rgba(38,50,74,0.35)" },
      horzLines: { color: "rgba(38,50,74,0.35)" },
    },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    rightPriceScale: { borderColor: "#26324A" },
    timeScale: { borderColor: "#26324A", timeVisible: false },
  });

  // Series UTAMA dibuat sesuai kebutuhan lewat setMainSeries(type):
  // candlestick (Binance klines) atau area (CoinGecko daily).

  state.series.vol = state.chart.addHistogramSeries({
    priceScaleId: "vol",
    priceFormat: { type: "volume" },
    color: "rgba(138,148,168,0.35)",
  });
  state.chart.priceScale("vol").applyOptions({
    scaleMargins: { top: 0.82, bottom: 0 },
  });

  new ResizeObserver(() => {
    state.chart.applyOptions({ width: el.clientWidth, height: el.clientHeight || 340 });
  }).observe(el);
}

function renderChart(history) {
  const series = setMainSeries("area");
  const prices = history.prices || [];
  const volumes = history.total_volumes || [];
  const volMap = new Map(volumes.map(([ts, v]) => [ts, v]));

  const priceData = prices.map(([ts, p]) => ({ time: Math.floor(ts / 1000), value: p }));
  const volData = prices.map(([ts, p]) => {
    const v = volMap.get(ts);
    return {
      time: Math.floor(ts / 1000),
      value: v ?? 0,
      color: "rgba(138,148,168,0.25)",
    };
  });

  series.setData(priceData);
  state.series.vol.setData(volData);
  state.chart.timeScale().fitContent();

  // Bar terakhir — titik ujung grafik digerakkan real-time oleh tick
  // Binance (live chart ticking, Phase 8/9).
  const lastBar = priceData[priceData.length - 1];
  state.lastBar = lastBar ? { time: lastBar.time, value: lastBar.value } : null;
  state.lastBarTime = lastBar ? lastBar.time : null;
}

function renderGauges(score, latest, analysis) {
  const s = score || {};
  const overall = Number(s.technical_score ?? 0);

  const gauge = $("#g-overall");
  gauge.style.setProperty("--pct", overall.toFixed(0));
  gauge.style.setProperty("--gauge-color", scoreColor(overall));
  $("#g-overall-value").textContent = overall.toFixed(1);

  const comps = [
    ["trend", s.trend_score],
    ["momentum", s.momentum_score],
    ["volatility", s.volatility_score],
    ["volume", s.volume_score],
  ];
  comps.forEach(([key, val]) => {
    const v = Number(val ?? 0);
    $(`#v-${key}`).textContent = v.toFixed(1);
    $(`#b-${key}`).style.width = `${Math.max(2, Math.min(100, v))}%`;
  });

  const REGIME = {
    TRENDING: '<span class="badge badge-cyan"><i class="fa-solid fa-chart-line"></i>Trending</span>',
    SIDEWAYS: '<span class="badge badge-hold"><i class="fa-solid fa-arrows-left-right"></i>Sideways</span>',
    TRANSITION: '<span class="badge badge-neutral">Transition</span>',
    UNKNOWN: '<span class="badge badge-neutral">Unknown</span>',
  };
  const adx = s.adx_14;
  $("#d-regime").innerHTML =
    (REGIME[s.regime] || `<span class="badge badge-neutral">${esc(s.regime)}</span>`) +
    (adx != null ? `<div class="num mt-1 text-[11px] text-muted">ADX ${Number(adx).toFixed(1)}</div>` : "");

  const rsi = latest?.rsi_14;
  const rsiEl = $("#d-rsi");
  rsiEl.textContent = rsi != null ? Number(rsi).toFixed(1) : "—";
  rsiEl.className = `num mt-1 text-sm font-bold ${
    rsi == null ? "" : rsi < 30 ? "text-bull" : rsi > 70 ? "text-bear" : ""
  }`;

  const macdH = latest?.macd_histogram;
  const macdEl = $("#d-macd");
  macdEl.textContent = macdH != null ? Number(macdH).toFixed(4) : "—";
  macdEl.className = `num mt-1 text-sm font-bold ${macdH == null ? "" : macdH > 0 ? "text-bull" : "text-bear"}`;

  const vr = latest?.volume_ratio;
  $("#d-volratio").textContent = vr != null ? `${Number(vr).toFixed(2)}×` : "n/a";

  if (analysis) {
    const cond = analysis.sentiment?.condition || "—";
    const cls = cond === "BULLISH" ? "text-bull" : cond === "BEARISH" ? "text-bear" : "text-amber";
    $("#d-sentiment").textContent = `${cond} (${Number(analysis.sentiment?.sentiment_score ?? 0).toFixed(1)})`;
    $("#d-sentiment").className = cls;
    $("#d-final").textContent = `${Number(analysis.final?.final_score ?? 0).toFixed(1)} — ${analysis.final?.recommendation || "—"}`;
  }
}

/* ---------------- 4. Execution card + news ---------------- */

const PLAN = {
  BUY: { cls: "plan-buy", icon: "fa-circle-check", text: "BELI / BUILD POSITION — patuhi level SL & TP" },
  HOLD: { cls: "plan-hold", icon: "fa-hourglass-half", text: "TAHAN / TUNGGU KONFIRMASI — jangan entry agresif" },
  SELL: { cls: "plan-sell", icon: "fa-triangle-exclamation", text: "KURANGI POSISI / KELUAR — jangan entry baru" },
};

function renderExecution(analysis, watchRow) {
  // Fallback: pakai baris watchlist bila /analysis gagal (mis. kuota GNews).
  const e = analysis?.execution || (watchRow ? {
    current_price: watchRow.price,
    stop_loss_price: watchRow.sl_price,
    take_profit_price: watchRow.tp_price,
    trailing_stop_trigger: watchRow.trailing_stop_trigger,
    risk_reward_ratio: watchRow.risk_reward_ratio,
    suggested_allocation_pct: watchRow.suggested_allocation_pct,
    note: "Data detail tidak tersedia — angka dari watchlist.",
  } : null);

  state.exec = e; // untuk kalkulator posisi
  updateCalculator();

  if (!e) {
    $("#plan-banner").innerHTML = `<i class="fa-solid fa-circle-exclamation"></i><span>Data eksekusi tidak tersedia.</span>`;
    return;
  }

  const rec = analysis?.final?.recommendation || watchRow?.recommendation || "HOLD";
  const plan = PLAN[rec] || PLAN.HOLD;
  const banner = $("#plan-banner");
  banner.className = `plan-banner ${plan.cls} mb-4`;
  banner.innerHTML = `<i class="fa-solid ${plan.icon}"></i><span>${plan.text}</span>`;

  $("#p-sl").textContent = `$${fmtPrice(e.stop_loss_price)}`;
  $("#p-sl-dist").textContent = e.sl_distance_pct != null ? `−${Number(e.sl_distance_pct).toFixed(2)}% dari harga` : "—";
  $("#p-tp").textContent = `$${fmtPrice(e.take_profit_price)}`;
  $("#p-tp-dist").textContent = e.tp_distance_pct != null ? `+${Number(e.tp_distance_pct).toFixed(2)}% dari harga` : "—";
  $("#p-rr").textContent = e.risk_reward_ratio || "—";
  $("#p-alloc").textContent = e.suggested_allocation_pct || "—";
  $("#p-trailing").textContent = e.trailing_stop_trigger || "—";
  $("#p-note").textContent = e.note || "—";

  updatePriceLines(); // garis SL/TP/trailing di chart (Phase 9)
}

function renderNews(analysis) {
  const articles = analysis?.articles || [];
  $("#news-count").textContent = articles.length
    ? `${articles.length} artikel`
    : "0 artikel — kuota GNews mungkin habis";
  const list = $("#news-list");

  if (!articles.length) {
    list.innerHTML =
      `<div class="p-6 text-center text-muted">
         <i class="fa-regular fa-face-meh mb-2 block text-2xl opacity-60"></i>
         Tidak ada berita (free plan GNews ~30 hari / kuota harian).
       </div>`;
    return;
  }

  const SENT = {
    positive: { cls: "badge-buy", icon: "fa-arrow-trend-up", label: "BULLISH" },
    negative: { cls: "badge-sell", icon: "fa-arrow-trend-down", label: "BEARISH" },
    neutral: { cls: "badge-hold", icon: "fa-minus", label: "NEUTRAL" },
  };

  list.innerHTML = articles
    .map((a) => {
      const st = SENT[a.sentiment] || SENT.neutral;
      const conf = (Number(a.score) * 100).toFixed(0);
      const date = a.published_at ? new Date(a.published_at).toLocaleDateString("id-ID", { day: "numeric", month: "short" }) : "";
      return `
      <div class="news-item">
        <div class="mb-1 flex items-center justify-between gap-2">
          <span class="text-[11px] text-muted">${esc(a.source || "-")} ${date ? "• " + date : ""}</span>
          <span class="badge ${st.cls}"><i class="fa-solid ${st.icon}"></i>${st.label} · ${conf}%</span>
        </div>
        <a href="${esc(a.url || "#")}" target="_blank" rel="noopener" class="text-[13.5px] font-semibold leading-snug block">
          ${esc(a.title)}
        </a>
        ${a.description ? `<p class="mt-1 line-clamp-2 text-[12px] text-muted">${esc(a.description)}</p>` : ""}
      </div>`;
    })
    .join("");
}

/* ---------------- Kalkulator posisi & risiko ---------------- */

function parseAllocPct(text) {
  // "10-15%" -> 10 (batas bawah, konservatif); "3-5%" -> 3.
  const m = String(text || "").match(/(\d+(?:\.\d+)?)/);
  return m ? parseFloat(m[1]) : null;
}

function updateCalculator() {
  const e = state.exec;
  if (!e) return;

  const cur = $("#calc-currency").value; // USD | IDR
  const rate = cur === "IDR" ? (parseFloat($("#calc-rate").value) || 16300) : 1;
  const sym = cur === "IDR" ? "Rp" : "$";
  const modal = parseFloat($("#calc-asset").value) || 0;

  const pct = parseAllocPct(e.suggested_allocation_pct) ?? 10;
  const alloc = modal * (pct / 100);

  const priceUsd = Number(e.current_price) || 0;
  const price = priceUsd * rate;
  const qty = price > 0 ? alloc / price : 0;

  // Risiko/potensi dihitung dari jarak SL/TP terhadap harga (persen).
  const sl = Number(e.stop_loss_price);
  const tp = Number(e.take_profit_price);
  const risk = priceUsd > 0 && sl > 0 ? -alloc * ((priceUsd - sl) / priceUsd) : 0;
  const reward = priceUsd > 0 && tp > 0 ? alloc * ((tp - priceUsd) / priceUsd) : 0;

  const dec = cur === "IDR" ? 0 : 2;
  const money = (v) =>
    (v < 0 ? "−" : "+") +
    sym + Math.abs(v).toLocaleString("id-ID", { maximumFractionDigits: dec });

  $("#calc-pct").textContent = `${pct}%`;
  $("#calc-alloc").textContent = `${sym}${alloc.toLocaleString("id-ID", { maximumFractionDigits: dec })}`;
  $("#calc-qty").textContent = qty.toLocaleString("id-ID", { maximumFractionDigits: qty >= 1 ? 4 : 8 });
  $("#calc-risk").textContent = money(risk);
  $("#calc-reward").textContent = money(reward);
}

/* ---------------- Portofolio: jurnal posisi pribadi ---------------- */

const PF_FIELDS = ["pf-coin", "pf-buy-price", "pf-amount", "pf-notes"];

function openPfModal(prefillCoin = "") {
  $("#pf-modal").classList.remove("hidden");
  if (prefillCoin) $("#pf-coin").value = prefillCoin;
  $("#pf-coin").focus();
}

function closePfModal() {
  $("#pf-modal").classList.add("hidden");
  PF_FIELDS.forEach((id) => { $("#" + id).value = ""; });
}

async function addPosition() {
  const coinId = $("#pf-coin").value.trim();
  const buyPrice = parseFloat($("#pf-buy-price").value);
  const amount = parseFloat($("#pf-amount").value);
  const notes = $("#pf-notes").value.trim();

  if (!coinId) return toast("Nama koin wajib diisi.", "err");
  if (!(buyPrice > 0)) return toast("Harga beli harus > 0.", "err");
  if (!(amount > 0)) return toast("Jumlah beli harus > 0.", "err");

  try {
    const res = await fetch("/api/portfolio/positions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ coin_id: coinId, buy_price: buyPrice, amount, notes }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.detail || res.statusText);

    closePfModal();
    toast(`✅ Posisi ${body.position.coin_id} tercatat.`);
    await loadPortfolio();
  } catch (err) {
    toast("Gagal mencatat posisi: " + err.message, "err");
  }
}

async function deletePosition(id, label) {
  if (!confirm(`Hapus posisi ${label} TANPA mencatat PnL? (pakai ikon 🚩 untuk tutup dengan PnL)`)) return;
  try {
    const res = await fetch(`/api/portfolio/positions/${id}`, { method: "DELETE" });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
    toast(`🗑️ Posisi ${label} dihapus.`);
    await loadPortfolio();
  } catch (err) {
    toast("Gagal menghapus posisi: " + err.message, "err");
  }
}

function pfMoney(v, signed = true) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  const n = Number(v);
  return (signed ? (n < 0 ? "−" : "+") : "") +
    "$" + Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function pfStatusBadge(status) {
  const map = {
    AMAN: "badge badge-bull", DEKAT: "badge badge-hold", TERSENTUH: "badge badge-sell",
    MENUNGGU: "badge badge-neutral", TERCAPAI: "badge badge-buy",
  };
  const cls = map[status] || "badge badge-neutral";
  return `<span class="${cls}">${esc(status || "—")}</span>`;
}

function renderPortfolio(data) {
  const totals = data.totals || {};
  $("#pf-total-cost").textContent = pfMoney(totals.total_cost_usd, false);
  $("#pf-total-value").textContent = pfMoney(totals.total_value_usd, false);

  const pnlEl = $("#pf-total-pnl");
  pnlEl.textContent = totals.total_pnl_pct != null
    ? `${pfMoney(totals.total_pnl_usd)} (${totals.total_pnl_pct >= 0 ? "+" : "−"}${Math.abs(totals.total_pnl_pct).toFixed(2)}%)`
    : "—";
  pnlEl.className = `num mt-1 text-sm font-bold ${totals.total_pnl_usd == null ? "" : totals.total_pnl_usd >= 0 ? "text-bull" : "text-bear"}`;

  $("#pf-count").textContent = data.count;

  // (Phase 9) Chip portofolio di topbar — selalu terlihat tanpa buka tab.
  const chipVal = $("#pf-chip-value");
  if (chipVal) {
    chipVal.textContent = pfMoney(totals.total_value_usd ?? totals.total_cost_usd, false);
  }
  const chipPnl = $("#pf-chip-pnl");
  if (chipPnl) {
    if (totals.total_pnl_usd == null) {
      chipPnl.textContent = "";
      chipPnl.className = "num text-[11px] font-bold text-muted";
    } else {
      chipPnl.textContent = pfMoney(totals.total_pnl_usd);
      chipPnl.className = `num text-[11px] font-bold ${totals.total_pnl_usd >= 0 ? "text-bull" : "text-bear"}`;
    }
  }

  const body = $("#portfolio-body");
  if (!data.positions.length) {
    body.innerHTML = `<tr><td colspan="6" class="p-6 text-center text-muted">Belum ada posisi — klik <b>“+ Catat Posisi”</b> untuk mulai jurnal.</td></tr>`;
    return;
  }

  // Tabel kompak: Coin (jumlah di sub-baris) | Harga masuk->sekarang | PnL
  // | SL | Trailing | Aksi.
  body.innerHTML = data.positions.map((p) => {
    const pnlCls = p.floating_pnl_usd == null ? "text-muted" : p.floating_pnl_usd >= 0 ? "text-bull" : "text-bear";
    const pnlPct = p.floating_pnl_pct != null
      ? `<div class="text-[10px] ${pnlCls}">${p.floating_pnl_pct >= 0 ? "+" : "−"}${Math.abs(p.floating_pnl_pct).toFixed(2)}%</div>`
      : "";
    const label = `${p.symbol || p.coin_id}`;
    const amt = Number(p.amount).toLocaleString("id-ID", { maximumFractionDigits: 8 });
    const now = p.current_price != null ? `$${fmtPrice(p.current_price)}` : "—";
    return `<tr class="wl-row" data-coin="${esc(p.coin_id)}">
      <td><div class="flex items-center gap-2.5">${coinIcon(p.symbol)}<div class="min-w-0"><div class="truncate font-semibold">${esc(p.name)}</div><div class="text-[10px] uppercase text-muted">${amt} ${esc(p.symbol)}${p.notes ? " • " + esc(p.notes) : ""}</div></div></div></td>
      <td class="num">
        <div>$${fmtPrice(p.buy_price)}</div>
        <div class="text-[11px] text-cyan">${now}</div>
        ${p.error ? `<div class="text-[9.5px] text-bear">data error</div>` : ""}
      </td>
      <td class="text-right"><div class="num font-bold ${pnlCls}">${pfMoney(p.floating_pnl_usd)}</div>${pnlPct}</td>
      <td class="text-center">${pfStatusBadge(p.sl_status)}</td>
      <td class="text-center">${pfStatusBadge(p.trailing_stop_status)}</td>
      <td class="text-center" style="white-space:nowrap;"><span class="pf-act close" data-close="${esc(p.id)}" data-label="${esc(label)}" title="Tutup posisi & catat realized PnL"><i class="fa-solid fa-flag-checkered"></i></span><span class="pf-act del" data-del="${esc(p.id)}" data-label="${esc(label)}" title="Hapus posisi tanpa mencatat PnL"><i class="fa-solid fa-trash-can"></i></span></td>
    </tr>`;
  }).join("");

  body.querySelectorAll("[data-close]").forEach((el) =>
    el.addEventListener("click", (ev) => {
      ev.stopPropagation();
      openCloseModal(el.dataset.close, el.dataset.label);
    })
  );
  body.querySelectorAll("[data-del]").forEach((el) =>
    el.addEventListener("click", (ev) => {
      ev.stopPropagation();
      deletePosition(el.dataset.del, el.dataset.label);
    })
  );
}

async function loadPortfolio() {
  try {
    const [active, summary] = await Promise.all([
      api("/api/portfolio/positions"),
      api("/api/portfolio/summary"),
    ]);
    renderPortfolio(active);
    renderClosedTrades(summary);
    checkPortfolioAlerts(active.positions || []);
  } catch (err) {
    console.warn("portfolio:", err.message);
    $("#portfolio-body").innerHTML = `<tr><td colspan="6" class="p-6 text-center text-bear">Gagal memuat portofolio: ${esc(err.message)}</td></tr>`;
  }
}

/* ============ Phase 9: Candle Chart, Uji Strategi, Alert, Equity ============ */

/* --------- Jenis series chart: candlestick (klines) / area (CoinGecko) --------- */

function setMainSeries(type) {
  ensureChart();
  if (state.seriesType === type && state.series.main) return state.series.main;
  if (state.series.main) {
    try { state.chart.removeSeries(state.series.main); } catch (_) {}
  }
  if (type === "candles") {
    state.series.main = state.chart.addCandlestickSeries({
      upColor: "#00E599",
      downColor: "#FF3B69",
      borderVisible: false,
      wickUpColor: "rgba(0,229,153,0.6)",
      wickDownColor: "rgba(255,59,105,0.6)",
      priceFormat: { type: "price", precision: 2, minMove: 0.01 },
    });
  } else {
    state.series.main = state.chart.addAreaSeries({
      lineColor: "#00D8FF",
      lineWidth: 2,
      topColor: "rgba(0,216,255,0.35)",
      bottomColor: "rgba(0,216,255,0.02)",
      priceLineColor: "#00D8FF",
      priceFormat: { type: "price", precision: 2, minMove: 0.01 },
    });
  }
  state.seriesType = type;
  state.priceLines = {}; // garis lama menempel di series lama -> buang ref
  return state.series.main;
}

function renderCandles(payload) {
  const series = setMainSeries("candles");
  const bars = payload.bars || [];
  series.setData(bars.map((b) => ({
    time: b.time, open: b.open, high: b.high, low: b.low, close: b.close,
  })));
  state.series.vol.setData(bars.map((b) => ({
    time: b.time,
    value: b.volume,
    color: b.close >= b.open ? "rgba(0,229,153,0.28)" : "rgba(255,59,105,0.28)",
  })));
  state.chart.timeScale().fitContent();
  const last = bars[bars.length - 1];
  state.lastBar = last
    ? { time: last.time, open: last.open, high: last.high, low: last.low, close: last.close }
    : null;
}

async function fetchAndRenderChart(coinId) {
  const cfg = TF_CONFIG[state.tf] || TF_CONFIG["90D"];
  if (cfg.src === "binance") {
    try {
      const k = await api(
        `/api/crypto/${coinId}/klines?interval=${cfg.interval}&limit=${cfg.limit}`
      );
      if (k && k.bars && k.bars.length) {
        renderCandles(k);
        return;
      }
    } catch (_) { /* fallback CoinGecko di bawah */ }
  }
  const history = await api(`/api/crypto/${coinId}/history?days=${cfg.days || 90}`);
  renderChart(history);
}

/* --------- Live ticking bar terakhir (candle OHLC / titik area) --------- */

function tickLastBar(newPrice) {
  if (!state.series.main || !state.lastBar || Number.isNaN(newPrice)) return;
  try {
    if (state.seriesType === "candles") {
      const bar = {
        time: state.lastBar.time,
        open: state.lastBar.open,
        high: Math.max(state.lastBar.high, newPrice),
        low: Math.min(state.lastBar.low, newPrice),
        close: newPrice,
      };
      state.series.main.update(bar);
      state.lastBar = bar;
    } else {
      state.series.main.update({ time: state.lastBar.time, value: newPrice });
      state.lastBar = { time: state.lastBar.time, value: newPrice };
    }
  } catch (_) {}
}

/* --------- Garis SL / TP / Trailing di chart --------- */

function updatePriceLines() {
  if (!state.series.main) return;
  for (const ref of Object.values(state.priceLines || {})) {
    try { state.series.main.removePriceLine(ref); } catch (_) {}
  }
  state.priceLines = {};
  const e = state.exec;
  if (!e) return;
  const add = (price, color, title, style) => {
    // Trailing berupa kalimat ("Trigger saat harga >= 85493.51 (+1.6%…)")
    // — ambil ANGKA PERTAMA dari teks; angka polos ikut terbaca.
    const m = String(price ?? "").match(/\d+(?:\.\d+)?/);
    const p = m ? parseFloat(m[0]) : NaN;
    if (!(p > 0)) return;
    try {
      state.priceLines[title] = state.series.main.createPriceLine({
        price: p, color, lineWidth: 1, lineStyle: style,
        axisLabelVisible: true, title,
      });
    } catch (_) {}
  };
  add(e.stop_loss_price, "#FF3B69", "SL", LightweightCharts.LineStyle.Solid);
  add(e.take_profit_price, "#00E599", "TP", LightweightCharts.LineStyle.Solid);
  add(e.trailing_stop_trigger, "#F59E0B", "Trailing", LightweightCharts.LineStyle.Dashed);
}

/* --------- Uji Strategi (backtest on-demand, mesin 29 unit test) --------- */

async function runBacktest() {
  if (!state.selected) return;
  const btn = $("#btn-backtest");
  const orig = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<i class="fa-solid fa-spinner spin"></i> Menguji…';
  try {
    renderBacktest(await api(`/api/backtest/${state.selected}?days=365`));
  } catch (err) {
    toast("Backtest gagal: " + err.message, "err");
  } finally {
    btn.disabled = false;
    btn.innerHTML = orig;
  }
}

function renderBacktest(r) {
  const m = r.metrics || {};
  const panel = $("#bt-panel");
  panel.classList.remove("hidden");
  const pct = (v) => v == null ? "—" : `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(2)}%`;
  const n = (v) => (v == null ? "—" : v);
  const retCls = (m.total_return_pct ?? 0) >= 0 ? "text-bull" : "text-bear";
  const beat = (m.excess_return_pct ?? 0) >= 0;
  panel.innerHTML = `
    <div class="bt-grid">
      <div class="level-box"><div class="lbl">Return 365 Hari</div><div class="val num ${retCls}">${pct(m.total_return_pct)}</div><div class="sub">buy &amp; hold ${pct(m.buy_hold_return_pct)}</div></div>
      <div class="level-box"><div class="lbl">Win Rate</div><div class="val num text-cyan">${m.win_rate_pct == null ? "—" : m.win_rate_pct + "%"}</div><div class="sub">${n(m.n_trades_closed)} trade tertutup</div></div>
      <div class="level-box level-sl"><div class="lbl">Max Drawdown</div><div class="val num text-bear">−${Number(m.max_drawdown_pct ?? 0).toFixed(2)}%</div><div class="sub">sharpe ${n(m.sharpe)}</div></div>
      <div class="level-box"><div class="lbl">Exit SL / Trail / TP</div><div class="val num">${n(m.n_atr_stop_loss_triggered)} / ${n(m.n_trailing_stop_triggered)} / ${n(m.n_take_profit_triggered)}</div><div class="sub">avg ${pct(m.avg_trade_pct)} / trade</div></div>
    </div>
    <div class="mt-2 text-[10px] leading-snug text-muted">
      ${esc(r.strategy)} • fee ${r.fee_pct_per_side}%/sisi • ${r.start_date} → ${r.end_date} •
      excess vs buy &amp; hold <b class="${beat ? "text-bull" : "text-bear"}">${pct(m.excess_return_pct)}</b>
      — statistik historis, bukan jaminan masa depan.
    </div>`;
}

/* --------- Alert harga custom (sekali tembak, live ~5 detik) --------- */

async function openAlertModal() {
  $("#alert-modal").classList.remove("hidden");
  $("#al-coin").value = state.selected || "";
  await refreshAlertList();
}

function closeAlertModal() {
  $("#alert-modal").classList.add("hidden");
}

async function refreshAlertList() {
  const list = $("#al-list");
  if (!list) return;
  try {
    const d = await api("/api/alerts/price");
    const items = [...(d.active || []), ...(d.triggered || [])];
    if (!items.length) {
      list.innerHTML = `<div class="p-4 text-center text-[11.5px] text-muted">Belum ada aturan — contoh: <b class="text-cyan">BTC ≥ $90.000</b> memberi kabar saat harga menyentuh.</div>`;
      return;
    }
    list.innerHTML = items.map((a) => {
      const arrow = a.direction === "ABOVE" ? "≥" : "≤";
      const done = !a.active;
      const meta = done
        ? `terpicu ${new Date(a.triggered_at).toLocaleString("id-ID", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })} @ $${fmtPrice(a.trigger_price)}`
        : `aktif • sejak ${new Date(a.created_at).toLocaleDateString("id-ID", { day: "2-digit", month: "2-digit" })}`;
      return `<div class="al-row ${done ? "al-done" : ""}">
        <div class="min-w-0">
          <div class="truncate text-[12.5px] font-semibold">${esc(a.coin_id.toUpperCase())} ${arrow} $${fmtPrice(a.target_price)}${done ? ` <span class="badge badge-bull" style="padding:1px 6px;font-size:9px;">TERPICU</span>` : ""}</div>
          <div class="text-[10px] text-muted">${meta}</div>
        </div>
        <span class="pf-act del" data-al-del="${esc(a.id)}" title="Hapus aturan"><i class="fa-solid fa-trash-can"></i></span>
      </div>`;
    }).join("");
    list.querySelectorAll("[data-al-del]").forEach((el) =>
      el.addEventListener("click", async () => {
        await fetch(`/api/alerts/price/${el.dataset.alDel}`, { method: "DELETE" }).catch(() => {});
        refreshAlertList();
      })
    );
  } catch (err) {
    list.innerHTML = `<div class="p-4 text-center text-bear text-[11.5px]">Gagal memuat: ${esc(err.message)}</div>`;
  }
}

async function addPriceAlert() {
  const coinId = $("#al-coin").value.trim();
  const target = parseFloat($("#al-target").value);
  const dir = $("#al-dir").value;
  if (!coinId) return toast("Koin wajib diisi.", "err");
  if (!(target > 0)) return toast("Target harga harus > 0.", "err");
  try {
    const res = await fetch("/api/alerts/price", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ coin_id: coinId, direction: dir, target_price: target }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.detail || res.statusText);
    $("#al-target").value = "";
    toast(`🔔 Alert ${body.alert.coin_id.toUpperCase()} ${dir === "ABOVE" ? "≥" : "≤"} $${fmtPrice(target)} aktif.`);
    refreshAlertList();
  } catch (err) {
    toast("Gagal menambah alert: " + err.message, "err");
  }
}

function handleAlertTriggers(triggered) {
  for (const a of triggered) {
    const arrow = a.direction === "ABOVE" ? "≥" : "≤";
    const title = `🚨 ALERT ${String(a.coin_id).toUpperCase()}: ${arrow} $${fmtPrice(a.target_price)}`;
    const body = `Terkirim pada harga live $${fmtPrice(a.trigger_price)}`;
    fireNotif(title, body, `alert-${a.id}`);
    toast(`${title} — ${body}`);
  }
  if (!$("#alert-modal").classList.contains("hidden")) refreshAlertList();
}

/* --------- Equity curve realized PnL + ekspor CSV --------- */

function renderEquityChart(trades) {
  const el = $("#equity-chart");
  if (!el || !el.clientWidth) return; // panel tersembunyi -> render saat tampil

  if (!state.equityChart) {
    state.equityChart = LightweightCharts.createChart(el, {
      width: el.clientWidth,
      height: 120,
      layout: {
        background: { type: "solid", color: "#0B0E14" },
        textColor: "#8A94A8",
        fontFamily: "Inter, sans-serif",
      },
      grid: {
        vertLines: { color: "rgba(38,50,74,0.25)" },
        horzLines: { color: "rgba(38,50,74,0.25)" },
      },
      rightPriceScale: { borderColor: "#26324A" },
      timeScale: { borderColor: "#26324A" },
      handleScroll: false,
      handleScale: false,
    });
    state.equitySeries = state.equityChart.addAreaSeries({
      lineColor: "#00D8FF",
      lineWidth: 2,
      topColor: "rgba(0,216,255,0.28)",
      bottomColor: "rgba(0,216,255,0.02)",
      priceFormat: { type: "price", precision: 0, minMove: 1 },
    });
    new ResizeObserver(() =>
      state.equityChart.applyOptions({ width: el.clientWidth })
    ).observe(el);
  } else {
    state.equityChart.applyOptions({ width: el.clientWidth });
  }

  const asc = [...(trades || [])]
    .filter((t) => t.closed_at && t.realized_pnl_usd != null)
    .sort((a, b) => new Date(a.closed_at) - new Date(b.closed_at));
  if (!asc.length) {
    state.equitySeries.setData([]);
    return;
  }

  let cum = 0;
  const byTime = new Map();
  for (const t of asc) {
    cum += Number(t.realized_pnl_usd) || 0;
    byTime.set(
      Math.floor(new Date(t.closed_at).getTime() / 1000),
      Math.round(cum * 100) / 100
    );
  }
  state.equitySeries.setData(
    [...byTime.entries()]
      .map(([time, value]) => ({ time, value }))
      .sort((a, b) => a.time - b.time)
  );
}

function exportTradesCsv() {
  const trades = state.lastClosed || [];
  if (!trades.length) return toast("Belum ada trade untuk diekspor.", "err");
  const cols = [
    "coin_id", "name", "symbol", "buy_price", "amount", "opened_at",
    "exit_price", "exit_reason", "realized_pnl_usd", "realized_pnl_pct", "closed_at",
  ];
  const q = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const csv = [
    cols.join(","),
    ...trades.map((t) => cols.map((c) => q(t[c])).join(",")),
  ].join("\r\n");
  const blob = new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `recy-trades-${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
  toast(`⬇️ ${trades.length} trade diekspor ke CSV.`);
}

/* ============ Phase 8: Jurnal Trade Selesai + Notifikasi Desktop ============ */

let closeTarget = null;

function openCloseModal(id, label) {
  closeTarget = { id, label };
  $("#close-label").innerHTML =
    `<b class="text-cyan">${esc(label)}</b> — harga keluar default = harga live saat ini; realized PnL langsung tercatat di <b>Riwayat Trade Selesai</b>.`;
  $("#close-price").value = "";
  $("#close-reason").value = "MANUAL";
  $("#close-modal").classList.remove("hidden");
}

function closeCloseModal() {
  $("#close-modal").classList.add("hidden");
  closeTarget = null;
}

async function confirmClosePosition() {
  if (!closeTarget) return;
  const raw = $("#close-price").value.trim();
  const price = raw ? parseFloat(raw) : null;
  if (raw && !(price > 0)) return toast("Harga keluar harus > 0.", "err");

  try {
    const res = await fetch(`/api/portfolio/positions/${closeTarget.id}/close`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ exit_price: price, exit_reason: $("#close-reason").value }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.detail || res.statusText);

    const t = body.trade;
    closeCloseModal();
    toast(`🏁 ${t.coin_id} ditutup: ${pfMoney(t.realized_pnl_usd)} (${t.realized_pnl_pct >= 0 ? "+" : "−"}${Math.abs(t.realized_pnl_pct).toFixed(2)}%)`);
    await loadPortfolio();
    switchPfView("pf-history-view"); // langsung tampil di tab riwayat
  } catch (err) {
    toast("Gagal menutup posisi: " + err.message, "err");
  }
}

function renderClosedTrades(s) {
  state.lastClosed = s.closed_positions || [];
  const pnl = Number(s.total_realized_pnl_usd ?? 0);
  const pnlEl = $("#pf-realized-pnl");
  pnlEl.textContent = pfMoney(pnl);
  pnlEl.className = `val num ${pnl >= 0 ? "text-bull" : "text-bear"}`;

  const total = Number(s.total_closed_trades || 0);
  $("#pf-winrate").textContent = total
    ? `${s.win_rate_pct}% (${s.win_count} Win / ${s.loss_count} Loss)`
    : "—";

  const body = $("#pf-history-body");
  const trades = s.closed_positions || [];
  if (!trades.length) {
    body.innerHTML = `<tr><td colspan="6" class="p-6 text-center text-muted">Belum ada trade selesai — tutup posisi dari tab <b>Posisi Aktif</b> (ikon 🚩).</td></tr>`;
    return;
  }

  const fmtDate = (iso) => iso
    ? new Date(iso).toLocaleDateString("id-ID", { day: "2-digit", month: "2-digit", year: "2-digit" })
    : "—";

  body.innerHTML = trades.map((t) => {
    const realized = Number(t.realized_pnl_usd);
    const cls = realized >= 0 ? "text-bull" : "text-bear";
    const reasonCls = t.exit_reason === "TP" ? "reason-tp" : t.exit_reason === "SL" ? "reason-sl" : "reason-manual";
    const amt = Number(t.amount).toLocaleString("id-ID", { maximumFractionDigits: 8 });
    return `<tr class="wl-row" data-coin="${esc(t.coin_id)}">
      <td><div class="flex items-center gap-2.5">${coinIcon(t.symbol)}<div class="min-w-0"><div class="truncate font-semibold">${esc(t.name)}<span class="reason-tag ${reasonCls}">${esc(t.exit_reason)}</span></div><div class="text-[10px] uppercase text-muted">${amt} ${esc(t.symbol)}</div></div></div></td>
      <td class="hist-date">${fmtDate(t.opened_at)}</td>
      <td class="num text-right">$${fmtPrice(t.buy_price)}</td>
      <td class="hist-date">${fmtDate(t.closed_at)}</td>
      <td class="num text-right">$${fmtPrice(t.exit_price)}</td>
      <td class="text-right"><div class="num font-bold ${cls}">${pfMoney(realized)}</div><div class="text-[10px] ${cls}">${realized >= 0 ? "+" : "−"}${Math.abs(Number(t.realized_pnl_pct)).toFixed(2)}%</div></td>
    </tr>`;
  }).join("");

  body.querySelectorAll(".wl-row").forEach((row) =>
    row.addEventListener("click", () => selectCoin(row.dataset.coin))
  );

  renderEquityChart(state.lastClosed);
}

function switchPfView(viewId) {
  document.querySelectorAll(".pf-subtab").forEach((b) =>
    b.classList.toggle("active", b.dataset.view === viewId)
  );
  document.querySelectorAll(".pf-view").forEach((v) =>
    v.classList.toggle("hidden", v.id !== viewId)
  );
  if (viewId === "pf-history-view") renderEquityChart(state.lastClosed);
}

/* --------- Notifikasi desktop native (Web Notification API) --------- */

const LS_NOTIF = "recy.notif.desktop";

function notifPref() {
  try { return localStorage.getItem(LS_NOTIF) === "1"; } catch (_) { return false; }
}

function setNotifPref(on) {
  try { localStorage.setItem(LS_NOTIF, on ? "1" : "0"); } catch (_) {}
}

function updateNotifBtn() {
  const btn = $("#btn-notif");
  if (!btn) return;
  const supported = "Notification" in window;
  const perm = supported ? Notification.permission : "unsupported";
  const active = supported && perm === "granted" && notifPref();
  btn.classList.toggle("active", active);
  btn.classList.toggle("denied", perm === "denied");
  const label = $("#notif-state");
  if (label) {
    label.textContent = !supported
      ? "N/A"
      : perm === "denied" ? "Diblokir" : active ? "Aktif" : "Nonaktif";
  }
}

function fireNotif(title, body, tag = "") {
  if (!("Notification" in window)) return;
  if (Notification.permission !== "granted" || !notifPref()) return;
  try {
    const n = new Notification(title, { body, tag });
    n.onclick = () => { window.focus(); n.close(); };
  } catch (_) {}
}

async function toggleNotif() {
  if (!("Notification" in window)) {
    return toast("Browser ini tidak mendukung Notification API.", "err");
  }

  // Sudah aktif -> matikan (toggle).
  if (notifPref() && Notification.permission === "granted") {
    setNotifPref(false);
    updateNotifBtn();
    return toast("Notifikasi desktop dimatikan.");
  }

  let perm = Notification.permission;
  if (perm === "default") perm = await Notification.requestPermission();

  if (perm !== "granted") {
    updateNotifBtn();
    return toast("Izin notifikasi ditolak — izinkan lewat ikon gembok address bar.", "err");
  }

  setNotifPref(true);
  updateNotifBtn();
  // Pop-up uji coba langsung muncul di layar PC.
  fireNotif(
    "🔔 Notifikasi Recy Aktif",
    "Pop-up uji coba: sinyal BUY & peringatan Stop-Loss akan muncul di sini.",
    "recy-test"
  );
  toast("✅ Notifikasi desktop AKTIF — pop-up uji coba dikirim.");
}

/* Deteksi transisi sinyal -> BUY (baseline pertama kali tdk dinotifikasi). */
function checkBuySignal(c) {
  if (!c || c.error || !c.recommendation) return;
  const prev = state.prevRec[c.coin_id];
  state.prevRec[c.coin_id] = c.recommendation;
  if (prev && prev !== "BUY" && c.recommendation === "BUY") {
    fireNotif(
      `🚨 Sinyal BUY: ${c.name} (${c.symbol || c.coin_id})`,
      `Harga saat ini: $${fmtPrice(c.price)} | Target TP: $${fmtPrice(c.tp_price)} | Stop-Loss: $${fmtPrice(c.sl_price)}`,
      `buy-${c.coin_id}`
    );
  }
}

/* Peringatan portofolio: SL/Trailing mendekati / tersentuh (dedupe per posisi). */
function checkPortfolioAlerts(positions) {
  const ids = new Set(positions.map((p) => p.id));
  for (const k of Object.keys(state.notifFired)) {
    if (!ids.has(k)) delete state.notifFired[k];
  }

  for (const p of positions) {
    if (p.error) continue;
    const touched = p.sl_status === "TERSENTUH" || p.trailing_stop_status === "TERCAPAI";
    const near = p.sl_status === "DEKAT";
    const key = touched ? "HIT" : near ? "NEAR" : "";
    const prev = state.notifFired[p.id] || "";
    if (key && key !== prev) {
      const title = touched
        ? `⛔ ${p.symbol || p.coin_id}: Stop-Loss / Trailing TERVERSENTUH`
        : `⚠️ ${p.symbol || p.coin_id}: Mendekati Stop-Loss`;
      fireNotif(
        title,
        `Harga: $${fmtPrice(p.current_price)} | SL: $${fmtPrice(p.sl_price)} | Trailing trigger: ${p.trailing_trigger_price != null ? "$" + fmtPrice(p.trailing_trigger_price) : "—"}`,
        `risk-${p.id}`
      );
    }
    if (key) state.notifFired[p.id] = key;
    else delete state.notifFired[p.id];
  }
}

/* ---------------- Selection & detail loading ---------------- */

/* --------- Header koin terpilih + live price polling (Phase 7) --------- */

function setCoinHeader(c) {
  if (!c) return;
  $("#d-name").textContent = c.name || "—";
  $("#d-symbol").textContent = c.symbol || "—";

  const iconUrl = `https://cdn.jsdelivr.net/gh/spothq/cryptocurrency-icons@master/128/color/${String(c.symbol || "").toLowerCase()}.png`;
  const icon = $("#d-icon");
  if (icon.getAttribute("src") !== iconUrl) icon.src = iconUrl;
  icon.style.visibility = "visible";

  $("#d-price").textContent = `$${fmtPrice(c.price)}`;
  $("#d-signal-line").innerHTML = `${TREND_BADGE[c.trend] || ""} ${REC_BADGE[c.recommendation] || ""}`;

  // %24 jam (Binance)
  const chEl = $("#d-change24h");
  const hasCh = c.change_24h_pct != null && !Number.isNaN(Number(c.change_24h_pct));
  if (hasCh) {
    const ch = Number(c.change_24h_pct);
    chEl.textContent = `${ch >= 0 ? "+" : "−"}${Math.abs(ch).toFixed(2)}%`;
    chEl.className = `num text-sm font-bold ${ch >= 0 ? "text-bull" : "text-bear"}`;
  } else {
    chEl.textContent = "—";
    chEl.className = "num text-sm font-bold text-muted";
  }

  // Sumber harga: WebSocket Binance vs REST vs fallback CoinGecko
  const srcEl = $("#d-source");
  if (c.price_source === "binance_ws") {
    srcEl.textContent = "live • binance ws";
    srcEl.className = "text-cyan font-semibold";
  } else if (c.price_source === "binance") {
    srcEl.textContent = "live • binance rest";
    srcEl.className = "text-bull";
  } else {
    srcEl.textContent = "coingecko • fallback";
    srcEl.className = "text-amber";
  }
}

function patchDetailLive(c) {
  if (!c || c.error || !state.selected || c.coin_id !== state.selected) return;
  setCoinHeader(c);

  // Kartu Execution: level SL/TP/trailing ikut bergerak dengan harga live,
  // kalkulator dihitung ulang dari harga terbaru.
  if (state.exec) {
    state.exec.current_price = c.price;
    if (c.sl_price != null) state.exec.stop_loss_price = c.sl_price;
    if (c.tp_price != null) state.exec.take_profit_price = c.tp_price;
    if (c.trailing_stop_trigger != null) state.exec.trailing_stop_trigger = c.trailing_stop_trigger;
    const slEl = $("#p-sl");
    if (slEl) slEl.textContent = `$${fmtPrice(c.sl_price)}`;
    const tpEl = $("#p-tp");
    if (tpEl) tpEl.textContent = `$${fmtPrice(c.tp_price)}`;
    const trEl = $("#p-trailing");
    if (trEl && c.trailing_stop_trigger) trEl.textContent = c.trailing_stop_trigger;
    updateCalculator();
    updatePriceLines();
  }

  // (Phase 8/9) Live ticking grafik — juga dari jalur HTTP polling
  // fallback agar grafik ikut bergerak walau WebSocket offline.
  if (c.price != null) tickLastBar(Number(c.price));
}

function applyLiveItems(items) {
  const byId = new Map(items.map((c) => [c.coin_id, c]));

  // 1. Perbarui state (sumber kebenaran untuk render berikutnya).
  for (const c of state.coins) {
    const lp = byId.get(c.coin_id);
    if (!lp || lp.error) continue;
    for (const key of [
      "price", "price_source", "sl_price", "tp_price",
      "trailing_stop_trigger", "risk_reward_ratio",
      "suggested_allocation_pct", "trend", "recommendation",
      "change_24h_pct", "adx_14",
    ]) {
      if (lp[key] != null) c[key] = lp[key];
    }
  }

  // 2. Patch sel tabel watchlist tanpa re-render penuh (tanpa kedip).
  document.querySelectorAll("#watchlist-body tr[data-coin]").forEach((tr) => {
    const c = state.coins.find((x) => x.coin_id === tr.dataset.coin);
    if (!c) return;
    const price = tr.querySelector(".cell-price");
    if (price) price.innerHTML = `$${fmtPrice(c.price)}${c.error ? `<div class="text-[9.5px] text-bear">error</div>` : ""}`;
    const sl = tr.querySelector(".cell-sl");
    if (sl) sl.textContent = `$${fmtPrice(c.sl_price)}`;
    const tp = tr.querySelector(".cell-tp");
    if (tp) tp.textContent = `$${fmtPrice(c.tp_price)}`;
    const sig = tr.querySelector(".cell-signal");
    if (sig) sig.innerHTML = REC_BADGE[c.recommendation] || `<span class="badge badge-neutral">${esc(c.recommendation || "—")}</span>`;
  });

  // 3. Header koin terpilih + kartu execution (bila koin tsb dipilih).
  const sel = state.coins.find((c) => c.coin_id === state.selected);
  if (sel) patchDetailLive(sel);

  // (Phase 8) Cek transisi sinyal -> BUY utk notifikasi desktop.
  state.coins.forEach(checkBuySignal);
}

/* ==================== Binance WebSocket Integration ==================== */

function fallbackToHttpPolling() {
  const dot = $("#ws-dot");
  const text = $("#ws-text");
  if (dot) dot.className = "live-dot ws-offline";
  if (text) text.textContent = "Live Stream Offline (HTTP Fallback)";
  if (!state.timers.live) {
    state.timers.live = setInterval(pollLivePrices, POLL_LIVE_MS);
    pollLivePrices();
  }
}

function scheduleWsReconnect() {
  clearTimeout(wsReconnectTimer);
  wsReconnectTimer = setTimeout(() => {
    initBinanceWebSocket();
  }, 3500);
}

function handleWsTickerBatch(tickers) {
  if (!Array.isArray(tickers) || !state.coins.length) return;
  const tickerMap = new Map();
  for (const t of tickers) {
    if (t && t.s) tickerMap.set(t.s, t);
  }

  let updatedCount = 0;
  for (const c of state.coins) {
    const sym = BINANCE_SYMBOLS[c.coin_id] || (c.symbol ? `${c.symbol.toUpperCase()}USDT` : null);
    if (!sym || !tickerMap.has(sym)) continue;

    const t = tickerMap.get(sym);
    const newPrice = Number(t.c);
    const openPrice = Number(t.o);
    if (Number.isNaN(newPrice)) continue;

    const prevPrice = c.price != null ? Number(c.price) : null;
    const movedUp = prevPrice != null && newPrice > prevPrice;
    const movedDown = prevPrice != null && newPrice < prevPrice;

    c.price = newPrice;
    if (openPrice > 0) {
      c.change_24h_pct = ((newPrice - openPrice) / openPrice) * 100;
    }
    c.price_source = "binance_ws";
    updatedCount++;

    // Update baris DOM watchlist secara langsung
    const tr = document.querySelector(`#watchlist-body tr[data-coin="${c.coin_id}"]`);
    if (tr) {
      const priceEl = tr.querySelector(".cell-price");
      if (priceEl) {
        priceEl.innerHTML = `$${fmtPrice(newPrice)}${c.error ? `<div class="text-[9.5px] text-bear">error</div>` : ""}`;
        if (movedUp) {
          priceEl.classList.remove("price-flash-down");
          priceEl.classList.add("price-flash-up");
          setTimeout(() => priceEl.classList.remove("price-flash-up"), 600);
        } else if (movedDown) {
          priceEl.classList.remove("price-flash-up");
          priceEl.classList.add("price-flash-down");
          setTimeout(() => priceEl.classList.remove("price-flash-down"), 600);
        }
      }
    }

    // Bila koin ini sedang dipilih, perbarui header & kartu eksekusi
    if (state.selected && c.coin_id === state.selected) {
      // (Phase 8/9) Live chart ticking — bar terakhir (candle OHLC atau
      // titik area) langsung bergerak mengikuti tick harga Binance.
      tickLastBar(newPrice);
      patchDetailLive(c);
      const dPrice = $("#d-price");
      if (dPrice) {
        if (movedUp) {
          dPrice.classList.remove("price-flash-down");
          dPrice.classList.add("price-flash-up");
          setTimeout(() => dPrice.classList.remove("price-flash-up"), 600);
        } else if (movedDown) {
          dPrice.classList.remove("price-flash-up");
          dPrice.classList.add("price-flash-down");
          setTimeout(() => dPrice.classList.remove("price-flash-down"), 600);
        }
      }
    }
  }

  if (updatedCount > 0) {
    const el = $("#wl-updated");
    if (el) el.textContent = `ws live ${new Date().toLocaleTimeString("id-ID")}`;
  }
}

function initBinanceWebSocket() {
  if (binanceWs) {
    try { binanceWs.close(); } catch (_) {}
    binanceWs = null;
  }

  const url = BINANCE_WS_URLS[wsUrlIdx];
  const dot = $("#ws-dot");
  const text = $("#ws-text");

  try {
    binanceWs = new WebSocket(url);
  } catch (err) {
    console.warn("[WS] Init failed:", err);
    fallbackToHttpPolling();
    scheduleWsReconnect();
    return;
  }

  binanceWs.onopen = () => {
    wsActive = true;
    clearTimeout(wsReconnectTimer);
    if (dot) {
      dot.className = "live-dot ws-live";
    }
    if (text) {
      text.textContent = "Binance WS Stream Live (Sub-detik)";
    }
    // Hentikan polling HTTP cepat agar zero-load ke server
    if (state.timers.live) {
      clearInterval(state.timers.live);
      state.timers.live = null;
    }
  };

  binanceWs.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      handleWsTickerBatch(data);
    } catch (err) {
      console.warn("[WS] Parse error:", err);
    }
  };

  binanceWs.onerror = (err) => {
    console.warn("[WS] Error encountered, switching host:", err);
    wsUrlIdx = (wsUrlIdx + 1) % BINANCE_WS_URLS.length;
    fallbackToHttpPolling();
  };

  binanceWs.onclose = () => {
    wsActive = false;
    fallbackToHttpPolling();
    scheduleWsReconnect();
  };
}

async function pollLivePrices() {
  try {
    const data = await api(`/api/crypto/live-prices?coins=${encodeURIComponent(watchParams())}`);
    // (Phase 9) Alert harga yang baru terpicu -> notifikasi desktop + toast.
    if (data.alerts_triggered && data.alerts_triggered.length) {
      handleAlertTriggers(data.alerts_triggered);
    }
    const items = data.coins || [];
    if (!items.length) return;
    applyLiveItems(items);
    $("#wl-updated").textContent = `live ${new Date().toLocaleTimeString("id-ID")}`;
  } catch (err) {
    console.warn("live-prices:", err.message);
  }
}

/* (Phase 9) Polling alert harga INDEPENDEN — tetap jalan walau WebSocket
   aktif menahan polling harga (endpoint ringan: batch Binance cache 5 dtk). */
async function pollAlerts() {
  try {
    const d = await api(`/api/alerts/price/check?coins=${encodeURIComponent(watchParams())}`);
    if (d.alerts_triggered && d.alerts_triggered.length) {
      handleAlertTriggers(d.alerts_triggered);
    }
  } catch (err) {
    console.warn("alerts:", err.message); // alert bersifat opsional
  }
}

async function selectCoin(coinId) {
  if (!coinId) return;
  state.selected = coinId;
  renderWatchlist(); // highlight baris
  $("#bt-panel")?.classList.add("hidden"); // hasil backtest per-koin

  $("#detail-empty").classList.add("hidden");
  const detail = $("#detail");
  detail.classList.remove("hidden");
  detail.classList.add("fade-up");

  // Instant feedback dari data watchlist yang sudah di tangan.
  const row = state.coins.find((c) => c.coin_id === coinId);
  if (row) {
    setCoinHeader(row);
    renderExecution(null, row);
  }

  await loadDetail(coinId, { withAnalysis: true });
}

async function loadDetail(coinId, { withAnalysis = false } = {}) {
  if (state.loadingDetail) return;
  if (state.selected !== coinId) return; // pilihan sudah berganti
  state.loadingDetail = true;

  try {
    const jobs = [
      fetchAndRenderChart(coinId),
      api(`/api/crypto/${coinId}/technical/score`),
    ];
    if (withAnalysis) jobs.push(api(`/api/crypto/${coinId}/analysis`));

    const results = await Promise.allSettled(jobs);
    if (state.selected !== coinId) return; // tidak tampil lagi

    const [hist, score, analysis] = results;
    if (hist.status === "rejected") console.warn("chart:", hist.reason?.message);
    // hist (fetchAndRenderChart) sudah me-render chart di dalam promise.
    if (score.status === "fulfilled") {
      renderGauges(score.value.score, score.value.latest_data, analysis?.status === "fulfilled" ? analysis.value : null);
    }
    if (withAnalysis) {
      if (analysis.status === "fulfilled") {
        renderExecution(analysis.value, state.coins.find((c) => c.coin_id === coinId));
        renderNews(analysis.value);
      } else {
        console.warn("analysis:", analysis.reason?.message);
        renderNews(null);
      }
    } else if (analysis === undefined && score.status === "fulfilled") {
      // refresh berkala: gauges pakai sentimen dari render sebelumnya (tetap)
    }
    updatePriceLines(); // pastikan garis SL/TP melekat di series terbaru
  } finally {
    state.loadingDetail = false;
  }
}

/* ---------------- Polling & boot ---------------- */

function startPolling() {
  // 1. Hubungkan WebSocket Binance publik (sub-detik stream)
  initBinanceWebSocket();

  // 2. Polling watchlist & portofolio (status kalkulasi makro & sentimen)
  state.timers.watchlist = setInterval(() => {
    loadWatchlist();
    loadPortfolio();
    if (state.selected) loadDetail(state.selected, { withAnalysis: false });
  }, POLL_WATCHLIST_MS);

  state.timers.analysis = setInterval(() => {
    if (state.selected) loadDetail(state.selected, { withAnalysis: true });
  }, POLL_ANALYSIS_MS);

  // (Phase 9) Cek alert harga independen dari siklus polling lain.
  state.timers.alerts = setInterval(pollAlerts, POLL_ALERTS_MS);
  pollAlerts();
}

function setTimeframe(tf) {
  state.tf = tf;
  document.querySelectorAll(".tf-btn").forEach((b) =>
    b.classList.toggle("active", b.dataset.tf === tf)
  );
  if (state.selected) refreshChart();
}

async function refreshChart() {
  if (!state.selected) return;
  try {
    await fetchAndRenderChart(state.selected);
    updatePriceLines();
  } catch (err) {
    console.warn("chart:", err.message);
  }
}

function pausePolling() {
  clearInterval(state.timers.watchlist);
  clearInterval(state.timers.analysis);
  if (state.timers.live) clearInterval(state.timers.live);
  if (state.timers.alerts) clearInterval(state.timers.alerts);
  state.timers = {};
  clearTimeout(wsReconnectTimer);
  if (binanceWs) {
    try { binanceWs.close(); } catch (_) {}
    binanceWs = null;
  }
}

function resumePolling() {
  if (state.timers.watchlist) return; // sudah jalan
  startPolling();
}

async function addCoin() {
  const input = $("#input-add-coin");
  const q = input.value.trim().toLowerCase();
  if (!q) return;
  if (DEFAULT_COINS.includes(q) || state.custom.includes(q)) {
    toast(`"${q}" sudah ada di watchlist.`);
    input.value = "";
    return;
  }
  state.custom.push(q);
  saveCustomCoins();
  state.pendingAdd = q;
  input.value = "";
  await loadWatchlist(); // backend resolve nama/simbol -> coin_id
}

async function testTelegram() {
  try {
    const r = await (await fetch("/api/alerts/telegram/test", { method: "POST" })).json();
    if (r.sent) toast("✅ Tes alert terkirim ke Telegram!");
    else toast(r.detail || "Telegram gagal mengirim pesan.", r.configured ? "err" : "ok");
  } catch (err) {
    toast("Gagal memanggil endpoint Telegram: " + err.message, "err");
  }
}

function boot() {
  $("#btn-refresh").addEventListener("click", () => {
    const icon = $("#btn-refresh i");
    icon.classList.add("spin");
    Promise.all([loadWatchlist(), loadFng()]).finally(() =>
      setTimeout(() => icon.classList.remove("spin"), 600)
    );
  });

  // Tambah / hapus koin watchlist (tersimpan di localStorage).
  $("#btn-add-coin").addEventListener("click", addCoin);
  $("#input-add-coin").addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") addCoin();
  });

  // Timeframe chart (tanpa reload halaman).
  document.querySelectorAll(".tf-btn").forEach((b) =>
    b.addEventListener("click", () => setTimeframe(b.dataset.tf))
  );

  // Tab switcher kolom kiri: Watchlist <-> Portofolio.
  document.querySelectorAll(".panel-tab").forEach((b) =>
    b.addEventListener("click", () => {
      document.querySelectorAll(".panel-tab").forEach((x) =>
        x.classList.toggle("active", x === b)
      );
      $("#watchlist-panel").classList.toggle("hidden", b.dataset.panel !== "watchlist-panel");
      $("#portfolio-panel").classList.toggle("hidden", b.dataset.panel !== "portfolio-panel");
    })
  );

  // Kalkulator posisi — hitung ulang real-time.
  ["#calc-asset", "#calc-rate"].forEach((sel) =>
    $(sel).addEventListener("input", updateCalculator)
  );
  $("#calc-currency").addEventListener("change", () => {
    $("#calc-rate").classList.toggle("hidden", $("#calc-currency").value !== "IDR");
    updateCalculator();
  });

  // Telegram test.
  $("#btn-tg").addEventListener("click", testTelegram);

  // Portofolio: modal tambah & hapus posisi.
  $("#btn-add-position").addEventListener("click", () => openPfModal(state.selected || ""));
  $("#pf-modal-close").addEventListener("click", closePfModal);
  $("#pf-modal").addEventListener("click", (ev) => {
    if (ev.target === $("#pf-modal")) closePfModal();
  });
  $("#pf-save").addEventListener("click", addPosition);

  // Modal tutup posisi (realized PnL).
  $("#close-modal-cancel-x").addEventListener("click", closeCloseModal);
  $("#close-cancel").addEventListener("click", closeCloseModal);
  $("#close-confirm").addEventListener("click", confirmClosePosition);
  $("#close-modal").addEventListener("click", (ev) => {
    if (ev.target === $("#close-modal")) closeCloseModal();
  });

  // Sub-tab portofolio: Posisi Aktif <-> Riwayat Trade Selesai.
  document.querySelectorAll(".pf-subtab").forEach((b) =>
    b.addEventListener("click", () => switchPfView(b.dataset.view))
  );

  // Quick filter watchlist (scanner instan, tanpa panggil API).
  document.querySelectorAll(".chip[data-filter]").forEach((b) =>
    b.addEventListener("click", () => {
      state.filter = b.dataset.filter;
      document.querySelectorAll(".chip[data-filter]").forEach((x) =>
        x.classList.toggle("active", x === b)
      );
      renderWatchlist();
    })
  );

  // Notifikasi desktop native (Web Notification API).
  $("#btn-notif").addEventListener("click", toggleNotif);
  updateNotifBtn();

  // (Phase 9) Uji Strategi — backtest on-demand.
  $("#btn-backtest").addEventListener("click", runBacktest);

  // (Phase 9) Alert harga custom (modal).
  $("#btn-alerts").addEventListener("click", openAlertModal);
  $("#alert-modal-close").addEventListener("click", closeAlertModal);
  $("#alert-modal").addEventListener("click", (ev) => {
    if (ev.target === $("#alert-modal")) closeAlertModal();
  });
  $("#al-save").addEventListener("click", addPriceAlert);
  $("#al-target").addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") addPriceAlert();
  });

  // (Phase 9) Sortir watchlist (client-side instan).
  $("#wl-sort").addEventListener("change", () => {
    state.sort = $("#wl-sort").value;
    renderWatchlist();
  });

  // (Phase 9) Ekspor CSV jurnal trade selesai.
  $("#btn-csv").addEventListener("click", exportTradesCsv);

  // Tab visibility: jeda polling saat tersembunyi, refresh saat kembali.
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      pausePolling();
    } else {
      resumePolling();
      loadFng();
      loadWatchlist();
      loadPortfolio();
      if (state.selected) loadDetail(state.selected, { withAnalysis: true });
    }
  });

  loadFng();
  loadWatchlist();
  loadPortfolio();
  startPolling();
}

document.addEventListener("DOMContentLoaded", boot);
