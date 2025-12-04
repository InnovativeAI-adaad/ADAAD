(function() {
  const listEl = document.getElementById("agents-list");

  const renderEmpty = () => {
    const placeholder = document.createElement("li");
    placeholder.textContent = "No demo agents available";
    listEl.replaceChildren(placeholder);
  };

  const renderAgents = (agents) => {
    if (!Array.isArray(agents) || agents.length === 0) {
      renderEmpty();
      return;
    }

    const entries = agents.map((agent) => {
      const li = document.createElement("li");
      li.textContent = `${agent.name} — ${agent.status} — ${agent.description}`;
      return li;
    });

    listEl.replaceChildren(...entries);
  };

  const loadAgents = async () => {
    try {
      const agents = await API.agents();
      renderAgents(agents);
    } catch (err) {
      console.error(err);
      renderEmpty();
    }
  };

  loadAgents();
})();

