(function() {
  const statusEl = document.getElementById("status");
  const agentCountEl = document.getElementById("agents-count");
  const survivalEl = document.getElementById("survival");

  const renderDefaults = () => {
    statusEl.textContent = "offline";
    agentCountEl.textContent = "0";
    survivalEl.textContent = "0.00";
  };

  const renderKpi = (health, metrics, agents) => {
    statusEl.textContent = health.status ?? "unknown";
    agentCountEl.textContent = Array.isArray(agents) ? agents.length : 0;

    const survival = Number(metrics.mutation_survival_rate ?? 0);
    survivalEl.textContent = survival.toFixed(2);
  };

  const loadKpi = async () => {
    try {
      const [health, metrics, agents] = await Promise.all([
        API.health(),
        API.metrics(),
        API.agents(),
      ]);

      renderKpi(health, metrics, agents);
    } catch (err) {
      console.error(err);
      renderDefaults();
    }
  };

  loadKpi();
})();

