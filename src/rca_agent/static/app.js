'use strict';
const $ = id => document.getElementById(id);
let scenarios = [], report = null, busy = false, historyRequest = 0;
function node(tag, text = '', cls) {
  const element = document.createElement(tag);
  element.textContent = text;
  if (cls) element.className = cls;
  return element;
}
function show(id, on) { $(id).classList.toggle('hidden', !on); }
function refs(ids) {
  const container = node('div', '', 'refs');
  ids.forEach(id => {
    const anchor = node('a', id);
    anchor.href = '#evidence-' + encodeURIComponent(id);
    anchor.onclick = () => { $('evidence-section').open = true; };
    container.append(anchor);
  });
  return container;
}
function setBusy(value) {
  busy = value;
  $('report-panel').setAttribute('aria-busy', String(value));
  document.querySelectorAll('#form input, #form select, #form textarea, #form button, .history-item, #refresh').forEach(e => { e.disabled = value; });
}
async function loadHistory() {
  const sequence = ++historyRequest, customer = $('customer').value.trim();
  $('history').replaceChildren();
  $('history-label').textContent = customer ? 'Saved runs for ' + customer : 'Enter a customer ID to see saved runs.';
  if (!customer) return;
  try {
    const response = await fetch('/api/investigations?customerId=' + encodeURIComponent(customer));
    if (!response.ok) throw new Error('History unavailable.');
    const runs = await response.json();
    if (sequence !== historyRequest) return;
    if (!runs.length) $('history').append(node('p', 'No saved investigations yet.', 'small muted'));
    runs.forEach(run => {
      const button = node('button', run.transactionId + ' · ' + run.status.replaceAll('_', ' '), 'history-item');
      button.type = 'button'; button.disabled = busy;
      button.append(node('span', run.mode + ' · ' + run.outcome + ' · ' + new Date(run.createdAt).toLocaleString()));
      button.onclick = () => openHistory(run.investigationId);
      $('history').append(button);
    });
  } catch (error) {
    if (sequence === historyRequest) $('history').append(node('p', error.message, 'small error'));
  }
}
async function getAudit(id) {
  const response = await fetch('/api/investigations/' + encodeURIComponent(id));
  if (!response.ok) throw new Error('Saved audit could not be loaded.');
  return response.json();
}
function render(body, audit, meta = {}) {
  report = body;
  const observedEvidence = audit?.evidenceSnapshot?.map(item => item.evidence) || body.evidence;
  $('status').textContent = body.rootCause.status.replaceAll('_', ' ');
  $('status').classList.toggle('uncertain', ['suspected', 'insufficient_evidence'].includes(body.rootCause.status));
  $('title').textContent = body.customerId + ' / ' + body.transactionId;
  $('summary').textContent = body.rootCause.summary;
  $('root-refs').replaceChildren(refs(body.rootCause.evidenceIds));
  $('limitations').replaceChildren(...body.rootCause.limitations.map(text => node('p', text, 'limitation')));
  $('flow').replaceChildren();
  body.failureFlow.forEach(step => {
    const li = node('li', step.service + ' — ' + step.event);
    li.append(node('div', step.timestamp || 'Time unknown', 'small muted'), refs(step.evidenceIds));
    $('flow').append(li);
  });
  $('recommendations').replaceChildren();
  body.recommendation.forEach(item => {
    const li = node('li', item.action);
    li.append(node('div', item.reason, 'small muted'), refs(item.evidenceIds));
    $('recommendations').append(li);
  });
  $('evidence').replaceChildren();
  observedEvidence.forEach(item => {
    const element = node('div', '', 'evidence');
    element.id = 'evidence-' + item.evidenceId;
    element.append(node('strong', item.evidenceId), node('p', item.locator, 'small'), node('code', 'traceId: ' + (item.traceId || 'missing')), node('pre', item.excerpt));
    $('evidence').append(element);
  });
  $('json').textContent = JSON.stringify(body, null, 2);
  ['calls', 'coverage', 'runmeta', 'correlation', 'metrics'].forEach(id => $(id).replaceChildren());
  const d = audit?.diagnostics;
  const mode = d?.mode || meta.mode || 'unknown', outcome = d?.outcome || meta.outcome || 'unknown';
  $('execution').textContent = (mode === 'foundry' ? 'Azure Foundry · real LLM' : mode === 'replay' ? 'Offline replay · no LLM' : 'Mode unknown') + ' · Execution: ' + outcome.replaceAll('_', ' ');
  $('execution').className = 'small ' + (outcome === 'completed' ? 'muted' : 'error');
  const values = [[observedEvidence.length, 'Evidence records'], [new Set(observedEvidence.map(e => e.traceId).filter(Boolean)).size, 'Trace IDs'], [d ? (d.elapsedMs / 1000).toFixed(1) + 's' : '—', 'Investigation time']];
  values.forEach(([value, label]) => { const metric = node('div', '', 'metric'); metric.append(node('strong', String(value)), node('span', label)); $('metrics').append(metric); });
  if (d) {
    $('runmeta').append(node('p', d.modelTurns + ' model turns · ' + d.toolCalls.length + ' tool calls · Run ' + d.investigationId, 'small muted'));
    Object.entries(d.sourceCoverage).forEach(([source, coverage]) => $('coverage').append(node('span', source + ': ' + (coverage.complete ? 'complete' : coverage.status))));
    d.toolCalls.forEach(call => {
      const row = document.createElement('tr');
      [call.tool, call.status, call.eventCount, call.elapsedMs + ' ms'].forEach(value => row.append(node('td', String(value))));
      $('calls').append(row);
    });
    if (d.conversationId) $('runmeta').append(node('p', 'Foundry conversation: ' + d.conversationId, 'small muted'));
    d.errors.forEach(error => $('runmeta').append(node('p', error, 'small error')));
    (d.correlation.attempts || []).forEach(attempt => {
      const group = node('div', '', 'trace-group');
      group.append(node('strong', 'Attempt ' + (attempt.attemptId || 'unknown')));
      d.scope.traceMappings.filter(mapping => mapping.attemptId === attempt.attemptId).forEach(mapping => group.append(node('code', 'traceId: ' + mapping.traceId)));
      group.append(refs(attempt.evidenceIds));
      $('correlation').append(group);
    });
    d.correlation.causalEdges.forEach(edge => $('correlation').append(node('p', edge.from + ' → ' + edge.to, 'edge')));
    if (!d.correlation.causalEdges.length) $('correlation').append(node('p', 'No explicit causal links were observed.', 'small muted'));
    if (d.correlation.conflictingAttempts.length) $('correlation').append(node('p', 'Conflicting outcomes: ' + d.correlation.conflictingAttempts.join(', '), 'limitation'));
  } else {
    $('runmeta').append(node('p', 'Report available; execution audit could not be loaded.', 'small error'));
    $('correlation').append(node('p', 'Correlation audit unavailable.', 'small muted'));
  }
  show('empty', false); show('result', true);
}
async function openHistory(id) {
  if (busy) return;
  setBusy(true); $('error').textContent = ''; show('candidates', false);
  try {
    const audit = await getAudit(id);
    render(audit.report, audit);
    $('report-panel').scrollIntoView({block: 'start'});
  } catch (error) { $('error').textContent = error.message; }
  finally { setBusy(false); }
}
function showCandidates(candidates) {
  $('candidates').replaceChildren(node('p', 'Select a transaction to investigate:', 'small'));
  candidates.forEach(candidate => {
    const button = node('button', candidate.transaction_id + ' · ' + candidate.final_status, 'candidate');
    button.type = 'button';
    button.onclick = () => { $('transaction').value = candidate.transaction_id; $('form').requestSubmit(); };
    $('candidates').append(button);
  });
  show('candidates', true);
}
$('form').onsubmit = async event => {
  event.preventDefault(); if (busy) return;
  const payload = {customerId: $('customer').value.trim(), transactionId: $('transaction').value.trim() || null, fromTime: $('from').value, toTime: $('to').value, issueDescription: $('issue').value};
  setBusy(true); $('error').textContent = ''; report = null;
  show('empty', false); show('result', false); show('working', true); show('candidates', false);
  const start = Date.now(); $('elapsed').textContent = '0 seconds elapsed';
  const timer = setInterval(() => { $('elapsed').textContent = Math.floor((Date.now() - start) / 1000) + ' seconds elapsed'; }, 1000);
  try {
    const response = await fetch('/api/analyze', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
    const body = await response.json();
    if (response.status === 409 && body.detail?.candidates) {
      showCandidates(body.detail.candidates); show('empty', true); return;
    }
    if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : body.detail?.message || JSON.stringify(body.detail));
    const id = response.headers.get('X-Investigation-Id'); let audit = null;
    try { if (id) audit = await getAudit(id); } catch (error) { $('error').textContent = error.message; }
    render(body, audit, {mode: response.headers.get('X-RCA-Mode'), outcome: response.headers.get('X-RCA-Outcome')});
    await loadHistory();
  } catch (error) { $('error').textContent = error.message; show('empty', true); }
  finally { clearInterval(timer); show('working', false); setBusy(false); }
};
$('download').onclick = () => {
  if (!report) return;
  const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], {type: 'application/json'}));
  const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'rca-' + report.transactionId + '.json'; anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};
let printDetails = [];
window.addEventListener('beforeprint', () => { printDetails = [...document.querySelectorAll('#result details')].map(element => [element, element.open]); printDetails.forEach(([element]) => { element.open = true; }); });
window.addEventListener('afterprint', () => { printDetails.forEach(([element, open]) => { element.open = open; }); });
$('print').onclick = () => window.print();
$('refresh').onclick = loadHistory;
$('customer').onchange = loadHistory;
$('scenario').onchange = () => {
  const request = scenarios[Number($('scenario').value)].request;
  $('customer').value = request.customerId; $('transaction').value = request.transactionId;
  $('from').value = request.fromTime; $('to').value = request.toTime; $('issue').value = request.issueDescription;
  show('candidates', false); loadHistory();
};
async function load() {
  try {
    const response = await fetch('/health'); if (!response.ok) throw new Error('Health check failed.');
    const health = await response.json();
    $('mode').textContent = health.mode === 'replay' ? 'Offline replay · no LLM' : 'Foundry agent · live LLM mode';
    $('mode').classList.toggle('replay', health.mode === 'replay');
    if (!health.dataReady) $('error').textContent = 'Run rca seed before investigating.';
    const scenariosResponse = await fetch('/api/scenarios'); if (!scenariosResponse.ok) throw new Error('Scenarios could not be loaded.');
    scenarios = await scenariosResponse.json();
    scenarios.forEach((scenario, index) => { const option = node('option', scenario.name); option.value = index; $('scenario').append(option); });
    await loadHistory();
  } catch (error) { $('error').textContent = error.message; }
}
load();
