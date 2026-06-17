const form = document.querySelector('#proposal-form');
const responseElement = document.querySelector('#response');
const metadataInput = document.querySelector('#metadata');
const agentInput = document.querySelector('#agent_id');
const targetInput = document.querySelector('#target_path');
const pythonInput = document.querySelector('#python_content');

let lintTimer = null;

const lintPreviewNotice = document.createElement('p');
lintPreviewNotice.id = 'lint-preview-notice';
lintPreviewNotice.textContent = 'Lint preview is advisory and non-authorizing; proposal queue admission still requires governed validation.';
lintPreviewNotice.style.fontSize = '0.9rem';
lintPreviewNotice.style.opacity = '0.8';
form?.insertBefore(lintPreviewNotice, form.firstChild);

function setFieldLintMessage(field, message, severity = 'info') {
  if (!field) {
    return;
  }
  const id = `${field.id || field.name}-lint-preview`;
  let element = document.querySelector(`#${id}`);
  if (!element) {
    element = document.createElement('p');
    element.id = id;
    element.className = 'lint-preview-message';
    element.setAttribute('aria-live', 'polite');
    field.insertAdjacentElement('afterend', element);
  }
  element.dataset.severity = severity;
  element.textContent = message || '';
}

function clearFieldLintMessages() {
  for (const field of [metadataInput, agentInput, targetInput, pythonInput]) {
    setFieldLintMessage(field, '');
  }
}

function fieldForAnnotation(annotation) {
  const target = `${annotation?.field || annotation?.path || annotation?.target || ''}`.toLowerCase();
  if (target.includes('metadata')) {
    return metadataInput;
  }
  if (target.includes('agent')) {
    return agentInput;
  }
  if (target.includes('path') || target.includes('target')) {
    return targetInput;
  }
  return pythonInput;
}

function renderLintPreview(body) {
  clearFieldLintMessages();
  setFieldLintMessage(pythonInput, 'Lint preview complete: advisory only, not an authorization to execute.', 'info');

  const annotations = Array.isArray(body?.annotations) ? body.annotations : [];
  if (!annotations.length) {
    return;
  }

  const grouped = new Map();
  for (const annotation of annotations) {
    const field = fieldForAnnotation(annotation);
    const current = grouped.get(field) || [];
    current.push(annotation?.message || annotation?.detail || annotation?.code || JSON.stringify(annotation));
    grouped.set(field, current);
  }

  for (const [field, messages] of grouped.entries()) {
    setFieldLintMessage(field, messages.join(' | '), 'advisory');
  }
}

function showResponse(payload) {
  responseElement.textContent = JSON.stringify(payload, null, 2);
}

function parseMetadata(rawText) {
  try {
    const parsed = JSON.parse(rawText || '{}');
    if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') {
      return {
        ok: false,
        error: 'invalid_metadata_json',
        detail: 'Metadata must be a JSON object (for example: {"change_reason":"safety hardening"}).',
      };
    }
    return { ok: true, value: parsed };
  } catch (error) {
    return {
      ok: false,
      error: 'invalid_metadata_json',
      detail: `Metadata JSON parse failed: ${String(error)}`,
    };
  }
}

function buildProposalPayload(formData) {
  const agentId = (formData.get('agent_id') || '').toString().trim();
  const targetPath = (formData.get('target_path') || '').toString().trim();
  const pythonContent = (formData.get('python_content') || '').toString();
  const metadataResult = parseMetadata((formData.get('metadata') || '').toString());
  if (!metadataResult.ok) {
    return metadataResult;
  }
  const signature = (formData.get('signature') || 'unsigned-local-draft').toString().trim() || 'unsigned-local-draft';
  const nonce = (formData.get('nonce') || 'draft-nonce').toString().trim() || 'draft-nonce';

  const op = {
    op: 'replace_file_content',
    language: 'python',
    content: pythonContent,
    metadata: metadataResult.value,
  };

  return {
    ok: true,
    value: {
      agent_id: agentId,
      generation_ts: new Date().toISOString(),
      intent: 'governed_mutation_proposal_authoring',
      ops: [op],
      targets: [
        {
          agent_id: agentId,
          path: targetPath,
          target_type: 'python_module',
          ops: [op],
        },
      ],
      signature,
      nonce,
    },
  };
}

async function postToGovernedEndpoint(payload) {
  const endpoints = ['/api/mutations/proposals', '/mutation/propose'];
  let lastError = null;

  for (const endpoint of endpoints) {
    try {
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      const body = await response.json().catch(() => ({}));
      if (response.ok) {
        return { endpoint, status: response.status, body };
      }
      lastError = { endpoint, status: response.status, body };
    } catch (error) {
      lastError = { endpoint, error: String(error) };
    }
  }

  throw new Error(JSON.stringify(lastError, null, 2));
}

async function fetchLintPreview() {
  const metadataText = (metadataInput?.value || '').trim() || '{}';
  const metadataResult = parseMetadata(metadataText);
  if (!metadataResult.ok) {
    clearFieldLintMessages();
    setFieldLintMessage(metadataInput, metadataResult.detail, 'advisory');
    showResponse({ phase: 'lint_preview_invalid', metadata: metadataResult });
    return;
  }

  const lintPayload = {
    agent_id: (agentInput?.value || '').trim(),
    target_path: (targetInput?.value || '').trim(),
    python_content: pythonInput?.value || '',
    metadata: metadataResult.value,
  };

  const params = new URLSearchParams({
    ...lintPayload,
    metadata: JSON.stringify(metadataResult.value),
  });

  try {
    let response = await fetch('/api/lint/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(lintPayload),
    });

    if (response.status === 404 || response.status === 405) {
      response = await fetch(`/api/lint/preview?${params.toString()}`);
    }

    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      showResponse({ phase: 'lint_preview_error', status: response.status, body });
      return;
    }
    renderLintPreview(body);
    showResponse({ phase: 'lint_preview', advisory: true, authorizing: false, preview: body });
  } catch (error) {
    showResponse({ phase: 'lint_preview_error', error: String(error) });
  }
}

function scheduleLintPreview() {
  if (lintTimer) {
    window.clearTimeout(lintTimer);
  }
  lintTimer = window.setTimeout(() => {
    fetchLintPreview();
  }, 800);
}

for (const field of [metadataInput, agentInput, targetInput, pythonInput]) {
  field?.addEventListener('input', scheduleLintPreview);
}

form?.addEventListener('submit', async (event) => {
  event.preventDefault();
  const formData = new FormData(form);

  try {
    const payloadResult = buildProposalPayload(formData);
    if (!payloadResult.ok) {
      showResponse({ phase: 'validation_error', ...payloadResult });
      return;
    }

    showResponse({ phase: 'submitting', payload: payloadResult.value });
    const result = await postToGovernedEndpoint(payloadResult.value);
    showResponse({ phase: 'submitted', result });
  } catch (error) {
    showResponse({ phase: 'error', message: String(error) });
  }
});
