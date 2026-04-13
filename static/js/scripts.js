let dailyPnlChart = null;

//Helpers

function formatMoney(value) {
    const num = Number(value || 0);
    return num.toLocaleString(undefined, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    });
}

function formatDateTime(value) {
    if (!value) return "";
    return new Date(value).toLocaleString("en-US", {
        timeZone: "America/New_York",
        year: "numeric",
        month: "numeric",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
        second: "2-digit",
        hour12: true
    });
}

function updateBannerState(netPl) {
    const banner = document.getElementById("hero-banner");
    if (!banner) return;

    banner.classList.remove("banner-positive", "banner-negative", "banner-neutral");

    const value = Number(netPl || 0);

    if (value > 0) {
        banner.classList.add("banner-positive");
    } else if (value < 0) {
        banner.classList.add("banner-negative");
    } else {
        banner.classList.add("banner-neutral");
    }
}

function setupBannerParallax() {
    const banner = document.getElementById("hero-banner");
    if (!banner) return;

    window.addEventListener("scroll", () => {
        const offset = window.scrollY * 0.12;
        banner.style.backgroundPosition = `center calc(38% + ${offset}px)`;
    });
}

//

function setSignedClass(element, value) {
    if (!element) return;
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

function getFilterParams() {
    const symbol = document.getElementById("symbol-filter")?.value || "";
    const startDate = document.getElementById("start-date")?.value || "";
    const endDate = document.getElementById("end-date")?.value || "";

    const params = new URLSearchParams();

    if (symbol) params.append("symbol", symbol);
    if (startDate) params.append("start_date", startDate);
    if (endDate) params.append("end_date", endDate);

    return params.toString();
}

async function loadAvailableSymbols() {
    const rows = await fetchJson("/api/available-symbols");
    const select = document.getElementById("symbol-filter");
    if (!select) return;

    select.innerHTML = `<option value="">All Symbols</option>`;

    rows.forEach((row) => {
        const option = document.createElement("option");
        option.value = row.symbol;
        option.textContent = row.symbol;
        select.appendChild(option);
    });
}

async function loadSummary() {
    const params = getFilterParams();
    const url = params ? `/api/summary?${params}` : "/api/summary";
    const data = await fetchJson(url);

    document.getElementById("total-trades").textContent = data.total_trades ?? 0;
    document.getElementById("total-shares").textContent = data.total_shares ?? 0;
    document.getElementById("gross-pl").textContent = formatMoney(data.gross_pl);
    document.getElementById("total-fees").textContent = formatMoney(data.total_fees);
    document.getElementById("net-pl").textContent = formatMoney(data.net_pl);
    document.getElementById("win-rate").textContent = `${Number(data.win_rate || 0).toFixed(2)}%`;

    setSignedClass(document.getElementById("gross-pl"), data.gross_pl);
    setSignedClass(document.getElementById("net-pl"), data.net_pl);

    updateBannerState(data.net_pl);
}

async function loadDailyPnlChart() {
    const params = getFilterParams();
    const url = params ? `/api/daily-pnl?${params}` : "/api/daily-pnl";
    const rows = await fetchJson(url);

    const labels = rows.map((r) => r.trade_date);
    const values = rows.map((r) => Number(r.net_pl || 0));

    const canvas = document.getElementById("dailyPnlChart");
    if (!canvas) return;

    const ctx = canvas.getContext("2d");

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
                    ticks: { color: "#94a3b8" },
                    grid: { color: "#1f2937" },
                },
                y: {
                    ticks: { color: "#94a3b8" },
                    grid: { color: "#1f2937" },
                },
            },
        },
    });
}

async function loadTradesTable() {
    const params = getFilterParams();
    const url = params ? `/api/trades?limit=100&${params}` : "/api/trades?limit=100";
    const rows = await fetchJson(url);

    const tbody = document.getElementById("trades-table-body");
    if (!tbody) return;

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
    console.log("Trades rows:", rows);
}

async function loadSymbolsTable() {
    const params = getFilterParams();
    const url = params ? `/api/symbols?${params}` : "/api/symbols";
    const rows = await fetchJson(url);

    const tbody = document.querySelector("#symbols-table-body");
    if (!tbody) return;

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
    console.log("Symbols rows:", rows);
}

function setupTabs() {
    const buttons = document.querySelectorAll(".tab-button[data-tab]");
    const panels = document.querySelectorAll(".tab-panel");

    buttons.forEach((button) => {
        button.addEventListener("click", () => {
            buttons.forEach((b) => b.classList.remove("active"));
            panels.forEach((p) => p.classList.remove("active"));

            button.classList.add("active");

            const targetPanel = document.getElementById(button.dataset.tab);
            if (targetPanel) {
                targetPanel.classList.add("active");
            }
        });
    });
}

function setupFilters() {
    const applyButton = document.getElementById("apply-filters");
    const resetButton = document.getElementById("reset-filters");

    applyButton?.addEventListener("click", async () => {
        await refreshDashboardData();
    });

    resetButton?.addEventListener("click", async () => {
        const symbolFilter = document.getElementById("symbol-filter");
        const startDate = document.getElementById("start-date");
        const endDate = document.getElementById("end-date");

        if (symbolFilter) symbolFilter.value = "";
        if (startDate) startDate.value = "";
        if (endDate) endDate.value = "";

        await refreshDashboardData();
    });
}

async function refreshDashboardData() {
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

async function initDashboard() {
    setupTabs();
    setupFilters();
    setupBannerParallax();

    await loadAvailableSymbols(); // load dropdown first so filters work on initial load

    const symbolFilter = document.getElementById("symbol-filter");
    const startDate = document.getElementById("start-date");
    const endDate = document.getElementById("end-date");

    if (symbolFilter) symbolFilter.value = "";
    if (startDate) startDate.value = "";
    if (endDate) endDate.value = "";

    await refreshDashboardData(); // THEN fetch everything
}

document.addEventListener("DOMContentLoaded", initDashboard);