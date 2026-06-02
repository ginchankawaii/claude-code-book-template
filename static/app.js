"use strict";

let selectedCode = null;
let priceChart = null;

// ---------------------------------------------------------------------------
// ユーティリティ
// ---------------------------------------------------------------------------
async function api(path, opts) {
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || `エラー (${res.status})`);
  }
  return data;
}

function jpy(n) {
  if (n === null || n === undefined) return "—";
  return "¥" + Math.round(n).toLocaleString("ja-JP");
}

function signClass(n) {
  if (n > 0) return "up";
  if (n < 0) return "down";
  return "flat";
}

function fmtPct(n) {
  if (n === null || n === undefined) return "—";
  return (n > 0 ? "+" : "") + n.toFixed(2) + "%";
}

function toast(msg, type = "") {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.className = "toast show " + type;
  setTimeout(() => (el.className = "toast " + type), 3200);
}

// ---------------------------------------------------------------------------
// データ読み込み
// ---------------------------------------------------------------------------
async function loadStatus() {
  const s = await api("/api/status");
  const advisor = s.advisor_enabled
    ? `AI判断: 有効 (${s.advisor_model})`
    : "AI判断: 無効 (ANTHROPIC_API_KEY 未設定)";
  document.getElementById("status").innerHTML =
    `データソース: <b>${s.data_source}</b> ／ ${advisor}`;
  if (!s.advisor_enabled) {
    document.getElementById("ai-one").disabled = true;
    document.getElementById("ai-all").disabled = true;
  }
}

async function loadSummary() {
  const p = await api("/api/portfolio");
  const cards = [
    { label: "総資産", value: jpy(p.total_value) },
    { label: "現金残高", value: jpy(p.cash) },
    { label: "評価額(保有)", value: jpy(p.holdings_value) },
    {
      label: "損益(対 元本)",
      value: `<span class="${signClass(p.total_pl)}">${jpy(p.total_pl)} (${fmtPct(p.total_pl_pct)})</span>`,
    },
  ];
  document.getElementById("summary").innerHTML = cards
    .map(
      (c) =>
        `<div class="card"><div class="label">${c.label}</div><div class="value">${c.value}</div></div>`
    )
    .join("");

  const tbody = document.querySelector("#holdings-table tbody");
  if (!p.holdings.length) {
    tbody.innerHTML = `<tr><td colspan="5" class="flat">保有銘柄はありません</td></tr>`;
  } else {
    tbody.innerHTML = p.holdings
      .map(
        (h) => `<tr data-code="${h.code}">
          <td>${h.name}<br><span class="flat">${h.code}</span></td>
          <td>${h.quantity.toLocaleString()}</td>
          <td>${jpy(h.avg_cost)}</td>
          <td>${jpy(h.current_price)}</td>
          <td class="${signClass(h.unrealized_pl)}">${jpy(h.unrealized_pl)}<br>${fmtPct(h.unrealized_pl_pct)}</td>
        </tr>`
      )
      .join("");
    tbody.querySelectorAll("tr[data-code]").forEach((tr) =>
      tr.addEventListener("click", () => selectCode(tr.dataset.code))
    );
  }
}

async function loadWatchlist() {
  const items = await api("/api/watchlist");
  const tbody = document.querySelector("#watchlist-table tbody");
  if (!items.length) {
    tbody.innerHTML = `<tr><td colspan="5" class="flat">銘柄を追加してください</td></tr>`;
    return;
  }
  tbody.innerHTML = items
    .map(
      (it) => `<tr data-code="${it.code}">
        <td>${it.code}</td>
        <td>${it.name || "—"}</td>
        <td>${jpy(it.price)}</td>
        <td class="${signClass(it.change)}">${fmtPct(it.change_pct)}</td>
        <td><button class="del" data-code="${it.code}">×</button></td>
      </tr>`
    )
    .join("");
  tbody.querySelectorAll("tr[data-code]").forEach((tr) =>
    tr.addEventListener("click", (e) => {
      if (e.target.classList.contains("del")) return;
      selectCode(tr.dataset.code);
    })
  );
  tbody.querySelectorAll("button.del").forEach((b) =>
    b.addEventListener("click", async (e) => {
      e.stopPropagation();
      await api(`/api/watchlist/${b.dataset.code}`, { method: "DELETE" });
      loadWatchlist();
    })
  );
  if (!selectedCode && items.length) selectCode(items[0].code);
}

async function selectCode(code) {
  selectedCode = code;
  document.getElementById("trade-code").value = code;
  const data = await api(`/api/history/${code}?days=120`);
  document.getElementById("chart-title").textContent = `${data.name} (${code})`;
  const src = data.history.length && data.history[data.history.length - 1]._mock ? "mock" : "";
  document.getElementById("chart-source").textContent = src ? "擬似データ" : "";
  renderChart(data.history);
  renderIndicators(data.indicators);
}

function renderChart(history) {
  const labels = history.map((h) => h.date);
  const closes = history.map((h) => h.close);
  const ctx = document.getElementById("price-chart");
  if (priceChart) priceChart.destroy();
  priceChart = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          data: closes,
          borderColor: "#4c8dff",
          backgroundColor: "rgba(76,141,255,0.1)",
          fill: true,
          pointRadius: 0,
          borderWidth: 2,
          tension: 0.15,
        },
      ],
    },
    options: {
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: "#8b97a7", maxTicksLimit: 6 }, grid: { display: false } },
        y: { ticks: { color: "#8b97a7" }, grid: { color: "#2c3543" } },
      },
    },
  });
}

function renderIndicators(ind) {
  if (!ind) return;
  const items = [
    ["現在値", jpy(ind.last_close)],
    ["5日線", jpy(ind.sma5)],
    ["25日線", jpy(ind.sma25)],
    ["RSI(14)", ind.rsi14 ?? "—"],
    ["5日変化", fmtPct(ind.change_5d_pct)],
    ["25日変化", fmtPct(ind.change_25d_pct)],
    ["トレンド", ind.trend],
  ];
  document.getElementById("indicators").innerHTML = items
    .map(([k, v]) => `<div class="ind"><div class="k">${k}</div><div class="v">${v}</div></div>`)
    .join("");
}

async function loadTrades() {
  const trades = await api("/api/trades?limit=100");
  const tbody = document.querySelector("#trades-table tbody");
  if (!trades.length) {
    tbody.innerHTML = `<tr><td colspan="8" class="flat">取引履歴はありません</td></tr>`;
    return;
  }
  tbody.innerHTML = trades
    .map(
      (t) => `<tr>
        <td>${t.ts.replace("T", " ").slice(0, 16)}</td>
        <td>${t.name || t.code}</td>
        <td class="${t.side === "BUY" ? "up" : "down"}">${t.side === "BUY" ? "買" : "売"}</td>
        <td>${t.quantity.toLocaleString()}</td>
        <td>${jpy(t.price)}</td>
        <td>${jpy(t.amount)}</td>
        <td class="${signClass(t.realized_pl)}">${t.realized_pl != null ? jpy(t.realized_pl) : "—"}</td>
        <td>${t.decided_by === "claude" ? "🤖 Claude" : "手動"}</td>
      </tr>`
    )
    .join("");
}

async function loadDecisions() {
  const decs = await api("/api/decisions?limit=50");
  const tbody = document.querySelector("#decisions-table tbody");
  if (!decs.length) {
    tbody.innerHTML = `<tr><td colspan="7" class="flat">AI判断ログはありません</td></tr>`;
    return;
  }
  tbody.innerHTML = decs
    .map(
      (d) => `<tr>
        <td>${d.ts.replace("T", " ").slice(0, 16)}</td>
        <td>${d.name || d.code}</td>
        <td><span class="tag ${d.action}">${d.action}</span></td>
        <td>${d.quantity ? d.quantity.toLocaleString() : "—"}</td>
        <td>${d.confidence != null ? (d.confidence * 100).toFixed(0) + "%" : "—"}</td>
        <td class="rationale-cell">${d.rationale || ""}</td>
        <td>${d.executed ? "✅" : "—"}</td>
      </tr>`
    )
    .join("");
}

function renderDecisionCard(d) {
  if (d.error && !d.action) {
    return `<div class="decision"><b>${d.code}</b>: <span class="down">${d.error}</span></div>`;
  }
  let exec = "";
  if (d.executed) {
    exec = `<div class="exec-note up">✅ 執行: ${d.execution.side} ${d.execution.quantity}株 @ ${jpy(d.execution.price)}</div>`;
  } else if (d.error) {
    exec = `<div class="exec-note down">⚠️ 執行できず: ${d.error}</div>`;
  } else if (d.action !== "HOLD" && d.auto_execute === false) {
    exec = `<div class="exec-note flat">自動執行はオフ（判断のみ）</div>`;
  }
  return `<div class="decision">
    <div class="head">
      <span class="tag ${d.action}">${d.action}</span>
      <b>${d.name} (${d.code})</b>
      ${d.quantity ? `<span class="flat">${d.quantity}株</span>` : ""}
      <span class="flat" style="margin-left:auto">確信度 ${(d.confidence * 100).toFixed(0)}%</span>
    </div>
    <div class="conf-bar"><div style="width:${d.confidence * 100}%"></div></div>
    <div class="rationale" style="margin-top:8px">${d.rationale}</div>
    ${exec}
  </div>`;
}

// ---------------------------------------------------------------------------
// アクション
// ---------------------------------------------------------------------------
async function runAdvisor(all) {
  const autoExec = document.getElementById("auto-exec").checked;
  const resultEl = document.getElementById("ai-result");
  const btns = [document.getElementById("ai-one"), document.getElementById("ai-all")];
  btns.forEach((b) => (b.disabled = true));
  resultEl.innerHTML = `<div class="flat"><span class="spinner"></span> Claude が判断中...</div>`;
  try {
    let cards;
    if (all) {
      const res = await api("/api/advisor/run-all", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ auto_execute: autoExec }),
      });
      cards = res.results.map(renderDecisionCard).join("");
    } else {
      if (!selectedCode) throw new Error("銘柄を選択してください。");
      const d = await api("/api/advisor/decide", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code: selectedCode, auto_execute: autoExec }),
      });
      cards = renderDecisionCard(d);
    }
    resultEl.innerHTML = cards;
    await refreshAll();
  } catch (e) {
    resultEl.innerHTML = `<div class="down">${e.message}</div>`;
    toast(e.message, "error");
  } finally {
    btns.forEach((b) => (b.disabled = false));
  }
}

async function manualTrade(side) {
  const code = document.getElementById("trade-code").value.trim();
  const qty = parseInt(document.getElementById("trade-qty").value, 10);
  if (!code || !qty) return toast("コードと数量を入力してください。", "error");
  try {
    const r = await api(`/api/trade/${side}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code, quantity: qty }),
    });
    toast(`${r.side === "BUY" ? "買い" : "売り"}約定: ${r.name} ${r.quantity}株 @ ${jpy(r.price)}`, "success");
    await refreshAll();
  } catch (e) {
    toast(e.message, "error");
  }
}

async function refreshAll() {
  await Promise.all([loadSummary(), loadWatchlist(), loadTrades(), loadDecisions()]);
}

// ---------------------------------------------------------------------------
// 初期化
// ---------------------------------------------------------------------------
document.getElementById("add-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = document.getElementById("add-code");
  const code = input.value.trim();
  if (!code) return;
  await api("/api/watchlist", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code }),
  });
  input.value = "";
  loadWatchlist();
});

document.getElementById("buy-btn").addEventListener("click", () => manualTrade("buy"));
document.getElementById("sell-btn").addEventListener("click", () => manualTrade("sell"));
document.getElementById("ai-one").addEventListener("click", () => runAdvisor(false));
document.getElementById("ai-all").addEventListener("click", () => runAdvisor(true));
document.getElementById("reset-btn").addEventListener("click", async () => {
  if (!confirm("シミュレーションを初期状態に戻します。よろしいですか？")) return;
  await api("/api/reset", { method: "POST" });
  toast("リセットしました。", "success");
  refreshAll();
});

(async function init() {
  await loadStatus();
  await refreshAll();
})();
