/* ═══════════════════════════════════════════════════════════════════════════
   app.js  —  AI Jira Ticket Evaluator Frontend Logic
   ═══════════════════════════════════════════════════════════════════════════ */

// ─── State ──────────────────────────────────────────────────────────────────
let currentReport = null;

// ─── Agent pipeline step tracking ────────────────────────────────────────────
const AGENT_STEPS = [
  { id: 'prog-jira',     nodeId: 'node-jira',     label: 'Fetching Jira ticket…',         ms: 800 },
  { id: 'prog-github',   nodeId: 'node-github',   label: 'Fetching GitHub PR & diffs…',   ms: 800 },
  { id: 'prog-analysis', nodeId: 'node-analysis', label: 'Analyzing requirements vs code…', ms: 1000 },
  { id: 'prog-testgen',  nodeId: 'node-testgen',  label: 'Generating validation tests…',  ms: 600 },
  { id: 'prog-verdict',  nodeId: 'node-verdict',  label: 'Producing final verdict…',       ms: 600 },
];

// ─── Helpers ─────────────────────────────────────────────────────────────────
function $(id) { return document.getElementById(id); }

function setLoadingStep(index) {
  AGENT_STEPS.forEach((step, i) => {
    const el = $(step.id);
    const node = $(step.nodeId);
    if (!el) return;
    if (i < index) {
      el.className = 'progress-step done';
      if (node) { node.className = 'agent-node done'; }
    } else if (i === index) {
      el.className = 'progress-step active';
      if (node) { node.className = 'agent-node active'; }
      $('loadingTitle').textContent = step.label;
      $('loadingStatus').textContent = `Step ${i + 1} of ${AGENT_STEPS.length}`;
    } else {
      el.className = 'progress-step';
      if (node) { node.className = 'agent-node'; }
    }
  });
}

function resetAgentNodes() {
  AGENT_STEPS.forEach(step => {
    const node = $(step.nodeId);
    if (node) node.className = 'agent-node';
    const el = $(step.id);
    if (el) el.className = 'progress-step';
  });
}

async function simulateProgress(durationMs) {
  const totalMs = durationMs;
  const stepMs = totalMs / AGENT_STEPS.length;
  for (let i = 0; i < AGENT_STEPS.length; i++) {
    setLoadingStep(i);
    await delay(stepMs);
  }
}

function delay(ms) { return new Promise(r => setTimeout(r, ms)); }

// ─── UI State Transitions ─────────────────────────────────────────────────────
function showLoading() {
  $('loadingSection').style.display = 'block';
  $('resultsSection').style.display = 'none';
  $('errorSection').style.display = 'none';
  $('evaluateBtn').disabled = true;
  $('loadingSection').scrollIntoView({ behavior: 'smooth', block: 'center' });
}

function showResults() {
  $('loadingSection').style.display = 'none';
  $('resultsSection').style.display = 'block';
  $('errorSection').style.display = 'none';
  $('evaluateBtn').disabled = false;
  $('resultsSection').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function showError(title, message) {
  $('loadingSection').style.display = 'none';
  $('resultsSection').style.display = 'none';
  $('errorSection').style.display = 'block';
  $('evaluateBtn').disabled = false;
  $('errorTitle').textContent = title;
  $('errorMessage').textContent = message;
}

function resetUI() {
  $('loadingSection').style.display = 'none';
  $('resultsSection').style.display = 'none';
  $('errorSection').style.display = 'none';
  $('evaluateBtn').disabled = false;
  resetAgentNodes();
}

// ─── Render Functions ─────────────────────────────────────────────────────────

function animateConfidence(value) {
  const circumference = 201.06;
  const ring = $('ringFill');
  const numEl = $('confNum');
  const offset = circumference - (value / 100) * circumference;
  ring.style.strokeDashoffset = offset;

  // Color by confidence
  if (value >= 80) ring.style.stroke = '#10b981';
  else if (value >= 50) ring.style.stroke = '#f59e0b';
  else ring.style.stroke = '#ef4444';

  // Count-up animation
  let current = 0;
  const increment = value / 40;
  const timer = setInterval(() => {
    current = Math.min(current + increment, value);
    numEl.textContent = Math.round(current);
    if (current >= value) clearInterval(timer);
  }, 25);
}

function renderVerdict(report) {
  const badge = $('verdictBadge');
  badge.textContent = report.verdict;
  badge.className = `verdict-badge ${report.verdict}`;

  $('ticketInfo').innerHTML = `<strong>${report.jira_ticket.ticket_id}</strong> · ${escapeHtml(report.jira_ticket.title)}`;
  $('prInfo').textContent = `PR #${report.pull_request.pr_number} · ${escapeHtml(report.pull_request.title)} by @${report.pull_request.author}`;

  // Stats
  $('statTotalNum').textContent = report.total_requirements;
  $('statMetNum').textContent = report.met_count;
  $('statUnmetNum').textContent = report.unmet_count;

  // Summary
  $('summaryText').textContent = report.summary;

  setTimeout(() => animateConfidence(report.confidence), 300);
}

function renderRequirements(results) {
  const grid = $('requirementsGrid');
  grid.innerHTML = '';
  results.forEach((r, i) => {
    const metClass = r.met ? 'met' : 'unmet';
    const statusLabel = r.met ? '✅ Satisfied' : '❌ Not Satisfied';

    const evidenceHtml = (r.evidence || []).map(e => `
      <div class="evidence-item">
        <div class="evidence-file">📄 ${escapeHtml(e.file)}${e.start_line ? ` · L${e.start_line}${e.end_line ? `–${e.end_line}` : ''}` : ''}</div>
        <div class="evidence-snippet">${escapeHtml(e.snippet)}</div>
        <div class="evidence-rationale">${escapeHtml(e.rationale)}</div>
      </div>
    `).join('');

    const card = document.createElement('div');
    card.className = `req-card ${metClass} fade-in`;
    card.style.animationDelay = `${i * 60}ms`;
    card.innerHTML = `
      <div class="req-header">
        <span class="req-id">${escapeHtml(r.requirement_id)}</span>
        <span class="req-status ${metClass}">${statusLabel}</span>
        <span class="req-confidence">${r.confidence}% confidence</span>
      </div>
      <div class="req-desc">${escapeHtml(r.description)}</div>
      ${r.notes ? `<div class="req-notes">💬 ${escapeHtml(r.notes)}</div>` : ''}
      ${evidenceHtml ? `<div class="evidence-list">${evidenceHtml}</div>` : ''}
    `;
    grid.appendChild(card);
  });
}

function renderTests(tests) {
  if (!tests || tests.length === 0) {
    $('testsCard').style.display = 'none';
    return;
  }
  $('testsCard').style.display = 'block';
  const grid = $('testsGrid');
  grid.innerHTML = '';
  tests.forEach((t, i) => {
    const card = document.createElement('div');
    card.className = 'test-card fade-in';
    card.style.animationDelay = `${i * 60}ms`;
    card.innerHTML = `
      <div class="test-header">
        <span class="test-name">def ${escapeHtml(t.test_name)}()</span>
        <span class="test-req-id">→ ${escapeHtml(t.requirement_id)}</span>
      </div>
      <pre class="test-code">${escapeHtml(t.test_code)}</pre>
    `;
    grid.appendChild(card);
  });
}

function renderFiles(files) {
  const grid = $('filesGrid');
  grid.innerHTML = '';
  files.forEach((f, i) => {
    const item = document.createElement('div');
    item.className = 'file-item fade-in';
    item.style.animationDelay = `${i * 40}ms`;
    item.innerHTML = `
      <span class="file-status-badge ${f.status}">${f.status}</span>
      <span class="file-name">${escapeHtml(f.filename)}</span>
      <span class="file-stats">
        <span class="add">+${f.additions}</span> / <span class="del">-${f.deletions}</span>
      </span>
    `;
    grid.appendChild(item);
  });
}

function renderReport(report) {
  currentReport = report;
  renderVerdict(report);
  renderRequirements(report.requirement_results);
  renderTests(report.generated_tests);
  renderFiles(report.pull_request.files_changed);
  showResults();
}

// ─── API Calls ────────────────────────────────────────────────────────────────

async function runEvaluation() {
  const prUrl = $('prUrl').value.trim();
  const jiraId = $('jiraId').value.trim();

  if (!prUrl) { alert('Please enter a GitHub PR URL.'); return; }
  if (!jiraId) { alert('Please enter a Jira Ticket ID.'); return; }

  showLoading();
  resetAgentNodes();

  // Simulate pipeline progress visually while API call runs
  const progressPromise = simulateProgress(4000);

  try {
    const response = await fetch('/evaluate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ github_pr_url: prUrl, jira_ticket_id: jiraId }),
    });

    await progressPromise; // ensure loading animation finishes

    if (!response.ok) {
      const err = await response.json().catch(() => ({ detail: 'Unknown error' }));
      throw new Error(err.detail || `HTTP ${response.status}`);
    }

    const report = await response.json();
    // Mark all nodes done
    AGENT_STEPS.forEach(s => {
      const el = $(s.id); if (el) el.className = 'progress-step done';
      const node = $(s.nodeId); if (node) node.className = 'agent-node done';
    });
    await delay(300);
    renderReport(report);

  } catch (err) {
    showError('Evaluation Failed', err.message);
  }
}

async function runDemo() {
  showLoading();
  resetAgentNodes();

  $('loadingTitle').textContent = 'Running demo evaluation…';
  $('loadingStatus').textContent = 'Using built-in sample data (no API keys needed)';

  const progressPromise = simulateProgress(3000);

  try {
    const response = await fetch('/demo');
    await progressPromise;

    if (!response.ok) {
      const err = await response.json().catch(() => ({ detail: 'Unknown error' }));
      throw new Error(err.detail || `HTTP ${response.status}`);
    }

    const report = await response.json();

    // Prefill the form with demo values
    $('prUrl').value = 'https://github.com/demo-org/demo-repo/pull/42';
    $('jiraId').value = 'PROJ-123';

    AGENT_STEPS.forEach(s => {
      const el = $(s.id); if (el) el.className = 'progress-step done';
      const node = $(s.nodeId); if (node) node.className = 'agent-node done';
    });
    await delay(300);
    renderReport(report);

  } catch (err) {
    showError('Demo Failed', err.message);
  }
}

// ─── Utility ──────────────────────────────────────────────────────────────────
function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
