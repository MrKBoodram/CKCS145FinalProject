let dailyPnlChart = null;

function formatMoney(value) { 
    const num = Number(value || 0);
    return num.toLocaleString(undefined, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    });
}

function formatDateTime(value) {
    if (!value) return "";
    return new Date(value).toLocaleString();
}

function setSignedClass(element, value) {
    element.classList.remove("positive", "negative");
    const num = Number(value || 0);
    if (num > 0) element.classList.add("positive");
    else if (num < 0) element.classList.add("negative");
}

async function fetchJson(url) {
    const response = await fetch(url);
    if (!response.ok) {
        throw new Error(`Request Failed: ${url}`);
    }
    return await response.json();
}

async function loadSummary() {
    const data = await fetchJson("/api/summary");

    document.getElementById("total-trades").textContent = data.total_trades ?? 0;
    document.getElementById("total-shares").textContent = data.total_shares ?? 0;
    document.getElementById("gross-pl").textContent = formatMoney(data.gross_pl);
    document.getElementById("total-fees").textContent = formatMoney(data.total_fees);
    document.getElementById("net-pl").textContent = formatMoney(data.net_pl);
    document.getElementById("win-rate").textContent = `${Number(data.win_rate || 0).toFixed(2)}%`;

    setSignedClass(document.getElementById("gross-pl"), data.gross_pl);
    setSignedClass(document.getElementById("net-pl"), data.net_pl);
}

async function loadDailyPnlChart() {
    const rows = await fetchJson("/api/daily-pnl");

    const labels = rows.map((r) => r.trade_date);
    const values = rows.map((r) => Number(r.net_pl || 0));

    const ctx = document.getElementById("dailyPnlChart").getContext("2d");

    if (dailyPnlChart) {
        dailyPnlChart.destroy();
    }

    dailyPnlChart = new Chart(ctx, {
        type: "line",
        data: {
            labels,
            datasets: [
                {
                    label: "Net P/L",
                    data: values,
                    tension: 0.2,
                },
            ],
        },
        options: {
            responsive: true,
            plugins: {
                legend: {
                    labels: {
                        color: "#e2e8f0",
                    },
                },
            },
            scales: {
                x: {
                    ticks: { color: "#94a3b8"},
                    grid: { color:"#1f2937"},
                },
                y: {
                    ticks: { color: "#94a3b8"},
                    grid: { color:"#1f2937"},
                },
            },
        },
    });
}

async function loadTradesTable() {
    const rows= await fetchJson("/api/trades");
    const tbody = document.querySelector("#trades-table tbody");
    tbody.innerHTML = "";

    rows.forEach((row) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
            <td>${row.symbol ?? ""}</td>
            <td>${row.side_open ?? ""}</td>
            <td>${formatDateTime(row.entry_time)}</td>
            <td>${formatDateTime(row.exit_time)}</td>
            <td>${row.total_shares ?? 0}</td>
            <td>${formatMoney(row.entry_avg_price)}</td>
            <td>${formatMoney(row.exit_avg_price)}</td>
            <td class="${Number(row.gross_pl) >= 0 ? "positive" : "negative"}">${formatMoney(row.gross_pl)}</td>
            <td>${formatMoney(row.total_fees)}</td>
            <td class="${Number(row.net_pl) >= 0 ? "positive" : "negative"}">${formatMoney(row.net_pl)}</td>
        `;
        tbody.appendChild(tr);
    });
}

async function loadSymbolsTable() { 
    const rows = await fetchJson("/api/symbols");
    const tbody = document.querySelector("#symbols-table-body");
    tbody.innerHTML = "";

    rows.forEach((row) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
            <td>${row.symbol ?? ""}</td>
            <td>${row.trades ?? 0}</td>
            <td>${row.total_shares ?? 0}</td>
            <td class="${Number(row.gross_pl) >= 0 ? "positive" : "negative"}">${formatMoney(row.gross_pl)}</td>
            <td>${formatMoney(row.total_fees)}</td>
            <td class="${Number(row.net_pl) >= 0 ? "positive" : "negative"}">${formatMoney(row.net_pl)}</td>
        `;
        tbody.appendChild(tr);
    }); 
}

function setupTabs() {
    const buttons = document.querySelectorAll(".tab-button");
    const panels = document.querySelectorAll(".tab-panel");

    buttons.forEach((button) => {
        button.addEventListener("click", () => {
            buttons.forEach((b) => b.classList.remove("active"));
            panels.forEach((p) => p.classList.remove("active"));

            button.classList.add("active");
            document.getElementById(button.dataset.tab).classList.add("active");
        });
    });
}

async function initDashboard() {
  setupTabs();

  const results = await Promise.allSettled([
    loadSummary(),
    loadDailyPnlChart(),
    loadTradesTable(),
    loadSymbolsTable(),
  ]);

  results.forEach((result, index) => {
    if (result.status === "rejected") {
      console.error(`Dashboard section ${index} failed:`, result.reason);
    }
  });
}

document.addEventListener("DOMContentLoaded", initDashboard);