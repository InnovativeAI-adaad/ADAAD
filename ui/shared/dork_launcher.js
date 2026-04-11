(function initSharedDorkLauncher() {
  'use strict';

  if (window.__DORK_LAUNCHER_READY__) return;
  window.__DORK_LAUNCHER_READY__ = true;

  const DORK_PATH = '/ui/dork.html';
  const MODAL_ID = 'dork-launcher-modal';
  const BTN_ID = 'dork-launcher-btn';

  const state = {
    isDorkPage: false,
    lastActive: null,
    deepLinkPrompt: null,
    focusables: [],
  };

  const qs = (sel, root = document) => root.querySelector(sel);

  function parseDeepLink() {
    const params = new URLSearchParams(window.location.search);
    const wantsDork = params.get('dork') === '1';
    const prompt = (params.get('prompt') || '').trim();
    if (prompt) state.deepLinkPrompt = prompt;
    return { wantsDork, prompt };
  }

  function buildDorkUrl(prompt) {
    const url = new URL(DORK_PATH, window.location.origin);
    if (prompt) {
      url.searchParams.set('dork', '1');
      url.searchParams.set('prompt', prompt);
    }
    return url.toString();
  }

  function focusNativeDorkInput(prompt) {
    const input = qs('#user-input');
    if (!input) return false;
    if (prompt) input.value = prompt;
    input.focus();
    return true;
  }

  function injectStyles() {
    if (qs('#dork-launcher-style')) return;
    const style = document.createElement('style');
    style.id = 'dork-launcher-style';
    style.textContent = `
      #${BTN_ID} {
        position: fixed;
        right: max(14px, env(safe-area-inset-right));
        bottom: calc(max(14px, env(safe-area-inset-bottom)) + 8px);
        z-index: 2147483000;
        display: inline-flex;
        align-items: center;
        gap: 8px;
        border: 1px solid rgba(0, 217, 255, 0.4);
        background: linear-gradient(180deg, rgba(0, 217, 255, 0.16), rgba(0, 217, 255, 0.06));
        color: #e6edf3;
        border-radius: 999px;
        padding: 10px 14px;
        font: 600 13px/1.1 system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
        cursor: pointer;
        box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
      }
      #${BTN_ID}:focus-visible {
        outline: 2px solid #7dd3fc;
        outline-offset: 2px;
      }
      #${MODAL_ID} {
        position: fixed;
        inset: 0;
        z-index: 2147483001;
        background: rgba(5, 8, 16, 0.78);
        backdrop-filter: blur(4px);
        display: none;
        align-items: center;
        justify-content: center;
        padding: 12px;
      }
      #${MODAL_ID}.open { display: flex; }
      #${MODAL_ID} .dork-launcher-dialog {
        width: min(1100px, 100%);
        height: min(86dvh, 860px);
        border-radius: 14px;
        border: 1px solid rgba(255,255,255,0.16);
        overflow: hidden;
        background: #0a0f1a;
        display: flex;
        flex-direction: column;
      }
      #${MODAL_ID} .dork-launcher-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 10px 12px;
        color: #e6edf3;
        border-bottom: 1px solid rgba(255,255,255,0.1);
      }
      #${MODAL_ID} .dork-launcher-close {
        border: 1px solid rgba(255,255,255,0.2);
        background: rgba(255,255,255,0.04);
        color: inherit;
        border-radius: 8px;
        padding: 6px 10px;
        cursor: pointer;
      }
      #${MODAL_ID} iframe {
        flex: 1;
        width: 100%;
        border: 0;
        background: #080c14;
      }
      @media (max-width: 768px) {
        #${BTN_ID} {
          left: max(12px, env(safe-area-inset-left));
          right: max(12px, env(safe-area-inset-right));
          justify-content: center;
          font-size: 14px;
          padding: 12px;
        }
        #${MODAL_ID} { padding: 0; }
        #${MODAL_ID} .dork-launcher-dialog {
          width: 100%;
          height: 100dvh;
          border-radius: 0;
        }
      }
    `;
    document.head.appendChild(style);
  }

  function getModal() {
    return qs('#' + MODAL_ID);
  }

  function updateFocusables() {
    const modal = getModal();
    if (!modal) return;
    state.focusables = Array.from(
      modal.querySelectorAll('button,[href],input,select,textarea,[tabindex]:not([tabindex="-1"])')
    ).filter((el) => !el.hasAttribute('disabled') && el.getAttribute('aria-hidden') !== 'true');
  }

  function trapFocus(e) {
    const modal = getModal();
    if (!modal || !modal.classList.contains('open') || e.key !== 'Tab') return;
    updateFocusables();
    if (!state.focusables.length) return;
    const first = state.focusables[0];
    const last = state.focusables[state.focusables.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }

  function postFocusToIframe() {
    const iframe = qs('#dork-launcher-frame');
    if (!iframe || !iframe.contentWindow) return;
    iframe.contentWindow.postMessage({ type: 'dork-focus-input' }, window.location.origin);
  }

  function openLauncher(prompt) {
    if (state.isDorkPage) {
      focusNativeDorkInput(prompt || state.deepLinkPrompt);
      return;
    }

    const modal = getModal();
    if (!modal) return;
    const iframe = qs('#dork-launcher-frame');
    const seededPrompt = (prompt || state.deepLinkPrompt || '').trim();
    iframe.src = buildDorkUrl(seededPrompt);
    state.deepLinkPrompt = null;
    state.lastActive = document.activeElement;
    modal.classList.add('open');
    document.body.style.overflow = 'hidden';
    const closeBtn = qs('.dork-launcher-close', modal);
    closeBtn.focus();
    iframe.onload = () => postFocusToIframe();
  }

  function closeLauncher() {
    const modal = getModal();
    if (!modal || !modal.classList.contains('open')) return;
    modal.classList.remove('open');
    document.body.style.overflow = '';
    if (state.lastActive && typeof state.lastActive.focus === 'function') {
      state.lastActive.focus();
    }
  }

  function injectMarkup() {
    const btn = document.createElement('button');
    btn.id = BTN_ID;
    btn.type = 'button';
    btn.setAttribute('aria-label', 'Ask dork assistant');
    btn.setAttribute('title', 'Ask dork (Ctrl/Cmd + Shift + D)');
    btn.innerHTML = '<span aria-hidden="true">◉</span><span>Ask dork</span>';
    btn.addEventListener('click', () => openLauncher());
    document.body.appendChild(btn);

    if (state.isDorkPage) return;

    const modal = document.createElement('div');
    modal.id = MODAL_ID;
    modal.setAttribute('role', 'dialog');
    modal.setAttribute('aria-modal', 'true');
    modal.setAttribute('aria-label', 'dork assistant launcher');
    modal.innerHTML = `
      <div class="dork-launcher-dialog">
        <div class="dork-launcher-head">
          <strong>Ask dork</strong>
          <button class="dork-launcher-close" type="button" aria-label="Close dork launcher">Close</button>
        </div>
        <iframe id="dork-launcher-frame" title="dork assistant"></iframe>
      </div>
    `;
    modal.addEventListener('click', (e) => {
      if (e.target === modal) closeLauncher();
    });
    qs('.dork-launcher-close', modal).addEventListener('click', closeLauncher);
    document.body.appendChild(modal);
  }

  function bindGlobalShortcuts() {
    document.addEventListener('keydown', (e) => {
      const isShortcut = (e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === 'd';
      if (isShortcut) {
        e.preventDefault();
        openLauncher();
        return;
      }
      if (e.key === 'Escape') closeLauncher();
      trapFocus(e);
    });
  }

  function init() {
    state.isDorkPage = Boolean(qs('#user-input')) || /\/dork\.html$/i.test(window.location.pathname);
    injectStyles();
    injectMarkup();
    bindGlobalShortcuts();

    const { wantsDork, prompt } = parseDeepLink();
    if (wantsDork) {
      window.requestAnimationFrame(() => openLauncher(prompt));
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();
