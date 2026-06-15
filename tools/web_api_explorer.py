#!/usr/bin/env python3
"""
tools/web_api_explorer.py
==========================
Веб-інтерфейс для тестування API маркетплейсів.

Запуск (на сервері):
    cd /home/tek/agent-system && source venv/bin/activate
    nohup python3 tools/web_api_explorer.py > /tmp/web_explorer.log 2>&1 &

Доступ: http://100.82.24.112:5555
"""

import os
import sys
import json
import time
import requests
import psycopg2
import psycopg2.extras
from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / '.env')

app = Flask(__name__)
CORS(app)

DB_DSN = 'host=localhost port=5432 dbname=agentdb user=agentadmin password=1'

MARKETPLACE_CONFIG = {
    'epicentr': {
        'label': 'Єпіцентр',
        'base_url': 'https://merchant-api.epicentrm.com.ua',
        'auth_type': 'bearer',
        'token_env': 'EPICENTR_TOKEN',
        'verify_ssl': True,
    },
    'prom': {
        'label': 'Prom.ua',
        'base_url': 'https://my.prom.ua/api/v1',
        'auth_type': 'bearer',
        'token_env': 'PROM_API_TOKEN',
        'verify_ssl': True,
    },
    'rozetka': {
        'label': 'Rozetka',
        'base_url': 'https://api-seller.rozetka.com.ua',
        'auth_type': 'bearer',
        'token_env': 'ROZETKA_API_TOKEN',
        'verify_ssl': False,
    },
    'nova_poshta': {
        'label': 'Нова Пошта',
        'base_url': 'https://api.novaposhta.ua/v2.0/json',
        'auth_type': 'apikey',
        'token_env': 'NP_API_KEY',
        'verify_ssl': True,
    },
}

QUICK_COMMANDS = [
    {
        'label': 'Єпіцентр — замовлення',
        'marketplace': 'epicentr',
        'method': 'GET',
        'url': '/v3/oms/orders',
        'body': '',
        'params': '?status=pending&limit=10',
    },
    {
        'label': 'Єпіцентр — категорії PIM',
        'marketplace': 'epicentr',
        'method': 'GET',
        'url': '/v2/pim/categories',
        'body': '',
        'params': '?limit=20&page=1',
    },
    {
        'label': 'Єпіцентр — attribute sets',
        'marketplace': 'epicentr',
        'method': 'GET',
        'url': '/v2/pim/attribute-sets',
        'body': '',
        'params': '?limit=10&page=1',
    },
    {
        'label': 'Rozetka — нові замовлення',
        'marketplace': 'rozetka',
        'method': 'GET',
        'url': '/orders/search',
        'body': '',
        'params': '?types=4',
    },
    {
        'label': 'Rozetka — список замовлень',
        'marketplace': 'rozetka',
        'method': 'GET',
        'url': '/orders/list',
        'body': '',
        'params': '',
    },
    {
        'label': 'Prom — замовлення',
        'marketplace': 'prom',
        'method': 'GET',
        'url': '/orders/list',
        'body': '',
        'params': '',
    },
    {
        'label': 'Нова Пошта — міста',
        'marketplace': 'nova_poshta',
        'method': 'POST',
        'url': '',
        'body': json.dumps({
            'apiKey': '{{NP_API_KEY}}',
            'modelName': 'Address',
            'calledMethod': 'getCities',
            'methodProperties': {'FindByString': 'Київ', 'Limit': '5'}
        }, ensure_ascii=False, indent=2),
        'params': '',
    },
]

HTML = r'''<!DOCTYPE html>
<html lang="uk">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>API Explorer — Dropshipping</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Segoe UI', system-ui, sans-serif; background: #0f1117; color: #e2e8f0; height: 100vh; overflow: hidden; display: flex; flex-direction: column; }

  .header { background: linear-gradient(135deg, #1a1f2e 0%, #16213e 100%); padding: 12px 20px; border-bottom: 1px solid #2d3748; display: flex; align-items: center; gap: 12px; flex-shrink: 0; }
  .header h1 { font-size: 18px; font-weight: 700; color: #63b3ed; }
  .header .badge { background: #2d3748; color: #68d391; padding: 2px 10px; border-radius: 12px; font-size: 11px; font-family: monospace; }
  .token-status { display: flex; gap: 6px; flex-wrap: wrap; margin-left: auto; }
  .token-chip { font-size: 11px; padding: 2px 8px; border-radius: 10px; font-family: monospace; }
  .token-ok { background: #1a3a2a; color: #68d391; border: 1px solid #2f6546; }
  .token-missing { background: #3a1a1a; color: #fc8181; border: 1px solid #6b2222; }

  /* 3-column layout */
  .layout { display: grid; grid-template-columns: 220px 1fr 1fr; flex: 1; overflow: hidden; }

  /* ── LEFT: COMMAND SEARCH ── */
  .sidebar { background: #1a1f2e; border-right: 1px solid #2d3748; display: flex; flex-direction: column; overflow: hidden; }
  .sidebar-inner { flex: 1; overflow-y: auto; padding: 10px; }
  .sidebar h3 { font-size: 10px; text-transform: uppercase; letter-spacing: 1px; color: #718096; margin-bottom: 8px; margin-top: 12px; padding: 0 2px; }
  .sidebar h3:first-child { margin-top: 0; }
  #cmdSearch { width: 100%; background: #0f1117; border: 1px solid #3d4a5c; color: #e2e8f0; padding: 8px 10px; border-radius: 6px; font-size: 12px; margin-bottom: 8px; }
  #cmdSearch:focus { outline: none; border-color: #63b3ed; }
  .cmd-item { display: block; width: 100%; text-align: left; background: #2d3748; border: 1px solid #3d4a5c; color: #cbd5e0; padding: 7px 10px; border-radius: 6px; cursor: pointer; margin-bottom: 4px; font-size: 11px; transition: all 0.12s; line-height: 1.4; }
  .cmd-item:hover { background: #3d4a5c; border-color: #63b3ed; color: #fff; }
  .cmd-item .mtag { font-family: monospace; font-size: 9px; font-weight: 700; padding: 1px 5px; border-radius: 3px; margin-right: 5px; }
  .m-GET { background: #22543d; color: #68d391; }
  .m-POST { background: #2a4365; color: #63b3ed; }
  .m-PUT { background: #4a2535; color: #fc8181; }
  .m-PATCH { background: #4a3820; color: #f6ad55; }
  .m-DELETE { background: #5a1a1a; color: #fc8181; }
  .cmd-mkt { font-size: 9px; color: #718096; display: block; margin-top: 2px; }
  #cmdCount { font-size: 10px; color: #718096; margin-bottom: 6px; }

  /* ── CENTER: REQUEST FORM ── */
  .request-panel { border-right: 1px solid #2d3748; display: flex; flex-direction: column; overflow-y: auto; padding: 14px; gap: 10px; }
  .card { background: #1a1f2e; border: 1px solid #2d3748; border-radius: 10px; padding: 16px; }
  .card-title { font-size: 11px; font-weight: 600; color: #a0aec0; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 12px; }

  .form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 10px; }
  .form-group { display: flex; flex-direction: column; gap: 5px; }
  .form-group label { font-size: 11px; color: #718096; font-weight: 500; }
  select, input, textarea { background: #0f1117; border: 1px solid #3d4a5c; color: #e2e8f0; padding: 8px 10px; border-radius: 6px; font-size: 12px; width: 100%; transition: border-color 0.12s; font-family: inherit; }
  select:focus, input:focus, textarea:focus { outline: none; border-color: #63b3ed; }
  textarea { resize: vertical; font-family: 'Fira Code', 'Consolas', monospace; }

  .url-row { display: grid; grid-template-columns: 80px 1fr 1fr; gap: 8px; margin-bottom: 10px; align-items: end; }

  .btn { padding: 8px 16px; border: none; border-radius: 6px; cursor: pointer; font-size: 13px; font-weight: 600; transition: all 0.12s; }
  .btn-primary { background: linear-gradient(135deg, #3182ce, #2b6cb0); color: white; }
  .btn-primary:hover { background: linear-gradient(135deg, #4299e1, #3182ce); }
  .btn-secondary { background: #2d3748; color: #a0aec0; }
  .btn-secondary:hover { background: #3d4a5c; color: #fff; }
  .btn-success { background: #276749; color: #68d391; }
  .btn-success:hover { background: #2f855a; }
  .btn-row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  .spinner { display: none; width: 16px; height: 16px; border: 2px solid #3d4a5c; border-top-color: #63b3ed; border-radius: 50%; animation: spin 0.7s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* ── RIGHT: RESPONSE PANEL ── */
  .response-panel { display: flex; flex-direction: column; padding: 14px; gap: 8px; overflow: hidden; }
  .resp-header { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; flex-shrink: 0; }
  .status-badge { padding: 3px 10px; border-radius: 16px; font-size: 11px; font-weight: 700; font-family: monospace; }
  .status-2xx { background: #22543d; color: #68d391; }
  .status-4xx { background: #4a2535; color: #fc8181; }
  .status-5xx { background: #5a1a1a; color: #fc8181; }
  .elapsed { font-size: 12px; color: #718096; }
  #itemCount { font-size: 11px; color: #718096; }

  .result-tabs { display: flex; gap: 4px; border-bottom: 1px solid #2d3748; padding-bottom: 6px; flex-shrink: 0; }
  .tab-btn { padding: 5px 12px; border: 1px solid transparent; border-radius: 5px; background: none; color: #718096; cursor: pointer; font-size: 11px; font-weight: 500; transition: all 0.12s; }
  .tab-btn.active { background: #2d3748; color: #e2e8f0; border-color: #3d4a5c; }

  #response-body {
    flex: 1;
    width: 100%;
    height: 70vh;
    resize: none;
    background: #0a0e1a;
    color: #a8d8a8;
    border: 1px solid #2d3748;
    border-radius: 8px;
    padding: 14px;
    font-family: 'Fira Code', 'Consolas', 'Courier New', monospace;
    font-size: 12px;
    line-height: 1.6;
    tab-size: 2;
  }
  #response-body:focus { outline: none; border-color: #4a5568; }

  .resp-btn-row { display: flex; gap: 8px; align-items: center; flex-shrink: 0; }
  #saveStatus { font-size: 11px; color: #718096; }
</style>
</head>
<body>

<div class="header">
  <h1>⚡ API Explorer</h1>
  <span class="badge">Dropshipping Tools</span>
  <div class="token-status" id="tokenStatus"></div>
</div>

<div class="layout">

  <!-- LEFT: COMMAND SEARCH -->
  <div class="sidebar">
    <div class="sidebar-inner">
      <h3>🔍 Пошук команди</h3>
      <input type="text" id="cmdSearch" placeholder="orders, categories, ttn..." oninput="searchCommands(this.value)">
      <div id="cmdCount"></div>
      <div id="cmdResults">
        <!-- Швидкі запити -->
        <h3>Швидкі запити</h3>
        {% for cmd in quick_commands %}
        <button class="cmd-item" onclick="loadQuick({{ loop.index0 }})">
          <span class="mtag m-{{ cmd.method }}">{{ cmd.method }}</span>{{ cmd.label }}
          <span class="cmd-mkt">{{ cmd.marketplace }}</span>
        </button>
        {% endfor %}
      </div>
    </div>
  </div>

  <!-- CENTER: REQUEST FORM -->
  <div class="request-panel">
    <div class="card">
      <div class="card-title">Запит</div>

      <div class="form-row">
        <div class="form-group">
          <label>Маркетплейс</label>
          <select id="marketplace" onchange="onMarketplaceChange(this.value)">
            <option value="">— оберіть —</option>
            {% for key, cfg in marketplaces.items() %}
            <option value="{{ key }}">{{ cfg.label }}</option>
            {% endfor %}
          </select>
        </div>
        <div class="form-group">
          <label>Метод з бази</label>
          <select id="methodSelect" onchange="fillFromMethod(this)">
            <option value="">— оберіть метод —</option>
          </select>
        </div>
      </div>

      <div class="url-row">
        <div class="form-group">
          <label>HTTP</label>
          <select id="httpMethod">
            <option>GET</option>
            <option>POST</option>
            <option>PUT</option>
            <option>PATCH</option>
            <option>DELETE</option>
          </select>
        </div>
        <div class="form-group">
          <label>Endpoint (шлях)</label>
          <input type="text" id="endpointPath" placeholder="/v3/oms/orders">
        </div>
        <div class="form-group">
          <label>Query params</label>
          <input type="text" id="queryParams" placeholder="?limit=10&page=1">
        </div>
      </div>

      <div class="form-group" style="margin-bottom:10px">
        <label>JSON Body (для POST/PUT/PATCH)</label>
        <textarea id="jsonBody" rows="5" placeholder='{ "key": "value" }'></textarea>
      </div>

      <div class="form-group" style="margin-bottom:12px">
        <label>Додаткові Headers (JSON, опціонально)</label>
        <textarea id="extraHeaders" rows="2" placeholder='{ "X-Custom": "value" }'></textarea>
      </div>

      <div class="btn-row">
        <button class="btn btn-primary" onclick="executeRequest()">▶ Виконати</button>
        <button class="btn btn-secondary" onclick="clearResult()">✕ Очистити</button>
        <div class="spinner" id="spinner"></div>
        <span id="statusText" style="font-size:12px; color:#718096"></span>
      </div>
    </div>

    <!-- URL preview -->
    <div style="background:#1a1f2e; border:1px solid #2d3748; border-radius:8px; padding:10px 14px; font-family:monospace; font-size:11px; color:#718096; word-break:break-all;">
      <span style="color:#4a5568">URL: </span><span id="urlPreview" style="color:#63b3ed">—</span>
    </div>
  </div>

  <!-- RIGHT: RESPONSE PANEL -->
  <div class="response-panel">
    <div class="resp-header">
      <span class="status-badge" id="statusBadge" style="display:none"></span>
      <span class="elapsed" id="elapsedTime"></span>
      <span id="itemCount"></span>
    </div>

    <div class="result-tabs">
      <button class="tab-btn active" onclick="showTab('body')">Body</button>
      <button class="tab-btn" onclick="showTab('headers')">Headers</button>
      <button class="tab-btn" onclick="showTab('request')">Запит</button>
      <button class="tab-btn" onclick="showTab('timing')">Час</button>
    </div>

    <textarea id="response-body" readonly placeholder="← Оберіть маркетплейс, метод та натисніть «Виконати»"></textarea>

    <div class="resp-btn-row">
      <button class="btn btn-secondary" onclick="copyResult()" style="font-size:12px; padding:6px 14px">📋 Копіювати</button>
      <button class="btn btn-secondary" onclick="downloadResult()" style="font-size:12px; padding:6px 14px">⬇ Зберегти JSON</button>
      <button class="btn btn-success" onclick="saveToDb()" style="font-size:12px; padding:6px 14px">💾 Зберегти в БД</button>
      <span id="saveStatus"></span>
    </div>
  </div>

</div><!-- .layout -->

<script>
const QUICK = {{ quick_json }};
let currentTabs = { body: '', headers: '', request: '', timing: '' };
let activeTab = 'body';
let lastResult = null;   // зберігаємо для "Зберегти в БД"

// ── Токени ──────────────────────────────────────────────────────────────────
fetch('/api/tokens').then(r => r.json()).then(data => {
  const el = document.getElementById('tokenStatus');
  for (const [key, ok] of Object.entries(data)) {
    const chip = document.createElement('span');
    chip.className = 'token-chip ' + (ok ? 'token-ok' : 'token-missing');
    chip.textContent = key + (ok ? ' ✓' : ' ✗');
    el.appendChild(chip);
  }
});

// ── URL preview ──────────────────────────────────────────────────────────────
function updateUrlPreview() {
  const marketplace = document.getElementById('marketplace').value;
  const path = document.getElementById('endpointPath').value.trim();
  const params = document.getElementById('queryParams').value.trim();
  if (!marketplace || !path) { document.getElementById('urlPreview').textContent = '—'; return; }
  const bases = {{ base_urls_json }};
  const base = bases[marketplace] || '';
  const full = base.replace(/\/$/, '') + '/' + path.replace(/^\//, '') + (params.startsWith('?') ? params : (params ? '?' + params : ''));
  document.getElementById('urlPreview').textContent = full;
}
['marketplace', 'endpointPath', 'queryParams'].forEach(id => {
  document.getElementById(id).addEventListener('input', updateUrlPreview);
  document.getElementById(id).addEventListener('change', updateUrlPreview);
});

// ── Пошук команд ────────────────────────────────────────────────────────────
let searchTimer = null;
function searchCommands(q) {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => _doSearch(q), 220);
}

function _doSearch(q) {
  if (!q.trim()) {
    // Показуємо швидкі запити назад
    renderQuickCommands();
    document.getElementById('cmdCount').textContent = '';
    return;
  }
  const marketplace = document.getElementById('marketplace').value;
  let url = '/api/commands?q=' + encodeURIComponent(q);
  if (marketplace) url += '&marketplace=' + marketplace;

  fetch(url).then(r => r.json()).then(data => {
    if (data.error) return;
    document.getElementById('cmdCount').textContent = `${data.length} результатів`;
    const el = document.getElementById('cmdResults');
    el.innerHTML = '';
    if (!data.length) { el.innerHTML = '<div style="font-size:11px;color:#718096;padding:4px">Нічого не знайдено</div>'; return; }
    data.forEach(cmd => {
      const btn = document.createElement('button');
      btn.className = 'cmd-item';
      const mktLabels = { epicentr: 'Єпіцентр', rozetka: 'Rozetka', prom: 'Prom.ua', nova_poshta: 'НП' };
      btn.innerHTML = `<span class="mtag m-${cmd.http_method}">${cmd.http_method}</span>${cmd.method_name}
        <span class="cmd-mkt">${mktLabels[cmd.marketplace] || cmd.marketplace} — ${cmd.endpoint}</span>`;
      btn.onclick = () => loadFromDb(cmd);
      el.appendChild(btn);
    });
  });
}

function renderQuickCommands() {
  const el = document.getElementById('cmdResults');
  el.innerHTML = '<h3 style="font-size:10px;text-transform:uppercase;letter-spacing:1px;color:#718096;margin-bottom:8px">Швидкі запити</h3>';
  QUICK.forEach((cmd, idx) => {
    const btn = document.createElement('button');
    btn.className = 'cmd-item';
    btn.innerHTML = `<span class="mtag m-${cmd.method}">${cmd.method}</span>${cmd.label}<span class="cmd-mkt">${cmd.marketplace}</span>`;
    btn.onclick = () => loadQuick(idx);
    el.appendChild(btn);
  });
}

function loadFromDb(cmd) {
  document.getElementById('marketplace').value = cmd.marketplace;
  document.getElementById('httpMethod').value = cmd.http_method || 'GET';
  document.getElementById('endpointPath').value = cmd.endpoint || '';
  document.getElementById('queryParams').value = '';
  if (cmd.input_params) {
    try { document.getElementById('jsonBody').value = JSON.stringify(cmd.input_params, null, 2); }
    catch(e) { document.getElementById('jsonBody').value = ''; }
  } else {
    document.getElementById('jsonBody').value = '';
  }
  loadMethods(cmd.marketplace);
  updateUrlPreview();
}

// ── Методи з бази ────────────────────────────────────────────────────────────
function onMarketplaceChange(marketplace) {
  if (marketplace) loadMethods(marketplace);
  updateUrlPreview();
}

function loadMethods(marketplace) {
  if (!marketplace) return;
  fetch('/api/methods?marketplace=' + marketplace)
    .then(r => r.json())
    .then(data => {
      const sel = document.getElementById('methodSelect');
      sel.innerHTML = '<option value="">— оберіть метод —</option>';
      (data.error ? [] : data).forEach(m => {
        const opt = document.createElement('option');
        opt.value = JSON.stringify(m);
        opt.textContent = `[${m.http_method}] ${m.method_name} — ${m.endpoint}`;
        sel.appendChild(opt);
      });
    });
}

function fillFromMethod(sel) {
  if (!sel.value) return;
  const m = JSON.parse(sel.value);
  document.getElementById('httpMethod').value = m.http_method || 'GET';
  document.getElementById('endpointPath').value = m.endpoint || '';
  document.getElementById('queryParams').value = '';
  document.getElementById('jsonBody').value = m.input_params
    ? JSON.stringify(m.input_params, null, 2)
    : '';
  updateUrlPreview();
}

function loadQuick(idx) {
  const cmd = QUICK[idx];
  document.getElementById('marketplace').value = cmd.marketplace;
  document.getElementById('httpMethod').value = cmd.method;
  document.getElementById('endpointPath').value = cmd.url;
  document.getElementById('queryParams').value = cmd.params || '';
  document.getElementById('jsonBody').value = cmd.body || '';
  loadMethods(cmd.marketplace);
  updateUrlPreview();
}

// ── Виконання запиту ─────────────────────────────────────────────────────────
async function executeRequest() {
  const marketplace = document.getElementById('marketplace').value;
  const method      = document.getElementById('httpMethod').value;
  const path        = document.getElementById('endpointPath').value.trim();
  const params      = document.getElementById('queryParams').value.trim();
  const bodyText    = document.getElementById('jsonBody').value.trim();
  const extraText   = document.getElementById('extraHeaders').value.trim();

  if (!marketplace) { alert('Оберіть маркетплейс'); return; }
  if (!path && marketplace !== 'nova_poshta') { alert('Введіть endpoint'); return; }

  let body = null;
  if (bodyText) {
    try { body = JSON.parse(bodyText); }
    catch(e) { alert('Помилка JSON body: ' + e.message); return; }
  }

  let extraHeaders = {};
  if (extraText) {
    try { extraHeaders = JSON.parse(extraText); }
    catch(e) { alert('Помилка Extra Headers: ' + e.message); return; }
  }

  document.getElementById('spinner').style.display = 'block';
  document.getElementById('statusText').textContent = 'Виконую...';
  document.getElementById('statusBadge').style.display = 'none';
  document.getElementById('elapsedTime').textContent = '';
  document.getElementById('itemCount').textContent = '';
  document.getElementById('saveStatus').textContent = '';
  setTabContent('body', '⏳ Очікую відповіді...');

  const startTime = Date.now();
  try {
    const res = await fetch('/api/proxy', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ marketplace, method, path, params, body, extraHeaders })
    });
    const elapsed = ((Date.now() - startTime) / 1000).toFixed(2);
    const data = await res.json();

    document.getElementById('spinner').style.display = 'none';
    document.getElementById('statusText').textContent = '';
    document.getElementById('elapsedTime').textContent = `⏱ ${elapsed}с`;

    const badge = document.getElementById('statusBadge');
    badge.style.display = 'inline-block';
    badge.textContent = data.status_code || '???';
    const sc = data.status_code || 0;
    badge.className = 'status-badge ' + (sc >= 500 ? 'status-5xx' : sc >= 400 ? 'status-4xx' : 'status-2xx');

    // Body tab — plain pretty JSON
    let bodyStr = '';
    let parsedBody = null;
    if (data.error) {
      bodyStr = '❌ ' + data.error;
    } else if (data.body !== undefined) {
      try {
        parsedBody = typeof data.body === 'string' ? JSON.parse(data.body) : data.body;
        bodyStr = JSON.stringify(parsedBody, null, 2);
        const items = parsedBody?.data?.items || parsedBody?.items || parsedBody?.content?.items
                   || (Array.isArray(parsedBody) ? parsedBody : null);
        if (items) document.getElementById('itemCount').textContent = `${items.length} items`;
      } catch(e) {
        bodyStr = String(data.body);
      }
    }

    // Headers tab
    const headersStr = data.headers
      ? JSON.stringify(data.headers, null, 2)
      : '(немає)';

    // Request tab
    const requestStr = [
      `${method} ${data.full_url || path + params}`,
      '',
      'Headers відправлено:',
      JSON.stringify(data.request_headers || {}, null, 2),
      '',
      'Body відправлено:',
      bodyText || '(none)',
    ].join('\n');

    // Timing tab
    const timingStr = [
      `Час виконання:  ${data.elapsed ?? elapsed} с`,
      `HTTP метод:     ${method}`,
      `URL:            ${data.full_url || path}`,
      `Статус:         ${data.status_code}`,
      `Розмір body:    ${JSON.stringify(data.body ?? '').length} байт`,
    ].join('\n');

    setTabContent('body',    bodyStr);
    setTabContent('headers', headersStr);
    setTabContent('request', requestStr);
    setTabContent('timing',  timingStr);
    showTab('body');

    // Зберігаємо для кнопки "Зберегти в БД"
    lastResult = {
      marketplace,
      method,
      endpoint: path,
      params,
      status_code: data.status_code,
      response_body: parsedBody,
      elapsed: data.elapsed ?? parseFloat(elapsed),
    };

  } catch(e) {
    document.getElementById('spinner').style.display = 'none';
    document.getElementById('statusText').textContent = '❌ Помилка';
    setTabContent('body', '❌ Помилка зʼєднання: ' + e.message);
  }
}

// ── Таби ─────────────────────────────────────────────────────────────────────
function setTabContent(tab, content) {
  currentTabs[tab] = content;
  if (activeTab === tab) {
    document.getElementById('response-body').value = content || '';
  }
}

function showTab(tab) {
  activeTab = tab;
  document.querySelectorAll('.tab-btn').forEach((btn, i) => {
    btn.classList.toggle('active', ['body', 'headers', 'request', 'timing'][i] === tab);
  });
  document.getElementById('response-body').value = currentTabs[tab] || '';
}

function clearResult() {
  currentTabs = { body: '', headers: '', request: '', timing: '' };
  document.getElementById('response-body').value = '';
  document.getElementById('statusBadge').style.display = 'none';
  document.getElementById('elapsedTime').textContent = '';
  document.getElementById('itemCount').textContent = '';
  document.getElementById('saveStatus').textContent = '';
  lastResult = null;
}

// ── Зберегти в БД ────────────────────────────────────────────────────────────
async function saveToDb() {
  if (!lastResult) { alert('Спочатку виконайте запит'); return; }
  const el = document.getElementById('saveStatus');
  el.textContent = '⏳ Зберігаю...';
  try {
    const res = await fetch('/api/save-log', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(lastResult),
    });
    const data = await res.json();
    el.textContent = data.ok ? `✅ Збережено #${data.id}` : `❌ ${data.error}`;
    setTimeout(() => { el.textContent = ''; }, 4000);
  } catch(e) {
    el.textContent = '❌ ' + e.message;
  }
}

// ── Копіювати / Завантажити ───────────────────────────────────────────────────
function copyResult() {
  const text = document.getElementById('response-body').value;
  navigator.clipboard.writeText(text).then(() => {
    const btn = event.target;
    const orig = btn.textContent;
    btn.textContent = '✅ Скопійовано';
    setTimeout(() => btn.textContent = orig, 2000);
  });
}

function downloadResult() {
  const text = document.getElementById('response-body').value;
  const blob = new Blob([text], {type: 'application/json'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'api_' + new Date().toISOString().slice(0,19).replace(/:/g,'-') + '.json';
  a.click();
}
</script>
</body>
</html>
'''


def get_db():
    conn = psycopg2.connect(DB_DSN)
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    return conn


def init_db():
    """Створює api_test_log якщо не існує."""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS api_test_log (
                id           SERIAL PRIMARY KEY,
                marketplace  TEXT,
                method       TEXT,
                endpoint     TEXT,
                params       TEXT,
                status_code  INT,
                response_body TEXT,
                elapsed      FLOAT,
                created_at   TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        conn.commit()
        cur.close(); conn.close()
        print('✓ api_test_log ready')
    except Exception as e:
        print(f'Warning: init_db: {e}')


@app.route('/')
def index():
    base_urls = {k: v['base_url'] for k, v in MARKETPLACE_CONFIG.items()}
    return render_template_string(
        HTML,
        marketplaces=MARKETPLACE_CONFIG,
        quick_commands=QUICK_COMMANDS,
        quick_json=json.dumps(QUICK_COMMANDS, ensure_ascii=False),
        base_urls_json=json.dumps(base_urls, ensure_ascii=False),
    )


@app.route('/api/tokens')
def api_tokens():
    result = {}
    for key, cfg in MARKETPLACE_CONFIG.items():
        val = os.getenv(cfg['token_env'], '')
        result[cfg['label']] = bool(val and len(val) > 5)
    return jsonify(result)


@app.route('/api/methods')
def api_methods():
    marketplace = request.args.get('marketplace', '')
    if not marketplace:
        return jsonify([])
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT method_name, http_method, endpoint, description_ua, input_params
            FROM marketplace_api_methods
            WHERE marketplace = %s
            ORDER BY method_name
        """, (marketplace,))
        rows = cur.fetchall()
        cur.close(); conn.close()
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/commands')
def api_commands():
    """Пошук команд по тексту (method_name, endpoint, description_ua)."""
    q = request.args.get('q', '').strip()
    marketplace = request.args.get('marketplace', '').strip()
    try:
        conn = get_db()
        cur = conn.cursor()
        like = f'%{q}%'
        cur.execute("""
            SELECT marketplace, method_name, http_method, endpoint, description_ua, input_params
            FROM marketplace_api_methods
            WHERE (
                method_name   ILIKE %s OR
                endpoint      ILIKE %s OR
                description_ua ILIKE %s
            )
            AND (%s = '' OR marketplace = %s)
            ORDER BY marketplace, method_name
            LIMIT 50
        """, (like, like, like, marketplace, marketplace))
        rows = cur.fetchall()
        cur.close(); conn.close()
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/save-log', methods=['POST'])
def api_save_log():
    """Зберігає результат запиту в api_test_log."""
    data = request.json or {}
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO api_test_log
                (marketplace, method, endpoint, params, status_code, response_body, elapsed)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            data.get('marketplace', ''),
            data.get('method', ''),
            data.get('endpoint', ''),
            data.get('params', ''),
            data.get('status_code'),
            json.dumps(data.get('response_body'), ensure_ascii=False)
                if data.get('response_body') is not None else '',
            data.get('elapsed'),
        ))
        row = cur.fetchone()
        conn.commit()
        cur.close(); conn.close()
        return jsonify({'ok': True, 'id': row['id']})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/proxy', methods=['POST'])
def api_proxy():
    data = request.json or {}
    marketplace  = data.get('marketplace', '')
    method       = data.get('method', 'GET').upper()
    path         = data.get('path', '')          # endpoint, наприклад /v3/oms/orders
    params       = data.get('params', '')        # query string, наприклад ?limit=10
    body         = data.get('body')
    extra_headers = data.get('extraHeaders', {})

    cfg = MARKETPLACE_CONFIG.get(marketplace)
    if not cfg:
        return jsonify({'error': f'Невідомий маркетплейс: {marketplace}'}), 400

    token      = os.getenv(cfg['token_env'], '')
    base_url   = cfg['base_url']
    verify_ssl = cfg.get('verify_ssl', True)

    headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
    if cfg['auth_type'] == 'bearer' and token:
        headers['Authorization'] = f'Bearer {token}'
    elif cfg['auth_type'] == 'apikey' and body and isinstance(body, dict):
        body['apiKey'] = token

    headers.update(extra_headers)

    # ── Формування full_url: base_url + endpoint + params ──
    if marketplace == 'nova_poshta':
        full_url = base_url          # Nova Poshta — тільки base URL, метод у body
    else:
        full_url = base_url.rstrip('/') + '/' + path.lstrip('/')
        if params:
            full_url += params if params.startswith('?') else '?' + params

    start = time.time()
    try:
        import urllib3
        urllib3.disable_warnings()

        kwargs = {
            'headers': headers,
            'verify': verify_ssl,
            'timeout': 30,
        }
        if body is not None and method in ('POST', 'PUT', 'PATCH'):
            kwargs['json'] = body

        resp = getattr(requests, method.lower())(full_url, **kwargs)
        elapsed = round(time.time() - start, 3)

        try:
            resp_body = resp.json()
        except Exception:
            resp_body = resp.text[:20000]

        # Приховуємо токен з заголовків у відповіді
        safe_req_headers = {
            k: v for k, v in headers.items()
            if 'token' not in k.lower() and 'auth' not in k.lower()
        }

        return jsonify({
            'status_code':     resp.status_code,
            'elapsed':         elapsed,
            'full_url':        full_url,
            'body':            resp_body,
            'headers':         dict(resp.headers),
            'request_headers': safe_req_headers,
        })

    except requests.exceptions.SSLError as e:
        return jsonify({'error': f'SSL помилка: {e}'}), 502
    except requests.exceptions.ConnectionError as e:
        return jsonify({'error': f'Помилка зʼєднання: {e}'}), 502
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    import urllib3
    urllib3.disable_warnings()
    init_db()
    print('🚀 API Explorer: http://0.0.0.0:5555')
    print('   З ноутбука:   http://100.82.24.112:5555')
    app.run(host='0.0.0.0', port=5555, debug=False)
