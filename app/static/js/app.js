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
const POLL_LIVE_MS = 5_000;         // harga live Binance (detik per detik)

const TIMEFRAMES = { "7D": 7, "30D": 30, "90D": 90, "1Y": 365 };
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

function renderWatchlist() {
  const body = $("#watchlist-body");
  if (!state.coins.length) {
    body.innerHTML = `<tr><td colspan="6" class="p-6 text-center text-muted">Tidak ada data koin.</td></tr>`;
    return;
  }

  // Tabel kompak kolom kiri: Coin | Price (live) | Signal | SL | TP | Aksi.
  body.innerHTML = state.coins
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

  state.series.area = state.chart.addAreaSeries({
    lineColor: "#00D8FF",
    lineWidth: 2,
    topColor: "rgba(0,216,255,0.35)",
    bottomColor: "rgba(0,216,255,0.02)",
    priceLineColor: "#00D8FF",
    priceFormat: { type: "price", precision: 2, minMove: 0.01 },
  });

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
  ensureChart();
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

  state.series.area.setData(priceData);
  state.series.vol.setData(volData);
  state.chart.timeScale().fitContent();
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
  if (!confirm(`Tutup/hapus posisi ${label}?`)) return;
  try {
    const res = await fetch(`/api/portfolio/positions/${id}`, { method: "DELETE" });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
    toast(`🗑️ Posisi ${label} ditutup.`);
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
      <td class="text-center"><button class="wl-remove pf-close" data-id="${esc(p.id)}" data-label="${esc(label)}" title="Tutup posisi"><i class="fa-solid fa-trash-can"></i></button></td>
    </tr>`;
  }).join("");

  body.querySelectorAll(".pf-close").forEach((btn) =>
    btn.addEventListener("click", (ev) => {
      ev.stopPropagation();
      deletePosition(btn.dataset.id, btn.dataset.label);
    })
  );
}

async function loadPortfolio() {
  try {
    renderPortfolio(await api("/api/portfolio/positions"));
  } catch (err) {
    console.warn("portfolio:", err.message);
    $("#portfolio-body").innerHTML = `<tr><td colspan="6" class="p-6 text-center text-bear">Gagal memuat portofolio: ${esc(err.message)}</td></tr>`;
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

  // Sumber harga: live Binance vs fallback CoinGecko
  const live = c.price_source === "binance";
  const srcEl = $("#d-source");
  srcEl.textContent = live ? "live • binance" : "coingecko • fallback";
  srcEl.className = live ? "text-bull" : "text-amber";
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
  }
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
      "change_24h_pct",
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
}

async function pollLivePrices() {
  try {
    const data = await api(`/api/crypto/live-prices?coins=${encodeURIComponent(watchParams())}`);
    const items = data.coins || [];
    if (!items.length) return;
    applyLiveItems(items);
    $("#wl-updated").textContent = `live ${new Date().toLocaleTimeString("id-ID")}`;
  } catch (err) {
    console.warn("live-prices:", err.message);
  }
}

async function selectCoin(coinId) {
  if (!coinId) return;
  state.selected = coinId;
  renderWatchlist(); // highlight baris

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
      api(`/api/crypto/${coinId}/history?days=${TIMEFRAMES[state.tf] || 90}`),
      api(`/api/crypto/${coinId}/technical/score`),
    ];
    if (withAnalysis) jobs.push(api(`/api/crypto/${coinId}/analysis`));

    const results = await Promise.allSettled(jobs);
    if (state.selected !== coinId) return; // tidak tampil lagi

    const [hist, score, analysis] = results;
    if (hist.status === "fulfilled") renderChart(hist.value);
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
  } finally {
    state.loadingDetail = false;
  }
}

/* ---------------- Polling & boot ---------------- */

function startPolling() {
  // Harga live Binance + SL/TP: tiap 5 detik (endpoint ringan, cache BE 5 dtk).
  state.timers.live = setInterval(pollLivePrices, POLL_LIVE_MS);

  state.timers.watchlist = setInterval(() => {
    loadWatchlist();
    loadPortfolio();
    if (state.selected) loadDetail(state.selected, { withAnalysis: false });
  }, POLL_WATCHLIST_MS);

  state.timers.analysis = setInterval(() => {
    if (state.selected) loadDetail(state.selected, { withAnalysis: true });
  }, POLL_ANALYSIS_MS);
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
    const days = TIMEFRAMES[state.tf] || 90;
    const history = await api(`/api/crypto/${state.selected}/history?days=${days}`);
    renderChart(history);
  } catch (err) {
    console.warn("chart:", err.message);
  }
}

function pausePolling() {
  clearInterval(state.timers.watchlist);
  clearInterval(state.timers.analysis);
  clearInterval(state.timers.live);
  state.timers = {};
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
