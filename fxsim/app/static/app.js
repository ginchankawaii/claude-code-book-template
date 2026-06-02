"use strict";

const $ = (id) => document.getElementById(id);
const fmt = (n, d = 2) =>
  n === null || n === undefined || Number.isNaN(n)
    ? "–"
    : Number(n).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });

let charts = { equity: null, price: null, signal: null };

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(`${res.status}: ${txt}`);
  }
  return res.json();
}

async function loadRuns() {
  const runs = await api("/api/runs");
  const sel = $("runSelect");
  sel.innerHTML = "";
  if (!runs.length) {
    sel.innerHTML = '<option value="">（まだRunがありませんBacktestを実行してください）</option>';
    $("stats").innerHTML = "";
    return;
  }
  for (const r of runs) {
    const opt = document.createElement("option");
    opt.value = r.id;
    opt.textContent = `#${r.id} ${r.mode} ${r.instrument} ${r.granularity} — ${r.started_at?.slice(0, 16) || ""}`;
    sel.appendChild(opt);
  }
  await loadRun(runs[0].id);
}

function statCard(k, v, cls = "") {
  return `<div class="stat"><div class="k">${k}</div><div class="v ${cls}">${v}</div></div>`;
}

async function loadRun(runId) {
  if (!runId) return;
  $("runSelect").value = runId;
  const [detail, equity, trades, signals, fundamental] = await Promise.all([
    api(`/api/runs/${runId}`),
    api(`/api/runs/${runId}/equity`),
    api(`/api/runs/${runId}/trades`),
    api(`/api/runs/${runId}/signals`),
    api(`/api/fundamental`).catch(() => []),
  ]);
  const s = detail.stats;
  const run = detail.run;
  $("runMeta").textContent =
    `初期資金 ${fmt(run.initial_balance, 0)} / ${run.mode} / ${run.ended_at ? "終了" : "進行中"}`;

  const retCls = s.total_return_pct >= 0 ? "pos" : "neg";
  $("stats").innerHTML = [
    statCard("リターン", `${fmt(s.total_return_pct)}%`, retCls),
    statCard("最終資産", fmt(s.final_equity, 0)),
    statCard("取引数", s.num_trades),
    statCard("勝率", `${fmt(s.win_rate, 1)}%`),
    statCard("プロフィットファクター", fmt(s.profit_factor)),
    statCard("最大DD", `${fmt(s.max_drawdown_pct)}%`, "neg"),
    statCard("シャープ", fmt(s.sharpe)),
    statCard("平均利益/損失", `${fmt(s.avg_win, 0)} / ${fmt(s.avg_loss, 0)}`),
  ].join("");

  drawEquity(equity, run.initial_balance);
  drawPrice(equity, trades);
  drawSignals(signals);
  drawTrades(trades);
  drawFundamental(fundamental);
}

function drawEquity(equity, initial) {
  const labels = equity.map((e) => e.time.slice(5, 16).replace("T", " "));
  const ctx = $("equityChart");
  charts.equity?.destroy();
  charts.equity = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [
        { label: "Equity", data: equity.map((e) => e.equity), borderColor: "#58a6ff",
          backgroundColor: "rgba(88,166,255,.1)", fill: true, pointRadius: 0, borderWidth: 1.5 },
        { label: "Balance", data: equity.map((e) => e.balance), borderColor: "#8b949e",
          pointRadius: 0, borderWidth: 1, borderDash: [4, 4] },
        { label: "初期資金", data: equity.map(() => initial), borderColor: "#484f58",
          pointRadius: 0, borderWidth: 1, borderDash: [2, 4] },
      ],
    },
    options: baseOpts(),
  });
}

function drawPrice(equity, trades) {
  const labels = equity.map((e) => e.time.slice(5, 16).replace("T", " "));
  const timeIndex = new Map(equity.map((e, i) => [e.time.slice(0, 16), i]));
  const entries = [];
  const exits = [];
  for (const t of trades) {
    const ei = timeIndex.get((t.entry_time || "").slice(0, 16));
    if (ei !== undefined) entries.push({ x: labels[ei], y: t.entry_price, side: t.side });
    if (t.exit_time) {
      const xi = timeIndex.get((t.exit_time || "").slice(0, 16));
      if (xi !== undefined) exits.push({ x: labels[xi], y: t.exit_price });
    }
  }
  const ctx = $("priceChart");
  charts.price?.destroy();
  charts.price = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [
        { label: "Price", data: equity.map((e) => e.price), borderColor: "#d29922",
          pointRadius: 0, borderWidth: 1.5, fill: false },
        { label: "Entry", data: entries, type: "scatter",
          backgroundColor: entries.map((e) => (e.side === "LONG" ? "#3fb950" : "#f85149")),
          pointStyle: "triangle", radius: 7 },
        { label: "Exit", data: exits, type: "scatter",
          backgroundColor: "#e6edf3", pointStyle: "rectRot", radius: 5 },
      ],
    },
    options: baseOpts(),
  });
}

function drawSignals(signals) {
  const bySource = { technical: [], fundamental: [], combined: [] };
  const labels = [];
  const seen = new Set();
  for (const s of signals) {
    const lbl = s.time.slice(5, 16).replace("T", " ");
    if (s.source === "combined" && !seen.has(s.time)) { labels.push(lbl); seen.add(s.time); }
  }
  // align each source onto combined timeline
  const idx = new Map();
  let i = 0;
  for (const s of signals) if (s.source === "combined") idx.set(s.time, i++);
  const data = { technical: new Array(labels.length).fill(null),
                 fundamental: new Array(labels.length).fill(null),
                 combined: new Array(labels.length).fill(null) };
  for (const s of signals) {
    const k = idx.get(s.time);
    if (k === undefined) continue;
    if (data[s.source]) data[s.source][k] = s.score;
  }
  const ctx = $("signalChart");
  charts.signal?.destroy();
  charts.signal = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [
        { label: "統合", data: data.combined, borderColor: "#58a6ff", borderWidth: 1.5, pointRadius: 0 },
        { label: "テクニカル", data: data.technical, borderColor: "#d29922", borderWidth: 1, pointRadius: 0 },
        { label: "ファンダ", data: data.fundamental, borderColor: "#bc8cff", borderWidth: 1, pointRadius: 0 },
      ],
    },
    options: { ...baseOpts(), scales: { ...baseOpts().scales, y: { ...gridY(), min: -1, max: 1 } } },
  });
}

function drawTrades(trades) {
  const tbody = $("tradesTable").querySelector("tbody");
  tbody.innerHTML = "";
  trades.forEach((t, i) => {
    const pnl = t.pnl ?? 0;
    const cls = pnl >= 0 ? "pos" : "neg";
    const sideBadge = `<span class="badge ${t.side.toLowerCase()}">${t.side}</span>`;
    const status = t.status === "OPEN" ? " (OPEN)" : "";
    tbody.innerHTML += `<tr>
      <td>${i + 1}</td><td>${sideBadge}${status}</td><td>${fmt(t.units, 0)}</td>
      <td>${fmt(t.entry_price, 3)}</td><td>${t.exit_price ? fmt(t.exit_price, 3) : "–"}</td>
      <td class="${cls}">${t.pnl !== null ? fmt(pnl, 0) : "–"}</td>
      <td style="text-align:left">${t.reason || ""}</td>
    </tr>`;
  });
}

function drawFundamental(views) {
  const el = $("fundamental");
  if (!views.length) { el.innerHTML = '<div class="meta">見解なし</div>'; return; }
  el.innerHTML = views.map((v) => {
    const pct = (v.decayed * 50 + 50);
    const color = v.decayed >= 0 ? "#3fb950" : "#f85149";
    const left = v.decayed >= 0 ? 50 : pct;
    const width = Math.abs(v.decayed * 50);
    return `<div class="fund-item">
      <div><strong>${v.instrument}</strong>
        <span class="fund-bias" style="color:${color}">${v.decayed >= 0 ? "+" : ""}${fmt(v.decayed)}</span>
        <span class="meta">(raw ${fmt(v.bias)})</span></div>
      <div class="meta">${v.reason || ""} — ${v.asof.slice(0, 16).replace("T", " ")}</div>
      <div class="bar"><span style="left:${left}%;width:${width}%;background:${color}"></span></div>
    </div>`;
  }).join("");
}

function gridY() { return { grid: { color: "#21262d" }, ticks: { color: "#8b949e" } }; }
function baseOpts() {
  return {
    responsive: true, maintainAspectRatio: true, animation: false,
    interaction: { intersect: false, mode: "index" },
    plugins: { legend: { labels: { color: "#8b949e", boxWidth: 12 } } },
    scales: {
      x: { grid: { color: "#21262d" }, ticks: { color: "#8b949e", maxTicksLimit: 12, autoSkip: true } },
      y: gridY(),
    },
  };
}

async function runBacktest() {
  $("btStatus").textContent = "実行中 ...";
  $("btRun").disabled = true;
  try {
    const body = {
      provider: $("btProvider").value,
      instrument: $("btInstrument").value.trim(),
      granularity: $("btGran").value,
      bars: parseInt($("btBars").value, 10),
    };
    const res = await api("/api/backtest", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    $("btStatus").textContent = `完了 run #${res.run_id} (リターン ${fmt(res.stats.total_return_pct)}%)`;
    await loadRuns();
    await loadRun(res.run_id);
  } catch (e) {
    $("btStatus").textContent = `エラー: ${e.message}`;
  } finally {
    $("btRun").disabled = false;
  }
}

$("runSelect").addEventListener("change", (e) => loadRun(e.target.value));
$("refreshBtn").addEventListener("click", () => loadRuns());
$("btRun").addEventListener("click", runBacktest);
loadRuns().catch((e) => { $("btStatus").textContent = e.message; });
