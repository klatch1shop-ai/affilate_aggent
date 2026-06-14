#!/usr/bin/env python3
"""
tools/web_api_explorer.py
==========================
Веб-інтерфейс для тестування API маркетплейсів.

Запуск:
    python3 tools/web_api_explorer.py
    Або на сервері: nohup python3 tools/web_api_explorer.py > /tmp/web_explorer.log 2>&1 &

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
        'label': 'Єпіцентр — останні замовлення',
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

HTML = '''<!DOCTYPE html>
<html lang="uk">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>API Explorer — Dropshipping</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Segoe UI', system-ui, sans-serif; background: #0f1117; color: #e2e8f0; min-height: 100vh; }

  .header { background: linear-gradient(135deg, #1a1f2e 0%, #16213e 100%); padding: 16px 24px; border-bottom: 1px solid #2d3748; display: flex; align-items: center; gap: 12px; }
  .header h1 { font-size: 20px; font-weight: 700; color: #63b3ed; }
  .header .badge { background: #2d3748; color: #68d391; padding: 3px 10px; border-radius: 12px; font-size: 12px; font-family: monospace; }

  .layout { display: grid; grid-template-columns: 260px 1fr; min-height: calc(100vh - 57px); }

  /* SIDEBAR */
  .sidebar { background: #1a1f2e; border-right: 1px solid #2d3748; padding: 16px 12px; overflow-y: auto; }
  .sidebar h3 { font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: #718096; margin-bottom: 10px; padding: 0 4px; }
  .quick-btn { display: block; width: 100%; text-align: left; background: #2d3748; border: 1px solid #3d4a5c; color: #cbd5e0; padding: 9px 12px; border-radius: 8px; cursor: pointer; margin-bottom: 6px; font-size: 12px; transition: all 0.15s; line-height: 1.4; }
  .quick-btn:hover { background: #3d4a5c; border-color: #63b3ed; color: #fff; }
  .quick-btn .method-tag { font-family: monospace; font-size: 10px; font-weight: 700; padding: 1px 6px; border-radius: 4px; margin-right: 6px; }
  .method-GET { background: #22543d; color: #68d391; }
  .method-POST { background: #2a4365; color: #63b3ed; }
  .method-PUT { background: #4a2535; color: #fc8181; }
  .method-PATCH { background: #4a3820; color: #f6ad55; }
  .method-DELETE { background: #5a1a1a; color: #fc8181; }

  /* MAIN */
  .main { padding: 20px; display: flex; flex-direction: column; gap: 16px; }

  .card { background: #1a1f2e; border: 1px solid #2d3748; border-radius: 12px; padding: 20px; }
  .card-title { font-size: 13px; font-weight: 600; color: #a0aec0; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 16px; }

  .form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 12px; }
  .form-group { display: flex; flex-direction: column; gap: 6px; }
  .form-group label { font-size: 12px; color: #718096; font-weight: 500; }

  select, input, textarea { background: #0f1117; border: 1px solid #3d4a5c; color: #e2e8f0; padding: 9px 12px; border-radius: 8px; font-size: 13px; width: 100%; transition: border-color 0.15s; font-family: inherit; }
  select:focus, input:focus, textarea:focus { outline: none; border-color: #63b3ed; }
  textarea { resize: vertical; font-family: 'Fira Code', 'Consolas', monospace; }

  .url-row { display: grid; grid-template-columns: 90px 1fr 1fr; gap: 8px; margin-bottom: 12px; align-items: end; }

  .btn { padding: 10px 20px; border: none; border-radius: 8px; cursor: pointer; font-size: 14px; font-weight: 600; transition: all 0.15s; }
  .btn-primary { background: linear-gradient(135deg, #3182ce, #2b6cb0); color: white; }
  .btn-primary:hover { background: linear-gradient(135deg, #4299e1, #3182ce); transform: translateY(-1px); }
  .btn-primary:active { transform: translateY(0); }
  .btn-secondary { background: #2d3748; color: #a0aec0; }
  .btn-secondary:hover { background: #3d4a5c; color: #fff; }
  .btn-danger { background: #c53030; color: white; }

  .btn-row { display: flex; gap: 10px; align-items: center; }
  .spinner { display: none; width: 18px; height: 18px; border: 2px solid #3d4a5c; border-top-color: #63b3ed; border-radius: 50%; animation: spin 0.7s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* RESULT */
  .result-header { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; flex-wrap: wrap; }
  .status-badge { padding: 4px 12px; border-radius: 20px; font-size: 12px; font-weight: 700; font-family: monospace; }
  .status-2xx { background: #22543d; color: #68d391; }
  .status-4xx { background: #4a2535; color: #fc8181; }
  .status-5xx { background: #5a1a1a; color: #fc8181; }
  .elapsed { font-size: 12px; color: #718096; }

  .result-tabs { display: flex; gap: 4px; margin-bottom: 12px; border-bottom: 1px solid #2d3748; padding-bottom: 8px; }
  .tab-btn { padding: 6px 14px; border: 1px solid transparent; border-radius: 6px; background: none; color: #718096; cursor: pointer; font-size: 12px; font-weight: 500; transition: all 0.15s; }
  .tab-btn.active { background: #2d3748; color: #e2e8f0; border-color: #3d4a5c; }

  .result-area { background: #0a0e1a; border: 1px solid #2d3748; border-radius: 8px; padding: 16px; font-family: 'Fira Code', 'Consolas', monospace; font-size: 12px; line-height: 1.6; color: #a8d8a8; height: 550px; overflow-y: auto; white-space: pre-wrap; word-break: break-all; }
  .result-placeholder { color: #4a5568; font-style: italic; text-align: center; margin-top: 100px; }

  .token-status { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 8px; }
  .token-chip { font-size: 11px; padding: 2px 8px; border-radius: 10px; font-family: monospace; }
  .token-ok { background: #1a3a2a; color: #68d391; border: 1px solid #2f6546; }
  .token-missing { background: #3a1a1a; color: #fc8181; border: 1px solid #6b2222; }

  .json-key { color: #63b3ed; }
  .json-str { color: #68d391; }
  .json-num { color: #f6ad55; }
  .json-bool { color: #fc8181; }
  .json-null { color: #a0aec0; }
</style>
</head>
<body>

<div class="header">
  <h1>⚡ API Explorer</h1>
  <span class="badge">Dropshipping Tools</span>
  <div class="token-status" id="tokenStatus"></div>
</div>

<div class="layout">
  <!-- SIDEBAR -->
  <div class="sidebar">
    <h3>Швидкі запити</h3>
    {% for cmd in quick_commands %}
    <button class="quick-btn" onclick="loadQuick({{ loop.index0 }})">
      <span class="method-tag method-{{ cmd.method }}">{{ cmd.method }}</span>
      {{ cmd.label }}
    </button>
    {% endfor %}

    <h3 style="margin-top:20px">Маркетплейси</h3>
    {% for key, cfg in marketplaces.items() %}
    <button class="quick-btn" onclick="document.getElementById('marketplace').value='{{ key }}'; loadMethods('{{ key }}')">
      {{ cfg.label }}
    </button>
    {% endfor %}
  </div>

  <!-- MAIN -->
  <div class="main">
    <!-- REQUEST CARD -->
    <div class="card">
      <div class="card-title">Запит</div>

      <div class="form-row">
        <div class="form-group">
          <label>Маркетплейс</label>
          <select id="marketplace" onchange="loadMethods(this.value)">
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
          <input type="text" id="endpointPath" placeholder="/v3/oms/orders" />
        </div>
        <div class="form-group">
          <label>Query params</label>
          <input type="text" id="queryParams" placeholder="?limit=10&page=1" />
        </div>
      </div>

      <div class="form-group" style="margin-bottom:12px">
        <label>JSON Body (для POST/PUT/PATCH)</label>
        <textarea id="jsonBody" rows="4" placeholder='{ "key": "value" }'></textarea>
      </div>

      <div class="form-group" style="margin-bottom:12px">
        <label>Додаткові Headers (JSON, опціонально)</label>
        <textarea id="extraHeaders" rows="2" placeholder='{ "X-Custom": "value" }'></textarea>
      </div>

      <div class="btn-row">
        <button class="btn btn-primary" onclick="executeRequest()">▶ Виконати</button>
        <button class="btn btn-secondary" onclick="clearResult()">✕ Очистити</button>
        <div class="spinner" id="spinner"></div>
        <span id="statusText" style="font-size:13px; color:#718096"></span>
      </div>
    </div>

    <!-- RESULT CARD -->
    <div class="card">
      <div class="result-header">
        <div class="card-title" style="margin-bottom:0">Відповідь</div>
        <span class="status-badge" id="statusBadge" style="display:none"></span>
        <span class="elapsed" id="elapsedTime"></span>
        <button class="btn btn-secondary" style="padding:5px 12px; font-size:12px; margin-left:auto" onclick="copyResult()">📋 Копіювати</button>
        <button class="btn btn-secondary" style="padding:5px 12px; font-size:12px" onclick="downloadResult()">⬇ Зберегти</button>
      </div>

      <div class="result-tabs">
        <button class="tab-btn active" onclick="showTab('body')">Body</button>
        <button class="tab-btn" onclick="showTab('headers')">Headers</button>
        <button class="tab-btn" onclick="showTab('request')">Запит</button>
        <span id="itemCount" style="font-size:12px; color:#718096; margin-left:auto; align-self:center"></span>
      </div>

      <div class="result-area" id="resultArea">
        <div class="result-placeholder">← Оберіть маркетплейс, метод та натисніть "Виконати"</div>
      </div>
    </div>
  </div>
</div>

<script>
const QUICK = {{ quick_json }};
let currentTabs = { body: '', headers: '', request: '' };
let activeTab = 'body';

// Перевірка токенів при завантаженні
fetch('/api/tokens').then(r => r.json()).then(data => {
  const el = document.getElementById('tokenStatus');
  for (const [key, ok] of Object.entries(data)) {
    const chip = document.createElement('span');
    chip.className = 'token-chip ' + (ok ? 'token-ok' : 'token-missing');
    chip.textContent = key + (ok ? ' ✓' : ' ✗');
    el.appendChild(chip);
  }
});

function loadMethods(marketplace) {
  if (!marketplace) return;
  fetch('/api/methods?marketplace=' + marketplace)
    .then(r => r.json())
    .then(data => {
      const sel = document.getElementById('methodSelect');
      sel.innerHTML = '<option value="">— оберіть метод —</option>';
      data.forEach(m => {
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
  if (m.input_params) {
    try {
      document.getElementById('jsonBody').value = JSON.stringify(m.input_params, null, 2);
    } catch(e) {}
  } else {
    document.getElementById('jsonBody').value = '';
  }
}

function loadQuick(idx) {
  const cmd = QUICK[idx];
  document.getElementById('marketplace').value = cmd.marketplace;
  document.getElementById('httpMethod').value = cmd.method;
  document.getElementById('endpointPath').value = cmd.url;
  document.getElementById('queryParams').value = cmd.params || '';
  document.getElementById('jsonBody').value = cmd.body || '';
  loadMethods(cmd.marketplace);
}

async function executeRequest() {
  const marketplace = document.getElementById('marketplace').value;
  const method = document.getElementById('httpMethod').value;
  const path = document.getElementById('endpointPath').value.trim();
  const params = document.getElementById('queryParams').value.trim();
  const bodyText = document.getElementById('jsonBody').value.trim();
  const extraText = document.getElementById('extraHeaders').value.trim();

  if (!marketplace) { alert('Оберіть маркетплейс'); return; }
  if (!path) { alert('Введіть endpoint'); return; }

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
  setResult('body', '⏳ Очікую відповіді...');

  const startTime = Date.now();

  try {
    const res = await fetch('/api/proxy', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ marketplace, method, path, params, body, extraHeaders })
    });

    const elapsed = ((Date.now() - startTime) / 1000).toFixed(2);
    const data = await res.json();

    document.getElementById('elapsedTime').textContent = `⏱ ${elapsed}с`;
    document.getElementById('spinner').style.display = 'none';
    document.getElementById('statusText').textContent = '';

    const badge = document.getElementById('statusBadge');
    badge.style.display = 'inline-block';
    badge.textContent = data.status_code || '???';
    const sc = data.status_code || 0;
    badge.className = 'status-badge ' + (sc >= 500 ? 'status-5xx' : sc >= 400 ? 'status-4xx' : 'status-2xx');

    // Body
    let bodyStr = '';
    if (data.body) {
      try {
        const parsed = typeof data.body === 'string' ? JSON.parse(data.body) : data.body;
        bodyStr = syntaxHighlight(JSON.stringify(parsed, null, 2));
        // Count items
        const items = parsed.data?.items || parsed.items || parsed.content?.items || (Array.isArray(parsed) ? parsed : null);
        if (items) {
          document.getElementById('itemCount').textContent = `${items.length} items`;
        } else {
          document.getElementById('itemCount').textContent = '';
        }
      } catch(e) {
        bodyStr = data.body;
        document.getElementById('itemCount').textContent = '';
      }
    } else if (data.error) {
      bodyStr = '❌ ' + data.error;
    }

    const headersStr = data.headers ? JSON.stringify(data.headers, null, 2) : '';
    const requestStr = `${method} ${data.full_url || path + params}\n\nHeaders:\n${JSON.stringify(data.request_headers || {}, null, 2)}\n\nBody:\n${bodyText || '(none)'}`;

    setResult('body', bodyStr);
    setResult('headers', headersStr);
    setResult('request', requestStr);
    showTab('body');

  } catch(e) {
    document.getElementById('spinner').style.display = 'none';
    document.getElementById('statusText').textContent = '❌ Помилка з\'єднання';
    setResult('body', '❌ Помилка: ' + e.message);
  }
}

function syntaxHighlight(json) {
  return json
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"([ \t]*:)?|\\b(true|false|null)\\b|-?\\d+(?:\\.\\d*)?(?:[eE][+\\-]?\\d+)?)/g, function(match) {
      let cls = 'json-num';
      if (/^"/.test(match)) {
        cls = /:$/.test(match) ? 'json-key' : 'json-str';
      } else if (/true|false/.test(match)) {
        cls = 'json-bool';
      } else if (/null/.test(match)) {
        cls = 'json-null';
      }
      return `<span class="${cls}">${match}</span>`;
    });
}

function setResult(tab, content) {
  currentTabs[tab] = content;
  if (activeTab === tab) {
    document.getElementById('resultArea').innerHTML = content || '<div class="result-placeholder">Пусто</div>';
  }
}

function showTab(tab) {
  activeTab = tab;
  document.querySelectorAll('.tab-btn').forEach((b, i) => {
    const tabs = ['body', 'headers', 'request'];
    b.classList.toggle('active', tabs[i] === tab);
  });
  const content = currentTabs[tab];
  document.getElementById('resultArea').innerHTML = content || '<div class="result-placeholder">Пусто</div>';
}

function clearResult() {
  currentTabs = { body: '', headers: '', request: '' };
  document.getElementById('resultArea').innerHTML = '<div class="result-placeholder">← Оберіть маркетплейс, метод та натисніть "Виконати"</div>';
  document.getElementById('statusBadge').style.display = 'none';
  document.getElementById('elapsedTime').textContent = '';
  document.getElementById('itemCount').textContent = '';
}

function copyResult() {
  const text = document.getElementById('resultArea').innerText;
  navigator.clipboard.writeText(text).then(() => {
    const btn = event.target;
    btn.textContent = '✅ Скопійовано';
    setTimeout(() => btn.textContent = '📋 Копіювати', 2000);
  });
}

function downloadResult() {
  const text = document.getElementById('resultArea').innerText;
  const blob = new Blob([text], {type: 'application/json'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'api_response_' + new Date().toISOString().slice(0,19).replace(/:/g,'-') + '.json';
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


@app.route('/')
def index():
    return render_template_string(
        HTML,
        marketplaces=MARKETPLACE_CONFIG,
        quick_commands=QUICK_COMMANDS,
        quick_json=json.dumps(QUICK_COMMANDS, ensure_ascii=False),
    )


@app.route('/api/tokens')
def api_tokens():
    result = {}
    for key, cfg in MARKETPLACE_CONFIG.items():
        env_key = cfg['token_env']
        val = os.getenv(env_key, '')
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


@app.route('/api/proxy', methods=['POST'])
def api_proxy():
    data = request.json or {}
    marketplace = data.get('marketplace', '')
    method = data.get('method', 'GET').upper()
    path = data.get('path', '')
    params = data.get('params', '')
    body = data.get('body')
    extra_headers = data.get('extraHeaders', {})

    cfg = MARKETPLACE_CONFIG.get(marketplace)
    if not cfg:
        return jsonify({'error': f'Невідомий маркетплейс: {marketplace}'}), 400

    token = os.getenv(cfg['token_env'], '')
    base_url = cfg['base_url']
    verify_ssl = cfg.get('verify_ssl', True)

    headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}

    if cfg['auth_type'] == 'bearer' and token:
        headers['Authorization'] = f'Bearer {token}'
    elif cfg['auth_type'] == 'apikey' and body and isinstance(body, dict):
        body['apiKey'] = token

    headers.update(extra_headers)

    # Для Nova Poshta URL — просто base_url (POST)
    if marketplace == 'nova_poshta':
        full_url = base_url
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
        elapsed = time.time() - start

        try:
            resp_body = resp.json()
        except Exception:
            resp_body = resp.text[:10000]

        return jsonify({
            'status_code': resp.status_code,
            'elapsed': round(elapsed, 3),
            'full_url': full_url,
            'body': resp_body,
            'headers': dict(resp.headers),
            'request_headers': {k: v for k, v in headers.items() if 'token' not in k.lower() and 'auth' not in k.lower()},
        })

    except requests.exceptions.SSLError as e:
        return jsonify({'error': f'SSL помилка: {e}. Перевір verify_ssl в конфігурації.'}), 502
    except requests.exceptions.ConnectionError as e:
        return jsonify({'error': f'Помилка з\'єднання: {e}'}), 502
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    import urllib3
    urllib3.disable_warnings()
    print('🚀 API Explorer запущено: http://0.0.0.0:5555')
    print('   Доступ з ноутбука: http://100.82.24.112:5555')
    app.run(host='0.0.0.0', port=5555, debug=False)
