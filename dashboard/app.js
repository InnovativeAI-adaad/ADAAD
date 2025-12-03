const API_BASE = "http://localhost:8088/api";

const rollingContainer = document.getElementById("rolling");
const summaryGrid = document.getElementById("summary-grid");
const agentRows = document.getElementById("agent-rows");
const lineageList = document.getElementById("lineage-list");
const diffViewer = document.getElementById("diff-viewer");
const actionLog = document.getElementById("action-log");
const themeToggle = document.getElementById("theme-toggle");
const sourceModal = document.getElementById("source-modal");
const modalTitle = document.getElementById("modal-title");
const modalBody = document.getElementById("modal-body");
const closeModal = document.getElementById("close-modal");

const fallback = {
  metrics: {
    trends: [],
    promotion_summary: { promoted: 0, quarantined: 0, survival_rate: 0 },
    rolling: [],
  },
  agents: [],
  lineage: [],
  diff: { diff: "", label: "mutation" },
  actions: [],
};

const fetchJson = async (path) => {
  try {
    const res = await fetch(`${API_BASE}${path}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (err) {
    console.warn("API fallback", path, err.message);
    if (path === "/metrics") return fallback.metrics;
    if (path === "/agents") return fallback.agents;
    if (path === "/lineage") return fallback.lineage;
    if (path === "/diff") return fallback.diff;
    if (path === "/actions") return fallback.actions;
    return null;
  }
};

const toDate = (value) => new Date(value).toLocaleString();

const renderRolling = (rolling) => {
  rollingContainer.innerHTML = "";
  rolling.forEach((entry) => {
    const row = document.createElement("div");
    row.className = "summary-box";
    row.innerHTML = `<p class="muted">${entry.label}</p><h3>${entry.value}</h3>`;
    rollingContainer.appendChild(row);
  });
};

const renderSummary = (summary) => {
  const { promoted = 0, quarantined = 0, survival_rate = 0 } = summary;
  summaryGrid.innerHTML = "";
  const entries = [
    { label: "Promoted", value: promoted, color: "success" },
    { label: "Quarantined", value: quarantined, color: "danger" },
    { label: "Survival", value: `${(survival_rate * 100).toFixed(1)}%`, color: "accent" },
  ];
  entries.forEach((entry) => {
    const box = document.createElement("div");
    box.className = "summary-box";
    box.innerHTML = `<p class="muted">${entry.label}</p><h3>${entry.value}</h3>`;
    summaryGrid.appendChild(box);
  });
};

const badgeForStatus = (status) => {
  const badge = document.createElement("span");
  badge.className = `badge ${status}`;
  badge.textContent = status;
  return badge;
};

const renderAgents = (agents) => {
  agentRows.innerHTML = "";
  agents.forEach((agent) => {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${agent.id}</td>
      <td></td>
      <td>${agent.score}</td>
      <td>${agent.version}</td>
      <td>${toDate(agent.last_seen)}</td>
      <td class="table-actions"></td>
    `;
    const statusCell = row.children[1];
    statusCell.appendChild(badgeForStatus(agent.status));

    const actionCell = row.querySelector(".table-actions");
    const viewBtn = document.createElement("button");
    viewBtn.textContent = "View source";
    viewBtn.className = "ghost";
    viewBtn.onclick = () => openModal(agent.id, agent.source_content || "Source unavailable");

    const lineageBtn = document.createElement("button");
    lineageBtn.textContent = "Lineage";
    lineageBtn.className = "ghost";
    lineageBtn.onclick = () => highlightLineage(agent.lineage);

    actionCell.append(viewBtn, lineageBtn);
    agentRows.appendChild(row);
  });
};

const renderLineage = (entries) => {
  lineageList.innerHTML = "";
  entries.forEach((item) => {
    const li = document.createElement("li");
    li.innerHTML = `<strong>${item.label}</strong><br /><span>${item.detail}</span><br /><time>${toDate(item.ts)}</time>`;
    lineageList.appendChild(li);
  });
};

const renderDiff = (diff) => {
  diffViewer.innerHTML = "";
  (diff.diff || "").split("\n").forEach((line) => {
    const div = document.createElement("div");
    if (line.startsWith("+")) div.classList.add("add");
    if (line.startsWith("-")) div.classList.add("remove");
    div.textContent = line;
    diffViewer.appendChild(div);
  });
};

const renderActions = (actions) => {
  actionLog.innerHTML = "";
  actions.slice(-5).reverse().forEach((entry) => {
    const row = document.createElement("div");
    row.className = "summary-box";
    row.innerHTML = `<strong>${entry.action}</strong> → ${entry.result || "accepted"}<br/><span class="muted">${toDate(entry.ts)}</span>`;
    actionLog.appendChild(row);
  });
};

const renderChart = (metrics) => {
  const ctx = document.getElementById("metrics-chart");
  if (!metrics.trends.length || !window.Chart) return;
  const grouped = metrics.trends.reduce((acc, item) => {
    acc[item.metric] = acc[item.metric] || [];
    acc[item.metric].push(item);
    return acc;
  }, {});
  const datasets = Object.entries(grouped).map(([metric, points], index) => {
    return {
      label: metric,
      data: points.map((p) => ({ x: toDate(p.ts), y: p.value })),
      borderColor: ["#7dd3fc", "#22c55e", "#f97316", "#f43f5e"][index % 4],
      tension: 0.35,
    };
  });
  new Chart(ctx, {
    type: "line",
    data: { datasets },
    options: {
      responsive: true,
      interaction: { mode: "index", intersect: false },
      scales: {
        x: { type: "category" },
        y: { beginAtZero: true },
      },
      plugins: { legend: { position: "bottom" } },
    },
  });
};

const openModal = (title, content) => {
  modalTitle.textContent = title;
  modalBody.textContent = content;
  document.body.classList.add("dialog-open");
  sourceModal.showModal();
};

const highlightLineage = (steps) => {
  const lines = (steps || []).map((step) => ({ ts: "", label: step, detail: "" }));
  if (lines.length) renderLineage(lines);
};

const wireModal = () => {
  closeModal.onclick = () => {
    document.body.classList.remove("dialog-open");
    sourceModal.close();
  };
  sourceModal.addEventListener("click", (e) => {
    if (e.target === sourceModal) {
      document.body.classList.remove("dialog-open");
      sourceModal.close();
    }
  });
};

const sendAction = async (action) => {
  const res = await fetch(`${API_BASE}/actions/${action}`, { method: "POST", body: JSON.stringify({ via: "dashboard" }), headers: { "Content-Type": "application/json" } });
  if (res.ok) {
    const payload = await res.json();
    renderActions([{ action, result: "accepted", ts: payload.ts }]);
  }
};

const wireControls = () => {
  document.querySelectorAll("[data-action]").forEach((btn) => {
    btn.addEventListener("click", () => sendAction(btn.dataset.action));
  });
};

const wireThemeToggle = () => {
  themeToggle.addEventListener("click", () => {
    const current = document.documentElement.getAttribute("data-theme");
    const next = current === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
  });
};

const bootstrap = async () => {
  wireModal();
  wireControls();
  wireThemeToggle();

  const [metrics, agents, lineage, diff, actions] = await Promise.all([
    fetchJson("/metrics"),
    fetchJson("/agents"),
    fetchJson("/lineage"),
    fetchJson("/diff"),
    fetchJson("/actions"),
  ]);

  renderRolling(metrics.rolling || []);
  renderSummary(metrics.promotion_summary || {});
  renderChart(metrics);
  renderAgents(agents || []);
  renderLineage(lineage || []);
  renderDiff(diff || {});
  renderActions(actions || []);
};

bootstrap();
