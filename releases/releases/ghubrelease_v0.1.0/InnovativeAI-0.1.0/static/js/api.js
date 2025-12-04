# © InnovativeAI LLC — ADAAD Inside™ — All Rights Reserved
const API = (() => {
  const jsonGet = async (path) => {
    const response = await fetch(path, { cache: "no-cache" });
    if (!response.ok) {
      throw new Error(`Request failed: ${path}`);
    }
    return response.json();
  };

  return {
    health: () => jsonGet("/health"),
    metrics: () => jsonGet("/metrics"),
    agents: () => jsonGet("/agents"),
  };
})();
