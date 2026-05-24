/**
 * ADAAD Aponi — DORK Panel (Phase 186)
 * ══════════════════════════════════════════════════════════════════════
 * Embeds the DORK Governance Intelligence chat natively inside the Aponi
 * tab system. Connects to /api/dork/console/route (streaming JSON-SSE)
 * and /api/whale/snapshot for live governance context.
 *
 * Architecture:
 *   - Self-contained IIFE; exposes window._dorkPanel.view()
 *   - Full ADAAD brand palette (void-black / whale-cyan accent)
 *   - Markdown rendering via inline parser (no external dep)
 *   - Streaming response chunks rendered incrementally
 *   - Governance context bar: phase · version · invariants · CEL status
 *   - Preset prompt chips for fast entry
 *   - Keyboard: Enter to send · Shift+Enter for newline · Escape to clear
 *
 * Governor: DUSTIN L REID · INNOV-91-DORK-APONI · InnovativeAI LLC
 */

(function (global) {
  "use strict";

  /* ══════════════════════════════════════════════════════════════════════
     GUARD — single init
  ══════════════════════════════════════════════════════════════════════ */
  if (global._dorkPanel) return;

  /* ══════════════════════════════════════════════════════════════════════
     CSS
  ══════════════════════════════════════════════════════════════════════ */
  const CSS = `
    @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:wght@400;500;700&family=Syne:wght@600;700;800&display=swap');

    .dp-root {
      display: flex;
      flex-direction: column;
      height: calc(100dvh - 148px);
      min-height: 500px;
      background: #080c14;
      border-radius: 14px;
      border: 1px solid rgba(0,217,255,0.14);
      overflow: hidden;
      font-family: 'DM Sans', system-ui, sans-serif;
      position: relative;
    }

    /* ── Gov context bar ───────────────────────────────────────────── */
    .dp-govbar {
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
      padding: 10px 16px;
      background: rgba(0,217,255,0.04);
      border-bottom: 1px solid rgba(0,217,255,0.10);
      font-family: 'DM Mono', monospace;
      font-size: 11px;
      color: rgba(0,217,255,0.55);
      user-select: none;
    }
    .dp-govbar-pill {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      padding: 3px 9px;
      border-radius: 20px;
      border: 1px solid rgba(0,217,255,0.12);
      background: rgba(0,217,255,0.05);
      color: rgba(0,217,255,0.7);
      font-size: 10.5px;
      cursor: default;
      transition: border-color 0.2s, color 0.2s;
    }
    .dp-govbar-pill.ok  { border-color: rgba(34,197,94,0.25);  color: rgba(34,197,94,0.8); }
    .dp-govbar-pill.warn{ border-color: rgba(234,179,8,0.25);  color: rgba(234,179,8,0.8); }
    .dp-govbar-pill.bad { border-color: rgba(239,68,68,0.25);  color: rgba(239,68,68,0.8); }
    .dp-govbar-dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }

    /* ── Message list ──────────────────────────────────────────────── */
    .dp-messages {
      flex: 1;
      overflow-y: auto;
      padding: 20px 16px 12px;
      display: flex;
      flex-direction: column;
      gap: 16px;
      scroll-behavior: smooth;
    }
    .dp-messages::-webkit-scrollbar { width: 4px; }
    .dp-messages::-webkit-scrollbar-track { background: transparent; }
    .dp-messages::-webkit-scrollbar-thumb { background: rgba(0,217,255,0.15); border-radius: 2px; }

    /* ── Message bubbles ───────────────────────────────────────────── */
    .dp-msg { display: flex; flex-direction: column; gap: 4px; max-width: 100%; }
    .dp-msg.user  { align-items: flex-end; }
    .dp-msg.dork  { align-items: flex-start; }
    .dp-msg.sys   { align-items: center; }

    .dp-bubble {
      padding: 11px 15px;
      border-radius: 12px;
      font-size: 13.5px;
      line-height: 1.65;
      max-width: min(740px, 94%);
      word-break: break-word;
    }
    .dp-msg.user .dp-bubble {
      background: rgba(59,130,246,0.15);
      border: 1px solid rgba(59,130,246,0.22);
      color: #e6edf3;
    }
    .dp-msg.dork .dp-bubble {
      background: rgba(0,217,255,0.06);
      border: 1px solid rgba(0,217,255,0.13);
      color: #d6e4f0;
    }
    .dp-msg.sys .dp-bubble {
      background: rgba(255,255,255,0.03);
      border: 1px solid rgba(255,255,255,0.07);
      color: rgba(255,255,255,0.35);
      font-size: 11.5px;
      font-family: 'DM Mono', monospace;
    }

    /* ── DORK label ────────────────────────────────────────────────── */
    .dp-label {
      font-family: 'Syne', sans-serif;
      font-size: 10px;
      font-weight: 700;
      letter-spacing: .12em;
      text-transform: uppercase;
      margin-bottom: 2px;
      opacity: .55;
    }
    .dp-msg.user .dp-label { color: #7dd3fc; text-align: right; }
    .dp-msg.dork .dp-label { color: #00d9ff; }

    /* ── Markdown inside bubbles ───────────────────────────────────── */
    .dp-bubble code {
      font-family: 'DM Mono', monospace;
      font-size: 12px;
      background: rgba(0,0,0,0.35);
      padding: 1px 5px;
      border-radius: 4px;
      color: #7dd3fc;
    }
    .dp-bubble pre {
      background: rgba(0,0,0,0.45);
      border: 1px solid rgba(0,217,255,0.10);
      border-radius: 8px;
      padding: 10px 12px;
      overflow-x: auto;
      margin: 8px 0;
    }
    .dp-bubble pre code { background: none; padding: 0; }
    .dp-bubble strong { color: #e6edf3; font-weight: 600; }
    .dp-bubble em { color: #c8d8e8; font-style: italic; }
    .dp-bubble ul, .dp-bubble ol { padding-left: 20px; margin: 6px 0; }
    .dp-bubble li { margin: 3px 0; }
    .dp-bubble p { margin: 0 0 8px 0; }
    .dp-bubble p:last-child { margin-bottom: 0; }
    .dp-bubble blockquote {
      border-left: 2px solid rgba(0,217,255,0.3);
      margin: 8px 0;
      padding-left: 12px;
      color: rgba(214,228,240,0.7);
      font-style: italic;
    }
    .dp-bubble h3, .dp-bubble h4 {
      font-family: 'Syne', sans-serif;
      color: #00d9ff;
      margin: 10px 0 4px;
      font-size: 13px;
    }

    /* ── Streaming cursor ──────────────────────────────────────────── */
    .dp-cursor {
      display: inline-block;
      width: 7px; height: 14px;
      background: rgba(0,217,255,0.7);
      border-radius: 1px;
      animation: dp-blink 0.85s step-end infinite;
      vertical-align: text-bottom;
      margin-left: 2px;
    }
    @keyframes dp-blink { 0%,100%{opacity:1} 50%{opacity:0} }

    /* ── Preset chips ──────────────────────────────────────────────── */
    .dp-chips {
      display: flex;
      gap: 7px;
      flex-wrap: wrap;
      padding: 8px 16px 0;
    }
    .dp-chip {
      font-size: 11px;
      font-family: 'DM Mono', monospace;
      padding: 5px 11px;
      border-radius: 20px;
      border: 1px solid rgba(0,217,255,0.18);
      background: rgba(0,217,255,0.04);
      color: rgba(0,217,255,0.65);
      cursor: pointer;
      transition: all 0.15s;
      white-space: nowrap;
    }
    .dp-chip:hover {
      border-color: rgba(0,217,255,0.45);
      background: rgba(0,217,255,0.10);
      color: rgba(0,217,255,1);
    }

    /* ── Input bar ─────────────────────────────────────────────────── */
    .dp-inputbar {
      display: flex;
      align-items: flex-end;
      gap: 10px;
      padding: 12px 14px;
      border-top: 1px solid rgba(0,217,255,0.10);
      background: rgba(5,10,20,0.6);
    }
    .dp-textarea {
      flex: 1;
      background: rgba(0,217,255,0.05);
      border: 1px solid rgba(0,217,255,0.15);
      border-radius: 10px;
      color: #e6edf3;
      font-family: 'DM Sans', system-ui, sans-serif;
      font-size: 13.5px;
      padding: 10px 13px;
      resize: none;
      min-height: 42px;
      max-height: 140px;
      outline: none;
      transition: border-color 0.2s;
      line-height: 1.5;
    }
    .dp-textarea::placeholder { color: rgba(140,145,155,0.55); }
    .dp-textarea:focus { border-color: rgba(0,217,255,0.4); }
    .dp-send {
      flex: 0 0 auto;
      background: linear-gradient(180deg, rgba(0,217,255,0.22), rgba(0,217,255,0.10));
      border: 1px solid rgba(0,217,255,0.35);
      border-radius: 10px;
      color: #e6edf3;
      padding: 10px 16px;
      font-family: 'Syne', sans-serif;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: .08em;
      cursor: pointer;
      transition: all 0.15s;
      align-self: flex-end;
    }
    .dp-send:hover:not(:disabled) {
      background: linear-gradient(180deg, rgba(0,217,255,0.35), rgba(0,217,255,0.18));
      border-color: rgba(0,217,255,0.6);
    }
    .dp-send:disabled { opacity: .4; cursor: not-allowed; }

    /* ── Empty state ───────────────────────────────────────────────── */
    .dp-empty {
      flex: 1;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 12px;
      padding: 40px 20px;
      pointer-events: none;
    }
    .dp-empty-logo {
      font-family: 'Syne', sans-serif;
      font-size: 42px;
      font-weight: 800;
      background: linear-gradient(135deg, #00d9ff, #7dd3fc);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      letter-spacing: .04em;
      opacity: .8;
    }
    .dp-empty-sub {
      font-size: 13px;
      color: rgba(140,145,155,0.6);
      text-align: center;
      max-width: 360px;
      line-height: 1.6;
    }

    /* ── Error / offline banner ────────────────────────────────────── */
    .dp-offline {
      text-align: center;
      font-size: 12px;
      font-family: 'DM Mono', monospace;
      color: rgba(239,68,68,0.8);
      padding: 6px;
    }
  `;

  /* ══════════════════════════════════════════════════════════════════════
     PRESET CHIPS
  ══════════════════════════════════════════════════════════════════════ */
  const CHIPS = [
    "Which invariants are under the most pressure?",
    "Explain INNOV-88 CPE in plain English.",
    "Is the HUMAN-0 gate active?",
    "What changed in the last 3 phases?",
    "Trace the CEL loop status.",
    "What is my current V10 readiness score?",
  ];

  /* ══════════════════════════════════════════════════════════════════════
     MINIMAL MARKDOWN RENDERER
  ══════════════════════════════════════════════════════════════════════ */
  function renderMd(text) {
    // Escape HTML first
    let s = text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");

    // Fenced code blocks
    s = s.replace(/```[\w]*\n?([\s\S]*?)```/g, (_, code) =>
      `<pre><code>${code.trim()}</code></pre>`
    );
    // Inline code
    s = s.replace(/`([^`]+)`/g, "<code>$1</code>");
    // Bold / italic
    s = s.replace(/\*\*\*(.+?)\*\*\*/g, "<strong><em>$1</em></strong>");
    s = s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    s = s.replace(/\*(.+?)\*/g, "<em>$1</em>");
    // Headings
    s = s.replace(/^###\s+(.+)$/gm, "<h3>$1</h3>");
    s = s.replace(/^##\s+(.+)$/gm, "<h3>$1</h3>");
    // Blockquote
    s = s.replace(/^>\s*(.+)$/gm, "<blockquote>$1</blockquote>");
    // Unordered list items
    s = s.replace(/^[\-\*]\s+(.+)$/gm, "<li>$1</li>");
    s = s.replace(/(<li>[\s\S]+?<\/li>)/g, "<ul>$1</ul>");
    // Paragraphs (double newlines)
    s = s
      .split(/\n{2,}/)
      .map((p) => {
        p = p.trim();
        if (!p) return "";
        if (/^<(h[1-6]|pre|ul|ol|blockquote)/.test(p)) return p;
        return `<p>${p.replace(/\n/g, "<br>")}</p>`;
      })
      .join("\n");
    return s;
  }

  /* ══════════════════════════════════════════════════════════════════════
     STATE
  ══════════════════════════════════════════════════════════════════════ */
  const state = {
    messages: [],    // [{role, text, id}]
    streaming: false,
    govCtx: null,    // snapshot from /api/whale/snapshot
    govLoaded: false,
    offline: false,
    _el: null,       // root DOM element (reused across renders)
  };

  let _msgIdSeq = 0;
  const uid = () => `dp-${Date.now()}-${_msgIdSeq++}`;

  /* ══════════════════════════════════════════════════════════════════════
     GOV CONTEXT LOADER
  ══════════════════════════════════════════════════════════════════════ */
  async function loadGovCtx() {
    try {
      const base = (window._adaadState && window._adaadState.baseUrl) || "";
      const r = await fetch(`${base}/api/whale/snapshot`, {
        signal: AbortSignal.timeout(5000),
      });
      if (r.ok) {
        state.govCtx = await r.json();
        state.govLoaded = true;
        renderGovBar();
      }
    } catch (_) {
      // silent — gov bar shows defaults
    }
  }

  /* ══════════════════════════════════════════════════════════════════════
     STREAMING SEND
  ══════════════════════════════════════════════════════════════════════ */
  async function send(text) {
    if (state.streaming || !text.trim()) return;
    state.streaming = true;

    // Add user message
    state.messages.push({ role: "user", text: text.trim(), id: uid() });
    const assistId = uid();
    state.messages.push({ role: "dork", text: "", id: assistId, streaming: true });
    renderMessages();
    scrollBottom();

    const base = (window._adaadState && window._adaadState.baseUrl) || "";
    try {
      const res = await fetch(`${base}/api/dork/console/route`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: text.trim() }),
        signal: AbortSignal.timeout(60000),
      });

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }

      const ct = res.headers.get("content-type") || "";
      let fullText = "";

      if (ct.includes("text/event-stream") || ct.includes("text/plain")) {
        // SSE / streaming
        const reader = res.body.getReader();
        const dec = new TextDecoder();
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          const chunk = dec.decode(value, { stream: true });
          // Parse SSE lines
          for (const line of chunk.split("\n")) {
            if (line.startsWith("data: ")) {
              const data = line.slice(6).trim();
              if (data === "[DONE]") break;
              try {
                const obj = JSON.parse(data);
                const delta =
                  obj.delta || obj.text || obj.content || obj.response || "";
                fullText += delta;
              } catch (_) {
                // plain text delta
                fullText += data;
              }
              _updateStreamingMsg(assistId, fullText);
              scrollBottom();
            }
          }
        }
      } else {
        // JSON response
        const json = await res.json();
        fullText =
          json.response ||
          json.text ||
          json.content ||
          json.answer ||
          JSON.stringify(json, null, 2);
      }

      _finalizeMsg(assistId, fullText || "(no response)");
    } catch (err) {
      _finalizeMsg(
        assistId,
        `⚠ DORK offline or unreachable. Error: ${err.message}\n\nEnsure the ADAAD server is running (\`python server.py\`) and the Anthropic API key is configured.`
      );
      state.offline = true;
    }

    state.streaming = false;
    renderMessages();
    enableInput();
  }

  function _updateStreamingMsg(id, text) {
    const msg = state.messages.find((m) => m.id === id);
    if (msg) {
      msg.text = text;
      // Live-update the bubble DOM without full re-render
      const bubble = document.querySelector(`[data-msgid="${id}"] .dp-bubble`);
      if (bubble) {
        bubble.innerHTML =
          renderMd(text) + '<span class="dp-cursor"></span>';
      }
    }
  }

  function _finalizeMsg(id, text) {
    const msg = state.messages.find((m) => m.id === id);
    if (msg) {
      msg.text = text;
      msg.streaming = false;
      const bubble = document.querySelector(`[data-msgid="${id}"] .dp-bubble`);
      if (bubble) bubble.innerHTML = renderMd(text);
    }
  }

  /* ══════════════════════════════════════════════════════════════════════
     DOM RENDERING
  ══════════════════════════════════════════════════════════════════════ */
  function injectStyles() {
    if (document.getElementById("dp-styles")) return;
    const el = document.createElement("style");
    el.id = "dp-styles";
    el.textContent = CSS;
    document.head.appendChild(el);
  }

  function buildRoot() {
    const root = document.createElement("div");
    root.className = "dp-root";
    root.innerHTML = `
      <div class="dp-govbar" id="dp-govbar">
        <span class="dp-govbar-pill" id="dp-pill-ver">v—</span>
        <span class="dp-govbar-pill" id="dp-pill-phase">Phase —</span>
        <span class="dp-govbar-pill" id="dp-pill-inv">— invariants</span>
        <span class="dp-govbar-pill" id="dp-pill-cel">CEL —</span>
        <span class="dp-govbar-pill" id="dp-pill-innov">— innovations</span>
      </div>
      <div class="dp-messages" id="dp-messages"></div>
      <div class="dp-chips" id="dp-chips"></div>
      <div class="dp-offline" id="dp-offline" style="display:none">
        ⚡ DORK server offline — start with <code>python server.py</code>
      </div>
      <div class="dp-inputbar">
        <textarea
          class="dp-textarea"
          id="dp-input"
          placeholder="Ask DORK anything about your governance state…"
          rows="1"
        ></textarea>
        <button class="dp-send" id="dp-send">Send</button>
      </div>
    `;
    return root;
  }

  function renderGovBar() {
    const ctx = state.govCtx || {};
    const set = (id, text, cls) => {
      const el = document.getElementById(id);
      if (!el) return;
      el.textContent = text;
      if (cls) el.classList.add(cls);
    };
    const cel = (ctx.cel_loop_status || "").toUpperCase();
    const celCls = cel === "FULLY CLOSED" ? "ok" : cel ? "warn" : "";
    set("dp-pill-ver",   `v${ctx.version || ctx.software_version || "—"}`);
    set("dp-pill-phase", `Phase ${ctx.current_phase || ctx.phase || "—"}`);
    set("dp-pill-inv",   `${ctx.hard_class_invariants || ctx.constitutional_invariants || "—"} invariants`);
    set("dp-pill-cel",   cel || "CEL —", celCls);
    set("dp-pill-innov", `${ctx.innovations_shipped || ctx.total_innovations_shipped || "—"} innovations`);
  }

  function renderChips() {
    const el = document.getElementById("dp-chips");
    if (!el) return;
    el.innerHTML = "";
    // Only show chips when no messages
    if (state.messages.length > 0) return;
    CHIPS.forEach((chip) => {
      const btn = document.createElement("button");
      btn.className = "dp-chip";
      btn.textContent = chip;
      btn.addEventListener("click", () => {
        const input = document.getElementById("dp-input");
        if (input) input.value = chip;
        doSend();
      });
      el.appendChild(btn);
    });
  }

  function renderMessages() {
    const el = document.getElementById("dp-messages");
    if (!el) return;
    el.innerHTML = "";

    if (state.messages.length === 0) {
      const empty = document.createElement("div");
      empty.className = "dp-empty";
      empty.innerHTML = `
        <div class="dp-empty-logo">DORK</div>
        <div class="dp-empty-sub">
          Governance Intelligence — ask anything about your constitutional history,
          invariant pressure, mutation lineage, or V10 readiness.
        </div>`;
      el.appendChild(empty);
      renderChips();
      return;
    }

    renderChips();

    state.messages.forEach((msg) => {
      const wrap = document.createElement("div");
      wrap.className = `dp-msg ${msg.role}`;
      wrap.setAttribute("data-msgid", msg.id);

      const label = document.createElement("div");
      label.className = "dp-label";
      label.textContent = msg.role === "user" ? "YOU" : "DORK";
      wrap.appendChild(label);

      const bubble = document.createElement("div");
      bubble.className = "dp-bubble";
      if (msg.streaming) {
        bubble.innerHTML =
          renderMd(msg.text) + '<span class="dp-cursor"></span>';
      } else {
        bubble.innerHTML = renderMd(msg.text);
      }
      wrap.appendChild(bubble);
      el.appendChild(wrap);
    });
  }

  function scrollBottom() {
    const el = document.getElementById("dp-messages");
    if (el) el.scrollTop = el.scrollHeight;
  }

  function enableInput() {
    const inp = document.getElementById("dp-input");
    const btn = document.getElementById("dp-send");
    if (inp) inp.disabled = false;
    if (btn) btn.disabled = false;
    if (inp) inp.focus();
  }

  function disableInput() {
    const inp = document.getElementById("dp-input");
    const btn = document.getElementById("dp-send");
    if (inp) inp.disabled = true;
    if (btn) btn.disabled = true;
  }

  function doSend() {
    const inp = document.getElementById("dp-input");
    if (!inp) return;
    const text = inp.value.trim();
    if (!text || state.streaming) return;
    inp.value = "";
    inp.style.height = "auto";
    disableInput();
    send(text);
  }

  function bindInput(root) {
    const inp = root.querySelector("#dp-input");
    const btn = root.querySelector("#dp-send");

    if (inp) {
      inp.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          doSend();
        }
        if (e.key === "Escape") {
          inp.value = "";
          inp.style.height = "auto";
        }
      });
      inp.addEventListener("input", () => {
        inp.style.height = "auto";
        inp.style.height = Math.min(inp.scrollHeight, 140) + "px";
      });
    }
    if (btn) btn.addEventListener("click", doSend);
  }

  /* ══════════════════════════════════════════════════════════════════════
     PUBLIC API
  ══════════════════════════════════════════════════════════════════════ */
  const panel = {
    /**
     * Called by Aponi render() each time the DORK tab is shown.
     * Returns a DOM element; reuses existing root if possible.
     */
    view() {
      injectStyles();

      if (!state._el) {
        state._el = buildRoot();
        bindInput(state._el);
        // Initial render
        renderMessages();
        renderGovBar();
        // Load gov context async
        loadGovCtx();
      }

      // Refresh gov bar on each tab switch
      loadGovCtx();

      // Show/hide offline warning
      const offlineEl = state._el.querySelector("#dp-offline");
      if (offlineEl) offlineEl.style.display = state.offline ? "block" : "none";

      return state._el;
    },

    /** Programmatically send a prompt (for deep-link / chip injection). */
    ask(prompt) {
      if (prompt && !state.streaming) {
        const inp = document.getElementById("dp-input");
        if (inp) inp.value = prompt;
        doSend();
      }
    },
  };

  global._dorkPanel = panel;
})(window);
