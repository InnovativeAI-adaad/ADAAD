(function(global){
  "use strict";

  const DEFAULT_CFG = Object.freeze({
    provider: "groq",
    groqKey: "",
    ollamaModel: "llama3.2",
    tokenWarn: 12000,
    maxContextTurns: 16,
    convStorageKey: "whaledic_v3_conv",
    cfgStorageKey: "dork_llm_v3",
    stateBusChannel: "adaad_state_bus",
    stateBusSnapshotKey: "adaad_state_bus_snapshot",
    deepLinkParam: "dork_seed",
  });

  function nowIso(){ return new Date().toISOString(); }

  function createRuntime(userConfig){
    let cfg = { ...DEFAULT_CFG, ...(userConfig || {}) };
    let conversation = [];
    let totalTokens = 0;
    let inFlight = false;
    const listeners = new Set();
    let channel = null;

    try {
      if (typeof BroadcastChannel !== "undefined") {
        channel = new BroadcastChannel(cfg.stateBusChannel);
        channel.onmessage = (event) => {
          const data = event && event.data;
          if (!data || data.type !== "state_bus_patch" || !data.patch) return;
          emit("state_bus_ingested", { source: data.source || "external", patch: data.patch });
          applyStatePatch(data.patch, { source: data.source || "external", broadcast: false, persist: true });
        };
      }
    } catch (_) {}

    try {
      global.addEventListener("storage", (event) => {
        if (event.key !== cfg.stateBusSnapshotKey || !event.newValue) return;
        try {
          const parsed = JSON.parse(event.newValue);
          if (!parsed || typeof parsed !== "object") return;
          global.ADAAD_STATE_BUS = Object.freeze(parsed);
          emit("state_bus_ingested", { source: "storage", patch: parsed });
        } catch (_) {}
      });
    } catch (_) {}

    function emit(type, payload){
      const evt = { type, payload: payload || {}, ts: nowIso() };
      listeners.forEach((listener) => {
        try { listener(evt); } catch (_) {}
      });
      if (typeof cfg.onEvent === "function") {
        try { cfg.onEvent(evt); } catch (_) {}
      }
    }

    function loadConversation(){
      try {
        const raw = global.localStorage.getItem(cfg.convStorageKey);
        if (!raw) return;
        const parsed = JSON.parse(raw);
        if (parsed && parsed.schema === "3.0" && Array.isArray(parsed.turns)) {
          conversation = parsed.turns;
        }
      } catch (_) {}
    }

    function persistConversation(){
      try {
        global.localStorage.setItem(
          cfg.convStorageKey,
          JSON.stringify({ schema: "3.0", turns: conversation.slice(-40), ts: nowIso() }),
        );
      } catch (_) {}
    }

    function loadProviderConfig(){
      try {
        const raw = global.localStorage.getItem(cfg.cfgStorageKey);
        if (!raw) return;
        const parsed = JSON.parse(raw);
        if (parsed && typeof parsed === "object") {
          cfg = { ...cfg, ...parsed };
        }
      } catch (_) {}
    }

    function persistProviderConfig(){
      try {
        global.localStorage.setItem(
          cfg.cfgStorageKey,
          JSON.stringify({ provider: cfg.provider, groqKey: cfg.groqKey, ollamaModel: cfg.ollamaModel }),
        );
      } catch (_) {}
    }

    function applyStatePatch(patch, opts){
      if (!patch || typeof patch !== "object") return global.ADAAD_STATE_BUS || null;
      const options = { broadcast: true, persist: true, source: "dork_runtime", ...(opts || {}) };
      const merged = Object.freeze({
        ...(global.ADAAD_STATE_BUS || {}),
        ...patch,
        captured_at_iso: nowIso(),
        schema_version: "1.0.0",
      });
      global.ADAAD_STATE_BUS = merged;
      if (options.persist) {
        try { global.localStorage?.setItem(cfg.stateBusSnapshotKey, JSON.stringify(merged)); } catch (_) {}
      }
      if (options.broadcast) {
        try {
          channel?.postMessage({ type: "state_bus_patch", patch, ts: nowIso(), source: options.source });
        } catch (_) {}
      }
      emit("state_bus_ingested", { source: options.source, patch, merged });
      return merged;
    }

    function estimateTokens(value){
      return Math.ceil(String(value || "").length / 4);
    }

    function getConversation(){
      return conversation.slice();
    }

    function getConfig(){
      return { provider: cfg.provider, groqKey: cfg.groqKey, ollamaModel: cfg.ollamaModel };
    }

    function setConfig(patch){
      if (!patch || typeof patch !== "object") return getConfig();
      cfg = { ...cfg, ...patch };
      persistProviderConfig();
      emit("provider_changed", { provider: cfg.provider });
      return getConfig();
    }

    function clearConversation(){
      conversation = [];
      totalTokens = 0;
      persistConversation();
      emit("conversation_cleared", {});
    }

    function buildPrompt(){
      if (typeof cfg.buildSystemPrompt === "function") {
        return cfg.buildSystemPrompt();
      }
      return "You are dork, the ADAAD assistant. Stay concise, factual, and governance-safe.";
    }

    async function callGroq(msgs, sys, onChunk){
      if (!cfg.groqKey) throw new Error("No Groq key");
      const resp = await fetch("https://api.groq.com/openai/v1/chat/completions", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Authorization": "Bearer " + cfg.groqKey },
        body: JSON.stringify({
          model: "llama-3.3-70b-versatile",
          max_tokens: 1024,
          stream: true,
          messages: [{ role: "system", content: sys }, ...msgs],
        }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error((err.error && err.error.message) || ("Groq " + resp.status));
      }
      const reader = resp.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop();
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const payload = line.slice(6).trim();
          if (payload === "[DONE]") return;
          try {
            const parsed = JSON.parse(payload);
            const token = parsed.choices && parsed.choices[0] && parsed.choices[0].delta && parsed.choices[0].delta.content;
            if (token) onChunk(token);
          } catch (_) {}
        }
      }
    }

    async function callOllama(msgs, sys, onChunk){
      const model = cfg.ollamaModel || "llama3.2";
      const resp = await fetch("http://localhost:11434/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model, stream: true, messages: [{ role: "system", content: sys }, ...msgs] }),
      });
      if (!resp.ok) throw new Error("Ollama " + resp.status);
      const reader = resp.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop();
        for (const line of lines) {
          if (!line.trim()) continue;
          try {
            const parsed = JSON.parse(line);
            if (parsed.message && parsed.message.content) onChunk(parsed.message.content);
            if (parsed.done) return;
          } catch (_) {}
        }
      }
    }

    async function callEngine(msgs, onChunk){
      const lastUser = msgs.filter((m) => m.role === "user").pop();
      const prompt = lastUser ? lastUser.content : "";
      const answer = typeof cfg.engineResponder === "function"
        ? cfg.engineResponder(prompt)
        : "DorkEngine is active. Configure Groq/Ollama for expanded reasoning.";
      const words = String(answer).split(" ");
      for (let i = 0; i < words.length; i += 1) {
        onChunk(words[i] + (i < words.length - 1 ? " " : ""));
        await new Promise((resolve) => setTimeout(resolve, 16));
      }
    }

    function providerSequence(){
      const preferred = cfg.provider || "dorkengine";
      if (preferred === "groq") return ["groq", "ollama", "dorkengine"];
      if (preferred === "ollama") return ["ollama", "groq", "dorkengine"];
      return ["dorkengine", "groq", "ollama"];
    }

    async function sendMessage(text, options){
      const msg = String(text || "").trim();
      if (!msg) return { response: "", provider: cfg.provider, skipped: true };
      if (inFlight) throw new Error("Message already in flight");
      const opts = options || {};
      inFlight = true;
      conversation.push({ role: "user", content: msg });
      emit("message_user", { text: msg });
      const sys = buildPrompt();
      const ctx = conversation.slice(-cfg.maxContextTurns).map((turn) => ({ role: turn.role, content: turn.content }));
      let output = "";
      let selected = null;
      let lastError = null;

      const onChunk = (chunk) => {
        output += chunk;
        emit("message_chunk", { chunk, text: output, provider: selected || cfg.provider });
        if (typeof opts.onChunk === "function") {
          try { opts.onChunk(chunk, output, selected || cfg.provider); } catch (_) {}
        }
      };

      try {
        for (const provider of providerSequence()) {
          selected = provider;
          try {
            if (provider === "groq") {
              await callGroq(ctx, sys, onChunk);
            } else if (provider === "ollama") {
              await callOllama(ctx, sys, onChunk);
            } else {
              await callEngine(ctx, onChunk);
            }
            break;
          } catch (err) {
            lastError = err;
            emit("provider_error", { provider, error: err.message || String(err) });
            if (provider === "dorkengine") throw err;
            if (provider === cfg.provider) {
              emit("provider_fallback", { from: provider });
            }
            continue;
          }
        }

        if (!output && lastError) {
          throw lastError;
        }

        conversation.push({ role: "assistant", content: output });
        totalTokens += estimateTokens(msg) + estimateTokens(output);
        persistConversation();
        applyStatePatch({ dork_last: { q: msg.slice(0, 120), a: output.slice(0, 200), ts: nowIso() } }, { source: "dork_runtime" });
        emit("message_assistant", { text: output, provider: selected || cfg.provider, totalTokens });
        if (totalTokens > cfg.tokenWarn) emit("token_warn", { totalTokens });
        return { response: output, provider: selected || cfg.provider, totalTokens };
      } finally {
        inFlight = false;
      }
    }

    function subscribeEvents(listener){
      if (typeof listener !== "function") return () => {};
      listeners.add(listener);
      return () => listeners.delete(listener);
    }

    function deepLinkSeed(){
      try {
        const params = new URLSearchParams(global.location.search || "");
        const seed = params.get(cfg.deepLinkParam);
        if (seed) emit("bridge_deeplink", { seed, param: cfg.deepLinkParam });
        return seed || "";
      } catch (_) {
        return "";
      }
    }

    function buildDeepLink(seed, page){
      const basePage = page || "whaledic.html";
      return `${basePage}?${cfg.deepLinkParam}=${encodeURIComponent(seed || "")}`;
    }

    loadProviderConfig();
    loadConversation();

    return {
      sendMessage,
      subscribeEvents,
      hydrateContext: applyStatePatch,
      getConversation,
      getConfig,
      setConfig,
      clearConversation,
      getDeepLinkSeed: deepLinkSeed,
      buildDeepLink,
    };
  }

  let runtimeInstance = null;

  function initDorkRuntime(config){
    if (!runtimeInstance) {
      runtimeInstance = createRuntime(config);
    } else if (config && typeof config === "object") {
      runtimeInstance.setConfig(config);
    }
    return runtimeInstance;
  }

  function withRuntime(fn){
    return function proxy(){
      if (!runtimeInstance) runtimeInstance = createRuntime({});
      return fn(runtimeInstance, arguments);
    };
  }

  global.initDorkRuntime = initDorkRuntime;
  global.sendMessage = withRuntime((runtime, args) => runtime.sendMessage(args[0], args[1]));
  global.subscribeEvents = withRuntime((runtime, args) => runtime.subscribeEvents(args[0]));
  global.hydrateContext = withRuntime((runtime, args) => runtime.hydrateContext(args[0], args[1]));

  global.ADAADDorkRuntime = {
    initDorkRuntime,
    sendMessage: global.sendMessage,
    subscribeEvents: global.subscribeEvents,
    hydrateContext: global.hydrateContext,
  };
})(window);
