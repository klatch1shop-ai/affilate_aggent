# DUMP_CODE_GENERATORS.md — повний код generator/checker/validator/utility (не дубльує CORE)

### `tools/ai_xml_generator.py` — 636 рядків

````python
#!/usr/bin/env python3
"""
tools/ai_xml_generator.py
==========================
AI-асистент для генерації XML для будь-якого маркетплейсу та категорії.

Запуск:
    python3 tools/ai_xml_generator.py
    Або на сервері: nohup python3 tools/ai_xml_generator.py > /tmp/ai_xml_gen.log 2>&1 &

Доступ: http://100.82.24.112:5556
"""

import os
import sys
import json
import uuid
import csv
import io
import xml.dom.minidom
from flask import Flask, request, jsonify, render_template_string, session
from flask_cors import CORS
from pathlib import Path
from dotenv import load_dotenv
import anthropic

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / '.env')

app = Flask(__name__)
app.secret_key = os.urandom(32)
CORS(app)

ANTHROPIC_KEY = os.getenv('ANTHROPIC_API_KEY', '')
ai_client = anthropic.Anthropic(api_key=ANTHROPIC_KEY) if ANTHROPIC_KEY else None

# Сесії в пам'яті
sessions: dict[str, dict] = {}

MARKETPLACE_SCHEMAS = {
    'epicentr': {
        'label': 'Єпіцентр',
        'root': 'yml_catalog',
        'offer_tag': 'offer',
        'required_fields': ['id', 'price', 'category', 'name', 'vendor', 'country_of_origin'],
        'example': '''<yml_catalog date="2026-06-14">
<offers>
  <offer id="ART001" available="true">
    <price>1500.00</price>
    <category code="4907">Магнітоли</category>
    <attribute_set code="4907">Магнітоли</attribute_set>
    <name lang="ua">Назва товару</name>
    <name lang="ru">Назва товару</name>
    <picture>https://example.com/img.jpg</picture>
    <description lang="ua">Опис товару</description>
    <vendor code="brand_code">Бренд</vendor>
    <country_of_origin code="chn">Китай</country_of_origin>
    <param name="Бренд" paramcode="brand" valuecode="brand_code">Бренд</param>
    <weight>500</weight><width>200</width><height>100</height><length>200</length>
  </offer>
</offers>
</yml_catalog>'''
    },
    'prom': {
        'label': 'Prom.ua',
        'root': 'yml_catalog',
        'offer_tag': 'offer',
        'required_fields': ['id', 'price', 'categoryId', 'name_ua', 'vendor', 'url'],
        'example': '''<yml_catalog date="2026-06-14">
<shop>
  <offers>
    <offer id="ART001" available="true">
      <price>1500</price>
      <currencyId>UAH</currencyId>
      <categoryId>1</categoryId>
      <name_ua>Назва товару UA</name_ua>
      <name>Назва товару RU</name>
      <vendor>Бренд</vendor>
      <article>ART001</article>
      <picture>https://example.com/img.jpg</picture>
      <description_ua>Опис товару</description_ua>
      <url>https://myshop.prom.ua/product-art001.html</url>
    </offer>
  </offers>
</shop>
</yml_catalog>'''
    },
    'rozetka': {
        'label': 'Rozetka',
        'root': 'yml_catalog',
        'offer_tag': 'offer',
        'required_fields': ['id', 'price', 'categoryId', 'name', 'vendor', 'article'],
        'example': '''<yml_catalog date="2026-06-14">
<shop>
  <offers>
    <offer id="ART001" available="true">
      <price>1500</price>
      <currencyId>UAH</currencyId>
      <categoryId>80011</categoryId>
      <name>Назва товару</name>
      <vendor>Бренд</vendor>
      <article>ART001</article>
      <picture>https://example.com/img.jpg</picture>
      <description>Опис товару</description>
      <param name="Гарантія">12 місяців</param>
    </offer>
  </offers>
</shop>
</yml_catalog>'''
    },
}

SYSTEM_PROMPT = """Ти — асистент з генерації XML для дропшипінгових магазинів в Україні.
Твоя задача: допомогти користувачу згенерувати правильний XML файл для завантаження товарів на маркетплейс.

Ти спілкуєшся українською мовою.

Коли користувач описує категорію товарів, ти:
1. Визначаєш потрібні поля для цієї категорії
2. Задаєш уточнюючі питання (по одному, не більше 3 питань всього)
3. Генеруєш XML після отримання відповідей

При генерації XML:
- Використовуй надані дані про товари
- Дотримуйся формату маркетплейсу
- Генеруй реалістичні описи якщо їх немає
- Повертай лише XML блок коли просять згенерувати, без пояснень

Якщо бачиш слово ГЕНЕРУЙ_XML в повідомленні — поверни готовий XML для перших 5 товарів.
"""

HTML = '''<!DOCTYPE html>
<html lang="uk">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI XML Generator</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Segoe UI', system-ui, sans-serif; background: #0f1117; color: #e2e8f0; }

  .header { background: linear-gradient(135deg, #1a1f2e 0%, #16213e 100%); padding: 16px 24px; border-bottom: 1px solid #2d3748; display: flex; align-items: center; gap: 12px; }
  .header h1 { font-size: 20px; font-weight: 700; color: #9f7aea; }
  .header .badge { background: #2d3748; color: #68d391; padding: 3px 10px; border-radius: 12px; font-size: 12px; }

  .layout { display: grid; grid-template-columns: 1fr 1fr; height: calc(100vh - 57px); }

  /* LEFT — wizard */
  .wizard { padding: 24px; overflow-y: auto; border-right: 1px solid #2d3748; }

  .step { background: #1a1f2e; border: 1px solid #2d3748; border-radius: 12px; padding: 20px; margin-bottom: 16px; }
  .step.active { border-color: #9f7aea; }
  .step.done { border-color: #2f6546; opacity: 0.7; }
  .step-header { display: flex; align-items: center; gap: 10px; margin-bottom: 16px; }
  .step-num { width: 28px; height: 28px; border-radius: 50%; background: #9f7aea; color: white; display: flex; align-items: center; justify-content: center; font-size: 13px; font-weight: 700; flex-shrink: 0; }
  .step.done .step-num { background: #2f6546; }
  .step-title { font-weight: 600; font-size: 15px; }

  .form-group { margin-bottom: 14px; }
  .form-group label { display: block; font-size: 12px; color: #718096; margin-bottom: 6px; font-weight: 500; }
  select, input, textarea { background: #0f1117; border: 1px solid #3d4a5c; color: #e2e8f0; padding: 9px 12px; border-radius: 8px; font-size: 13px; width: 100%; font-family: inherit; }
  textarea { resize: vertical; }
  select:focus, input:focus, textarea:focus { outline: none; border-color: #9f7aea; }

  .btn { padding: 10px 20px; border: none; border-radius: 8px; cursor: pointer; font-size: 14px; font-weight: 600; transition: all 0.15s; }
  .btn-ai { background: linear-gradient(135deg, #6b46c1, #553c9a); color: white; }
  .btn-ai:hover { background: linear-gradient(135deg, #7c3aed, #6b46c1); }
  .btn-secondary { background: #2d3748; color: #a0aec0; margin-left: 8px; }
  .btn-secondary:hover { background: #3d4a5c; color: #fff; }
  .btn-success { background: linear-gradient(135deg, #276749, #22543d); color: white; }
  .btn-success:hover { background: linear-gradient(135deg, #38a169, #276749); }

  /* CHAT */
  .chat-container { background: #0a0e1a; border: 1px solid #2d3748; border-radius: 10px; height: 300px; overflow-y: auto; padding: 12px; margin-bottom: 10px; }
  .msg { margin-bottom: 12px; display: flex; flex-direction: column; }
  .msg.user { align-items: flex-end; }
  .msg.ai { align-items: flex-start; }
  .msg-bubble { max-width: 85%; padding: 10px 14px; border-radius: 12px; font-size: 13px; line-height: 1.5; }
  .msg.user .msg-bubble { background: #553c9a; color: white; border-radius: 12px 12px 2px 12px; }
  .msg.ai .msg-bubble { background: #1e2a3a; color: #cbd5e0; border-radius: 12px 12px 12px 2px; }
  .msg-meta { font-size: 10px; color: #4a5568; margin-top: 3px; }
  .typing { display: none; }
  .typing.show { display: flex; }
  .typing .msg-bubble { background: #1e2a3a; }
  .dot { width: 6px; height: 6px; background: #9f7aea; border-radius: 50%; display: inline-block; animation: bounce 1.2s infinite; margin: 0 2px; }
  .dot:nth-child(2) { animation-delay: 0.2s; }
  .dot:nth-child(3) { animation-delay: 0.4s; }
  @keyframes bounce { 0%,60%,100%{transform:translateY(0)}30%{transform:translateY(-6px)} }

  .chat-input-row { display: flex; gap: 8px; }
  .chat-input-row input { flex: 1; }

  .field-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
  .chip { padding: 4px 10px; border-radius: 12px; font-size: 11px; background: #2d3748; color: #a0aec0; border: 1px solid #3d4a5c; cursor: pointer; }
  .chip.selected { background: #553c9a; color: white; border-color: #9f7aea; }

  /* RIGHT — preview */
  .preview-panel { padding: 20px; overflow-y: auto; display: flex; flex-direction: column; gap: 16px; }
  .preview-card { background: #1a1f2e; border: 1px solid #2d3748; border-radius: 12px; padding: 16px; }
  .preview-title { font-size: 13px; color: #718096; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 12px; font-weight: 600; }
  .xml-area { background: #0a0e1a; border: 1px solid #2d3748; border-radius: 8px; padding: 14px; font-family: 'Fira Code', monospace; font-size: 11px; line-height: 1.6; color: #a8d8a8; white-space: pre; overflow-x: auto; max-height: 500px; overflow-y: auto; }
  .xml-placeholder { color: #4a5568; text-align: center; padding: 40px 0; font-style: italic; }

  .stats-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
  .stat-card { background: #0f1117; border: 1px solid #2d3748; border-radius: 8px; padding: 12px; text-align: center; }
  .stat-val { font-size: 24px; font-weight: 700; color: #9f7aea; }
  .stat-label { font-size: 11px; color: #718096; margin-top: 4px; }

  .progress-bar { background: #2d3748; border-radius: 4px; height: 4px; margin-top: 8px; overflow: hidden; }
  .progress-fill { background: linear-gradient(90deg, #9f7aea, #6b46c1); height: 100%; border-radius: 4px; transition: width 0.3s; }

  .btn-row { display: flex; gap: 8px; margin-top: 12px; }
</style>
</head>
<body>

<div class="header">
  <h1>🤖 AI XML Generator</h1>
  <span class="badge">Claude Haiku</span>
  <span id="aiStatus" style="font-size:12px; margin-left:auto; color:#68d391">{{ ai_ok }}</span>
</div>

<div class="layout">
  <!-- LEFT — Wizard -->
  <div class="wizard">

    <!-- КРОК 1 -->
    <div class="step active" id="step1">
      <div class="step-header">
        <div class="step-num">1</div>
        <div class="step-title">Базова інформація</div>
      </div>

      <div class="form-group">
        <label>Маркетплейс</label>
        <select id="marketplace" onchange="updateMarketplace()">
          <option value="">— оберіть —</option>
          <option value="epicentr">Єпіцентр</option>
          <option value="prom">Prom.ua</option>
          <option value="rozetka">Rozetka</option>
        </select>
      </div>

      <div class="form-group">
        <label>Категорія товарів (своїми словами)</label>
        <input type="text" id="category" placeholder="напр: автомагнітоли, одяг для жінок, інтимні товари..." />
      </div>

      <div class="form-group">
        <label>Дані товарів (CSV/JSON/текст або залиш пусто для прикладу)</label>
        <textarea id="sourceData" rows="5" placeholder="Артикул, Назва, Ціна, Опис&#10;ART001, Товар 1, 500, Опис 1&#10;ART002, Товар 2, 700, Опис 2"></textarea>
      </div>

      <div class="form-group">
        <label>Кількість товарів для генерації</label>
        <select id="genCount">
          <option value="3">3 (для тесту)</option>
          <option value="5" selected>5 (preview)</option>
          <option value="10">10</option>
          <option value="50">50</option>
          <option value="100">100</option>
        </select>
      </div>

      <button class="btn btn-ai" onclick="startAnalysis()">🔍 Аналізувати та почати чат</button>
    </div>

    <!-- КРОК 2 — Чат -->
    <div class="step" id="step2" style="display:none">
      <div class="step-header">
        <div class="step-num">2</div>
        <div class="step-title">AI Аналіз та уточнення</div>
      </div>

      <div class="chat-container" id="chatBox">
        <div class="msg ai typing" id="typingIndicator">
          <div class="msg-bubble"><span class="dot"></span><span class="dot"></span><span class="dot"></span></div>
        </div>
      </div>

      <div class="chat-input-row">
        <input type="text" id="chatInput" placeholder="Відповідь або уточнення..." onkeydown="if(event.key==='Enter') sendMessage()" />
        <button class="btn btn-ai" onclick="sendMessage()">▶</button>
      </div>

      <div style="margin-top:12px">
        <button class="btn btn-success" onclick="generateXML()">✨ Генерувати XML</button>
        <button class="btn btn-secondary" onclick="resetWizard()">↺ Почати знову</button>
      </div>
    </div>

    <!-- КРОК 3 — Готово -->
    <div class="step" id="step3" style="display:none">
      <div class="step-header">
        <div class="step-num">3</div>
        <div class="step-title">Результат</div>
      </div>

      <div class="stats-grid" id="statsGrid">
        <div class="stat-card"><div class="stat-val" id="statOffers">0</div><div class="stat-label">Офферів</div></div>
        <div class="stat-card"><div class="stat-val" id="statFields">0</div><div class="stat-label">Полів</div></div>
        <div class="stat-card"><div class="stat-val" id="statSize">0</div><div class="stat-label">KB</div></div>
      </div>

      <div class="btn-row">
        <button class="btn btn-success" onclick="downloadXML()">⬇ Завантажити XML</button>
        <button class="btn btn-secondary" onclick="copyXML()">📋 Копіювати</button>
        <button class="btn btn-secondary" onclick="resetWizard()">↺ Нова генерація</button>
      </div>
    </div>

  </div>

  <!-- RIGHT — Preview -->
  <div class="preview-panel">
    <div class="preview-card">
      <div class="preview-title">📄 XML Preview</div>
      <div class="xml-area" id="xmlPreview">
        <div class="xml-placeholder">AI згенерує XML тут після аналізу та відповідей на питання</div>
      </div>
    </div>

    <div class="preview-card" id="schemaCard">
      <div class="preview-title">📋 Структура для маркетплейсу</div>
      <div id="schemaInfo" style="font-size:13px; color:#a0aec0; line-height:1.6">
        Оберіть маркетплейс щоб побачити вимоги до структури XML.
      </div>
    </div>
  </div>
</div>

<script>
let sessionId = null;
let generatedXML = '';

const SCHEMAS = {{ schemas_json }};

function updateMarketplace() {
  const mp = document.getElementById('marketplace').value;
  const schema = SCHEMAS[mp];
  if (!schema) { document.getElementById('schemaInfo').textContent = 'Оберіть маркетплейс'; return; }
  document.getElementById('schemaInfo').innerHTML = `
    <b>Обов'язкові поля:</b> ${schema.required_fields.join(', ')}<br><br>
    <b>Приклад:</b><br>
    <pre style="background:#0a0e1a;padding:10px;border-radius:6px;font-size:10px;color:#a8d8a8;overflow-x:auto;margin-top:6px">${escapeHtml(schema.example)}</pre>
  `;
}

function escapeHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

async function startAnalysis() {
  const marketplace = document.getElementById('marketplace').value;
  const category = document.getElementById('category').value.trim();
  const sourceData = document.getElementById('sourceData').value.trim();

  if (!marketplace) { alert('Оберіть маркетплейс'); return; }
  if (!category) { alert('Введіть категорію товарів'); return; }

  // Ховаємо крок 1, показуємо крок 2
  document.getElementById('step1').classList.add('done');
  document.getElementById('step2').style.display = 'block';
  document.getElementById('typingIndicator').classList.add('show');

  const resp = await fetch('/api/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ marketplace, category, sourceData })
  });
  const data = await resp.json();
  sessionId = data.session_id;

  document.getElementById('typingIndicator').classList.remove('show');
  addMessage('ai', data.message);
}

async function sendMessage() {
  const input = document.getElementById('chatInput');
  const text = input.value.trim();
  if (!text || !sessionId) return;

  input.value = '';
  addMessage('user', text);
  document.getElementById('typingIndicator').classList.add('show');
  scrollChat();

  const resp = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, message: text })
  });
  const data = await resp.json();

  document.getElementById('typingIndicator').classList.remove('show');
  addMessage('ai', data.message);
  scrollChat();
}

async function generateXML() {
  if (!sessionId) return;
  const count = document.getElementById('genCount').value;

  addMessage('user', `Генеруй XML для ${count} товарів`);
  document.getElementById('typingIndicator').classList.add('show');
  scrollChat();

  const resp = await fetch('/api/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, count: parseInt(count) })
  });
  const data = await resp.json();

  document.getElementById('typingIndicator').classList.remove('show');

  if (data.xml) {
    generatedXML = data.xml;
    document.getElementById('xmlPreview').textContent = data.xml;

    // Статистика
    const offerCount = (data.xml.match(/<offer /g) || []).length;
    const fieldCount = (data.xml.match(/<[a-z]/g) || []).length;
    const sizeKB = Math.round(data.xml.length / 1024 * 10) / 10;
    document.getElementById('statOffers').textContent = offerCount;
    document.getElementById('statFields').textContent = fieldCount;
    document.getElementById('statSize').textContent = sizeKB;

    document.getElementById('step3').style.display = 'block';
    addMessage('ai', `✅ XML згенеровано: ${offerCount} товарів, ${sizeKB} KB. Перевір preview та завантаж файл.`);
  } else {
    addMessage('ai', data.message || 'Помилка генерації. Спробуй ще раз.');
  }
  scrollChat();
}

function addMessage(role, text) {
  const box = document.getElementById('chatBox');
  const indicator = document.getElementById('typingIndicator');

  const div = document.createElement('div');
  div.className = 'msg ' + role;
  div.innerHTML = `
    <div class="msg-bubble">${text.replace(/\n/g,'<br>')}</div>
    <div class="msg-meta">${new Date().toLocaleTimeString('uk')}</div>
  `;
  box.insertBefore(div, indicator);
  scrollChat();
}

function scrollChat() {
  const box = document.getElementById('chatBox');
  box.scrollTop = box.scrollHeight;
}

function downloadXML() {
  if (!generatedXML) return;
  const blob = new Blob([generatedXML], { type: 'application/xml' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'generated_' + document.getElementById('marketplace').value + '_' + Date.now() + '.xml';
  a.click();
}

function copyXML() {
  navigator.clipboard.writeText(generatedXML).then(() => {
    event.target.textContent = '✅ Скопійовано';
    setTimeout(() => event.target.textContent = '📋 Копіювати', 2000);
  });
}

function resetWizard() {
  sessionId = null;
  generatedXML = '';
  document.getElementById('step1').classList.remove('done');
  document.getElementById('step2').style.display = 'none';
  document.getElementById('step3').style.display = 'none';
  document.getElementById('chatBox').innerHTML = '<div class="msg ai typing" id="typingIndicator"><div class="msg-bubble"><span class="dot"></span><span class="dot"></span><span class="dot"></span></div></div>';
  document.getElementById('xmlPreview').innerHTML = '<div class="xml-placeholder">AI згенерує XML тут після аналізу та відповідей на питання</div>';
  document.getElementById('chatInput').value = '';
}
</script>
</body>
</html>
'''


def call_ai(messages: list, system: str = SYSTEM_PROMPT) -> str:
    if not ai_client:
        return 'Claude API не налаштовано. Перевір ANTHROPIC_API_KEY в .env'
    try:
        resp = ai_client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=2048,
            system=system,
            messages=messages,
        )
        return resp.content[0].text
    except Exception as e:
        return f'Помилка API: {e}'


def build_context_message(marketplace: str, category: str, source_data: str) -> str:
    schema = MARKETPLACE_SCHEMAS.get(marketplace, {})
    mp_label = schema.get('label', marketplace)
    required = ', '.join(schema.get('required_fields', []))

    msg = f"""Маркетплейс: {mp_label}
Категорія товарів: {category}
Обов'язкові поля XML: {required}

"""
    if source_data:
        msg += f"Дані товарів від користувача:\n{source_data[:2000]}\n\n"
    else:
        msg += "Даних товарів не надано — будь ласка, запитай у користувача або згенеруй приклади.\n\n"

    msg += f"""Будь ласка:
1. Коротко поясни яку структуру XML потрібно для {mp_label} в категорії "{category}"
2. Задай одне уточнююче питання щоб краще генерувати XML (наприклад про характеристики, ціни або бренди)
"""
    return msg


@app.route('/')
def index():
    ai_ok = '✅ Claude API підключено' if ANTHROPIC_KEY else '❌ ANTHROPIC_API_KEY відсутній'
    schemas_json = json.dumps({
        k: {'label': v['label'], 'required_fields': v['required_fields'], 'example': v['example']}
        for k, v in MARKETPLACE_SCHEMAS.items()
    }, ensure_ascii=False)
    return render_template_string(HTML, ai_ok=ai_ok, schemas_json=schemas_json)


@app.route('/api/start', methods=['POST'])
def api_start():
    data = request.json or {}
    marketplace = data.get('marketplace', '')
    category = data.get('category', '')
    source_data = data.get('sourceData', '')

    session_id = str(uuid.uuid4())
    first_msg = build_context_message(marketplace, category, source_data)

    messages = [{'role': 'user', 'content': first_msg}]
    ai_reply = call_ai(messages)

    messages.append({'role': 'assistant', 'content': ai_reply})

    sessions[session_id] = {
        'marketplace': marketplace,
        'category': category,
        'source_data': source_data,
        'messages': messages,
    }

    return jsonify({'session_id': session_id, 'message': ai_reply})


@app.route('/api/chat', methods=['POST'])
def api_chat():
    data = request.json or {}
    session_id = data.get('session_id', '')
    user_msg = data.get('message', '')

    sess = sessions.get(session_id)
    if not sess:
        return jsonify({'message': 'Сесію не знайдено. Почни знову.'}), 400

    sess['messages'].append({'role': 'user', 'content': user_msg})
    ai_reply = call_ai(sess['messages'])
    sess['messages'].append({'role': 'assistant', 'content': ai_reply})

    return jsonify({'message': ai_reply})


@app.route('/api/generate', methods=['POST'])
def api_generate():
    data = request.json or {}
    session_id = data.get('session_id', '')
    count = data.get('count', 5)

    sess = sessions.get(session_id)
    if not sess:
        return jsonify({'message': 'Сесію не знайдено'}), 400

    marketplace = sess['marketplace']
    category = sess['category']
    source_data = sess['source_data']
    schema = MARKETPLACE_SCHEMAS.get(marketplace, MARKETPLACE_SCHEMAS['prom'])

    gen_prompt = f"""ГЕНЕРУЙ_XML

Згенеруй XML для маркетплейсу {schema['label']} ({marketplace}), категорія: {category}.
Кількість товарів: {count}.

Формат XML:
{schema['example']}

{"Дані товарів:" + chr(10) + source_data[:3000] if source_data else "Вигадай реалістичні приклади товарів для цієї категорії."}

Поверни ЛИШЕ XML код, без пояснень. Починай з <?xml version="1.0" encoding="UTF-8"?> або з кореневого тегу.
"""

    messages = list(sess['messages']) + [{'role': 'user', 'content': gen_prompt}]
    xml_text = call_ai(messages)

    # Витягуємо XML якщо є зайвий текст
    import re
    xml_match = re.search(r'(<\?xml[^>]*>|<yml_catalog).*', xml_text, re.DOTALL)
    if xml_match:
        xml_text = xml_match.group(0)

    # Прибираємо markdown ```xml ... ``` якщо є
    xml_text = re.sub(r'^```xml?\s*', '', xml_text, flags=re.MULTILINE)
    xml_text = re.sub(r'```\s*$', '', xml_text, flags=re.MULTILINE).strip()

    # Спроба форматування
    try:
        parsed = xml.dom.minidom.parseString(xml_text.encode('utf-8'))
        xml_text = parsed.toprettyxml(indent='  ', encoding=None)
        # Прибираємо зайву декларацію якщо вже є
        xml_text = xml_text.replace('<?xml version="1.0" ?>\n', '')
        xml_text = '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_text.lstrip()
    except Exception:
        pass

    return jsonify({'xml': xml_text})


if __name__ == '__main__':
    print('🤖 AI XML Generator запущено: http://0.0.0.0:5556')
    print('   Доступ з ноутбука: http://100.82.24.112:5556')
    if not ANTHROPIC_KEY:
        print('   ⚠️  ANTHROPIC_API_KEY відсутній — AI не буде працювати')
    app.run(host='0.0.0.0', port=5556, debug=False)

````

### `tools/competitor_scraper.py` — 472 рядків

````python
#!/usr/bin/env python3
"""
competitor_scraper.py — збирає товари продавця на Rozetka.

Використання:
    python3 tools/competitor_scraper.py
    python3 tools/competitor_scraper.py --seller ttul --pages 5
    python3 tools/competitor_scraper.py --no-save   # тільки вивід у консоль
"""

import asyncio
import json
import os
import random
import sys
from datetime import datetime
from pathlib import Path

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

import argparse
from loguru import logger
from dotenv import load_dotenv
from shared.utils.db import get_connection

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../.env"))

# ── Константи ─────────────────────────────────────────────

DEFAULT_SELLER = "ttul"
SELLER_URL = "https://rozetka.com.ua/ua/seller/{seller}/goods/"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
]

VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
    {"width": 1536, "height": 864},
]

# ── Stealth-браузер ───────────────────────────────────────

async def build_stealth_context(playwright, headless: bool = True):
    from playwright_stealth import Stealth

    browser = await playwright.chromium.launch(
        headless=headless,
        args=[
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--disable-infobars",
        ],
    )
    context = await browser.new_context(
        user_agent=random.choice(USER_AGENTS),
        viewport=random.choice(VIEWPORTS),
        locale="uk-UA",
        timezone_id="Europe/Kiev",
        extra_http_headers={
            "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        },
    )
    # Зберігаємо stealth instance для застосування до кожної нової page
    context._stealth = Stealth()
    return browser, context


async def human_delay(min_ms: int = 700, max_ms: int = 2000):
    await asyncio.sleep(random.uniform(min_ms / 1000, max_ms / 1000))


async def human_scroll(page, steps: int = 4):
    for _ in range(steps):
        await page.mouse.wheel(0, random.randint(300, 700))
        await human_delay(250, 700)


# ── DDL ───────────────────────────────────────────────────

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS competitor_products (
    id              SERIAL PRIMARY KEY,
    seller          TEXT        NOT NULL,
    title           TEXT        NOT NULL,
    price           NUMERIC(12, 2),
    category        TEXT,
    url             TEXT        UNIQUE,
    reviews_count   INTEGER     DEFAULT 0,
    scraped_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_competitor_seller
    ON competitor_products (seller);
CREATE INDEX IF NOT EXISTS idx_competitor_scraped_at
    ON competitor_products (scraped_at);
"""

def ensure_table():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(CREATE_TABLE_SQL)
    conn.commit()
    cur.close()
    conn.close()
    logger.debug("Table competitor_products: OK")


# ── Парсинг однієї сторінки товарів ──────────────────────

async def parse_page(page, seller: str, debug_dump: bool = False) -> list[dict]:
    """Витягує всі товари з поточної сторінки пагінації."""
    products = []

    # Debug: зберігаємо HTML після завантаження
    if debug_dump:
        try:
            html = await page.content()
            Path("/tmp/rozetka_debug.html").write_text(html, encoding="utf-8")
            logger.debug("HTML збережено в /tmp/rozetka_debug.html")
        except Exception as e:
            logger.warning(f"Не вдалось зберегти debug HTML: {e}")

    # Чекаємо поки картки завантажаться (Angular-компонент rz-product-tile)
    try:
        await page.wait_for_selector("rz-product-tile", timeout=30000)
    except Exception:
        logger.warning("Картки товарів не знайдені на сторінці")
        return products

    await human_scroll(page, steps=5)
    await human_delay(500, 1000)

    items = await page.query_selector_all("rz-product-tile")
    logger.debug(f"  Карток на сторінці: {len(items)}")

    for item in items:
        try:
            # Назва + URL (один елемент a.tile-title)
            title_el = await item.query_selector("a.tile-title")
            title = (await title_el.inner_text()).strip() if title_el else None
            if not title:
                continue
            url = await title_el.get_attribute("href") if title_el else None

            # Ціна
            price_el = await item.query_selector("[class*='price']")
            price_raw = (await price_el.inner_text()).strip() if price_el else "0"
            price = float(
                price_raw
                .replace("\u00a0", "")
                .replace("\xa0", "")
                .replace(",", ".")
                .replace("грн", "")
                .replace("₴", "")
                .strip() or 0
            )

            # Категорія з URL: https://rozetka.com.ua/ua/<category>/<id>/p<id>/
            category = None
            if url:
                parts = [p for p in url.split("/") if p and p not in ("ua", "https:", "rozetka.com.ua")]
                if parts:
                    category = parts[0]

            # Кількість відгуків
            reviews_el = await item.query_selector(".rating-block-rating")
            reviews_count = 0
            if reviews_el:
                raw = (await reviews_el.inner_text()).strip()
                digits = "".join(filter(str.isdigit, raw))
                reviews_count = int(digits) if digits else 0

            products.append({
                "seller": seller,
                "title": title,
                "price": price,
                "category": category,
                "url": url,
                "reviews_count": reviews_count,
            })

        except Exception as e:
            logger.warning(f"  Помилка парсингу картки: {e}")
            continue

    return products


# ── Пагінація ─────────────────────────────────────────────

async def get_total_pages(page) -> int:
    """Визначає кількість сторінок пагінації (rz-paginator)."""
    try:
        # Збираємо всі a.page всередині rz-paginator і беремо останній href
        links = await page.query_selector_all("rz-paginator a.page")
        max_page = 1
        for link in links:
            href = await link.get_attribute("href") or ""
            if "page=" in href:
                num = int(href.split("page=")[-1].split("&")[0])
                if num > max_page:
                    max_page = num
        return max_page
    except Exception:
        return 1


# ── Головний скрапер ──────────────────────────────────────

async def scrape_seller(seller: str, max_pages: int | None = None, headless: bool = True) -> list[dict]:
    from playwright.async_api import async_playwright

    base_url = SELLER_URL.format(seller=seller)
    all_products: list[dict] = []

    # Seller ID потрібен для API запитів (отримаємо з першої сторінки)
    seller_api_id: str | None = None

    async with async_playwright() as p:
        browser, context = await build_stealth_context(p, headless=headless)
        page = await context.new_page()
        # Застосовуємо stealth до сторінки
        if hasattr(context, '_stealth'):
            await context._stealth.apply_stealth_async(page)

        # ── Перехоплення API відповідей catalog-api ──────
        api_data: dict[int, list[dict]] = {}

        async def on_response(resp):
            if 'catalog-api.rozetka' in resp.url and resp.status == 200:
                try:
                    body = await resp.body()
                    data = json.loads(body)
                    goods = (data.get('data') or {}).get('goods', [])
                    # Визначаємо номер сторінки з URL
                    pnum = 1
                    if 'page:' in resp.url:
                        pnum = int(resp.url.split('page:')[1].split('&')[0])
                    if goods:
                        api_data[pnum] = goods
                        logger.debug(f"  API page {pnum}: {len(goods)} товарів")
                except Exception as e:
                    logger.debug(f"  API parse error: {e}")

        page.on('response', on_response)

        try:
            # ── Перша сторінка (SSR — парсимо DOM) ──────
            logger.info(f"Відкриваю {base_url}")
            await page.goto(base_url, wait_until="domcontentloaded", timeout=30000)
            await human_delay(1500, 2500)

            total_pages = await get_total_pages(page)
            if max_pages:
                total_pages = min(total_pages, max_pages)
            logger.info(f"Сторінок для обходу: {total_pages}")

            # Парсимо page 1 з DOM (SSR вже рендерений)
            products = await parse_page(page, seller, debug_dump=True)
            all_products.extend(products)
            logger.info(f"Стор. 1/{total_pages}: {len(products)} товарів")

            # ── Решта сторінок через API перехоплення ────
            for page_num in range(2, total_pages + 1):
                logger.info(f"Стор. {page_num}/{total_pages}")
                try:
                    api_data.pop(page_num, None)  # скидаємо старі дані

                    # Клікаємо пагінатор щоб Angular зробив API запит
                    link = await page.query_selector(
                        f"rz-paginator a.page[href*='page={page_num}']"
                    )
                    if link:
                        await link.click()
                    else:
                        await page.evaluate("""
                            () => {
                                const btn = document.querySelector(
                                    "[data-testid='pagination_to_next_page']:not(.disabled)"
                                );
                                if (btn) btn.click();
                            }
                        """)

                    # Чекаємо поки API відповідь буде перехоплена
                    for _ in range(40):  # до 8 секунд
                        if page_num in api_data:
                            break
                        await asyncio.sleep(0.2)

                    if page_num in api_data:
                        # Конвертуємо API дані у наш формат
                        products = _parse_api_goods(api_data[page_num], seller)
                    else:
                        # Fallback: парсимо DOM (якщо API не відповів)
                        logger.debug(f"  API не відповів, fallback DOM парсинг")
                        await page.wait_for_selector("rz-product-tile", timeout=20000)
                        await human_delay(1500, 2500)
                        products = await parse_page(page, seller)

                    all_products.extend(products)
                    logger.info(f"  +{len(products)} товарів  (всього: {len(all_products)})")

                except Exception as e:
                    logger.error(f"  Помилка на сторінці {page_num}: {e}")
                    continue

        finally:
            await browser.close()

    return all_products


def _parse_api_goods(goods: list[dict], seller: str) -> list[dict]:
    """Конвертує сирі дані catalog API у наш формат."""
    products = []
    for g in goods:
        try:
            title = g.get('title') or g.get('name') or ''
            if not title:
                continue

            # Ціна
            price_raw = g.get('price') or g.get('sell_price') or 0
            try:
                price = float(str(price_raw).replace('\xa0', '').replace(' ', '').replace(',', '.') or 0)
            except Exception:
                price = 0.0

            # URL
            url = g.get('href') or g.get('url') or ''

            # Категорія з URL
            category = None
            if url:
                parts = [p for p in url.split('/') if p and p not in ('ua', 'https:', 'rozetka.com.ua')]
                if parts:
                    category = parts[0]

            # Відгуки
            reviews_count = 0
            comments = g.get('comments_amount') or g.get('reviews_count') or 0
            if comments:
                try:
                    reviews_count = int(comments)
                except Exception:
                    pass

            products.append({
                'seller': seller,
                'title': title,
                'price': price,
                'category': category,
                'url': url,
                'reviews_count': reviews_count,
            })
        except Exception as e:
            logger.debug(f"  _parse_api_goods error: {e}")
    return products


# ── Збереження ────────────────────────────────────────────

def save_products(products: list[dict]) -> tuple[int, int]:
    """Повертає (saved, skipped)."""
    if not products:
        return 0, 0

    conn = get_connection()
    cur = conn.cursor()
    saved = skipped = 0

    for p in products:
        try:
            cur.execute(
                """
                INSERT INTO competitor_products
                    (seller, title, price, category, url, reviews_count, scraped_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (url) DO UPDATE SET
                    price        = EXCLUDED.price,
                    reviews_count = EXCLUDED.reviews_count,
                    scraped_at   = EXCLUDED.scraped_at
                """,
                (
                    p["seller"], p["title"], p["price"],
                    p["category"], p["url"], p["reviews_count"],
                    datetime.utcnow(),
                ),
            )
            saved += 1
        except Exception as e:
            logger.warning(f"Помилка збереження: {e} | {p.get('url')}")
            skipped += 1

    conn.commit()
    cur.close()
    conn.close()
    return saved, skipped


# ── CLI ───────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Парсинг товарів продавця на Rozetka"
    )
    parser.add_argument(
        "--seller", default=DEFAULT_SELLER,
        help=f"Slug продавця (за замовчуванням: {DEFAULT_SELLER})",
    )
    parser.add_argument(
        "--pages", type=int, default=None,
        help="Максимальна кількість сторінок (за замовчуванням: всі)",
    )
    parser.add_argument(
        "--no-save", action="store_true",
        help="Не зберігати в БД, тільки вивести в консоль",
    )
    parser.add_argument(
        "--headful", action="store_true",
        help="Запустити браузер у видимому режимі (для ручного проходження Cloudflare)",
    )
    args = parser.parse_args()

    logger.info(f"Старт: seller={args.seller}, max_pages={args.pages or 'всі'}, headless={not args.headful}")

    products = asyncio.run(scrape_seller(args.seller, max_pages=args.pages, headless=not args.headful))

    if not products:
        logger.warning("Товарів не знайдено — перевір selector або доступність сайту")
        sys.exit(1)

    if args.no_save:
        for p in products:
            print(f"{p['price']:>10.2f} грн | {p['reviews_count']:>4} відг. | {p['title'][:60]}")
    else:
        ensure_table()
        saved, skipped = save_products(products)
        logger.success(
            f"Готово: знайдено {len(products)}, збережено {saved}, пропущено {skipped}"
        )

    # ── Звіт ──────────────────────────────────────────────
    if products:
        prices = [p["price"] for p in products if p["price"]]
        categories = {}
        for p in products:
            categories[p["category"] or "unknown"] = categories.get(p["category"] or "unknown", 0) + 1

        print("\n" + "=" * 55)
        print(f"  Продавець       : {args.seller}")
        print(f"  Всього товарів  : {len(products)}")
        if prices:
            print(f"  Мін. ціна       : {min(prices):.2f} грн")
            print(f"  Макс. ціна      : {max(prices):.2f} грн")
            print(f"  Середня ціна    : {sum(prices)/len(prices):.2f} грн")
        print(f"  Категорії ({len(categories)}):")
        for cat, cnt in sorted(categories.items(), key=lambda x: -x[1])[:10]:
            print(f"    {cnt:>4}x  {cat}")
        print("=" * 55)


if __name__ == "__main__":
    main()

````

### `tools/epicentr_attrs_explorer.py` — 385 рядків

````python
"""
tools/epicentr_attrs_explorer.py
=================================
Отримує всі обов'язкові атрибути для 7 категорій Єпіцентру через PIM API.

Запуск на сервері:
  cd /home/tek/agent-system && source venv/bin/activate
  EPICENTR_TOKEN=$(grep EPICENTR_TOKEN .env | cut -d= -f2) python3 tools/epicentr_attrs_explorer.py

Що робить:
  1. Сканує /v2/pim/attribute-sets (паралельно) — знаходить наші 6 atsets
  2. Для кожного required select/multiselect — бере всі options
  3. Зберігає в epicentr_required_attrs
  4. Виводить звіт + valuecodes для 'Універсальна' в car_brand
"""

import os, sys, json, time, threading
import requests
import psycopg2
from psycopg2.extras import execute_batch, Json

BASE    = 'https://merchant-api.epicentrm.com.ua'
TOKEN   = os.environ.get('EPICENTR_TOKEN', '')
HEADERS = {'Authorization': f'Bearer {TOKEN}'}
DB_DSN  = 'host=localhost port=5432 dbname=agentdb user=agentadmin password=1'

OUR_CATS = {
    '8743': 'Перехідні рамки для автомагнітол',
    '4907': 'Магнітоли',
    '3729': 'Камери заднього огляду',
    '2821': 'Кабелі та перехідники',
    '2848': 'Аксесуари для автосигналізацій',
    '2866': 'Автомагнітоли',
}

# ── API ──────────────────────────────────────────────────────────────────────

def _get(path, params=None, retries=3):
    for attempt in range(retries):
        try:
            r = requests.get(BASE + path, headers=HEADERS, params=params, timeout=20)
            if r.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            if attempt == retries - 1:
                raise
            time.sleep(1)


def _scan_pages_parallel(path, params=None, workers=20):
    """Сканує всі сторінки паралельно, повертає всі items."""
    params = dict(params or {})
    params['limit'] = 100
    first = _get(path, {**params, 'page': 1})
    total = first.get('pages', 1)
    all_items = list(first.get('items', []))

    results = {1: all_items}
    lock = threading.Lock()

    def fetch(pg):
        try:
            data = _get(path, {**params, 'page': pg})
            with lock:
                results[pg] = data.get('items', [])
        except Exception as e:
            with lock:
                results[pg] = []

    for i in range(2, total + 1, workers):
        batch = range(i, min(i + workers, total + 1))
        threads = [threading.Thread(target=fetch, args=(pg,)) for pg in batch]
        for t in threads: t.start()
        for t in threads: t.join()

    ordered = []
    for pg in sorted(results):
        ordered.extend(results[pg])
    return ordered, total


def get_options(atset_code, attr_code, workers=30):
    """Повертає всі options для атрибута: [{code, name_ua}]."""
    # brand має 54370 опцій — беремо з кешу щоб не сканувати 544 сторінки
    if attr_code == 'brand':
        return get_brand_options_from_cache(atset_code)

    path = f'/v2/pim/attribute-sets/{atset_code}/attributes/{attr_code}/options'
    items, pages = _scan_pages_parallel(path, workers=workers)
    result = []
    for item in items:
        name_ua = next(
            (t['value'] for t in item.get('translations', []) if t['languageCode'] == 'ua'),
            item.get('code', ''))
        result.append({'code': item['code'], 'name_ua': name_ua})
    return result


def get_brand_options_from_cache(atset_code):
    """
    Бренди вже кешовані в epicentr_brand_cache (54370 брендів).
    Якщо кеш порожній — сканує API і кешує.
    """
    try:
        with psycopg2.connect(DB_DSN) as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT COUNT(*) FROM epicentr_brand_cache')
                cnt = cur.fetchone()[0]
        if cnt > 1000:
            print(f' (з кешу DB: {cnt} брендів)', end='', flush=True)
            with psycopg2.connect(DB_DSN) as conn:
                with conn.cursor() as cur:
                    cur.execute('SELECT valuecode, value_ua FROM epicentr_brand_cache LIMIT 200')
                    rows = cur.fetchall()
            # Повертаємо тільки перші 200 для звіту (54k не потрібно в JSON)
            return [{'code': r[0], 'name_ua': r[1]} for r in rows]
    except Exception:
        pass

    print(f' сканую brand (544 сторінки, ~60с)', end='', flush=True)
    path = f'/v2/pim/attribute-sets/{atset_code}/attributes/brand/options'
    items, _ = _scan_pages_parallel(path, workers=50)
    result = []
    for item in items:
        name_ua = next(
            (t['value'] for t in item.get('translations', []) if t['languageCode'] == 'ua'),
            item.get('code', ''))
        result.append({'code': item['code'], 'name_ua': name_ua})

    # Кешуємо в DB
    try:
        with psycopg2.connect(DB_DSN) as conn:
            with conn.cursor() as cur:
                execute_batch(cur,
                    'INSERT INTO epicentr_brand_cache (valuecode, value_ua) VALUES (%s,%s) ON CONFLICT DO NOTHING',
                    [(b['code'], b['name_ua']) for b in result])
            conn.commit()
    except Exception as e:
        print(f'  [warn] brand cache: {e}')

    return result[:200]


# ── SCAN ATSETS ──────────────────────────────────────────────────────────────

def scan_atsets_for_our_cats():
    """
    Сканує /v2/pim/attribute-sets паралельно, зупиняється коли знайшла всі 6.
    Повертає {cat_code: [{code, name_ua, type, is_required}]}.
    """
    remaining = set(OUR_CATS.keys())
    found = {}
    lock = threading.Lock()
    stop_event = threading.Event()

    def parse_items(items):
        for item in items:
            code = str(item.get('code', ''))
            if code in remaining:
                attrs = []
                for a in item.get('attributes', []):
                    name_ua = next(
                        (t['title'] for t in a.get('translations', []) if t['languageCode'] == 'ua'),
                        a.get('code', ''))
                    attrs.append({
                        'code':        a.get('code'),
                        'name_ua':     name_ua,
                        'type':        a.get('type'),
                        'is_required': bool(a.get('isRequired', False)),
                    })
                with lock:
                    found[code] = attrs
                    remaining.discard(code)
                    if not remaining:
                        stop_event.set()

    print('Сканую /v2/pim/attribute-sets щоб знайти наші 6 категорій...')
    first = _get('/v2/pim/attribute-sets', {'limit': 100, 'page': 1})
    total_pages = first.get('pages', 1)
    parse_items(first.get('items', []))
    print(f'  Всього сторінок: {total_pages}')
    if stop_event.is_set():
        print(f'  Знайдено всі 6 за першу сторінку!')
        return found

    WORKERS = 30
    results_buf = {}
    buf_lock = threading.Lock()

    def fetch(pg):
        if stop_event.is_set():
            return
        try:
            data = _get('/v2/pim/attribute-sets', {'limit': 100, 'page': pg})
            items = data.get('items', [])
            parse_items(items)
            with buf_lock:
                results_buf[pg] = len(items)
        except Exception as e:
            pass

    for i in range(2, total_pages + 1, WORKERS):
        if stop_event.is_set():
            break
        batch = range(i, min(i + WORKERS, total_pages + 1))
        threads = [threading.Thread(target=fetch, args=(pg,)) for pg in batch]
        for t in threads: t.start()
        for t in threads: t.join()
        done = len(found)
        print(f'  Сторінки {i}-{min(i+WORKERS-1, total_pages)}: знайдено {done}/6  (залишилось: {remaining})')
        if stop_event.is_set():
            break

    print(f'\nЗнайдено {len(found)}/6 категорій')
    if remaining:
        print(f'  НЕ знайдено: {remaining}')
    return found


# ── DB ───────────────────────────────────────────────────────────────────────

def init_db():
    with psycopg2.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS epicentr_required_attrs (
                    category_code  TEXT,
                    attr_code      TEXT,
                    attr_name_ua   TEXT,
                    attr_type      TEXT,
                    is_required    BOOLEAN,
                    options        JSONB,
                    PRIMARY KEY (category_code, attr_code)
                );
            """)
        conn.commit()
    print('DB: таблиця epicentr_required_attrs готова')


def save_attrs(cat_code, attrs, options_map):
    rows = []
    for a in attrs:
        opts = options_map.get(a['code'])
        rows.append((
            cat_code, a['code'], a['name_ua'], a['type'],
            a['is_required'],
            Json(opts) if opts is not None else None,
        ))
    with psycopg2.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            execute_batch(cur, """
                INSERT INTO epicentr_required_attrs
                    (category_code, attr_code, attr_name_ua, attr_type, is_required, options)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (category_code, attr_code) DO UPDATE
                    SET attr_name_ua=EXCLUDED.attr_name_ua,
                        attr_type=EXCLUDED.attr_type,
                        is_required=EXCLUDED.is_required,
                        options=EXCLUDED.options
            """, rows)
        conn.commit()
    print(f'  DB: збережено {len(rows)} атрибутів для кат. {cat_code}')


# ── REPORT ───────────────────────────────────────────────────────────────────

def print_report(cat_code, cat_name, attrs, options_map):
    required = [a for a in attrs if a['is_required']]
    optional = [a for a in attrs if not a['is_required']]

    print(f'\n{"="*60}')
    print(f'=== {cat_code}  {cat_name} ===')
    print(f'{"="*60}')
    print(f'Всього атрибутів: {len(attrs)}  |  Обов\'язкових: {len(required)}  |  Опціональних: {len(optional)}')

    if required:
        print('\n[ОБОВ\'ЯЗКОВІ]:')
        for a in required:
            opts = options_map.get(a['code'])
            if opts:
                # Шукаємо 'universal' або 'Універсальна'
                universal = [o for o in opts if
                             'universal' in o['code'].lower() or
                             'універс' in o['name_ua'].lower()]
                print(f'  {a["code"]} ({a["type"]}): {a["name_ua"]} — {len(opts)} options', end='')
                if universal:
                    for u in universal:
                        print(f'\n    ★ UNIVERSAL: code={u["code"]!r}  ua={u["name_ua"]!r}', end='')
                print()
            else:
                print(f'  {a["code"]} ({a["type"]}): {a["name_ua"]}')

    if optional:
        codes = [a['code'] for a in optional]
        print(f'\n[ОПЦІОНАЛЬНІ ({len(optional)})]: {", ".join(codes[:20])}', end='')
        if len(optional) > 20:
            print(f' … ще {len(optional)-20}', end='')
        print()


# ── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    if not TOKEN:
        sys.exit('EPICENTR_TOKEN не встановлено')

    init_db()

    # КРОК 1: знайти атрибути для всіх 6 категорій
    cat_attrs = scan_atsets_for_our_cats()

    if not cat_attrs:
        print('Нічого не знайдено. Перевір TOKEN і доступ до API.')
        return

    # КРОК 2 + 3 + 4: для кожної категорії — options + DB + звіт
    all_universal = {}  # {cat_code: {attr_code: [universal options]}}

    for cat_code, cat_name in OUR_CATS.items():
        attrs = cat_attrs.get(cat_code)
        if attrs is None:
            print(f'\n⚠️  {cat_code} {cat_name}: не знайдено в API')
            continue

        print(f'\n--- {cat_code} {cat_name}: отримую options для select/multiselect ---')

        options_map = {}
        select_attrs = [a for a in attrs if a['type'] in ('select', 'multiselect')]

        for a in select_attrs:
            is_req = '★' if a['is_required'] else ' '
            print(f'  {is_req} {a["code"]} ({a["type"]}) ...', end='', flush=True)
            try:
                opts = get_options(cat_code, a['code'])
                options_map[a['code']] = opts
                print(f' {len(opts)} options')
            except Exception as e:
                print(f' ПОМИЛКА: {e}')
                options_map[a['code']] = []

        save_attrs(cat_code, attrs, options_map)
        print_report(cat_code, cat_name, attrs, options_map)

        # Збираємо universal для підсумку
        universal_in_cat = {}
        for attr_code, opts in options_map.items():
            univ = [o for o in opts if
                    'universal' in o['code'].lower() or
                    'універс' in o['name_ua'].lower()]
            if univ:
                universal_in_cat[attr_code] = univ
        if universal_in_cat:
            all_universal[cat_code] = universal_in_cat

    # КРОК 5: Зведений звіт по 'universal' / 'Універсальна'
    print(f'\n{"="*60}')
    print('=== ЗВІТ: valuecode "Універсальна" по категоріях ===')
    print(f'{"="*60}')
    if all_universal:
        for cat_code, attrs in all_universal.items():
            print(f'\n  Категорія {cat_code} ({OUR_CATS.get(cat_code, "")}):')
            for attr_code, opts in attrs.items():
                for o in opts:
                    print(f'    {attr_code}: code={o["code"]!r}  ua={o["name_ua"]!r}')
    else:
        print('  Не знайдено жодного "universal" значення в обов\'язкових select-атрибутах.')

    # Підсумок по required атрибутах
    print(f'\n{"="*60}')
    print('=== ПІДСУМОК required атрибутів ===')
    print(f'{"="*60}')
    for cat_code, cat_name in OUR_CATS.items():
        attrs = cat_attrs.get(cat_code)
        if not attrs:
            print(f'  {cat_code}: N/A')
            continue
        req = [a for a in attrs if a['is_required']]
        print(f'  {cat_code} {cat_name}: {len(req)} обов\'язкових — {[a["code"] for a in req]}')


if __name__ == '__main__':
    main()

````

### `tools/epicentr_category_mapper.py` — 151 рядків

````python
"""
tools/epicentr_category_mapper.py
Fuzzy-match TOPTUL XML categories → Epicentr DB categories.
"""
import os, sys, re, requests
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher

sys.path.append('/home/tek/agent-system')
from dotenv import load_dotenv; load_dotenv('/home/tek/agent-system/.env')
from shared.utils.db import get_connection

TOPTUL_FEED_URL = os.getenv('TOPTUL_FEED_URL', '')


# ── helpers ──────────────────────────────────────────────────────────────────

def normalize(text: str) -> str:
    """Lowercase + collapse whitespace. Works across Cyrillic dialects."""
    return re.sub(r'\s+', ' ', (text or '').lower().strip())


def best_match(query: str, candidates: list[tuple]) -> tuple:
    """Return (score, code, name) with highest SequenceMatcher ratio."""
    q = normalize(query)
    best_score, best_code, best_name = 0.0, '', ''
    for code, name in candidates:
        score = SequenceMatcher(None, q, normalize(name)).ratio()
        if score > best_score:
            best_score, best_code, best_name = score, code, name
    return best_score, best_code, best_name


# ── fetch TOPTUL categories ───────────────────────────────────────────────────

def fetch_toptul_categories() -> list[tuple]:
    """Return list of (id, name) from TOPTUL XML feed."""
    print('Завантажуємо TOPTUL фід…', flush=True)
    r = requests.get(TOPTUL_FEED_URL, timeout=120)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    cats = root.find('shop').find('categories')
    if cats is None:
        return []
    result = []
    for c in cats.findall('category'):
        cid  = c.get('id', '')
        name = (c.text or '').strip()
        if cid and name:
            result.append((cid, name))
    print(f'TOPTUL: {len(result)} категорій', flush=True)
    return result


# ── fetch Epicentr categories from DB ────────────────────────────────────────

def fetch_epicentr_categories() -> list[tuple]:
    """Return list of (code, name_ua) from epicentr_categories."""
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute("SELECT code, name_ua FROM epicentr_categories WHERE name_ua IS NOT NULL AND name_ua != ''")
    rows = cur.fetchall()
    cur.close(); conn.close()
    result = [(r['code'], r['name_ua']) for r in rows]
    print(f'Єпіцентр: {len(result)} категорій', flush=True)
    return result


# ── create / populate mapping table ──────────────────────────────────────────

DDL = """
CREATE TABLE IF NOT EXISTS toptul_epicentr_category_map (
    toptul_id      VARCHAR(50)   PRIMARY KEY,
    toptul_name    VARCHAR(500),
    epicentr_code  VARCHAR(50),
    epicentr_name  VARCHAR(500),
    score          NUMERIC(5,4),
    confirmed      BOOLEAN       DEFAULT FALSE
);
"""

def save_mapping(rows: list[dict]):
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute(DDL)
    for row in rows:
        cur.execute("""
            INSERT INTO toptul_epicentr_category_map
                (toptul_id, toptul_name, epicentr_code, epicentr_name, score, confirmed)
            VALUES (%(toptul_id)s, %(toptul_name)s, %(epicentr_code)s, %(epicentr_name)s,
                    %(score)s, FALSE)
            ON CONFLICT (toptul_id) DO UPDATE
            SET toptul_name   = EXCLUDED.toptul_name,
                epicentr_code = EXCLUDED.epicentr_code,
                epicentr_name = EXCLUDED.epicentr_name,
                score         = EXCLUDED.score
        """, row)
    conn.commit()
    cur.close(); conn.close()
    print(f'Збережено {len(rows)} записів у toptul_epicentr_category_map', flush=True)


# ── display ───────────────────────────────────────────────────────────────────

def print_table(rows: list[dict]):
    sep = '+' + '-'*14 + '+' + '-'*42 + '+' + '-'*7 + '+' + '-'*42 + '+'
    hdr = '| {:<12} | {:<40} | {:<5} | {:<40} |'.format(
        'TOPTUL ID', 'TOPTUL назва', 'Score', 'Єпіцентр назва'
    )
    print(sep)
    print(hdr)
    print(sep)
    for r in rows:
        tname = r['toptul_name'][:40]
        ename = r['epicentr_name'][:40]
        score = f"{float(r['score']):.3f}"
        print('| {:<12} | {:<40} | {:<5} | {:<40} |'.format(
            r['toptul_id'], tname, score, ename
        ))
    print(sep)
    print(f'Всього: {len(rows)} рядків')


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    toptul  = fetch_toptul_categories()
    epicentr = fetch_epicentr_categories()

    print('Матчимо категорії…', flush=True)
    mapping = []
    for i, (tid, tname) in enumerate(toptul, 1):
        score, ecode, ename = best_match(tname, epicentr)
        mapping.append({
            'toptul_id':    tid,
            'toptul_name':  tname,
            'epicentr_code': ecode,
            'epicentr_name': ename,
            'score':         round(score, 4),
        })
        if i % 50 == 0:
            print(f'  {i}/{len(toptul)}…', flush=True)

    mapping.sort(key=lambda r: r['score'], reverse=True)
    save_mapping(mapping)
    print()
    print_table(mapping)


if __name__ == '__main__':
    main()

````

### `tools/epicentr_confirm_categories.py` — 218 рядків

````python
"""
tools/epicentr_confirm_categories.py
Інтерактивне підтвердження маппінгу TOPTUL → Єпіцентр категорій.

Клавіші:
  Enter  — підтвердити поточний маппінг
  1–5    — обрати альтернативу зі списку
  s      — пропустити (залишити unconfirmed)
  q      — вийти
"""
import os, sys, re
from difflib import SequenceMatcher

sys.path.append('/home/tek/agent-system')
from dotenv import load_dotenv; load_dotenv('/home/tek/agent-system/.env')
from shared.utils.db import get_connection

# ── ANSI кольори ─────────────────────────────────────────────────────────────
RESET  = '\033[0m'
BOLD   = '\033[1m'
GREEN  = '\033[32m'
YELLOW = '\033[33m'
CYAN   = '\033[36m'
RED    = '\033[31m'
DIM    = '\033[2m'

def clr(text, *codes): return ''.join(codes) + str(text) + RESET
def score_color(s):
    if s >= 0.75: return GREEN
    if s >= 0.55: return YELLOW
    return RED


# ── DB helpers ────────────────────────────────────────────────────────────────

def get_pending(conn) -> list:
    cur = conn.cursor()
    cur.execute("""
        SELECT toptul_id, toptul_name, epicentr_code, epicentr_name, score
        FROM toptul_epicentr_category_map
        WHERE score < 0.85 AND confirmed = false
        ORDER BY score DESC
    """)
    rows = list(cur.fetchall())
    cur.close()
    return rows


def count_pending(conn) -> int:
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM toptul_epicentr_category_map WHERE score < 0.85 AND confirmed = false")
    n = cur.fetchone()['count']
    cur.close()
    return n


def count_confirmed(conn) -> int:
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM toptul_epicentr_category_map WHERE confirmed = true")
    n = cur.fetchone()['count']
    cur.close()
    return n


def load_epicentr(conn) -> list:
    cur = conn.cursor()
    cur.execute("SELECT code, name_ua FROM epicentr_categories WHERE name_ua IS NOT NULL AND name_ua != ''")
    rows = [(r['code'], r['name_ua']) for r in cur.fetchall()]
    cur.close()
    return rows


def confirm_row(conn, toptul_id: str, epicentr_code: str, epicentr_name: str):
    cur = conn.cursor()
    cur.execute("""
        UPDATE toptul_epicentr_category_map
        SET confirmed=true, epicentr_code=%s, epicentr_name=%s,
            score = CASE WHEN epicentr_code != %s THEN 1.0 ELSE score END
        WHERE toptul_id=%s
    """, (epicentr_code, epicentr_name, epicentr_code, toptul_id))
    conn.commit()
    cur.close()


# ── fuzzy search ──────────────────────────────────────────────────────────────

def normalize(text: str) -> str:
    return re.sub(r'\s+', ' ', (text or '').lower().strip())


def top_alternatives(query: str, candidates: list, n: int = 5) -> list:
    q = normalize(query)
    scored = [
        (SequenceMatcher(None, q, normalize(name)).ratio(), code, name)
        for code, name in candidates
    ]
    scored.sort(reverse=True)
    return scored[:n]


# ── display ───────────────────────────────────────────────────────────────────

def clear_line():
    print('\033[2K\r', end='')


def print_header(done: int, total_pending: int, total: int):
    confirmed = total - total_pending
    bar_len = 40
    filled  = int(bar_len * confirmed / total) if total else 0
    bar     = clr('█' * filled, GREEN) + clr('░' * (bar_len - filled), DIM)
    pct     = confirmed / total * 100 if total else 0
    print(f"\n{clr('TOPTUL → Єпіцентр  Підтвердження категорій', BOLD, CYAN)}")
    print(f"[{bar}] {clr(f'{confirmed}/{total}', BOLD)} ({pct:.1f}%)")
    print(f"{clr(f'Залишилось: {total_pending}', YELLOW)}   "
          f"Enter=підтвердити  1-5=альтернатива  s=пропустити  q=вийти\n")


def print_row(idx: int, total_pending: int, toptul_name: str,
              epicentr_name: str, score: float):
    sc = f'{score:.3f}'
    print(clr(f'  [{idx}/{total_pending}]', DIM) +
          f'  {clr(toptul_name, BOLD)}')
    print(f"  {'→':>3}  {clr(epicentr_name, CYAN)}  "
          f"[{clr(sc, score_color(score))}]")


def print_alternatives(alts: list):
    print(f"\n  {clr('Альтернативи:', DIM)}")
    for i, (sc, code, name) in enumerate(alts, 1):
        sc_str = f'{sc:.3f}'
        print(f"  {clr(str(i), BOLD, YELLOW)}. {name:<50}  "
              f"[{clr(sc_str, score_color(sc))}]  {clr(code, DIM)}")


# ── main loop ─────────────────────────────────────────────────────────────────

def main():
    conn        = get_connection()
    epicentr    = load_epicentr(conn)
    total       = count_confirmed(conn) + count_pending(conn)
    pending     = get_pending(conn)
    total_pend  = len(pending)

    if not pending:
        print(clr('Всі записи вже підтверджені!', GREEN, BOLD))
        conn.close()
        return

    print_header(0, total_pend, total)

    done = 0
    i    = 0
    while i < len(pending):
        row  = pending[i]
        tid, tname, ecode, ename, score = (
            row['toptul_id'], row['toptul_name'],
            row['epicentr_code'], row['epicentr_name'], float(row['score'])
        )

        remaining = count_pending(conn)
        print_row(i + 1, total_pend, tname, ename, score)

        alts = top_alternatives(tname, epicentr, 5)
        print_alternatives(alts)
        print()

        try:
            raw = input(clr('  > ', BOLD)).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if raw == 'q':
            break

        elif raw == 's':
            print(clr('  пропущено', DIM))
            i += 1
            print()
            continue

        elif raw == '':
            # підтвердити поточний
            confirm_row(conn, tid, ecode, ename)
            done += 1
            print(clr('  ✓ підтверджено', GREEN))

        elif raw in ('1', '2', '3', '4', '5'):
            idx_alt = int(raw) - 1
            if idx_alt < len(alts):
                _, new_code, new_name = alts[idx_alt]
                confirm_row(conn, tid, new_code, new_name)
                done += 1
                print(clr(f'  ✓ обрано: {new_name}', GREEN))
            else:
                print(clr('  невірний номер', RED))
                continue

        else:
            print(clr('  невідома команда (Enter/1-5/s/q)', RED))
            continue

        i += 1
        print()

    conn.close()
    print(clr(f'\nЗавершено. Підтверджено за сесію: {done}', BOLD))
    conn2 = get_connection()
    left  = count_pending(conn2)
    conf  = count_confirmed(conn2)
    conn2.close()
    print(f'Підтверджено всього: {clr(conf, GREEN, BOLD)} / {total}')
    print(f'Залишилось непідтверджених: {clr(left, YELLOW, BOLD)}\n')


if __name__ == '__main__':
    main()

````

### `tools/epicentr_fill_attributes.py` — 367 рядків

````python
"""
tools/epicentr_fill_attributes.py
Заповнює порожні * колонки xlsx-експорту Єпіцентру.
НЕ додає нових колонок — тільки ті, що вже є у файлі.

Використання: python3 tools/epicentr_fill_attributes.py path/to/export.xlsx
"""

import sys, re, os, shutil
import openpyxl


# ── EAN-13 ────────────────────────────────────────────────────────────────────

def ean13_from_article(article: str) -> str:
    digits = re.sub(r'\D', '', str(article))
    digits = digits[-12:].zfill(12) if len(digits) >= 12 else digits.zfill(12)
    odd   = sum(int(digits[i]) for i in range(0, 12, 2))
    even  = sum(int(digits[i]) for i in range(1, 12, 2))
    return digits + str((10 - (odd + even * 3) % 10) % 10)


# ── Extraction helpers ────────────────────────────────────────────────────────

def extract_model_code(name: str) -> str:
    codes = re.findall(r'\b[A-Z]{2,}[A-Z0-9]*[0-9]+[A-Z0-9]*\b', str(name))
    return codes[-1] if codes else ''


def first_num(text: str):
    m = re.search(r'(\d+(?:[.,]\d+)?)', str(text))
    return float(m.group(1).replace(',', '.')) if m else None


def count_before_unit(text: str):
    m = re.search(r'(\d+)\s*(?:ед|шт|пр|од)\.?\b', str(text), re.I)
    return int(m.group(1)) if m else None


def num_with_unit(text: str, unit: str):
    m = re.search(rf'(\d+(?:[.,]\d+)?)\s*{re.escape(unit)}\b', str(text), re.I)
    return float(m.group(1).replace(',', '.')) if m else None


def drive_square(text: str) -> str:
    for frac in ('3/4', '1/2', '3/8', '1/4'):
        if frac in text:
            return frac + '"'
    if re.search(r'\b1\s*["″]', text):
        return '1"'
    return ''


# ── Category handlers ─────────────────────────────────────────────────────────
# Each returns list of (col_regex_pattern, value).
# Pattern is matched against existing column headers that contain *.
# The regex ^ anchors to the start to avoid false matches.

def h_vorotky(name: str) -> list:
    nl = name.lower()
    if   'набір головок' in nl or ('набір' in nl and 'головк' in nl): vid = 'набір головок'
    elif re.search(r'тріскачк|трещотк', nl):   vid = 'тріскачка'
    elif 'вороток' in nl:                        vid = 'вороток'
    elif 'кардан'  in nl:                        vid = 'кардан'
    elif re.search(r'подовжувач|удлинитель|подовж', nl): vid = 'планка'
    elif re.search(r'перехідник|переходник', nl): vid = 'перехідник'
    elif 'головка' in nl:                         vid = 'головка'
    else:                                          vid = 'головка'
    return [(r'Вид\s*\*', vid)]


def h_klyuchi(name: str) -> list:
    nl = name.lower()
    if   re.search(r'ріжков', nl):                     vyd = 'ріжковий'
    elif re.search(r'накидн', nl):                     vyd = 'накидний'
    elif re.search(r'комбінован', nl):                 vyd = 'комбінований'
    elif re.search(r'hex|torx|імбус|шестигранн', nl):  vyd = 'шестигранний (імбусовий)'
    elif re.search(r'динамометричн', nl):              vyd = 'динамометричний'
    elif re.search(r'розвідн|разводн', nl):            vyd = ''   # немає у довіднику 903
    elif re.search(r'трубн', nl):                      vyd = 'трубний'
    else:                                               vyd = 'ріжковий'
    typ = 'набір ключів' if 'набір' in nl else 'ключ'
    qty = count_before_unit(name) or ''
    # Розмір — multiselect, значення тільки з довідника; залишаємо порожнім
    return [
        (r'Вид ключів\s*\*',         vyd),
        (r'Тип\s*\*',                typ),
        (r'Кількість у наборі\s*\*', qty),
    ]


def h_vikrutky(name: str) -> list:
    nu, nl = name.upper(), name.lower()
    if   re.search(r'\bPZ\b|pozidriv', nu):        shlits = 'позидрів (PZ)'
    elif re.search(r'\bPH\b|phillips', nu):         shlits = 'хрестоподібний (PH)'
    elif re.search(r'TORX|T\d+', nu):              shlits = 'зірочка (TORX)'
    elif re.search(r'\bHEX\b', nu):                shlits = 'шестигранний (HEX)'
    else:                                            shlits = 'прямий (SL)'
    vyd = 'набір викруток' if 'набір' in nl else 'викрутка'
    return [
        (r'Вид викрутки\s*\*', vyd),
        (r'Тип шліца\s*\*',    shlits),
    ]


def h_sharnirno(name: str) -> list:
    size_mm = num_with_unit(name, 'мм') or ''
    size_in = drive_square(name)
    return [
        (r'Типовий розмір\s*\*.*мм',  size_mm),
        (r'Типовий розмір\s*\*.*"',   size_in),
    ]


def h_bity(name: str) -> list:
    nu, nl = name.upper(), name.lower()
    qty = count_before_unit(name) or 1
    sm  = re.search(r'\b(PH\d+|PZ\d+|T\d+|HEX[\d.]+|SL[\d.]+)\b', nu)
    size = sm.group(1) if sm else ''
    if   re.search(r'\bPZ\b', nu):    typ = 'позидрів (PZ)'
    elif re.search(r'\bPH\b', nu):    typ = 'хрестоподібна (PH)'
    elif re.search(r'TORX|T\d+', nu): typ = 'зірочка (TORX)'
    elif re.search(r'\bHEX\b', nu):   typ = 'шестигранна (HEX)'
    elif re.search(r'\bSL\b', nu):    typ = 'пряма (SL)'
    else:                              typ = 'хрестоподібна (PH)'
    length = num_with_unit(name, 'мм') or 25
    return [
        (r'Матеріал виробу\s*\*',  'хромованадієва сталь'),
        (r'Розмір біти\s*\*',      size),
        (r'Тип біти\s*\*',         typ),
        (r'Довжина біти\s*\*',     length),
        (r'Кількість\s*\*',        qty),          # 'Кількість (float) (шт.)'
    ]


def h_molotky(name: str) -> list:
    nl = name.lower()
    if   re.search(r'рихтув', nl):               func = 'рихтувальний'
    elif re.search(r'мідн', nl):                 func = 'мідний'
    elif re.search(r'гумов', nl):                func = 'гумовий'
    elif re.search(r'полімерн|пластик|нейлон', nl): func = 'полімерний'
    else:                                          func = 'слюсарний'
    vyd = 'набір молотків' if 'набір' in nl else 'молоток'
    wt  = num_with_unit(name, 'г')
    if not wt:
        kg = num_with_unit(name, 'кг')
        wt = kg * 1000 if kg else 500
    return [
        (r'Вид\s*\*',         vyd),
        (r'Вид молотків\s*',  func),   # optional — no *, but try anyway
        (r'(?:^|\s)Вага\s*\*', wt),   # 'Вага* (float) (г)', not 'Вага упаковки*'
    ]


def h_dynamometr(name: str) -> list:
    rm = re.search(r'(\d+(?:[.,]\d+)?)\s*[-–]\s*(\d+(?:[.,]\d+)?)', name)
    if rm:
        mn = float(rm.group(1).replace(',', '.'))
        mx = float(rm.group(2).replace(',', '.'))
    else:
        nm = re.search(r'(\d+(?:[.,]\d+)?)\s*[HН][·•]?[мm]', name)
        mx = float(nm.group(1).replace(',', '.')) if nm else 100
        mn = 5
    return [
        (r'Мінімальне зусилля\s*\*',    mn),
        (r'Максимальне зусилля\s*\*',   mx),
    ]


def h_pnevmo_nabir(name: str) -> list:
    nl  = name.lower()
    if   'гайковерт' in nl: pred = 'гайковерт пневматичний'
    elif 'шліфмаш'   in nl: pred = 'пневматична шліфмашина'
    elif 'дриль'     in nl: pred = 'пневмодриль'
    else:                    pred = 'пневматичний інструмент'
    return [(r'Предмети в наборі\s*\*', pred)]


def h_nabory(name: str) -> list:
    nl  = name.lower()
    qty = count_before_unit(name) or first_num(name) or 1
    n   = int(qty)
    sel = 'до 20' if n < 20 else '20-49' if n < 50 else '50-110' if n <= 110 else 'більше 110'
    pack  = 'валіза пластикова' if re.search(r'валіз|кейс', nl) else 'коробка картонна'
    sfera = 'автомобільний' if re.search(r'авто|сто', nl) else 'універсальний'
    return [
        (r'Кількість в наборі\s*\*',   sel),
        (r'^Упаковка\s*\*',            pack),
        (r'Кількість у наборі\s*\*',   qty),
        (r'Сфера застосування\s*\*',   sfera),
    ]


def h_testery(name: str) -> list:
    nl = name.lower()
    vyd = 'мультиметр' if 'мультиметр' in nl else \
          'індикатор фази' if 'індикатор' in nl else 'тестер електричний'
    return [(r'Вид\s*\*', vyd)]


def h_multymetry(_: str) -> list:
    return [
        (r'Тип живлення\s*\*',          'батарейки'),
        (r'Вимірювання та тести\s*\*',  'напруга'),
    ]


def h_domkraty(_: str) -> list:
    return []   # Домкрати файл не має специфічних * атрибутів


def h_farbopulty(name: str) -> list:
    diam = num_with_unit(name, 'мм') or 1.4
    return [
        (r'Діаметр сопла\s*\*',     diam),
        (r'Витрата повітря\s*\*',   200),
    ]


HANDLERS = {
    'Воротки, тріскачки та головки': h_vorotky,
    'Ключі та набори ключів':        h_klyuchi,
    'Динамометричні ключі':          h_dynamometr,
    'Викрутки':                      h_vikrutky,
    'Шарнірно-губцевий інструмент':  h_sharnirno,
    'Біти для шуруповерта':          h_bity,
    'Молотки':                       h_molotky,
    'Набори пневмоінструменту':      h_pnevmo_nabir,
    'Набори інструментів':           h_nabory,
    'Тестери електричні':            h_testery,
    'Мультиметри':                   h_multymetry,
    'Домкрати':                      h_domkraty,
    'Фарбопульти пневматичні':       h_farbopulty,
}


# ── Column index helpers ──────────────────────────────────────────────────────

def build_col_index(headers: list) -> dict:
    """Returns {header_string: 0-based-index} for all non-None headers."""
    return {str(h): i for i, h in enumerate(headers) if h is not None}


def find_col(headers: list, pattern: str, require_star: bool = True) -> int | None:
    """First column whose header matches pattern (optionally must contain *)."""
    for i, h in enumerate(headers):
        if h is None:
            continue
        hs = str(h)
        if require_star and '*' not in hs:
            continue
        if re.search(pattern, hs, re.I | re.S):
            return i
    return None


def is_empty(value) -> bool:
    return value in (None, '', '0', 0)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print('Usage: python3 tools/epicentr_fill_attributes.py path/to/export.xlsx')
        sys.exit(1)

    in_path  = sys.argv[1]
    base_dir = os.path.dirname(in_path) or '.'
    base_nam = os.path.splitext(os.path.basename(in_path))[0]
    out_path = os.path.join(base_dir, base_nam + '_filled.xlsx')

    # ── Step 1: copy to preserve structure ───────────────────────────────────
    shutil.copy(in_path, out_path)
    print(f'Копію збережено: {out_path}')

    # ── Step 2: load copy ─────────────────────────────────────────────────────
    wb = openpyxl.load_workbook(out_path)
    ws = wb.active

    headers = [cell.value for cell in ws[1]]
    data_rows = ws.max_row - 1
    print(f'Колонок: {len(headers)}  Рядків: {data_rows}')

    # Detect primary category from first data row
    cat_ci = find_col(headers, r'Основна категорія', require_star=False)
    first_cat = ws.cell(row=2, column=(cat_ci or 0) + 1).value if cat_ci is not None else '?'
    print(f'Перша категорія: {first_cat}')

    # Pre-locate fixed columns (0-based)
    name_ci    = find_col(headers, r'Назва товару.*ua',     require_star=False)
    article_ci = find_col(headers, r'Артикул',              require_star=True)
    barcode_ci = find_col(headers, r'Штрих код',            require_star=False)
    model_ci   = find_col(headers, r'Модель виробника',     require_star=False)
    pack_cis   = {
        'Висота упаковки':  find_col(headers, r'Висота упаковки'),
        'Глибина упаковки': find_col(headers, r'Глибина упаковки'),
        'Вага упаковки':    find_col(headers, r'Вага упаковки'),
        'Ширина упаковки':  find_col(headers, r'Ширина упаковки'),
    }

    stats: dict[str, int] = {}

    def get(ri: int, ci: int):
        return ws.cell(row=ri, column=ci + 1).value

    def put(ri: int, ci: int, value, key: str):
        ws.cell(row=ri, column=ci + 1, value=value)
        stats[key] = stats.get(key, 0) + 1

    # ── Step 3: process rows ──────────────────────────────────────────────────
    for ri in range(2, ws.max_row + 1):
        name    = str(get(ri, name_ci)    or '') if name_ci    is not None else ''
        article = str(get(ri, article_ci) or '') if article_ci is not None else ''
        cat     = str(get(ri, cat_ci)     or '') if cat_ci     is not None else ''

        # Packaging dimensions: 0 → 1
        for pname, pc in pack_cis.items():
            if pc is not None and is_empty(get(ri, pc)):
                put(ri, pc, 1, pname)

        # Barcode: generate EAN-13
        if barcode_ci is not None and is_empty(get(ri, barcode_ci)) and article:
            put(ri, barcode_ci, ean13_from_article(article), 'Штрих код')

        # Model code: extract from name
        if model_ci is not None and is_empty(get(ri, model_ci)) and name:
            code = extract_model_code(name)
            if code:
                put(ri, model_ci, code, 'Модель виробника')

        # Category-specific attributes
        handler = HANDLERS.get(cat)
        if not handler:
            continue
        for pattern, value in handler(name):
            if not value and value != 0:
                continue
            ci = find_col(headers, pattern, require_star=False)
            if ci is not None and is_empty(get(ri, ci)):
                # Extract human-readable key: take text before first regex operator
                key = re.split(r'[\\*+?^${}|()\[\]]', pattern)[0].strip()
                put(ri, ci, value, key)

    # ── Step 4: save in place ─────────────────────────────────────────────────
    wb.save(out_path)
    print(f'Збережено: {out_path}')

    # ── Statistics ────────────────────────────────────────────────────────────
    print(f'\n{"Поле":<55} {"Заповнено":>10}')
    print('─' * 67)
    generic = ['Висота упаковки', 'Глибина упаковки', 'Вага упаковки', 'Ширина упаковки',
               'Штрих код', 'Модель виробника']
    for k in generic:
        if k in stats:
            print(f'  {k:<53} {stats[k]:>10}')
    cat_stats = {k: v for k, v in stats.items() if k not in generic}
    if cat_stats:
        print('  ' + '─' * 65)
        for k, v in sorted(cat_stats.items(), key=lambda x: -x[1]):
            print(f'  {k:<53} {v:>10}')
    print('─' * 67)
    print(f'  {"ВСЬОГО":<53} {sum(stats.values()):>10}')


if __name__ == '__main__':
    main()

````

### `tools/epicentr_pim_explorer.py` — 412 рядків

````python
"""
Epicentr PIM API explorer — categories, attributes, brands, countries.

Key facts:
- atset_code == category_code for all categories
- Brand options: 544 pages x100 = ~54400 brands, shared across atsets
- No search filter exists — scan all pages, cache in DB
- Country options: 50 pages x20 = ~1000 countries

DB: agentadmin/1/agentdb (docker exec agent_postgres psql -U agentadmin agentdb)
"""

import os, sys, time, threading
import requests
import psycopg2
from psycopg2.extras import execute_batch

BASE = 'https://merchant-api.epicentrm.com.ua'
TOKEN = os.environ.get('EPICENTR_TOKEN', '')
HEADERS = {'Authorization': 'Bearer ' + TOKEN}

DB_DSN = 'host=localhost port=5432 dbname=agentdb user=agentadmin password=1'

# Our target categories
OUR_CATS = {
    '8743': 'Перехідні рамки для автомагнітол',
    '4907': 'Магнітоли',
    '3729': 'Камери заднього огляду',
    '2821': 'Кабелі та перехідники',
    '2848': 'Аксесуари для автосигналізацій',
    '2883': 'LED-світло для автомобіля',
    '2866': 'Автомагнітоли',
}

OUR_BRANDS = ['QIV', 'Carav', 'Teyes', 'Pioneer', 'Alpine', 'Sony', 'Toyota']

# ── DB helpers ─────────────────────────────────────────────────────────────────

def get_conn():
    return psycopg2.connect(DB_DSN)


def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS epicentr_brand_map (
                    brand_name  TEXT NOT NULL,
                    atset_code  TEXT NOT NULL,
                    valuecode   TEXT NOT NULL,
                    value_ua    TEXT,
                    verified_at TIMESTAMP DEFAULT NOW(),
                    PRIMARY KEY (brand_name, atset_code)
                );
                CREATE TABLE IF NOT EXISTS epicentr_brand_cache (
                    valuecode  TEXT PRIMARY KEY,
                    value_ua   TEXT,
                    cached_at  TIMESTAMP DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS epicentr_country_cache (
                    valuecode  TEXT PRIMARY KEY,
                    value_ua   TEXT,
                    cached_at  TIMESTAMP DEFAULT NOW()
                );
            """)
        conn.commit()
    print('DB tables ready.')


# ── API helpers ────────────────────────────────────────────────────────────────

def _get(path, params=None, timeout=15):
    r = requests.get(BASE + path, headers=HEADERS, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _scan_pages(path, params=None, max_workers=20, verbose=False):
    """Scan all pages concurrently (limit=100 is max that works)."""
    params = dict(params or {})
    params['limit'] = 100
    first = _get(path, {**params, 'page': 1})
    total_pages = first.get('pages', 1)
    all_items = list(first.get('items', []))

    if verbose:
        print(f'  Total pages: {total_pages}')

    results = {1: all_items}
    lock = threading.Lock()

    def fetch(pg):
        try:
            data = _get(path, {**params, 'page': pg})
            with lock:
                results[pg] = data.get('items', [])
        except Exception as e:
            if verbose:
                print(f'  Page {pg} error: {e}')

    pages_left = list(range(2, total_pages + 1))
    batch_size = max_workers
    for i in range(0, len(pages_left), batch_size):
        batch = pages_left[i:i + batch_size]
        threads = [threading.Thread(target=fetch, args=(pg,)) for pg in batch]
        for t in threads: t.start()
        for t in threads: t.join()
        if verbose and (i // batch_size) % 10 == 0:
            print(f'  Progress: {min(i + batch_size, len(pages_left))}/{len(pages_left)} batches')

    ordered = []
    for pg in sorted(results):
        ordered.extend(results[pg])
    return ordered


# ── Core functions ─────────────────────────────────────────────────────────────

def get_category_atset(cat_code: str) -> str:
    """
    For Epicentr PIM, atset_code == category_code always.
    Returns immediately without API call.
    """
    return cat_code


def get_atset_attributes(atset_code: str) -> dict:
    """
    Scan attribute-sets pages to find attributes for given atset.
    Returns {attr_code: {name_ua, type, required}}.

    SLOW (1824 pages). Use only when needed.
    """
    path = '/v2/pim/attribute-sets'
    target = {}
    params = {'limit': 100}
    first = _get(path, {**params, 'page': 1})
    total_pages = first.get('pages', 1)

    def check_items(items):
        for item in items:
            if item['code'] == atset_code:
                for a in item.get('attributes', []):
                    title_ua = next(
                        (t['title'] for t in a.get('translations', []) if t['languageCode'] == 'ua'), a['code'])
                    target[a['code']] = {
                        'name_ua': title_ua,
                        'type': a.get('type'),
                        'required': a.get('isRequired', False),
                    }
                return True
        return False

    if check_items(first.get('items', [])):
        return target

    found = threading.Event()
    lock = threading.Lock()

    def fetch(pg):
        if found.is_set():
            return
        try:
            data = _get(path, {**params, 'page': pg})
            if check_items(data.get('items', [])):
                found.set()
        except Exception:
            pass

    for i in range(2, total_pages + 1, 20):
        if found.is_set():
            break
        batch = range(i, min(i + 20, total_pages + 1))
        threads = [threading.Thread(target=fetch, args=(pg,)) for pg in batch]
        for t in threads: t.start()
        for t in threads: t.join()

    return target


def get_attribute_options(atset_code: str, attr_code: str, verbose=False) -> list:
    """
    Get all options for an attribute. Returns [{code, name_ua}].
    Scans all pages concurrently (limit=100, up to 544 pages for brand).
    """
    path = f'/v2/pim/attribute-sets/{atset_code}/attributes/{attr_code}/options'
    items = _scan_pages(path, verbose=verbose)
    result = []
    for item in items:
        name_ua = next(
            (t['value'] for t in item.get('translations', []) if t['languageCode'] == 'ua'),
            item.get('code', ''))
        result.append({'code': item['code'], 'name_ua': name_ua})
    return result


def _cache_brands(atset_code='8743', verbose=True) -> list:
    """
    Fetch and cache all brands in DB. Uses atset 8743 (brands are shared).
    Returns list of {code, name_ua}.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT COUNT(*) FROM epicentr_brand_cache')
            cnt = cur.fetchone()[0]
    if cnt > 1000:
        if verbose:
            print(f'Using cached {cnt} brands from DB.')
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT valuecode, value_ua FROM epicentr_brand_cache')
                return [{'code': r[0], 'name_ua': r[1]} for r in cur.fetchall()]

    print(f'Caching all brands from API (544 pages × 100)...')
    brands = get_attribute_options(atset_code, 'brand', verbose=verbose)
    with get_conn() as conn:
        with conn.cursor() as cur:
            execute_batch(cur,
                'INSERT INTO epicentr_brand_cache (valuecode, value_ua) VALUES (%s, %s) ON CONFLICT DO NOTHING',
                [(b['code'], b['name_ua']) for b in brands])
        conn.commit()
    print(f'Cached {len(brands)} brands.')
    return brands


def _match_brand(query: str, brands: list) -> tuple | None:
    """
    Exact and fuzzy brand matching.
    Returns (code, name_ua) or None.
    Priority: exact → startswith → word-contains
    """
    q = query.lower().strip()
    exact, starts, contains = None, None, None
    for b in brands:
        name = b['name_ua'].lower().strip()
        if name == q:
            exact = (b['code'], b['name_ua'])
            break
        if name.startswith(q) or q.startswith(name):
            if starts is None:
                starts = (b['code'], b['name_ua'])
        elif q in name.split() or any(w == q for w in name.split()):
            if contains is None:
                contains = (b['code'], b['name_ua'])
    return exact or starts or contains


def find_brand(brand_name: str, atset_code: str = '8743') -> tuple | None:
    """Find brand in Epicentr options. Returns (code, name_ua) or None."""
    brands = _cache_brands(atset_code, verbose=False)
    return _match_brand(brand_name, brands)


def get_country_code(country_name: str, atset_code: str = '8743') -> tuple | None:
    """Find country code. Returns (code, name_ua) or None."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT COUNT(*) FROM epicentr_country_cache')
            cnt = cur.fetchone()[0]

    if cnt < 50:
        path = f'/v2/pim/attribute-sets/{atset_code}/attributes/country_of_origin/options'
        countries = _scan_pages(path)
        with get_conn() as conn:
            with conn.cursor() as cur:
                execute_batch(cur,
                    'INSERT INTO epicentr_country_cache (valuecode, value_ua) VALUES (%s, %s) ON CONFLICT DO NOTHING',
                    [(c['code'], next((t['value'] for t in c.get('translations', []) if t['languageCode'] == 'ua'), c['code']))
                     for c in countries])
            conn.commit()
        print(f'Cached {len(countries)} countries.')

    with get_conn() as conn:
        with conn.cursor() as cur:
            q = country_name.lower()
            cur.execute('SELECT valuecode, value_ua FROM epicentr_country_cache WHERE LOWER(value_ua) = %s', (q,))
            row = cur.fetchone()
            if row:
                return row[0], row[1]
            cur.execute("SELECT valuecode, value_ua FROM epicentr_country_cache WHERE LOWER(value_ua) LIKE %s LIMIT 1", (q + '%',))
            row = cur.fetchone()
            return (row[0], row[1]) if row else None


def explore_category(cat_code: str) -> dict:
    """Full category report: atset, attributes, brand options count, our brand search."""
    atset = get_category_atset(cat_code)
    title = OUR_CATS.get(cat_code, cat_code)
    print(f'\n{"="*60}')
    print(f'Category {cat_code}: {title}')
    print(f'AtSet code: {atset}')
    print(f'{"="*60}')

    # Get attributes (fast path — skip full scan, just check known system attrs)
    known_attrs = ['measure', 'ratio', 'brand', 'country_of_origin', 'weight', 'width', 'height', 'length']
    print('\nChecking known system attributes...')
    attr_status = {}
    for attr in known_attrs:
        try:
            r = requests.get(BASE + f'/v2/pim/attribute-sets/{atset}/attributes/{attr}/options',
                             headers=HEADERS, params={'limit': 1}, timeout=10)
            if r.status_code == 200:
                pages = r.json().get('pages', 0)
                attr_status[attr] = pages
                print(f'  {attr}: OK (pages={pages})')
            else:
                print(f'  {attr}: {r.status_code}')
        except Exception as e:
            print(f'  {attr}: error {e}')

    # Search our brands
    print('\nSearching our brands...')
    brands_all = _cache_brands(verbose=False)
    brand_results = {}
    for brand in OUR_BRANDS:
        match = _match_brand(brand, brands_all)
        brand_results[brand] = match
        status = f'✅ code={match[0]} name={match[1]}' if match else '❌ NOT FOUND'
        print(f'  {brand}: {status}')

    # Country check
    print('\nCountry "Китай":')
    cn = get_country_code('Китай', atset)
    print(f'  {"✅ code=" + cn[0] if cn else "❌ NOT FOUND"}')

    return {
        'cat_code': cat_code,
        'atset': atset,
        'title': title,
        'brands': brand_results,
        'china_code': cn[0] if cn else None,
    }


def build_brand_map(cat_codes: list = None) -> dict:
    """
    Build brand→valuecode mapping for all our categories.
    Saves to epicentr_brand_map table.
    """
    if cat_codes is None:
        cat_codes = list(OUR_CATS.keys())

    brands_all = _cache_brands(verbose=True)
    mapping = {}

    with get_conn() as conn:
        rows = []
        for cat_code in cat_codes:
            atset = get_category_atset(cat_code)
            for brand in OUR_BRANDS:
                match = _match_brand(brand, brands_all)
                if match:
                    code, name_ua = match
                    mapping[brand] = {'code': code, 'name_ua': name_ua}
                    rows.append((brand, atset, code, name_ua))

        with conn.cursor() as cur:
            execute_batch(cur, """
                INSERT INTO epicentr_brand_map (brand_name, atset_code, valuecode, value_ua)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (brand_name, atset_code) DO UPDATE
                  SET valuecode=EXCLUDED.valuecode, value_ua=EXCLUDED.value_ua, verified_at=NOW()
            """, rows)
        conn.commit()

    print(f'\nSaved {len(rows)} brand mappings to DB.')
    return mapping


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    if not TOKEN:
        sys.exit('EPICENTR_TOKEN not set in environment')

    init_db()
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'explore'

    if cmd == 'explore':
        cat = sys.argv[2] if len(sys.argv) > 2 else '8743'
        explore_category(cat)

    elif cmd == 'explore-all':
        for cat_code in OUR_CATS:
            explore_category(cat_code)

    elif cmd == 'build-brand-map':
        print('\nBuilding brand map for all categories...')
        mapping = build_brand_map()
        print('\n=== Brand Map ===')
        for brand, info in mapping.items():
            print(f'  {brand} → {info["code"]} ({info["name_ua"]})')

    elif cmd == 'find-brand':
        brand = sys.argv[2] if len(sys.argv) > 2 else 'Pioneer'
        result = find_brand(brand)
        if result:
            print(f'Found: code={result[0]} name={result[1]}')
        else:
            print(f'Brand "{brand}" NOT FOUND in Epicentr')

    elif cmd == 'country':
        name = sys.argv[2] if len(sys.argv) > 2 else 'Китай'
        result = get_country_code(name)
        print(result if result else 'NOT FOUND')

    elif cmd == 'cache-brands':
        brands = _cache_brands(verbose=True)
        print(f'Total brands cached: {len(brands)}')

    else:
        print('Usage: python3 epicentr_pim_explorer.py [explore [cat_code] | explore-all | build-brand-map | find-brand NAME | country NAME | cache-brands]')

````

### `tools/epicentr_quality_checker.py` — 437 рядків

````python
"""
tools/epicentr_quality_checker.py
Інструмент перевірки якості XML-фіду для Єпіцентр.

CLI:
    python3 tools/epicentr_quality_checker.py --xml exports/carvol_epicentr.xml --report
    python3 tools/epicentr_quality_checker.py --xml exports/carvol_epicentr.xml --top-issues 20
    python3 tools/epicentr_quality_checker.py --xml exports/carvol_epicentr.xml --report --save-db
"""

import os, sys, re, json, argparse
from collections import Counter, defaultdict

import xml.etree.ElementTree as ET

sys.path.insert(0, '/home/tek/agent-system')
from dotenv import load_dotenv
load_dotenv('/home/tek/agent-system/.env')

from loguru import logger
from shared.utils.db import get_connection


CAR_BRANDS = [
    'Volkswagen', 'Toyota', 'BMW', 'Mercedes', 'Audi', 'Nissan',
    'Hyundai', 'Kia', 'Ford', 'Opel', 'Renault', 'Skoda',
    'Peugeot', 'Citroen', 'Chevrolet', 'Honda',
]

FORBIDDEN_WORDS = ['телефон', 'сайт', 'http', 'viber', 'telegram']


# ══════════════════════════════════════════════════════════════════════════════
# ProductChecker
# ══════════════════════════════════════════════════════════════════════════════

class ProductChecker:

    def check_vendor(self, offer: ET.Element, brand_cache: dict) -> dict:
        """brand_cache = {name_lower: (valuecode, value_ua)}
        Знайдено:   {ok: True,  score: 20, valuecode: '...', name: '...', issue: ''}
        Не знайдено:{ok: False, score: 0,  valuecode: '',    name: '...', issue: '...'}
        """
        vendor_el = offer.find('vendor')
        if vendor_el is None or not (vendor_el.text or '').strip():
            return {'ok': False, 'score': 0, 'valuecode': '', 'name': '',
                    'issue': 'Відсутній тег vendor'}
        name = vendor_el.text.strip()
        entry = brand_cache.get(name.lower())
        if entry:
            return {'ok': True, 'score': 20, 'valuecode': entry[0], 'name': entry[1], 'issue': ''}
        return {'ok': False, 'score': 0, 'valuecode': '', 'name': name,
                'issue': 'Бренд не зареєстрований'}

    def check_name(self, offer: ET.Element) -> dict:
        """score: 0-25"""
        score = 0
        issues = []
        name_el = offer.find("name[@lang='ua']")
        if name_el is None:
            name_el = offer.find('name')
        name = (name_el.text or '').strip() if name_el is not None else ''

        if not name:
            return {'score': 0, 'issues': ['Назва відсутня']}

        # 50-150 chars → +10
        if 50 <= len(name) <= 150:
            score += 10
        else:
            issues.append(f'Довжина назви {len(name)} симв. (потрібно 50-150)')

        # Car brand → +5
        if any(b.upper() in name.upper() for b in CAR_BRANDS):
            score += 5
        else:
            issues.append('Марка авто не знайдена в назві')

        # Inches or tech spec → +5
        if re.search(r'дюйм|дюймів|inch|"', name, re.IGNORECASE):
            score += 5

        # No ! or ? → +5
        if '!' not in name and '?' not in name:
            score += 5
        else:
            issues.append('Знаки ! або ? в назві')

        return {'score': score, 'issues': issues}

    def check_description(self, offer: ET.Element) -> dict:
        """score: 0-20
        >100 → +5, >300 → +5, >500 → +5, без заборонених слів → +5
        """
        score = 0
        issues = []
        desc_el = offer.find("description[@lang='ua']")
        if desc_el is None:
            desc_el = offer.find('description')
        text = (desc_el.text or '').strip() if desc_el is not None else ''

        if not text:
            return {'score': 0, 'issues': ['Опис відсутній']}

        if len(text) > 100:
            score += 5
        else:
            issues.append(f'Опис короткий ({len(text)} симв., потрібно >100)')
        if len(text) > 300:
            score += 5
        if len(text) > 500:
            score += 5

        text_lower = text.lower()
        found = [w for w in FORBIDDEN_WORDS if w in text_lower]
        if not found:
            score += 5
        else:
            issues.append(f'Заборонені слова в описі: {found}')

        return {'score': min(score, 20), 'issues': issues}

    def check_photos(self, offer: ET.Element) -> dict:
        """1 фото → 5, 2-3 → 10, 4+ → 15; score: 0-15"""
        count = len(offer.findall('picture'))
        if count == 0:
            return {'score': 0, 'count': 0, 'issues': ['Немає фото']}
        elif count == 1:
            return {'score': 5, 'count': 1, 'issues': []}
        elif count <= 3:
            return {'score': 10, 'count': count, 'issues': []}
        return {'score': 15, 'count': count, 'issues': []}

    def check_params(self, offer: ET.Element) -> dict:
        """measure є → +4, ratio є → +3, brand є → +3; score: 0-10"""
        score = 0
        issues = []
        by_code = {p.get('paramcode', ''): p for p in offer.findall('param')}

        m = by_code.get('measure')
        if m is not None and (m.get('valuecode') or '').strip():
            score += 4
        else:
            issues.append('measure відсутній або без valuecode')

        r = by_code.get('ratio')
        if r is not None and (r.text or '').strip():
            score += 3
        else:
            issues.append('ratio відсутній')

        b = by_code.get('brand')
        if b is not None and (b.text or '').strip():
            score += 3
        else:
            issues.append('brand param відсутній')

        return {'score': score, 'issues': issues}

    def check_logistics(self, offer: ET.Element) -> dict:
        """weight>0 → +3, всі габарити → +4, weight 50-50000 → +3; score: 0-10"""
        score = 0
        issues = []

        def num(tag: str) -> float:
            el = offer.find(tag)
            try:
                return float((el.text or '').strip()) if el is not None else 0.0
            except ValueError:
                return 0.0

        weight = num('weight')
        width, height, length = num('width'), num('height'), num('length')

        if weight > 0:
            score += 3
        else:
            issues.append('weight = 0')

        if width > 0 and height > 0 and length > 0:
            score += 4
        else:
            missing = [t for t, v in [('width', width), ('height', height), ('length', length)] if v == 0]
            issues.append(f'Відсутні габарити: {missing}')

        if 50 <= weight <= 50000:
            score += 3
        elif weight > 0:
            issues.append(f'Нереалістична вага {weight:.0f}г (50-50000)')

        return {'score': score, 'issues': issues}

    def calculate_score(self, offer: ET.Element, brand_cache: dict) -> int:
        """Сума всіх check_* методів. Повертає 0-100."""
        v  = self.check_vendor(offer, brand_cache)
        n  = self.check_name(offer)
        d  = self.check_description(offer)
        p  = self.check_photos(offer)
        pm = self.check_params(offer)
        lg = self.check_logistics(offer)
        return v['score'] + n['score'] + d['score'] + p['score'] + pm['score'] + lg['score']


# ══════════════════════════════════════════════════════════════════════════════
# QualityReport
# ══════════════════════════════════════════════════════════════════════════════

class QualityReport:

    def __init__(self):
        self.checker = ProductChecker()

    def load_brand_cache(self, conn) -> dict:
        """SELECT valuecode, value_ua FROM epicentr_brand_cache
        Повертає {value_ua.lower(): (valuecode, value_ua)}
        """
        cache = {}
        cur = conn.cursor()
        cur.execute("SELECT valuecode, value_ua FROM epicentr_brand_cache")
        for row in cur.fetchall():
            key = (row['value_ua'] or '').lower().strip()
            if key:
                cache[key] = (row['valuecode'], row['value_ua'])
        logger.info(f"Brand cache loaded: {len(cache)} entries")
        return cache

    def _init_table(self, conn):
        cur = conn.cursor()
        cur.execute("DROP TABLE IF EXISTS epicentr_quality_log")
        cur.execute("""
            CREATE TABLE epicentr_quality_log (
                offer_id        TEXT PRIMARY KEY,
                score           INTEGER,
                vendor_ok       BOOLEAN,
                vendor_issue    TEXT,
                name_score      INTEGER,
                desc_score      INTEGER,
                photo_count     INTEGER,
                params_score    INTEGER,
                logistics_score INTEGER,
                issues          JSONB,
                category        TEXT,
                checked_at      TIMESTAMP DEFAULT NOW()
            )
        """)
        conn.commit()
        logger.info("epicentr_quality_log — DROP + CREATE done")

    def _save_results(self, conn, results: list):
        sql = """
        INSERT INTO epicentr_quality_log
            (offer_id, score, vendor_ok, vendor_issue, name_score, desc_score,
             photo_count, params_score, logistics_score, issues, category, checked_at)
        VALUES
            (%(offer_id)s, %(score)s, %(vendor_ok)s, %(vendor_issue)s, %(name_score)s,
             %(desc_score)s, %(photo_count)s, %(params_score)s, %(logistics_score)s,
             %(issues)s::jsonb, %(category)s, NOW())
        ON CONFLICT (offer_id) DO UPDATE SET
            score=EXCLUDED.score, vendor_ok=EXCLUDED.vendor_ok,
            vendor_issue=EXCLUDED.vendor_issue, name_score=EXCLUDED.name_score,
            desc_score=EXCLUDED.desc_score, photo_count=EXCLUDED.photo_count,
            params_score=EXCLUDED.params_score, logistics_score=EXCLUDED.logistics_score,
            issues=EXCLUDED.issues, category=EXCLUDED.category, checked_at=NOW()
        """
        cur = conn.cursor()
        for r in results:
            row = dict(r)
            row['issues'] = json.dumps(row['issues'], ensure_ascii=False)
            cur.execute(sql, row)
        conn.commit()
        logger.info(f"Saved {len(results)} rows to epicentr_quality_log")

    def analyze_xml(self, xml_path: str, conn, save_db: bool = True) -> dict:
        """Парсить XML, рахує скори, опційно зберігає в БД (DROP+CREATE).
        Повертає dict зі summary та results.
        """
        brand_cache = self.load_brand_cache(conn)

        logger.info(f"Parsing: {xml_path}")
        tree = ET.parse(xml_path)
        root = tree.getroot()
        offers = root.findall('.//offer')
        logger.info(f"Offers found: {len(offers)}")

        c = self.checker
        results = []

        for offer in offers:
            v  = c.check_vendor(offer, brand_cache)
            n  = c.check_name(offer)
            d  = c.check_description(offer)
            p  = c.check_photos(offer)
            pm = c.check_params(offer)
            lg = c.check_logistics(offer)

            total = v['score'] + n['score'] + d['score'] + p['score'] + pm['score'] + lg['score']

            issues = []
            if not v['ok'] and v['issue']:
                issues.append(v['issue'])
            issues.extend(n['issues'])
            issues.extend(d['issues'])
            issues.extend(p['issues'])
            issues.extend(pm['issues'])
            issues.extend(lg['issues'])

            cat_el = offer.find('category')
            if cat_el is not None:
                category = (cat_el.text or cat_el.get('code', '') or '').strip()
            else:
                category = ''

            results.append({
                'offer_id':        offer.get('id', ''),
                'score':           total,
                'vendor_ok':       v['ok'],
                'vendor_issue':    v['issue'],
                'name_score':      n['score'],
                'desc_score':      d['score'],
                'photo_count':     p['count'],
                'params_score':    pm['score'],
                'logistics_score': lg['score'],
                'issues':          [i for i in issues if i],
                'category':        category,
            })

        if save_db:
            self._init_table(conn)
            self._save_results(conn, results)

        # Aggregation
        scores = [r['score'] for r in results]
        issue_counter: Counter = Counter()
        for r in results:
            for iss in r['issues']:
                issue_counter[iss] += 1

        buckets = {'90-100': 0, '70-89': 0, '50-69': 0, '30-49': 0, '0-29': 0}
        for s in scores:
            if s >= 90:   buckets['90-100'] += 1
            elif s >= 70: buckets['70-89'] += 1
            elif s >= 50: buckets['50-69'] += 1
            elif s >= 30: buckets['30-49'] += 1
            else:         buckets['0-29'] += 1

        cat_scores: dict = defaultdict(list)
        for r in results:
            if r['category']:
                cat_scores[r['category']].append(r['score'])
        cat_avg = {cat: round(sum(v) / len(v), 1) for cat, v in cat_scores.items()}

        return {
            'total':       len(results),
            'avg_score':   round(sum(scores) / len(scores), 1) if scores else 0,
            'min_score':   min(scores) if scores else 0,
            'max_score':   max(scores) if scores else 0,
            'buckets':     buckets,
            'vendor_ok':   sum(1 for r in results if r['vendor_ok']),
            'photo_4plus': sum(1 for r in results if r['photo_count'] >= 4),
            'top_issues':  issue_counter.most_common(50),
            'cat_avg':     dict(sorted(cat_avg.items(), key=lambda x: -x[1])),
            'results':     results,
        }

    def print_report(self, report: dict):
        """Таблиця розподілу + топ-10 проблем + середній score по категоріях."""
        total = report['total']
        print("\n" + "═" * 62)
        print("   ЗВІТ ЯКОСТІ — ЄПІЦЕНТР XML")
        print("═" * 62)
        print(f"  Товарів:          {total}")
        print(f"  Середній score:   {report['avg_score']}/100")
        print(f"  Мін / Макс:       {report['min_score']} / {report['max_score']}")
        print(f"  Бренд знайдено:   {report['vendor_ok']}  |  Не знайдено: {total - report['vendor_ok']}")
        print(f"  4+ фото:          {report['photo_4plus']}")
        print()
        print("  Розподіл score:")
        for bucket in ['90-100', '70-89', '50-69', '30-49', '0-29']:
            cnt = report['buckets'][bucket]
            pct = cnt / total * 100 if total else 0
            bar = '█' * int(pct / 2)
            print(f"    {bucket:7s}: {cnt:5d}  {pct:5.1f}%  {bar}")
        print()
        print("  Топ-10 проблем:")
        for issue, cnt in report['top_issues'][:10]:
            pct = cnt / total * 100 if total else 0
            print(f"    [{cnt:5d}  {pct:4.1f}%]  {issue}")
        if report.get('cat_avg'):
            print()
            print("  Середній score по категоріях (топ-10):")
            for cat, avg in list(report['cat_avg'].items())[:10]:
                print(f"    {avg:5.1f}  {cat}")
        print("═" * 62 + "\n")


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description='Epicentr XML Quality Checker')
    parser.add_argument('--xml', required=True, help='Шлях до XML файлу')
    parser.add_argument('--report', action='store_true', help='Показати звіт якості')
    parser.add_argument('--top-issues', type=int, default=0, metavar='N',
                        help='Показати топ-N проблем')
    parser.add_argument('--save-db', action='store_true',
                        help='Зберегти результати в БД (DROP + CREATE таблиці)')
    args = parser.parse_args()

    if not os.path.exists(args.xml):
        print(f"Файл не знайдено: {args.xml}")
        sys.exit(1)

    if not any([args.report, args.top_issues, args.save_db]):
        parser.print_help()
        sys.exit(0)

    conn = get_connection()
    try:
        rpt = QualityReport()
        report = rpt.analyze_xml(args.xml, conn, save_db=args.save_db)

        if args.report:
            rpt.print_report(report)

        if args.top_issues:
            print(f"\nТоп-{args.top_issues} проблем:")
            for issue, cnt in report['top_issues'][:args.top_issues]:
                pct = cnt / report['total'] * 100 if report['total'] else 0
                print(f"  [{cnt:5d}  {pct:4.1f}%]  {issue}")
            print()
    finally:
        conn.close()


if __name__ == '__main__':
    main()

````

### `tools/fix_rozetka_xml.py` — 561 рядків

````python
#!/usr/bin/env python3
"""
fix_rozetka_xml.py — виправляє price.xml за вимогами Розетки.

Використання:
    python tools/fix_rozetka_xml.py price.xml
    python tools/fix_rozetka_xml.py price.xml --out fixed_price.xml --errors errors.txt
    python tools/fix_rozetka_xml.py --url https://... --out fixed.xml
"""

import argparse
import re
import sys
import tempfile
from collections import Counter
from pathlib import Path

import requests

try:
    from lxml import etree as ET
    LXML = True
except ImportError:
    import xml.etree.ElementTree as ET
    LXML = False


# ── Очищення HTML ────────────────────────────────────────

import html as _html_module

# Видаляє будь-які HTML-теги, залишає лише текстовий вміст
_HTML_TAG_RE = re.compile(r"<[^>]+>")

def decode_html_entities(text: str) -> str:
    """&mdash; → —, &rsquo; → ', &nbsp; → ' ', тощо."""
    return _html_module.unescape(text or "")

def strip_html(text: str) -> str:
    """<a href="...">текст</a>  →  текст; також декодує HTML-ентіті."""
    clean = _HTML_TAG_RE.sub("", text)
    clean = decode_html_entities(clean)
    clean = re.sub(r"\s{2,}", " ", clean).strip()
    return clean


# ── Видалення рекламних фраз ─────────────────────────────

AD_PHRASES = [
    "почуваєшся майстром",
    "почувствуешь себя мастером",
    "профессионалами для профессионалов",
    "професіоналами для професіоналів",
    "гарантія успіху",
    "гарантия успеха",
    "незамінний помічник",
    "незаменимый помощник",
    "широкий термін служби",
    "широкий срок службы",
    "використовуючи інструменти toptul",
    "используя инструменты toptul",
    "створені професіоналами",
    "созданы профессионалами",
]

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")

def remove_ad_phrases(text: str) -> tuple[str, int]:
    """Видаляє речення що містять рекламні фрази.
    Повертає (очищений текст, кількість видалених речень)."""
    if not text:
        return text, 0
    sentences = _SENTENCE_RE.split(text)
    clean = []
    removed = 0
    lower_phrases = AD_PHRASES  # вже в нижньому регістрі
    for s in sentences:
        s_lower = s.lower()
        if any(ph in s_lower for ph in lower_phrases):
            removed += 1
        else:
            clean.append(s)
    return " ".join(clean).strip(), removed


# ── Форматування назви ────────────────────────────────────

def format_name(raw: str) -> str:
    """
    Схема: Тип Бренд Модель (Артикул)
    - Видаляє зайві дефіси між словами та коми між частинами назви
    - Нормалізує пробіли
    """
    # Видаляємо коми (розділювачі між частинами)
    name = raw.replace(",", " ")
    # Видаляємо дефіси що стоять між словами (тобто оточені пробілами)
    name = re.sub(r"\s+-\s+", " ", name)
    # Нормалізуємо пробіли
    name = re.sub(r"\s{2,}", " ", name).strip()
    return name


# ── Видалення категорій ───────────────────────────────────

REMOVE_CATEGORY_KEYWORDS = [
    "зарядные станции",
    "пусковые и зарядные",
]

def remove_categories(root, keywords: list[str]) -> int:
    """Видаляє offers чиї категорії містять будь-яке з ключових слів (без урахування регістру).
    Повертає кількість видалених offers."""
    # Будуємо карту categoryId → назва
    cat_names: dict[str, str] = {}
    for cat in root.iter("category"):
        cid = cat.get("id")
        if cid:
            cat_names[cid] = (cat.text or "").lower()

    # Знаходимо id категорій що підпадають під видалення
    blocked_ids: set[str] = set()
    for cid, name in cat_names.items():
        if any(kw in name for kw in keywords):
            blocked_ids.add(cid)

    # Видаляємо offers
    removed = 0
    for offers_parent in root.iter():
        to_remove = []
        for child in list(offers_parent):
            if child.tag == "offer":
                cat_el = child.find("categoryId")
                if cat_el is not None and cat_el.text in blocked_ids:
                    to_remove.append(child)
        for child in to_remove:
            offers_parent.remove(child)
            removed += 1

    return removed


# ── Переклад категорій ────────────────────────────────────

CATEGORY_TRANSLATIONS = {
    "Головки торцевые": "Головки торцеві",
    "Форсунки и ремкомплекты для краскопультов": "Форсунки та ремкомплекти для фарбопультів",
    "Головки торцевые ударные": "Головки торцеві ударні",
    "Краскопульты пневматические": "Фарбопульти пневматичні",
    "Цанговые соединения": "Цангові з'єднання",
    "Ключи комбинированные": "Ключі комбіновані",
    "Трещотки, воротки": "Тріскачки воротки",
    "Наборы инструмента в ложементах": "Набори інструменту в ложементах",
    "Отвертки": "Викрутки",
    "Плоскогубцы": "Плоскогубці",
    "Головки с насадкой": "Головки з насадкою",
    "Биты, насадки": "Біти насадки",
    "Переходники, удлинители, карданы": "Перехідники подовжувачі кардани",
    "Съемники подшипников": "Знімачі підшипників",
    "Наборы головок с трещоткой": "Набори головок з тріскачкою",
    "Развертки": "Розвертки",
    "Гайковерты пневматические": "Гайковерти пневматичні",
    "Зубила, пробойники, выколотки": "Зубила пробійники виколотки",
    "Ключи торцевые": "Ключі торцеві",
    "Наборы торцевых головок на планках": "Набори торцевих головок на планках",
    "Шарниры, карданы": "Шарніри кардани",
    "Съемники масляных фильтров": "Знімачі масляних фільтрів",
    "Ключи разрезные": "Ключі розрізні",
    "Метчики, плашки": "Мітчики плашки",
    "Пресс-клещи, обжимной инструмент": "Прес-кліщі обтискний інструмент",
    "Инструмент для тормозной системы": "Інструмент для гальмівної системи",
    "Воротки": "Воротки",
    "Захваты, зажимы": "Захвати затискачі",
    "Ключи трубные": "Ключі трубні",
    "Монтажный инструмент для сальников": "Монтажний інструмент для сальників",
    "Инструмент для работы с крепежом": "Інструмент для роботи з кріпленням",
    "Наборы ключей": "Набори ключів",
    "Динамометрические ключи": "Динамометричні ключі",
    "Ключи накидные": "Ключі накидні",
    "Наборы инструментов": "Набори інструментів",
    "Длинногубцы": "Довгогубці",
    "Кусачки, бокорезы": "Кусачки бокорізи",
    "Съемники ступиц": "Знімачі маточин",
    "Инструмент для сжатия пружин": "Інструмент для стиснення пружин",
    "Гидроцилиндры": "Гідроциліндри",
    "Станки для проточки тормозных дисков": "Верстати для проточування гальмівних дисків",
    "Маслозаправщики": "Маслозаправники",
    "Домкраты": "Домкрати",
    "Съемники рулевых наконечников": "Знімачі рульових наконечників",
    "Стенды для развала-схождения": "Стенди для розвалу сходження",
    "Прессы гидравлические": "Преси гідравлічні",
    "Стойки, подставки": "Стійки підставки",
    "Подъемники": "Підйомники",
    "Инструмент для двигателя": "Інструмент для двигуна",
    "Инструмент для КПП": "Інструмент для КПП",
    "Тиски": "Лещата",
    "Шуруповерт аккумуляторный": "Шуруповерт акумуляторний",
    "Отвертки аккумуляторные": "Викрутки акумуляторні",
    "Тестеры, диагностика": "Тестери діагностика",
    "Измерительные инструменты": "Вимірювальні інструменти",
    "Краскопульты безвоздушные": "Фарбопульти безповітряні",
    "Компрессоры": "Компресори",
    "Пневматические инструменты": "Пневматичні інструменти",
    "Ключи с трещоткой": "Ключі з тріскачкою",
    "Ключи рожковые": "Ключі ріжкові",
    "Ключи динамометрические": "Ключі динамометричні",
    "Ключи шестигранные": "Ключі шестигранні",
    "Наборы шестигранников": "Набори шестигранників",
    "Съемники рулевых тяг": "Знімачі рульових тяг",
    "Пневмопистолеты для подкачки колес": "Пневмопістолети для підкачування коліс",
    "Пневматические инструменты, аксессуары": "Пневматичні інструменти аксесуари",
    "Шланги, фитинги": "Шланги фітинги",
    "Аксессуары для компрессоров": "Аксесуари для компресорів",
    "Масленки, смазочный инструмент": "Маслянки мастильний інструмент",
    "Молотки": "Молотки",
    "Напильники": "Напилки",
    "Ножи монтажные": "Ножі монтажні",
    "Наборы инструмента": "Набори інструменту",
    "Наборы для авто": "Набори для авто",
    "Инструмент для рулевого управления": "Інструмент для рульового управління",
    "Инструмент для электрики": "Інструмент для електрики",
    "Съемники стопорных колец": "Знімачі стопорних кілець",
    "Зажимы, струбцины": "Затискачі струбцини",
    "Инструмент для кузовных работ": "Інструмент для кузовних робіт",
    "Пинцеты": "Пінцети",
    "Скребки": "Скребки",
    "Приспособления для снятия фаски": "Пристосування для зняття фаски",
    "Инструмент для радиаторов": "Інструмент для радіаторів",
    "Инструмент для подвески": "Інструмент для підвіски",
    "Ключи ударные": "Ключі ударні",
    "Наборы гаечных ключей": "Набори гайкових ключів",
    "Измерители температуры": "Вимірювачі температури",
    "Автосканеры": "Автосканери",
    "Наборы бит": "Набори біт",
    "Ключи (головки) ступичные": "Ключі головки ступичні",
    "Ящики, сумки для инструментов": "Ящики сумки для інструментів",
    "Подъемники автомобильные": "Підйомники автомобільні",
    "Отвертки крестовые, TORX": "Викрутки хрестові TORX",
    "Прокачка тормозов": "Прокачка гальм",
    "Стяжки пружин": "Стяжки пружин",
    "Съемники шаровых опор": "Знімачі кульових опор",
    "Нутромеры": "Нутроміри",
    "Микрометры": "Мікрометри",
    "Штангенциркули": "Штангенциркулі",
    "Индикаторы часового типа": "Індикатори годинникового типу",
    "Наборы метчиков и плашек": "Набори мітчиків та плашок",
    "Наборы напильников": "Набори напилків",
    "Ключи свечные": "Ключі свічні",
    "Съемники форсунок": "Знімачі форсунок",
    "Инструмент для сайлентблоков": "Інструмент для сайлентблоків",
    "Обжимной инструмент для шлангов": "Обтискний інструмент для шлангів",
    "Скобы, крюки, крепеж": "Скоби гачки кріплення",
    "Фонари, освещение": "Ліхтарі освітлення",
    "Рукоятки, ворота": "Рукоятки ворота",
    "Угольники": "Кутники",
    "Отвертки шлицевые": "Викрутки шліцеві",
    "Наборы инструмента комбинированные": "Набори інструменту комбіновані",
    "Съемники рулевых тяг и шаровых опор": "Знімачі рульових тяг та кульових опор",
    "Зенкеры": "Зенкери",
    "Головки специальные": "Головки спеціальні",
    "Тележки для инструментов": "Візки для інструментів",
    "Ключи специальные": "Ключі спеціальні",
    "Захваты для труб": "Захвати для труб",
    "Степперы, ступенчатые сверла": "Степпери ступінчасті свердла",
    "Наборы отверток": "Набори викруток",
    "Сверла": "Свердла",
    "Щупы": "Щупи",
    "Съемники клапанов": "Знімачі клапанів",
    "Хомуты": "Хомути",
    "Торцевые ключи": "Торцеві ключі",
    "Плоскогубцы переставные": "Плоскогубці переставні",
    "Ключи г-образные": "Ключі Г-подібні",
    "Магниты": "Магніти",
    "Кернеры": "Кернери",
    "Уровни": "Рівні",
    "Фонари и прожекторы": "Ліхтарі та прожектори",
    "Ключи, съемники специальные": "Ключі знімачі спеціальні",
    "Бокорезы, кусачки": "Бокорізи кусачки",
    "Шприцы для смазки": "Шприци для змащування",
    "Наборы торцевых головок": "Набори торцевих головок",
    "Круглогубцы для снятия стопорных колец": "Круглогубці для зняття стопорних кілець",
    "Безвоздушные распылители краски": "Безповітряні розпилювачі фарби",
    "Ремкомплекты для трещеток": "Ремкомплекти для тріскачок",
    "Струбцины": "Струбцини",
    "Кольца стопорные": "Кільця стопорні",
    "Насосы гидравлические": "Насоси гідравлічні",
}

def translate_categories(root) -> int:
    """Перекладає назви категорій за словником. Повертає кількість перекладених."""
    translated = 0
    for cat in root.iter("category"):
        original = (cat.text or "").strip()
        if original in CATEGORY_TRANSLATIONS:
            cat.text = CATEGORY_TRANSLATIONS[original]
            translated += 1
    return translated


# ── Видалення малих фото ──────────────────────────────────

def remove_offers_without_photos(root) -> int:
    """Видаляє всі offer що не мають жодного тегу <picture>.
    Повертає кількість видалених."""
    removed = 0
    for offers_parent in root.iter():
        to_remove = []
        for child in list(offers_parent):
            if child.tag == "offer" and not child.findall("picture"):
                to_remove.append(child)
        for child in to_remove:
            offers_parent.remove(child)
            removed += 1
    return removed


def remove_small_pictures(root, xlsx_path: str) -> int:
    """Читає Toptul_Image_Check.xlsx і видаляє <picture> з малим розміром.

    Структура XLSX: ID | ImageURL | Width | Height | Status
    Рядки де Status != 'OK' — малі фото, їх видаляємо.
    Повертає кількість видалених фото.
    """
    import openpyxl
    wb = openpyxl.load_workbook(xlsx_path, read_only=True)
    ws = wb.active
    bad_urls: set[str] = set()
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[0] and row[4] != "OK":
            bad_urls.add(row[1])
    wb.close()

    removed = 0
    no_photo_offers = 0
    for offer in root.iter("offer"):
        pics = offer.findall("picture")
        for pic in pics:
            url = (pic.text or "").strip()
            if url in bad_urls:
                offer.remove(pic)
                removed += 1
        if not offer.findall("picture"):
            no_photo_offers += 1

    print(f"[INFO] Видалено малих фото: {removed}")
    print(f"[INFO] Офферів без фото після видалення: {no_photo_offers}")
    return removed


# ── Основна обробка ───────────────────────────────────────

def process(input_path: Path, output_path: Path, errors_path: Path, images_check: str | None = None):
    # Парсимо з збереженням оригінального форматування якщо lxml
    if LXML:
        parser = ET.XMLParser(remove_blank_text=False)
        tree = ET.parse(str(input_path), parser)
        root = tree.getroot()
    else:
        tree = ET.parse(str(input_path))
        root = tree.getroot()

    # Знаходимо всі offer-елементи незалежно від структури документа
    offers = root.findall(".//offer")
    if not offers:
        print("[WARN] Не знайдено жодного <offer> в файлі.")

    fixed_stock = 0
    fixed_photos = 0
    fixed_html = 0
    fixed_ad_offers = 0
    fixed_ad_sentences = 0
    name_counts: Counter = Counter()
    name_to_ids: dict[str, list] = {}

    for offer in offers:
        offer_id = offer.get("id", "<no id>")

        # 1. stock_quantity ─────────────────────────────────
        if offer.find("stock_quantity") is None:
            sq = ET.SubElement(offer, "stock_quantity")
            sq.text = "10"
            fixed_stock += 1

        # 2. Форматування назви ─────────────────────────────
        name_el = offer.find("name")
        if name_el is not None and name_el.text:
            name_el.text = format_name(name_el.text)

        # 3. Очищення HTML з description / description_ua ───
        offer_ad_sentences = 0
        for field in ("description", "description_ua"):
            el = offer.find(field)
            if el is not None and el.text:
                original = el.text
                if "<" in original:
                    el.text = strip_html(el.text)
                    fixed_html += 1
                else:
                    el.text = decode_html_entities(el.text)
                # Видалення рекламних фраз
                el.text, removed = remove_ad_phrases(el.text)
                offer_ad_sentences += removed
        if offer_ad_sentences:
            fixed_ad_offers += 1
            fixed_ad_sentences += offer_ad_sentences

        # 4. Дублі фото ─────────────────────────────────────
        pictures = offer.findall("picture")
        seen_urls: set[str] = set()
        for pic in pictures:
            url = (pic.text or "").strip()
            if url in seen_urls:
                offer.remove(pic)
                fixed_photos += 1
            else:
                seen_urls.add(url)

        # 5. Збираємо назви для перевірки унікальності ──────
        name_el = offer.find("name")
        if name_el is not None and name_el.text:
            title = name_el.text.strip()
            name_counts[title] += 1
            name_to_ids.setdefault(title, []).append(offer_id)

    # 5. Визначаємо неунікальні назви
    duplicated_names = {n: ids for n, ids in name_to_ids.items() if name_counts[n] > 1}

    # 6. Видалення заборонених категорій ────────────────────
    removed_offers = remove_categories(root, REMOVE_CATEGORY_KEYWORDS)

    # 7. Переклад категорій ─────────────────────────────────
    translated_cats = translate_categories(root)

    # 8. Видалення малих фото (якщо передано xlsx) ──────────
    removed_small_pics = 0
    if images_check:
        if Path(images_check).exists():
            removed_small_pics = remove_small_pictures(root, images_check)
        else:
            print(f"[WARN] Файл не знайдено: {images_check}")

    # 9. Видалення офферів без фото ─────────────────────────
    removed_no_photo = remove_offers_without_photos(root)

    # ── Запис errors.txt ─────────────────────────────────
    with errors_path.open("w", encoding="utf-8") as ef:
        if duplicated_names:
            ef.write("=== Неунікальні назви товарів ===\n\n")
            for name, ids in sorted(duplicated_names.items()):
                ef.write(f"[{len(ids)}x] {name}\n")
                ef.write(f"      offer id: {', '.join(ids)}\n\n")
        else:
            ef.write("Неунікальних назв не знайдено.\n")

    # ── Запис fixed_price.xml ────────────────────────────
    if LXML:
        tree.write(
            str(output_path),
            pretty_print=True,
            xml_declaration=True,
            encoding="UTF-8",
        )
    else:
        ET.indent(tree)   # Python 3.9+
        tree.write(
            str(output_path),
            encoding="unicode",
            xml_declaration=False,
        )
        # Додаємо xml-декларацію вручну для ElementTree
        content = output_path.read_text(encoding="utf-8")
        output_path.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n' + content,
            encoding="utf-8",
        )

    # ── Звіт ─────────────────────────────────────────────
    print("=" * 50)
    print("Звіт fix_rozetka_xml")
    print("=" * 50)
    print(f"  Оброблено офферів  : {len(offers)}")
    print(f"  Додано stock_qty   : {fixed_stock}")
    print(f"  Очищено HTML опис  : {fixed_html}")
    print(f"  Видалено дублів фото: {fixed_photos}")
    print(f"  Видалено офферів   : {removed_offers} (заборонені категорії)")
    print(f"  Перекладено кат.   : {translated_cats}")
    print(f"  Офферів з рекламою : {fixed_ad_offers}")
    print(f"  Рекламних речень   : {fixed_ad_sentences} видалено")
    print(f"  Малих фото видалено: {removed_small_pics}")
    print(f"  Офферів без фото видалено: {removed_no_photo}")
    print(f"  Неунікальних назв  : {len(duplicated_names)}")
    print("-" * 50)
    print(f"  Вихідний файл      : {output_path}")
    print(f"  Файл помилок       : {errors_path}")
    print("=" * 50)

    if duplicated_names:
        sys.exit(1)   # Ненульовий код щоб CI міг відловити


# ── CLI ───────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Виправляє price.xml за вимогами Розетки"
    )
    parser.add_argument(
        "input", type=str, nargs="?", default=None,
        help="Локальний XML-файл або URL (позиційний)",
    )
    parser.add_argument(
        "--url", type=str, default=None,
        help="URL фіду — альтернатива позиційному аргументу",
    )
    parser.add_argument(
        "--out", type=Path, default=None,
        help="Вихідний файл (за замовчуванням: fixed_price.xml)",
    )
    parser.add_argument(
        "--errors", type=Path, default=Path("errors.txt"),
        help="Файл для списку неунікальних назв (за замовчуванням: errors.txt)",
    )
    parser.add_argument(
        "--images-check", type=str, default=None,
        help="Шлях до Toptul_Image_Check.xlsx для видалення малих фото",
    )
    args = parser.parse_args()

    src = args.url or args.input
    if not src:
        parser.error("Вкажи файл або --url <URL>")
    tmp = None

    if src.startswith("http://") or src.startswith("https://"):
        print(f"[INFO] Завантажую {src[:80]}...")
        try:
            resp = requests.get(src, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"[ERROR] Не вдалось завантажити URL: {e}", file=sys.stderr)
            sys.exit(2)
        tmp = tempfile.NamedTemporaryFile(suffix=".xml", delete=False)
        tmp.write(resp.content)
        tmp.flush()
        input_path = Path(tmp.name)
        output = args.out or Path("fixed_price.xml")
    else:
        input_path = Path(src)
        if not input_path.exists():
            print(f"[ERROR] Файл не знайдено: {input_path}", file=sys.stderr)
            sys.exit(2)
        output = args.out or input_path.parent / f"fixed_{input_path.name}"

    try:
        process(input_path, output, args.errors, images_check=args.images_check)
    finally:
        if tmp:
            Path(tmp.name).unlink(missing_ok=True)


if __name__ == "__main__":
    main()

````

### `tools/katran_category_xml.py` — 440 рядків

````python
#!/usr/bin/env python3
"""
tools/katran_category_xml.py — XML для конкретних категорій з фіду Катрана.

Usage:
  python3 tools/katran_category_xml.py 80158,237815
  python3 tools/katran_category_xml.py 80158,237815 --output /tmp/my.xml

Фіксить:
  - URL в description (видаляє)
  - Дублі URL фото (унікальні)
  - Дублі назв (додає артикул)
  - vendor порожній / "no name" → "Без бренду"
"""

import math
import os
import re
import subprocess
import sys
import zipfile
import io
from collections import Counter
from datetime import datetime
from xml.etree import ElementTree as ET

import requests
from dotenv import load_dotenv
from loguru import logger

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../.env"))

SHOP_NAME        = "HYPER_STORE"
SHOP_URL         = "https://seller.rozetka.com.ua/"
DEFAULT_COMMISSION = 7.0
DEFAULT_RZ_ID    = "25636737"
DEFAULT_CAT_NAME = "Інструменти"
URL_RE           = re.compile(r"https?://\S+")
VENDOR_BAD       = {"no name", "noname", "no-name", "unknown", ""}

# категорії що пропускаються повністю (мало характеристик або потребують дозволу)
SKIP_CATEGORIES = {
    "80255",   # Батарейки — без характеристик
    "80108",   # ДБЖ — потребує 60%+ виконаних замовлень і документів
    "4674585", # Зарядні станції — потребує дозволу
    "1554082", # Акумулятори для ДБЖ — потребує дозволу
}

# категорії де аксесуари без бренду допустимі (Кріплення для ТВ тощо)
ACCESSORIES_ALLOWED_CATS = {"80071"}

ACCESSORY_KEYWORDS = [
    "насадка", "фільтр для", "мішок для", "щітка для",
    "засіб для", "refill", "картридж для",
]

# ─── brand stop-list (VAL-67764, 2026-06-08) ─────────────────────────────────

STOP_BRANDS_UPPER = {
    'BOSCH', 'COOPER&HUNTER', 'TEFAL', 'SAMSUNG', 'ROWENTA',
    'PHILIPS', 'MOULINEX', 'DELONGHI',
    'COOPER', 'HUNTER',
}

# rz_id де заборонений бренд дозволений як виняток
STOP_BRANDS_EXCEPTIONS = {
    'BOSCH':   {'80133'},                                                         # Кондиціонери
    'SAMSUNG': {'80037', '4628124', '80100', '80105', '80193', '80194', '80090'}, # IT категорії
}


def is_stop_brand(vendor: str, rz_id: str) -> bool:
    vendor_upper = vendor.upper()
    for brand, allowed_cats in STOP_BRANDS_EXCEPTIONS.items():
        if brand in vendor_upper and rz_id in allowed_cats:
            return False
    for brand in STOP_BRANDS_UPPER:
        if brand in vendor_upper:
            return True
    return False


# ─── helpers (mirrors katran_xml_generator) ───────────────────────────────────

def get_katran_feed() -> ET.Element:
    url = os.getenv("KATRAN_FEED_URL_STOCK")
    if not url:
        raise ValueError("KATRAN_FEED_URL_STOCK не встановлено в .env")
    logger.info(f"[KatranCat] Завантажую фід...")
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        xml_names = [n for n in zf.namelist() if n.lower().endswith(".xml")]
        if not xml_names:
            raise ValueError("XML не знайдено в ZIP архіві")
        with zf.open(xml_names[0]) as f:
            return ET.parse(f).getroot()


def get_category_map() -> dict:
    try:
        from shared.utils.db import get_connection
        conn = get_connection()
        cur  = conn.cursor()
        cur.execute("""
            SELECT id, rozetka_category, rozetka_rz_id, commission_pct
            FROM katran_categories WHERE rozetka_rz_id IS NOT NULL
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        result = {}
        for r in rows:
            result[str(r["id"])] = {
                "rz_id":      str(r["rozetka_rz_id"]),
                "name":       r["rozetka_category"] or DEFAULT_CAT_NAME,
                "commission": float(r["commission_pct"]),
            }
        logger.info(f"[KatranCat] Категорій з БД: {len(result)}")
        return result
    except Exception as e:
        logger.warning(f"[KatranCat] БД недоступна: {e}")
        return {}


def parse_float(text: str) -> float:
    try:
        return float((text or "0").replace(",", ".").strip())
    except ValueError:
        return 0.0


def clean_text(text: str) -> str:
    return (text or "").strip()


def calc_price(price_rrc: float, commission_pct: float) -> int:
    if price_rrc <= 0:
        return 0
    return int(math.ceil(price_rrc * (1 + commission_pct / 100) / 10) * 10)


def is_in_stock(stock_str: str) -> bool:
    s = (stock_str or "").lower().strip()
    return s.startswith("е") or s.startswith("є")


def fix_name(name: str, artikul: str) -> str:
    if not name:
        return artikul
    name = re.sub(r'^[!@#$%^&*()\[\]{}\-_=+|\\/<>\'"`~]+\s*', '', name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:255] if name else artikul


def strip_urls(text: str) -> str:
    cleaned = URL_RE.sub("", text)
    return re.sub(r"\s{2,}", " ", cleaned).strip()


def xml_escape(text: str) -> str:
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def fix_vendor(raw: str) -> str:
    v = raw.strip()
    return "Без бренду" if v.lower() in VENDOR_BAD else v


# ─── core ─────────────────────────────────────────────────────────────────────

def generate_category_xml(rz_ids: list, output_file: str) -> dict:
    target_rz_ids = set(rz_ids) - SKIP_CATEGORIES
    skipped_cats = set(rz_ids) & SKIP_CATEGORIES
    if skipped_cats:
        logger.warning(f"[KatranCat] Пропускаю категорії зі SKIP_CATEGORIES: {skipped_cats}")
    logger.info(f"[KatranCat] Цільові rz_id: {target_rz_ids}")

    root     = get_katran_feed()
    cat_map  = get_category_map()

    products_el  = root.find("products")
    if products_el is None:
        products_el = root
    all_products = products_el.findall("product")
    logger.info(f"[KatranCat] Товарів у фіді: {len(all_products)}")

    # ── pass 1: filter qualifying products ────────────────────────────────
    qualified = []
    seen_artikuls: set = set()

    for p in all_products:
        code        = clean_text(p.findtext("code") or "")
        artikul     = clean_text(p.findtext("artikul") or code)
        stock_str   = clean_text(p.findtext("stock") or "")
        category_id = clean_text(p.findtext("categoryId") or "")
        cat_info    = cat_map.get(category_id, {})
        rz_id       = cat_info.get("rz_id", DEFAULT_RZ_ID)

        if rz_id not in target_rz_ids:
            continue
        if not is_in_stock(stock_str):
            continue
        if artikul in seen_artikuls:
            continue

        seen_artikuls.add(artikul)
        qualified.append((p, cat_info, rz_id, artikul))

    logger.info(f"[KatranCat] Відповідають фільтру: {len(qualified)}")

    # ── pass 2: count names to detect duplicates ──────────────────────────
    name_counter: Counter = Counter()
    for p, _, _, artikul in qualified:
        name_counter[fix_name(p.findtext("name") or "", artikul)] += 1

    # ── pass 3: build offers ──────────────────────────────────────────────
    categories_used: dict = {}
    offers_data: list = []
    brands: set = set()
    skipped_price     = 0
    skipped_sale      = 0
    skipped_accessory = 0
    skipped_brand     = 0
    skipped_nophoto   = 0

    for p, cat_info, rz_id, artikul in qualified:
        raw_name    = fix_name(p.findtext("name") or "", artikul)
        name        = f"{raw_name} ({artikul})" if name_counter[raw_name] > 1 else raw_name
        description = strip_urls(clean_text(p.findtext("description") or ""))
        vendor      = fix_vendor(clean_text(p.findtext("vendor") or ""))
        warranty    = clean_text(p.findtext("warranty") or "")
        stock_qty   = max(int(parse_float(p.findtext("stock_quantity") or "0")), 1)
        price_rrc   = parse_float(p.findtext("price_rrc") or "0")
        commission  = cat_info.get("commission", DEFAULT_COMMISSION)
        cat_name    = cat_info.get("name", DEFAULT_CAT_NAME)

        # фільтр уцінок і вживаних (після парсингу vendor)
        if vendor and ("уцін" in vendor.lower() or vendor.startswith("!") or "б/у" in vendor.lower()):
            skipped_sale += 1
            continue
        if "_У" in artikul and artikul.endswith("_У"):
            skipped_sale += 1
            continue

        # фільтр стоп-брендів (Philips, Tefal, Rowenta тощо — VAL-67764)
        if is_stop_brand(vendor, rz_id):
            skipped_brand += 1
            continue

        # фільтр аксесуарів без бренду
        if vendor == "Без бренду" and rz_id not in ACCESSORIES_ALLOWED_CATS:
            name_lower = name.lower()
            if any(kw in name_lower for kw in ACCESSORY_KEYWORDS):
                skipped_accessory += 1
                continue

        price = calc_price(price_rrc, commission)
        if price <= 0:
            skipped_price += 1
            continue

        # deduplicate photo URLs
        pictures: list = []
        seen_pics: set = set()
        images_el = p.find("images")
        if images_el is not None:
            for img in images_el.findall("image"):
                url = (img.text or img.get("url") or "").strip()
                last_seg = url.rstrip("/").split("/")[-1]
                if (url.startswith("http") and len(url) < 500
                        and last_seg and "." in last_seg
                        and url not in seen_pics):
                    seen_pics.add(url)
                    pictures.append(url)

        if not pictures:
            skipped_nophoto += 1
            continue

        if rz_id not in categories_used:
            categories_used[rz_id] = cat_name
        brands.add(vendor)

        offers_data.append({
            "artikul":     artikul,
            "name":        name,
            "description": description,
            "rz_id":       rz_id,
            "vendor":      vendor,
            "warranty":    warranty,
            "stock_qty":   stock_qty,
            "price":       price,
            "pictures":    pictures,
        })

    # ── build XML ─────────────────────────────────────────────────────────
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<yml_catalog date="{datetime.now().strftime("%Y-%m-%d %H:%M")}">',
        "  <shop>",
        f"    <name>{SHOP_NAME}</name>",
        "    <company>FOP Oliinyk Serhii</company>",
        f"    <url>{SHOP_URL}</url>",
        "    <currencies>",
        '      <currency id="UAH" rate="1"/>',
        "    </currencies>",
        "    <categories>",
    ]
    for cat_rz_id, cat_name in categories_used.items():
        lines.append(f'      <category id="{cat_rz_id}">{xml_escape(cat_name)}</category>')
    lines.extend(["    </categories>", "    <offers>"])

    for o in offers_data:
        oid   = xml_escape(o["artikul"])
        offer = [f'      <offer id="{oid}" available="true">']
        offer.append(f'        <price>{o["price"]}</price>')
        offer.append("        <currencyId>UAH</currencyId>")
        offer.append(f'        <categoryId>{o["rz_id"]}</categoryId>')
        for pic in o["pictures"][:10]:
            offer.append(f"        <picture>{pic}</picture>")
        offer.append(f'        <vendor>{xml_escape(o["vendor"])}</vendor>')
        offer.append(f'        <article>{xml_escape(o["artikul"])}</article>')
        offer.append(f'        <stock_quantity>{o["stock_qty"]}</stock_quantity>')
        offer.append(f'        <name_ua>{xml_escape(o["name"])}</name_ua>')
        if o["description"]:
            offer.append(
                f'        <description_ua><![CDATA[<p>{xml_escape(o["description"])}</p>]]></description_ua>'
            )
        offer.append(f'        <param name="Бренд">{xml_escape(o["vendor"])}</param>')
        if o["warranty"] and o["warranty"] != "0":
            offer.append(f'        <param name="Гарантія">{xml_escape(o["warranty"])} міс</param>')
        offer.append(f'        <param name="Артикул">{xml_escape(o["artikul"])}</param>')
        offer.append("      </offer>")
        lines.extend(offer)

    lines.extend(["    </offers>", "  </shop>", "</yml_catalog>"])

    os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    logger.success(f"[KatranCat] XML збережено: {output_file} ({len(offers_data)} офферів)")
    return {
        "output":        output_file,
        "total":         len(offers_data),
        "categories":    len(categories_used),
        "cat_names":     categories_used,
        "brands":        sorted(brands),
        "skipped_price":     skipped_price,
        "skipped_sale":      skipped_sale,
        "skipped_accessory": skipped_accessory,
        "skipped_brand":     skipped_brand,
        "skipped_nophoto":   skipped_nophoto,
    }


# ─── entry point ──────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Генерація XML Розетки по конкретних категоріях Катрана"
    )
    parser.add_argument("rz_ids", help="rz_id через кому: 80158,237815")
    parser.add_argument("--output", default=None, help="Вихідний XML (default: /tmp/katran_cat_{ids}.xml)")
    args = parser.parse_args()

    rz_ids = [r.strip() for r in args.rz_ids.split(",") if r.strip()]
    if not rz_ids:
        print("Помилка: порожній список rz_id")
        sys.exit(1)

    filename_part = "_".join(rz_ids)
    output_file   = args.output or f"/tmp/katran_cat_{filename_part}.xml"

    stats = generate_category_xml(rz_ids, output_file)

    print(f"\n{'='*62}")
    print(f"  Категорії rz_id: {', '.join(rz_ids)}")
    print(f"{'='*62}")
    print(f"  Офферів    : {stats['total']}")
    print(f"  Категорій  : {stats['categories']}")
    print(f"  Збережено  : {stats['output']}")
    if stats["skipped_price"]:
        print(f"  Пропущено (ціна=0)  : {stats['skipped_price']}")
    if stats["skipped_sale"]:
        print(f"  Пропущено (уцінки)  : {stats['skipped_sale']}")
    if stats["skipped_accessory"]:
        print(f"  Пропущено (аксесуари без бренду): {stats['skipped_accessory']}")
    if stats["skipped_brand"]:
        print(f"  Пропущено (стоп-бренди)         : {stats['skipped_brand']}")
    if stats["skipped_nophoto"]:
        print(f"  Пропущено (без фото)            : {stats['skipped_nophoto']}")

    print(f"\n  Бренди ({len(stats['brands'])}):")
    for b in stats["brands"]:
        print(f"    - {b}")

    # ── show first 3 offers ───────────────────────────────────────────────
    print(f"\n  Перші 3 оффери:")
    try:
        tree      = ET.parse(output_file)
        offers_el = tree.getroot().find("shop").find("offers")
        for i, offer in enumerate(offers_el.findall("offer")[:3], 1):
            oid    = offer.get("id", "?")
            name   = (offer.findtext("name_ua") or "")[:65]
            cat    = offer.findtext("categoryId") or "?"
            price  = offer.findtext("price") or "?"
            vendor = offer.findtext("vendor") or "?"
            pics   = len(offer.findall("picture"))
            desc_raw = offer.findtext("description_ua") or ""
            desc   = desc_raw[:60].replace("\n", " ") if desc_raw else "(без опису)"
            print(f"\n  [{i}] id       = {oid}")
            print(f"       name_ua  = {name}")
            print(f"       category = {cat}  price = {price} UAH  vendor = {vendor}")
            print(f"       photos   = {pics}  desc  = {desc}...")
    except Exception as e:
        print(f"  (помилка при читанні XML: {e})")

    # ── run validator ─────────────────────────────────────────────────────
    print(f"\n{'─'*62}")
    print("  Запускаю валідатор...")
    print(f"{'─'*62}\n")
    sys.stdout.flush()  # flush before subprocess to preserve output order
    script_dir = os.path.dirname(os.path.abspath(__file__))
    validator  = os.path.join(script_dir, "rozetka_xml_validator.py")
    result = subprocess.run(
        [sys.executable, validator, "--no-xlsx", output_file],
    )
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()

````

### `tools/katran_pipeline.py` — 275 рядків

````python
#!/usr/bin/env python3
"""
tools/katran_pipeline.py — Автоматичний pipeline генерації XML фіду Катрана.

Usage:
  python3 tools/katran_pipeline.py --categories ALL
  python3 tools/katran_pipeline.py --categories 80158,237815,80011
  python3 tools/katran_pipeline.py --categories ALL --push
  python3 tools/katran_pipeline.py --categories ALL --output-dir /tmp/katran_pipeline/
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from xml.etree import ElementTree as ET

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
from loguru import logger

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../.env"))

# import shared logic from katran_category_xml
from tools.katran_category_xml import (
    SKIP_CATEGORIES,
    generate_category_xml,
    get_category_map,
    get_katran_feed,
)

REPO_ROOT   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VALIDATOR   = os.path.join(REPO_ROOT, "tools", "rozetka_xml_validator.py")
OUTPUT_XML  = os.path.join(REPO_ROOT, "data", "katran_rozetka.xml")


# ─── validation helpers ───────────────────────────────────────────────────────

def run_validator(xml_path: str) -> dict:
    result = subprocess.run(
        [sys.executable, VALIDATOR, "--no-xlsx", xml_path],
        capture_output=True, text=True
    )
    errors   = result.stdout.count("ERR=") and _extract_count(result.stdout, "ERR")
    warnings = _extract_count(result.stdout, "WARN")
    ok = result.returncode == 0
    return {"ok": ok, "errors": errors, "warnings": warnings, "output": result.stdout}


def _extract_count(text: str, label: str) -> int:
    import re
    m = re.search(rf"Помилок:\s+(\d+)", text)
    if label == "ERR" and m:
        return int(m.group(1))
    m2 = re.search(rf"Попереджень:\s+(\d+)", text)
    if label == "WARN" and m2:
        return int(m2.group(1))
    return 0


# ─── merge ────────────────────────────────────────────────────────────────────

def merge_xmls(xml_files: list, output_path: str) -> int:
    cats: dict   = {}
    offers: list = []
    seen: set    = set()

    for f in sorted(xml_files):
        tree = ET.parse(f)
        for cat in tree.findall(".//category"):
            cid = cat.get("id")
            if cid not in cats:
                cats[cid] = ET.tostring(cat, encoding="unicode")
        for offer in tree.findall(".//offer"):
            oid = offer.get("id")
            if oid not in seen:
                seen.add(oid)
                offers.append(ET.tostring(offer, encoding="unicode"))

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<yml_catalog date="{now}">',
        "  <shop>",
        "    <name>HYPER_STORE</name>",
        "    <company>3721108</company>",
        "    <url>https://seller.rozetka.com.ua/</url>",
        "    <currencies><currency id=\"UAH\" rate=\"1\"/></currencies>",
        "    <categories>",
    ] + ["      " + c for c in cats.values()] + [
        "    </categories>",
        "    <offers>",
    ] + ["      " + o for o in offers] + [
        "    </offers>",
        "  </shop>",
        "</yml_catalog>",
    ]

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return len(offers)


# ─── git push ─────────────────────────────────────────────────────────────────

def git_push(message: str) -> bool:
    for cmd in [
        ["git", "-C", REPO_ROOT, "add", "-f", OUTPUT_XML],
        ["git", "-C", REPO_ROOT, "commit", "-m", message],
        ["git", "-C", REPO_ROOT, "pull", "--rebase"],
        ["git", "-C", REPO_ROOT, "push"],
    ]:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0 and "nothing to commit" not in result.stdout:
            logger.error(f"git error: {result.stderr.strip()}")
            return False
    return True


# ─── main pipeline ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Автоматичний pipeline генерації XML фіду Катрана для Розетки"
    )
    parser.add_argument(
        "--categories", default="ALL",
        help="rz_ids через кому або ALL (default: ALL)"
    )
    parser.add_argument(
        "--output-dir", default="/tmp/katran_pipeline/",
        help="Директорія для окремих XML файлів категорій"
    )
    parser.add_argument(
        "--feed-url", default=None,
        help="URL фіду (default: KATRAN_FEED_URL_STOCK з .env)"
    )
    parser.add_argument(
        "--push", action="store_true",
        help="Запушити data/katran_rozetka.xml на GitHub після генерації"
    )
    args = parser.parse_args()

    if args.feed_url:
        os.environ["KATRAN_FEED_URL_STOCK"] = args.feed_url

    os.makedirs(args.output_dir, exist_ok=True)

    # ── step 1: отримати список категорій ────────────────────────────────────
    logger.info("[Pipeline] Крок 1: Отримую список категорій...")
    if args.categories.upper() == "ALL":
        cat_map = get_category_map()
        all_rz_ids = list({v["rz_id"] for v in cat_map.values()} - SKIP_CATEGORIES)
        if not all_rz_ids:
            logger.error("Жодної категорії не знайдено в БД")
            sys.exit(1)
        logger.info(f"[Pipeline] Категорій з БД: {len(all_rz_ids)}")
    else:
        all_rz_ids = [r.strip() for r in args.categories.split(",") if r.strip()]
        logger.info(f"[Pipeline] Категорії з аргументу: {all_rz_ids}")

    # ── step 2: завантажити фід один раз ─────────────────────────────────────
    logger.info("[Pipeline] Крок 2: Завантажую фід Катрана...")
    feed_root = get_katran_feed()
    logger.success(f"[Pipeline] Фід завантажено")

    # ── step 3: генерувати XML для кожної категорії ───────────────────────────
    logger.info(f"[Pipeline] Крок 3: Генерую XML для {len(all_rz_ids)} категорій...")
    results  = []
    xml_files = []

    for rz_id in sorted(all_rz_ids):
        out_file = os.path.join(args.output_dir, f"katran_cat_{rz_id}.xml")
        try:
            stats = generate_category_xml([rz_id], out_file)
            # ── step 4: валідатор на кожному файлі ───────────────────────────
            val = run_validator(out_file)
            status = "ok" if val["ok"] and val["errors"] == 0 else (
                "warn" if val["errors"] == 0 else "error"
            )
            rec = {
                "rz_id":        rz_id,
                "name":         list(stats["cat_names"].values())[0] if stats["cat_names"] else "?",
                "offers_count": stats["total"],
                "errors":       val["errors"],
                "warnings":     val["warnings"],
                "status":       status,
                "skipped_sale": stats.get("skipped_sale", 0),
                "skipped_acc":  stats.get("skipped_accessory", 0),
            }
            results.append(rec)
            if stats["total"] > 0:
                xml_files.append(out_file)
            logger.info(
                f"[Pipeline] {rz_id:12} | {stats['total']:4d} офферів | "
                f"ERR={val['errors']} WARN={val['warnings']} | {status}"
            )
        except Exception as e:
            logger.error(f"[Pipeline] {rz_id} — помилка: {e}")
            results.append({
                "rz_id": rz_id, "name": "?", "offers_count": 0,
                "errors": 1, "warnings": 0, "status": "error",
                "skipped_sale": 0, "skipped_acc": 0,
            })

    # ── step 5: зберегти JSON звіт ────────────────────────────────────────────
    report_path = os.path.join(args.output_dir, "pipeline_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    logger.info(f"[Pipeline] JSON звіт: {report_path}")

    # ── step 6: зведена таблиця ───────────────────────────────────────────────
    total_offers = sum(r["offers_count"] for r in results)
    total_errors = sum(r["errors"] for r in results)
    total_warns  = sum(r["warnings"] for r in results)
    ok_cats      = sum(1 for r in results if r["status"] == "ok")
    warn_cats    = sum(1 for r in results if r["status"] == "warn")
    err_cats     = sum(1 for r in results if r["status"] == "error")

    print(f"\n{'='*72}")
    print(f"  KATRAN PIPELINE — Зведена таблиця  ({datetime.now().strftime('%Y-%m-%d %H:%M')})")
    print(f"{'='*72}")
    print(f"  {'rz_id':<12} {'Категорія':<30} {'Офф':>5} {'ERR':>4} {'WARN':>5}  Статус")
    print(f"  {'-'*12} {'-'*30} {'-'*5} {'-'*4} {'-'*5}  {'------'}")
    for r in sorted(results, key=lambda x: -x["offers_count"]):
        status_icon = "✅" if r["status"] == "ok" else ("⚠️ " if r["status"] == "warn" else "❌")
        print(
            f"  {r['rz_id']:<12} {r['name'][:30]:<30} {r['offers_count']:>5} "
            f"{r['errors']:>4} {r['warnings']:>5}  {status_icon}"
        )
    print(f"{'─'*72}")
    print(f"  РАЗОМ: {len(results)} категорій | {total_offers} офферів | "
          f"ERR={total_errors} WARN={total_warns}")
    print(f"  ✅ OK: {ok_cats}  ⚠️  WARN: {warn_cats}  ❌ ERR: {err_cats}")

    # ── step 7: merge ─────────────────────────────────────────────────────────
    if not xml_files:
        logger.error("[Pipeline] Немає файлів для merge")
        sys.exit(1)

    logger.info(f"\n[Pipeline] Крок 7: Merge {len(xml_files)} файлів → {OUTPUT_XML}...")
    merged_count = merge_xmls(xml_files, OUTPUT_XML)
    print(f"\n  Merged XML: {OUTPUT_XML}")
    print(f"  Категорій: {len(xml_files)} | Офферів: {merged_count}")

    # ── step 8: валідатор на merged ───────────────────────────────────────────
    print(f"\n{'─'*72}")
    print("  Крок 8: Валідатор на merged XML...")
    print(f"{'─'*72}\n")
    sys.stdout.flush()
    val_final = subprocess.run(
        [sys.executable, VALIDATOR, "--no-xlsx", OUTPUT_XML]
    )

    # ── step 9: git push ──────────────────────────────────────────────────────
    if args.push:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        msg = f"sync: katran pipeline {now_str} ({merged_count} offers, {len(xml_files)} cats)"
        print(f"\n[Pipeline] Крок 9: git push...")
        if git_push(msg):
            print("  PUSH_OK ✅")
        else:
            print("  PUSH_FAILED ❌")
            sys.exit(1)

    sys.exit(val_final.returncode)


if __name__ == "__main__":
    main()

````

### `tools/prom_feed_converter/scripts/analyze_feed.py` — 564 рядків

````python
"""
analyze_feed.py
---------------
Аналіз вхідного файлу від постачальника: XLS/XLSX/CSV/XML/YML.
Підтримує URL — завантажує автоматично.

Запуск:
  python3 analyze_feed.py файл.xlsx
  python3 analyze_feed.py файл.xml
  python3 analyze_feed.py https://example.com/feed.xml
"""
import sys
import os
import re
import tempfile
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from datetime import datetime

import chardet
import pandas as pd


# ── Шляхи ────────────────────────────────────────────────────────────────────
SCRIPT_DIR  = Path(__file__).resolve().parent
OUTPUT_DIR  = SCRIPT_DIR.parent / 'output'
REPORT_PATH = OUTPUT_DIR / 'analysis_report.txt'

# ── Словники для авто-маппінгу ────────────────────────────────────────────────
MAPPING_KEYWORDS = {
    'name':         ['назва', 'наименование', 'найменування', 'название', 'name', 'title',
                     'товар', 'product', 'номенклатура'],
    'article':      ['артикул', 'article', 'sku', 'код товара', 'код товару', 'part number',
                     'partnumber', 'part_number', 'oem', 'номер', 'vendorcode'],
    'price':        ['ціна', 'цена', 'price', 'вартість', 'стоимость', 'прайс'],
    'availability': ['наявність', 'наличие', 'available', 'склад', 'залишок', 'остаток',
                     'кількість', 'количество', 'qty', 'stock', 'в наличии'],
    'category':     ['категорія', 'категория', 'category', 'categoryid', 'category_name',
                     'розділ', 'раздел', 'группа', 'група', 'тип', 'type'],
    'photo':        ['фото', 'photo', 'image', 'зображення', 'картинка', 'picture', 'img',
                     'url', 'посилання', 'ссылка', 'link'],
    'description':  ['опис', 'описание', 'description', 'характеристика', 'характеристики',
                     'детальний', 'подробное'],
    'car_brand':    ['марка', 'бренд', 'brand', 'виробник', 'производитель', 'make',
                     'автомобіль', 'автомобиль', 'vendor', 'param__марка',
                     'param__марка авто', 'param__виробник'],
    'car_model':    ['модель', 'model', 'модифікація', 'модификация',
                     'param__модель', 'param__модель авто'],
    'year':         ['рік', 'год', 'year', 'роки', 'годы', 'від', 'до', 'від-до',
                     'param__рік', 'param__год', 'param__роки випуску'],
}

MAPPING_LABELS = {
    'name':         'Назва товару',
    'article':      'Артикул / SKU',
    'price':        'Ціна',
    'availability': 'Наявність / Кількість',
    'category':     'Категорія',
    'photo':        'Фото / URL',
    'description':  'Опис',
    'car_brand':    'Марка авто',
    'car_model':    'Модель авто',
    'year':         'Рік',
}

# Теги які відображаємо у прикладі рядків (решта param__ можуть бути сотні)
XML_CORE_COLS = ('id', 'available', 'name', 'price', 'oldprice', 'currencyId',
                 'categoryId', 'category_name', 'vendor', 'vendorCode',
                 'article', 'barcode', 'picture', 'description')


# ── Завантаження URL ──────────────────────────────────────────────────────────

def download_url(url: str) -> tuple[str, str]:
    """
    Завантажує URL у тимчасовий файл.
    Повертає (local_path, detected_ext).
    """
    print(f'Завантажуємо: {url}')
    parsed   = urllib.parse.urlparse(url)
    url_path = parsed.path.lower()

    ext = '.xml'
    for candidate in ('.xml', '.yml', '.xlsx', '.xls', '.csv'):
        if url_path.endswith(candidate):
            ext = candidate
            break

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext, dir='/tmp')
    tmp.close()

    try:
        req = urllib.request.Request(
            url, headers={'User-Agent': 'Mozilla/5.0 FeedAnalyzer/1.0'}
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            ct = resp.headers.get('Content-Type', '')
            if ext == '.xml' and 'yml' in ct:
                ext = '.yml'
            data = resp.read()

        with open(tmp.name, 'wb') as f:
            f.write(data)

        size_kb = len(data) / 1024
        print(f'Завантажено {size_kb:.1f} KB → {tmp.name}')
        return tmp.name, ext
    except Exception as e:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        sys.exit(f'Помилка завантаження {url}: {e}')


# ── Зчитування XLS/XLSX/CSV ───────────────────────────────────────────────────

def detect_csv_encoding(path: str) -> str:
    with open(path, 'rb') as f:
        raw = f.read(65536)
    result = chardet.detect(raw)
    return result.get('encoding') or 'utf-8'


def read_tabular(path: str) -> pd.DataFrame:
    ext = Path(path).suffix.lower()

    if ext == '.csv':
        enc = detect_csv_encoding(path)
        for sep in [';', ',', '\t', '|']:
            try:
                df = pd.read_csv(path, sep=sep, encoding=enc, dtype=str,
                                 keep_default_na=False, low_memory=False)
                if df.shape[1] > 1:
                    return df
            except Exception:
                continue
        return pd.read_csv(path, encoding=enc, dtype=str, keep_default_na=False)

    if ext == '.xlsx':
        return pd.read_excel(path, engine='openpyxl', dtype=str, keep_default_na=False)

    if ext == '.xls':
        try:
            import xlrd  # noqa: F401
            return pd.read_excel(path, engine='xlrd', dtype=str, keep_default_na=False)
        except ImportError:
            sys.exit(
                'Для читання .xls потрібен xlrd:\n'
                '  pip install xlrd\n'
                'Або конвертуйте файл у .xlsx і запустіть знову.'
            )

    sys.exit(f'Непідтримуваний формат: {ext}')


# ── Зчитування XML/YML ────────────────────────────────────────────────────────

def detect_xml_encoding(raw: bytes) -> str:
    m = re.match(rb'<\?xml[^?]*encoding=["\']([^"\']+)["\']', raw[:500])
    if m:
        return m.group(1).decode('ascii', errors='ignore')
    result = chardet.detect(raw[:65536])
    return result.get('encoding') or 'utf-8'


def _find_offers_root(root: ET.Element) -> ET.Element | None:
    """Шукає <offers> в різних варіантах структури фіду."""
    for path in ('shop/offers', 'offers', './/offers'):
        el = root.find(path)
        if el is not None:
            return el
    return None


def parse_xml_feed(path: str) -> tuple[pd.DataFrame, dict]:
    """
    Парсить YML/XML фід (Prom/Rozetka/Epicentr/Yandex Market).
    Повертає (DataFrame, xml_meta).
    """
    with open(path, 'rb') as f:
        raw = f.read()

    enc = detect_xml_encoding(raw)
    try:
        text = raw.decode(enc, errors='replace')
    except (LookupError, UnicodeDecodeError):
        text = raw.decode('utf-8', errors='replace')

    # ElementTree вимагає bytes з коректним encoding у декларації
    xml_bytes = text.encode('utf-8')
    # Замінюємо оголошення кодування на utf-8 щоб не конфліктувало
    xml_bytes = re.sub(
        rb'(<\?xml[^?]*encoding=)["\'][^"\']+["\']',
        rb'\1"utf-8"',
        xml_bytes[:500]
    ) + xml_bytes[500:]

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        sys.exit(f'Помилка парсингу XML: {e}')

    shop_el = root.find('shop')
    shop    = shop_el if shop_el is not None else root

    # ── Категорії з <categories> ──
    categories: dict[str, str] = {}
    cats_el = shop.find('categories')
    if cats_el is None:
        cats_el = root.find('.//categories')
    if cats_el is not None:
        for cat in cats_el.findall('category'):
            cid  = cat.get('id', '')
            name = (cat.text or '').strip()
            if cid:
                categories[cid] = name

    # ── Offers ──
    offers_el = _find_offers_root(root)
    if offers_el is None:
        sys.exit('Не знайдено тег <offers> у XML файлі.')

    offers = offers_el.findall('offer')
    if not offers:
        sys.exit('<offers> порожній — жодного <offer> не знайдено.')

    rows: list[dict] = []
    param_counter: Counter = Counter()
    n_with_pictures    = 0
    n_with_description = 0

    for offer in offers:
        row: dict[str, str] = {
            'id':        offer.get('id', ''),
            'available': offer.get('available', ''),
        }

        for tag in ('name', 'price', 'oldprice', 'currencyId', 'categoryId',
                    'vendor', 'vendorCode', 'description', 'barcode', 'article'):
            el = offer.find(tag)
            row[tag] = (el.text or '').strip() if el is not None else ''

        pictures = [p.text.strip() for p in offer.findall('picture') if p.text and p.text.strip()]
        row['picture'] = ' | '.join(pictures)
        if pictures:
            n_with_pictures += 1

        if row.get('description'):
            n_with_description += 1

        for param in offer.findall('param'):
            pname = (param.get('name') or '').strip()
            if not pname:
                continue
            param_counter[pname] += 1
            col = f'param__{pname}'
            val = (param.text or '').strip()
            if col in row and row[col]:
                row[col] += f', {val}'
            else:
                row[col] = val

        rows.append(row)

    df = pd.DataFrame(rows).fillna('')

    if categories and 'categoryId' in df.columns:
        df['category_name'] = df['categoryId'].map(categories).fillna('')

    xml_meta = {
        'categories':         categories,
        'n_offers':           len(offers),
        'n_with_pictures':    n_with_pictures,
        'n_with_description': n_with_description,
        'param_counts':       param_counter,
        'encoding':           enc,
    }
    return df, xml_meta


# ── Спільний аналіз ───────────────────────────────────────────────────────────

def fill_stats(df: pd.DataFrame) -> list[tuple[str, float, int]]:
    total = len(df)
    result = []
    for col in df.columns:
        filled = int(df[col].apply(lambda x: bool(str(x).strip())).sum())
        pct    = (filled / total * 100) if total else 0.0
        result.append((col, pct, filled))
    return result


def find_category_column(df: pd.DataFrame, mapping: dict) -> str | None:
    cats = mapping.get('category')
    if cats:
        return cats[0]
    best, best_score = None, 0
    for col in df.columns:
        n_uniq = df[col].nunique()
        if 2 <= n_uniq <= max(50, len(df) * 0.3):
            if n_uniq > best_score:
                best, best_score = col, n_uniq
    return best


def auto_map(df: pd.DataFrame) -> dict[str, list[str]]:
    cols_lower = {col: col.lower().strip() for col in df.columns}
    result: dict[str, list[str]] = {k: [] for k in MAPPING_KEYWORDS}
    for col, col_l in cols_lower.items():
        for field, keywords in MAPPING_KEYWORDS.items():
            for kw in keywords:
                if kw in col_l:
                    if col not in result[field]:
                        result[field].append(col)
                    break
    return result


def category_summary(df: pd.DataFrame, cat_col: str) -> list[tuple[str, int]]:
    counts = df[cat_col].value_counts()
    return [(str(c), int(n)) for c, n in counts.items()]


# ── Форматування звіту ────────────────────────────────────────────────────────

def bar(pct: float, width: int = 20) -> str:
    filled = round(pct / 100 * width)
    return '█' * filled + '░' * (width - filled)


def build_report(
    source:    str,
    local_path: str | None,
    df:         pd.DataFrame,
    xml_meta:   dict | None = None,
) -> str:
    lines: list[str] = []
    W = 72

    def hr(ch='─'):
        lines.append(ch * W)

    def h1(title: str):
        hr('═'); lines.append(f'  {title}'); hr('═')

    def h2(title: str):
        lines.append(''); hr(); lines.append(f'  {title}'); hr()

    is_xml  = xml_meta is not None
    is_url  = source.startswith('http')
    fmt_lbl = 'XML/YML' if is_xml else Path(source).suffix.upper().lstrip('.')

    # ── Заголовок ──
    h1('АНАЛІЗ ФАЙЛУ ПОСТАЧАЛЬНИКА')
    if is_url:
        lines.append(f'  URL     : {source}')
        lines.append(f'  Кеш     : {local_path}')
    else:
        lines.append(f'  Файл    : {source}')
    if local_path and os.path.exists(local_path):
        lines.append(f'  Розмір  : {os.path.getsize(local_path) / 1024:.1f} KB')
    lines.append(f'  Формат  : {fmt_lbl}')
    if is_xml:
        lines.append(f'  Кодування: {xml_meta["encoding"]}')
    lines.append(f'  Дата    : {datetime.now().strftime("%Y-%m-%d %H:%M")}')

    # ── 1. Загальна статистика ──
    h2('1. ЗАГАЛЬНА СТАТИСТИКА')
    lines.append(f'  Рядків (товарів)       : {len(df):,}')
    if is_xml:
        lines.append(f'  Offers у XML           : {xml_meta["n_offers"]:,}')
        lines.append(f'  З картинками           : {xml_meta["n_with_pictures"]:,}  '
                     f'({xml_meta["n_with_pictures"]/max(xml_meta["n_offers"],1)*100:.1f}%)')
        lines.append(f'  З описом               : {xml_meta["n_with_description"]:,}  '
                     f'({xml_meta["n_with_description"]/max(xml_meta["n_offers"],1)*100:.1f}%)')
        n_params = len(xml_meta['param_counts'])
        lines.append(f'  Унікальних param       : {n_params}')
    lines.append(f'  Колонок у DataFrame    : {len(df.columns)}')

    # ── 2. Список колонок ──
    h2('2. КОЛОНКИ ФАЙЛУ')
    core_cols  = [c for c in df.columns if not c.startswith('param__')]
    param_cols = [c for c in df.columns if c.startswith('param__')]
    for i, col in enumerate(core_cols, 1):
        lines.append(f'  {i:>3}. {col}')
    if param_cols:
        lines.append(f'  --- param-характеристики ({len(param_cols)} шт.) ---')
        for i, col in enumerate(param_cols, len(core_cols) + 1):
            lines.append(f'  {i:>3}. {col}')

    # ── 3. Заповненість колонок ──
    h2('3. ЗАПОВНЕНІСТЬ КОЛОНОК  (% непорожніх)')
    stats = fill_stats(df)
    # Окремо core і param, param — тільки заповнені
    core_stats  = [(c, p, n) for c, p, n in stats if not c.startswith('param__')]
    param_stats = [(c, p, n) for c, p, n in stats if c.startswith('param__') and p > 0]
    for col, pct, n in core_stats:
        b = bar(pct)
        lines.append(f'  {col:<30} {b} {pct:5.1f}%  ({n:,}/{len(df):,})')
    if param_stats:
        lines.append('')
        lines.append('  param-характеристики:')
        for col, pct, n in sorted(param_stats, key=lambda x: -x[1]):
            short = col[7:]  # без 'param__'
            b = bar(pct)
            lines.append(f'    {short:<28} {b} {pct:5.1f}%  ({n:,}/{len(df):,})')

    # ── 4. Авто-маппінг ──
    mapping = auto_map(df)
    h2('4. ВИЯВЛЕНІ КОЛОНКИ ДЛЯ МАППІНГУ')
    found_any = False
    for field, cols in mapping.items():
        label = MAPPING_LABELS[field]
        if cols:
            found_any = True
            lines.append(f'  {label:<25} → {", ".join(cols)}')
        else:
            lines.append(f'  {label:<25}   ⚠ не знайдено')
    if not found_any:
        lines.append('  ⚠  Жодного поля не вдалось визначити автоматично.')

    # ── 5. Категорії з DataFrame ──
    cat_col = find_category_column(df, mapping)
    # Для XML краще показувати category_name якщо є
    if is_xml and 'category_name' in df.columns:
        cat_col = 'category_name'

    h2('5. УНІКАЛЬНІ КАТЕГОРІЇ')
    if is_xml and xml_meta['categories']:
        cat_map = xml_meta['categories']
        # Рахуємо offers по categoryId
        if 'categoryId' in df.columns:
            counts_by_id = df['categoryId'].value_counts()
            lines.append(f'  {"ID":<6} {"Назва категорії":<42} {"К-сть":>6}')
            hr()
            for cid, cnt in counts_by_id.items():
                cname = cat_map.get(str(cid), f'(id={cid})')
                cname_t = (cname[:39] + '...') if len(cname) > 42 else cname
                lines.append(f'  {str(cid):<6} {cname_t:<42} {cnt:>6}')
            lines.append('')
            lines.append(f'  Всього унікальних категорій: {len(counts_by_id)}  '
                         f'(у довіднику: {len(cat_map)})')
    elif cat_col:
        lines.append(f'  Колонка: «{cat_col}»')
        lines.append('')
        cats = category_summary(df, cat_col)
        lines.append(f'  {"Категорія":<45} {"К-сть":>6}')
        hr()
        for cat, cnt in cats:
            t = (cat[:42] + '...') if len(cat) > 45 else cat
            lines.append(f'  {t:<45} {cnt:>6}')
        lines.append('')
        lines.append(f'  Всього унікальних категорій: {len(cats)}')
    else:
        lines.append('  ⚠  Колонку категорій не знайдено.')

    # ── 6. Топ param-характеристики (тільки для XML) ──
    if is_xml and xml_meta['param_counts']:
        h2('6. НАЙЧАСТІШІ PARAM-ХАРАКТЕРИСТИКИ')
        top_params = xml_meta['param_counts'].most_common(30)
        total_off  = xml_meta['n_offers']
        lines.append(f'  {"Param name":<35} {"Offers":>7}  {"% покриття":>10}')
        hr()
        for pname, cnt in top_params:
            pct = cnt / total_off * 100
            lines.append(f'  {pname:<35} {cnt:>7}  {pct:>9.1f}%')
        next_section = '7'
    else:
        next_section = '6'

    # ── Приклад рядків ──
    h2(f'{next_section}. ПЕРШІ 3 РЯДКИ (приклад)')
    sample_cols = XML_CORE_COLS if is_xml else df.columns
    sample = df.head(3)
    for i, (_, row) in enumerate(sample.iterrows(), 1):
        lines.append(f'  ─── Рядок {i} ───')
        for col in sample_cols:
            if col not in df.columns:
                continue
            val = str(row[col]).strip()
            if not val:
                continue
            truncated = (val[:55] + '...') if len(val) > 58 else val
            lines.append(f'    {col:<30} : {truncated}')
        # Кілька перших param якщо є
        if is_xml:
            shown = 0
            for col in df.columns:
                if col.startswith('param__') and str(row.get(col, '')).strip():
                    val = str(row[col]).strip()
                    truncated = (val[:55] + '...') if len(val) > 58 else val
                    lines.append(f'    {col:<30} : {truncated}')
                    shown += 1
                    if shown >= 8:
                        remaining = sum(
                            1 for c in df.columns
                            if c.startswith('param__') and str(row.get(c, '')).strip()
                        ) - shown
                        if remaining > 0:
                            lines.append(f'    ... ще {remaining} param ...')
                        break
        lines.append('')

    hr('═')
    lines.append(f'  Звіт збережено: {REPORT_PATH}')
    hr('═')

    return '\n'.join(lines)


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print('Використання: python3 analyze_feed.py <файл або URL>')
        print('  Підтримувані формати: xlsx, xls, csv, xml, yml')
        sys.exit(1)

    source    = sys.argv[1]
    local_path: str | None = None
    is_url    = source.lower().startswith('http')
    xml_meta: dict | None = None
    tmp_to_delete: str | None = None

    try:
        if is_url:
            local_path, ext = download_url(source)
            tmp_to_delete   = local_path
        else:
            local_path = source
            ext        = Path(source).suffix.lower()
            if not os.path.exists(local_path):
                sys.exit(f'Файл не знайдено: {local_path}')

        print(f'Читаємо: {local_path}  (формат: {ext})')

        if ext in ('.xml', '.yml'):
            df, xml_meta = parse_xml_feed(local_path)
        else:
            df = read_tabular(local_path)
            df = df.dropna(how='all')
            df.columns = [str(c).strip() for c in df.columns]

        print(f'Завантажено {len(df):,} рядків, {len(df.columns)} колонок')
        print('Аналізуємо...')

        report = build_report(source, local_path, df, xml_meta)

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(report, encoding='utf-8')

        print(report)

    finally:
        if tmp_to_delete and os.path.exists(tmp_to_delete):
            os.unlink(tmp_to_delete)


if __name__ == '__main__':
    main()

````

### `tools/prom_feed_converter/scripts/category_mapper.py` — 70 рядків

````python
"""
Category Mapper — знаходить відповідну категорію Prom по назві
"""
import sys
from difflib import SequenceMatcher
sys.path.insert(0, '/home/tekken/agent-system')
from shared.utils.db import get_connection


def get_all_categories():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('SELECT category_id, name, full_path, level FROM prom_categories ORDER BY level DESC')
    result = cur.fetchall()
    cur.close(); conn.close()
    return result


def find_category(search_name: str, top_n: int = 5) -> list:
    """Знаходить найближчі категорії по назві."""
    categories = get_all_categories()
    search_lower = search_name.lower().strip()
    
    scores = []
    for cat in categories:
        cat_name = (cat['name'] or '').lower()
        full_path = (cat['full_path'] or '').lower()
        
        # Точний збіг
        if search_lower == cat_name:
            score = 1.0
        # Пошук в назві
        elif search_lower in cat_name or cat_name in search_lower:
            score = 0.9
        # Пошук в повному шляху
        elif search_lower in full_path:
            score = 0.7
        # Fuzzy match
        else:
            score = SequenceMatcher(None, search_lower, cat_name).ratio()
        
        if score > 0.3:
            scores.append({
                'category_id': cat['category_id'],
                'name': cat['name'],
                'full_path': cat['full_path'],
                'level': cat['level'],
                'score': round(score, 3)
            })
    
    scores.sort(key=lambda x: (-x['score'], -x['level']))
    return scores[:top_n]


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Використання: python3 category_mapper.py "назва категорії"')
        sys.exit(1)
    
    query = ' '.join(sys.argv[1:])
    print(f'\nПошук категорії: "{query}"\n')
    results = find_category(query)
    
    if not results:
        print('Нічого не знайдено')
    else:
        print(f'{"ID":<12} {"Score":<8} {"Рівень":<8} {"Назва"}')
        print('-' * 80)
        for r in results:
            print(f'{r["category_id"]:<12} {r["score"]:<8} {r["level"]:<8} {r["full_path"]}')

````

### `tools/prom_feed_converter/scripts/validator.py` — 241 рядків

````python
"""
Prom.ua Feed Validator
Перевіряє файл товарів на відповідність вимогам Prom.ua
"""
import sys, os, re
import openpyxl
sys.path.insert(0, '/home/tekken/agent-system')
from shared.utils.db import get_connection
import logging; logger = logging.getLogger(__name__); logging.basicConfig(level=logging.INFO, format="%(message)s")

# Дозволені одиниці виміру
VALID_UNITS = {
    'шт.', 'т', 'кг', 'г', 'куб.м', 'л', 'кв.м', 'кв.см', 'кв.фут',
    'кв.дм', 'м', 'км', 'дав', 'мішок', 'пара', 'чол.', 'упаковка',
    'сотка', 'пог. м', 'ящик', 'мм', 'мл', 'гр/кв.м', 'кг/кв.м',
    '100 г', 'комплект', 'набір', 'моток', 'рулон', 'послуга', 'см',
    'секція', 'бухта', 'об\'єкт', 'сторінка', 'т/км', 'добу', 'ват',
    'лист', 'карат', 'хвилина', 'кВт', 'мВт', 'бобіна', 'палетомісць',
    'зміна', 'од.', 'година', 'день', 'тиждень', 'місяць'
}

VALID_CURRENCIES = {'UAH', 'USD', 'EUR', 'CHF', 'GBP', 'JPY', 'PLZ', 'BYN', 'KZT', 'MDL'}

VALID_AVAILABILITY = {'+', '-', '!'}

FORBIDDEN_WORDS = [
    'акція', 'безкоштовна доставка', 'знижка', 'найкраща ціна',
    'купити', 'замовити', 'prom.ua', 'уапром'
]

VALID_PRODUCT_TYPES = {'r', 'w', 'u', 's'}


def get_prom_categories():
    """Завантажити всі category_id з БД."""
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute('SELECT category_id, full_path FROM prom_categories')
        result = {row['category_id']: row['full_path'] for row in cur.fetchall()}
        cur.close(); conn.close()
        return result
    except Exception as e:
        logger.error(f'DB error: {e}')
        return {}


def validate_product(row_num, row, categories):
    """Валідує один рядок товару. Повертає список помилок."""
    errors = []
    warnings = []

    def err(field, msg, critical=True):
        if critical:
            errors.append({'field': field, 'message': msg, 'type': 'CRITICAL'})
        else:
            warnings.append({'field': field, 'message': msg, 'type': 'WARNING'})

    # 1. ID товару
    product_id = row.get('Код_товара') or row.get('Ідентифікатор_товару')
    if not product_id:
        err('Код_товара', 'ID товару обов\'язковий')

    # 2. Назва
    name = str(row.get('Название_позиции') or row.get('Назва_позиції') or '').strip()
    if not name:
        err('Название_позиции', 'Назва товару обов\'язкова')
    elif len(name) > 130:
        err('Название_позиции', f'Назва задовга: {len(name)} символів (макс 130)', critical=False)
    elif re.match(r'^\d+$', name):
        err('Название_позиции', 'Назва не може складатися тільки з цифр')
    elif name == name.upper() and len(name) > 3:
        err('Название_позиции', 'Назва написана ВЕЛИКИМИ ЛІТЕРАМИ', critical=False)
    else:
        name_lower = name.lower()
        for word in FORBIDDEN_WORDS:
            if word in name_lower:
                err('Название_позиции', f'Заборонене слово в назві: "{word}"', critical=False)

    # 3. Опис
    desc = str(row.get('Описание') or row.get('Опис') or '').strip()
    if not desc:
        err('Описание', 'Опис товару обов\'язковий', critical=False)
    elif len(desc) < 30:
        err('Описание', f'Опис занадто короткий: {len(desc)} символів (мін 30)', critical=False)
    elif len(desc) > 12160:
        err('Описание', f'Опис задовгий: {len(desc)} символів (макс 12160)', critical=False)

    # 4. Ціна
    price = row.get('Цена') or row.get('Ціна')
    try:
        price_val = float(str(price).replace(',', '.')) if price else 0
        if price_val <= 0:
            err('Цена', 'Ціна повинна бути більше 0')
        elif price_val > 9999999999:
            err('Цена', 'Ціна перевищує максимум')
    except:
        err('Цена', f'Некоректне значення ціни: {price}')

    # 5. Наявність
    avail = str(row.get('Цена от') or row.get('Наявність') or '').strip()
    if avail and avail not in VALID_AVAILABILITY:
        try:
            int(avail)  # може бути кількість днів
        except:
            err('Наявність', f'Некоректне значення наявності: {avail}', critical=False)

    # 6. Одиниця виміру
    unit = str(row.get('Единица_измерения') or row.get('Одиниця_виміру') or '').strip()
    if unit and unit not in VALID_UNITS:
        err('Единица_измерения', f'Невідома одиниця виміру: "{unit}"', critical=False)

    # 7. Валюта
    currency = str(row.get('Валюта') or 'UAH').strip()
    if currency not in VALID_CURRENCIES:
        err('Валюта', f'Невідома валюта: "{currency}"')

    # 8. Категорія
    cat_id = row.get('Ідентифікатор_підрозділу') or row.get('portal_category_id')
    if cat_id:
        try:
            cat_id_int = int(float(str(cat_id)))
            if cat_id_int not in categories:
                err('Ідентифікатор_підрозділу', f'Категорія ID {cat_id_int} не знайдена в Prom')
        except:
            err('Ідентифікатор_підрозділу', f'Некоректний ID категорії: {cat_id}')
    else:
        err('Ідентифікатор_підрозділу', 'Категорія не вказана — буде призначена автоматично', critical=False)

    # 9. Фото
    images = str(row.get('Ссылка_изображения') or row.get('Посилання_зображення') or '').strip()
    if not images:
        err('Ссылка_изображения', 'Немає посилань на фото', critical=False)
    else:
        img_list = [x.strip() for x in images.split(',')]
        if len(img_list) > 10:
            err('Ссылка_изображения', f'Забагато фото: {len(img_list)} (макс 10)', critical=False)
        for img in img_list:
            if not img.startswith('http'):
                err('Ссылка_изображення', f'Невірне посилання на фото: {img}', critical=False)

    return errors, warnings


def validate_file(filepath):
    """Головна функція валідації файлу."""
    logger.info(f'Валідація файлу: {filepath}')
    
    wb = openpyxl.load_workbook(filepath, data_only=True)
    
    # Знаходимо лист з товарами
    product_sheet = None
    for name in wb.sheetnames:
        if 'product' in name.lower() or 'товар' in name.lower() or 'export' in name.lower():
            product_sheet = wb[name]
            break
    if not product_sheet:
        product_sheet = wb.active

    logger.info(f'Лист: {product_sheet.title}')

    # Читаємо заголовки
    headers = []
    for cell in product_sheet[1]:
        headers.append(str(cell.value or '').strip())
    logger.info(f'Колонки: {headers[:10]}...')

    # Завантажуємо категорії
    categories = get_prom_categories()
    logger.info(f'Категорій в БД: {len(categories)}')

    # Валідуємо кожен рядок
    total = 0
    critical_count = 0
    warning_count = 0
    all_errors = []

    for row_num, row in enumerate(product_sheet.iter_rows(min_row=2, values_only=True), start=2):
        if not any(row):
            continue
        
        row_dict = {headers[i]: row[i] for i in range(min(len(headers), len(row)))}
        errors, warnings = validate_product(row_num, row_dict, categories)
        
        total += 1
        critical_count += len(errors)
        warning_count += len(warnings)
        
        for e in errors + warnings:
            all_errors.append({
                'row': row_num,
                'product_id': row_dict.get('Код_товара') or row_dict.get('Ідентифікатор_товару', '?'),
                'name': str(row_dict.get('Название_позиции') or row_dict.get('Назва_позиції', ''))[:50],
                **e
            })

    # Звіт
    print(f'\n{"="*60}')
    print(f'ЗВІТ ВАЛІДАЦІЇ: {os.path.basename(filepath)}')
    print(f'{"="*60}')
    print(f'Всього товарів: {total}')
    print(f'Критичних помилок: {critical_count}')
    print(f'Попереджень: {warning_count}')
    print(f'{"="*60}\n')

    if all_errors:
        print('Перші 20 помилок:')
        for e in all_errors[:20]:
            icon = '❌' if e['type'] == 'CRITICAL' else '⚠️'
            print(f'{icon} Рядок {e["row"]} | {e["name"][:30]} | {e["field"]}: {e["message"]}')

    # Зберігаємо в БД
    save_to_db(os.path.basename(filepath), all_errors)
    
    return total, critical_count, warning_count


def save_to_db(filename, errors):
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute('DELETE FROM prom_feed_validator_log WHERE file_name = %s', (filename,))
        for e in errors:
            cur.execute('''
                INSERT INTO prom_feed_validator_log 
                (file_name, row_number, product_id, product_name, error_type, error_field, error_message)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            ''', (filename, e['row'], str(e['product_id']), e['name'],
                  e['type'], e['field'], e['message']))
        conn.commit()
        cur.close(); conn.close()
        logger.info(f'Збережено {len(errors)} записів в БД')
    except Exception as ex:
        logger.error(f'DB save error: {ex}')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Використання: python3 validator.py <шлях_до_файлу>')
        sys.exit(1)
    validate_file(sys.argv[1])

````

### `tools/prom_seo_optimizer.py` — 251 рядків

````python
#!/usr/bin/env python3
"""
prom_seo_optimizer.py — SEO-аудит товарів на Prom.ua.

Використання:
    python3 tools/prom_seo_optimizer.py
    python3 tools/prom_seo_optimizer.py --limit 500 --out my_report.csv
    python3 tools/prom_seo_optimizer.py --top 30
"""

import argparse
import csv
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

import httpx
from dotenv import load_dotenv
from loguru import logger

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../.env"))

# ── Константи ─────────────────────────────────────────────

PROM_BASE_URL = "https://my.prom.ua/api/v1"
PROM_TOKEN    = os.getenv("PROM_API_TOKEN", "")
PAGE_LIMIT    = 100          # максимум для Prom API

NAME_MIN  = 50
NAME_MAX  = 150
DESC_MIN  = 300
PHOTO_MIN = 3

PRIORITY_WEIGHTS = {"high": 3, "medium": 2, "low": 1}


# ── Структури ─────────────────────────────────────────────

@dataclass
class Problem:
    issue: str
    priority: str  # high | medium | low


@dataclass
class ProductReport:
    product_id: int
    name: str
    problems: list[Problem] = field(default_factory=list)

    @property
    def score(self) -> int:
        """Загальна вага проблем (чим більше — тим гірше)."""
        return sum(PRIORITY_WEIGHTS[p.priority] for p in self.problems)

    @property
    def worst_priority(self) -> str:
        if any(p.priority == "high" for p in self.problems):
            return "high"
        if any(p.priority == "medium" for p in self.problems):
            return "medium"
        return "low"


# ── Prom API ──────────────────────────────────────────────

def prom_client() -> httpx.Client:
    if not PROM_TOKEN:
        logger.error("PROM_API_TOKEN не встановлено в .env")
        sys.exit(1)
    return httpx.Client(
        base_url=PROM_BASE_URL,
        headers={"Authorization": f"Bearer {PROM_TOKEN}"},
        timeout=30,
    )


def fetch_all_products(client: httpx.Client, max_products: int | None = None) -> list[dict]:
    """Завантажує всі товари через пагінацію page_from_id."""
    all_products: list[dict] = []
    last_id = 0

    while True:
        params: dict = {"limit": PAGE_LIMIT}
        if last_id:
            params["page_from_id"] = last_id

        resp = client.get("/products/list", params=params)
        if resp.status_code != 200:
            logger.error(f"Prom API error {resp.status_code}: {resp.text[:200]}")
            break

        data = resp.json()
        products = data.get("products", [])
        if not products:
            break

        all_products.extend(products)
        logger.info(f"  Завантажено {len(all_products)} товарів...")

        if len(products) < PAGE_LIMIT:
            break  # остання сторінка

        last_id = products[-1]["id"]

        if max_products and len(all_products) >= max_products:
            all_products = all_products[:max_products]
            break

    return all_products


# ── SEO-перевірки ─────────────────────────────────────────

def audit_product(product: dict) -> ProductReport:
    """Перевіряє один товар і повертає список проблем."""
    pid   = product.get("id", 0)
    name  = (product.get("name") or "").strip()
    desc  = (product.get("description") or "").strip()
    photos: list = product.get("images", []) or []
    attrs: list  = product.get("attributes", []) or []

    report = ProductReport(product_id=pid, name=name[:80] or f"<id={pid}>")

    # ── Назва ──────────────────────────────────────────────
    if not name:
        report.problems.append(Problem("Назва відсутня", "high"))
    elif len(name) < NAME_MIN:
        report.problems.append(Problem(
            f"Назва коротка ({len(name)} симв., мін. {NAME_MIN})", "high"
        ))
    elif len(name) > NAME_MAX:
        report.problems.append(Problem(
            f"Назва задовга ({len(name)} симв., макс. {NAME_MAX})", "medium"
        ))

    # ── Опис ───────────────────────────────────────────────
    if not desc:
        report.problems.append(Problem("Опис відсутній", "high"))
    elif len(desc) < DESC_MIN:
        report.problems.append(Problem(
            f"Опис короткий ({len(desc)} симв., мін. {DESC_MIN})", "high"
        ))

    # ── Фото ───────────────────────────────────────────────
    n_photos = len(photos)
    if n_photos == 0:
        report.problems.append(Problem("Фото відсутні", "high"))
    elif n_photos < PHOTO_MIN:
        report.problems.append(Problem(
            f"Мало фото ({n_photos}, мін. {PHOTO_MIN})", "medium"
        ))

    # ── Характеристики ─────────────────────────────────────
    if not attrs:
        report.problems.append(Problem("Характеристики не заповнені", "medium"))
    else:
        empty = sum(1 for a in attrs if not (a.get("value") or "").strip())
        if empty:
            report.problems.append(Problem(
                f"{empty} характеристик без значення", "low"
            ))

    return report


# ── Звіт ──────────────────────────────────────────────────

def write_csv(reports: list[ProductReport], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "назва", "проблема", "пріоритет"])
        for r in reports:
            if not r.problems:
                writer.writerow([r.product_id, r.name, "—", "ok"])
            else:
                for p in r.problems:
                    writer.writerow([r.product_id, r.name, p.issue, p.priority])


def print_top(reports: list[ProductReport], top_n: int) -> None:
    with_problems = [r for r in reports if r.problems]
    ranked = sorted(with_problems, key=lambda r: r.score, reverse=True)[:top_n]

    print(f"\n{'='*65}")
    print(f"  ТОП-{top_n} товарів що найбільше потребують покращення")
    print(f"{'='*65}")
    print(f"{'ID':>8}  {'Балів':>6}  {'Пріор.':>7}  Проблеми / Назва")
    print(f"{'-'*65}")
    for r in ranked:
        issues = ", ".join(p.issue for p in r.problems)
        print(f"{r.product_id:>8}  {r.score:>6}  {r.worst_priority:>7}  {issues}")
        print(f"{'':>8}  {'':>6}  {'':>7}  ↳ {r.name[:55]}")
    print(f"{'='*65}\n")


# ── CLI ───────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="SEO-аудит товарів Prom.ua")
    parser.add_argument("--limit", type=int, default=None,
                        help="Максимальна кількість товарів (за замовч.: всі)")
    parser.add_argument("--out", type=Path, default=Path("problems_report.csv"),
                        help="Шлях до вихідного CSV (за замовч.: problems_report.csv)")
    parser.add_argument("--top", type=int, default=20,
                        help="Кількість товарів у топ-списку (за замовч.: 20)")
    args = parser.parse_args()

    logger.info("Підключення до Prom API...")
    client = prom_client()

    logger.info("Завантаження товарів...")
    products = fetch_all_products(client, max_products=args.limit)
    logger.info(f"Завантажено {len(products)} товарів")

    if not products:
        logger.warning("Товарів не знайдено. Перевір PROM_API_TOKEN.")
        sys.exit(1)

    # Аудит
    logger.info("Аналіз SEO-якості...")
    reports = [audit_product(p) for p in products]

    ok      = sum(1 for r in reports if not r.problems)
    high    = sum(1 for r in reports if r.worst_priority == "high" and r.problems)
    medium  = sum(1 for r in reports if r.worst_priority == "medium" and r.problems)
    low     = sum(1 for r in reports if r.worst_priority == "low" and r.problems)

    # Запис CSV
    write_csv(reports, args.out)
    logger.success(f"Звіт збережено: {args.out}")

    # Топ-список
    print_top(reports, args.top)

    # Підсумок
    print(f"{'='*50}")
    print(f"  Всього товарів  : {len(reports)}")
    print(f"  Без проблем     : {ok}")
    print(f"  Критичні (high) : {high}")
    print(f"  Середні (medium): {medium}")
    print(f"  Незначні (low)  : {low}")
    print(f"  Звіт            : {args.out}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()

````

### `tools/prom_tecdoc_splitter.py` — 172 рядків

````python
#!/usr/bin/env python3
"""
tools/prom_tecdoc_splitter.py — розподіл товарів Prom.ua на tecdoc / manual.

Запуск:
  python3 tools/prom_tecdoc_splitter.py <файл.xlsx>
  python3 tools/prom_tecdoc_splitter.py <файл.xlsx> --col-id "Артикул" --col-brand "Бренд"
"""

import argparse
import os
import re
import sys
from pathlib import Path

import openpyxl
from openpyxl import load_workbook

ARTICLE_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9\-_./ ]{2,18}[A-Za-z0-9]$')

ARTICLE_COL_NAMES = {"артикул", "код", "oem", "part number", "part_number", "номер деталі", "номер детали"}
BRAND_COL_NAMES   = {"виробник", "brand", "бренд", "производитель"}
NO_BRAND_VALUES   = {"", "без бренда", "без бренду", "no brand", "—", "-", "none"}


def detect_article_col(headers: list[str], rows: list[list]) -> str | None:
    """Повертає назву колонки-кандидата для артикула."""
    for h in headers:
        if h.lower().strip() in ARTICLE_COL_NAMES:
            return h

    # евристика: >50% значень колонки відповідають патерну
    col_idx = {h: i for i, h in enumerate(headers)}
    for h, idx in col_idx.items():
        vals = [str(r[idx]).strip() for r in rows if idx < len(r) and r[idx]]
        if not vals:
            continue
        matches = sum(1 for v in vals if ARTICLE_PATTERN.match(v))
        if matches / len(vals) > 0.5:
            return h
    return None


def detect_brand_col(headers: list[str]) -> str | None:
    for h in headers:
        if h.lower().strip() in BRAND_COL_NAMES:
            return h
    return None


def read_xlsx(path: str) -> tuple[list[str], list[list]]:
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return [], []
    headers = [str(c).strip() if c is not None else "" for c in rows[0]]
    data = [list(r) for r in rows[1:] if any(c for c in r)]
    return headers, data


def classify(headers: list[str], rows: list[list],
             col_id: str | None, col_brand: str | None
             ) -> tuple[list[list], list[list]]:

    art_col   = col_id    or detect_article_col(headers, rows)
    brand_col = col_brand or detect_brand_col(headers)

    print(f"  Колонка артикула : {art_col or '(не знайдено)'}")
    print(f"  Колонка бренду   : {brand_col or '(не знайдено)'}")

    art_idx   = headers.index(art_col)   if art_col   and art_col   in headers else None
    brand_idx = headers.index(brand_col) if brand_col and brand_col in headers else None

    tecdoc, manual = [], []
    for row in rows:
        has_art   = False
        has_brand = False

        if art_idx is not None and art_idx < len(row):
            val = str(row[art_idx]).strip()
            has_art = bool(val and val not in ("None", "-", "—"))

        if brand_idx is not None and brand_idx < len(row):
            val = str(row[brand_idx]).strip().lower()
            has_brand = bool(val and val not in NO_BRAND_VALUES)

        if has_art and has_brand:
            tecdoc.append(row)
        else:
            manual.append(row)

    return tecdoc, manual


def save_xlsx(path: str, headers: list[str], rows: list[list]):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append(row)
    wb.save(path)


def top_brands(headers: list[str], rows: list[list], col_brand: str | None, n: int = 5):
    if not col_brand or col_brand not in headers:
        return []
    idx = headers.index(col_brand)
    counts: dict[str, int] = {}
    for row in rows:
        if idx < len(row):
            val = str(row[idx]).strip()
            if val and val.lower() not in NO_BRAND_VALUES and val != "None":
                counts[val] = counts.get(val, 0) + 1
    return sorted(counts.items(), key=lambda x: -x[1])[:n]


def main():
    parser = argparse.ArgumentParser(description="Prom TecDoc splitter")
    parser.add_argument("xlsx", help="Вхідний XLSX файл")
    parser.add_argument("--col-id",    default=None, help="Назва колонки артикула")
    parser.add_argument("--col-brand", default=None, help="Назва колонки бренду")
    args = parser.parse_args()

    if not os.path.exists(args.xlsx):
        sys.exit(f"Файл не знайдено: {args.xlsx}")

    print(f"\nЧитаємо: {args.xlsx}")
    headers, rows = read_xlsx(args.xlsx)
    if not headers:
        sys.exit("Файл порожній або пошкоджений")

    print(f"Колонки ({len(headers)}): {', '.join(h for h in headers if h)}\n")

    tecdoc, manual = classify(headers, rows, args.col_id, args.col_brand)

    total = len(tecdoc) + len(manual)
    print(f"\n{'─'*50}")
    print(f"Всього товарів    : {total}")
    print(f"З TecDoc кодами   : {len(tecdoc)}")
    if tecdoc:
        print("  Перші 5 прикладів:")
        for r in tecdoc[:5]:
            print(f"    {r}")
    print(f"Ручна сумісність  : {len(manual)}")
    if manual:
        print("  Перші 5 прикладів:")
        for r in manual[:5]:
            print(f"    {r}")

    brand_col = args.col_brand or detect_brand_col(headers)
    brands = top_brands(headers, tecdoc + manual, brand_col)
    if brands:
        print(f"\nТоп-5 виробників (TecDoc):")
        for name, cnt in top_brands(headers, tecdoc, brand_col):
            print(f"  {cnt:>5}  {name}")

    out_dir = Path(args.xlsx).parent / "exports"
    out_dir.mkdir(exist_ok=True)

    tecdoc_path = str(out_dir / "tecdoc_items.xlsx")
    manual_path = str(out_dir / "manual_items.xlsx")
    save_xlsx(tecdoc_path, headers, tecdoc)
    save_xlsx(manual_path, headers, manual)

    print(f"\nЗбережено:")
    print(f"  {tecdoc_path}  ({len(tecdoc)} рядків)")
    print(f"  {manual_path}  ({len(manual)} рядків)")


if __name__ == "__main__":
    main()

````

### `tools/prom_validator.py` — 274 рядків

````python
#!/usr/bin/env python3
"""
tools/prom_validator.py — валідатор XML/XLSX для Prom.ua

Usage:
  python3 tools/prom_validator.py feed.xml
  python3 tools/prom_validator.py feed.xml --no-warn
  python3 tools/prom_validator.py feed.xml --out report.txt
"""

import argparse
import os
import re
import sys
from collections import Counter
from xml.etree import ElementTree as ET


PROMO_WORDS = ["акція", "знижка", "знижк", "безкоштовн", "найкраща ціна"]
NAME_MAX    = 110
NAME_WARN   = 80

AVAILABLE_TRUE  = {"true", "1", "yes", "так", "+", "в наявності"}
AVAILABLE_KNOWN = AVAILABLE_TRUE | {"false", "0", "no", "ні", "-", "немає", "під замовлення"}


# ─── parsers ──────────────────────────────────────────────────────────────────

def parse_xml(path: str) -> list:
    tree = ET.parse(path)
    root = tree.getroot()
    items = []
    for o in root.findall(".//offer"):
        pics = [p.text or "" for p in o.findall("picture") if p.text]
        items.append({
            "id":                 o.get("id") or o.findtext("id") or "",
            "name":               o.findtext("name") or o.findtext("name_ua") or "",
            "available":          o.get("available") or o.findtext("available") or "",
            "price":              o.findtext("price") or "",
            "portal_category_id": o.findtext("portal_category_id") or "",
            "vendor":             o.findtext("vendor") or "",
            "description":        o.findtext("description") or o.findtext("description_ua") or "",
            "picture":            ",".join(pics),
        })
    return items


def parse_xlsx(path: str) -> list:
    try:
        import openpyxl
    except ImportError:
        print("ERROR: openpyxl не встановлено. pip install openpyxl", file=sys.stderr)
        sys.exit(1)

    ALIASES = {
        "id":                 ["id", "ід", "код", "external_id"],
        "name":               ["назва", "name", "назва товару", "найменування"],
        "available":          ["наявність", "available", "доступність"],
        "price":              ["ціна", "price", "ціна, грн", "ціна грн"],
        "portal_category_id": ["портал категорія", "portal_category_id", "категорія порталу"],
        "vendor":             ["виробник", "vendor", "бренд", "brand"],
        "description":        ["опис", "description", "опис товару"],
        "picture":            ["зображення", "picture", "фото"],
    }

    wb   = openpyxl.load_workbook(path, read_only=True, data_only=True)
    rows = list(wb.active.iter_rows(values_only=True))
    if not rows:
        return []

    headers = [str(h).strip().lower() if h else "" for h in rows[0]]
    col_map = {}
    for field, aliases in ALIASES.items():
        for i, h in enumerate(headers):
            if any(a in h for a in aliases):
                col_map[field] = i
                break

    items = []
    for row in rows[1:]:
        if all(c is None for c in row):
            continue
        def get(f):
            i = col_map.get(f)
            return str(row[i]).strip() if i is not None and row[i] is not None else ""
        items.append({f: get(f) for f in ALIASES})
    return items


# ─── validation ───────────────────────────────────────────────────────────────

def _is_all_caps(name: str) -> bool:
    words = name.split()
    if len(words) <= 3:
        return False
    upper = [w for w in words
             if re.search(r'[А-ЯЁІЇЄA-Z]', w) and not re.search(r'[а-яёіїєa-z]', w)]
    return len(upper) > 3


def validate(item: dict) -> tuple:
    errors   = []
    warnings = []
    name      = item["name"].strip()
    name_low  = name.lower()
    available = item["available"].strip().lower()

    # ── ERR ──────────────────────────────────────────────────────────────────
    if not item["id"].strip():
        errors.append("відсутній id")

    if not name:
        errors.append("відсутня назва")
    else:
        if not re.search(r'[А-ЯҐЄІЇа-яґєіїA-Za-z]', name):
            errors.append("назва без літер (тільки цифри/спецсимволи)")
        if _is_all_caps(name):
            errors.append("назва ALL CAPS (більше 3 слів)")
        if len(name) > NAME_MAX:
            errors.append(f"назва {len(name)} символів (макс {NAME_MAX})")
        for pw in PROMO_WORDS:
            if pw in name_low:
                errors.append(f"рекламне слово: «{pw}»")
                break

    if not item["portal_category_id"].strip():
        errors.append("відсутній portal_category_id")

    if available in AVAILABLE_TRUE:
        price_str = item["price"].strip()
        try:
            if not price_str or float(price_str.replace(",", ".")) <= 0:
                errors.append("ціна = 0 або відсутня при available=true")
        except ValueError:
            errors.append(f"ціна не є числом: «{price_str[:20]}»")

    # ── WARN ─────────────────────────────────────────────────────────────────
    if not item["vendor"].strip():
        warnings.append("відсутній vendor/brand")
    if not item["description"].strip():
        warnings.append("відсутній опис")
    if not item["picture"].strip():
        warnings.append("відсутні фото")
    if name and NAME_WARN < len(name) <= NAME_MAX:
        warnings.append(f"назва {len(name)} символів (ліміт {NAME_MAX})")
    if available and available not in AVAILABLE_KNOWN:
        warnings.append(f"незрозуміле available: «{available[:20]}»")

    return errors, warnings


# ─── report ───────────────────────────────────────────────────────────────────

def build_report(items: list, no_warn: bool) -> tuple:
    # pre-scan duplicate ids
    id_counts = Counter(i["id"].strip() for i in items if i["id"].strip())
    dup_ids   = {oid for oid, n in id_counts.items() if n > 1}

    results = []
    for item in items:
        errors, warnings = validate(item)
        oid = item["id"].strip()
        if oid in dup_ids:
            errors.insert(0, f"дублікат id «{oid}»")
        results.append({
            "id":    oid or "(немає)",
            "name":  (item["name"].strip() or "(немає)")[:60],
            "errs":  errors,
            "warns": warnings,
        })

    total     = len(results)
    err_items = [r for r in results if r["errs"]]
    wrn_items = [r for r in results if r["warns"]]
    n_errs    = sum(len(r["errs"])  for r in results)
    n_warns   = sum(len(r["warns"]) for r in results)
    valid_pct = round((total - len(err_items)) / total * 100) if total else 0

    lines = []
    SEP   = "=" * 64

    lines += [
        SEP,
        "  Prom.ua Validator",
        SEP,
        f"  Товарів        : {total}",
        f"  ERR            : {n_errs}  ({len(err_items)} товарів з помилками)",
    ]
    if not no_warn:
        lines.append(f"  WARN           : {n_warns}  ({len(wrn_items)} товарів з попередженнями)")
    lines += [
        f"  Валідних       : {total - len(err_items)} / {total}  ({valid_pct}%)",
        SEP,
    ]

    # errors
    if err_items:
        lines.append(f"\n  ПОМИЛКИ (перші 20 з {len(err_items)}):\n")
        for r in err_items[:20]:
            lines.append(f"  [{r['id']}] {r['name']}")
            for e in r["errs"]:
                lines.append(f"    ERR  {e}")

    # warnings
    if not no_warn and wrn_items:
        lines.append(f"\n  ПОПЕРЕДЖЕННЯ (перші 20 з {len(wrn_items)}):\n")
        for r in wrn_items[:20]:
            lines.append(f"  [{r['id']}] {r['name']}")
            for w in r["warns"]:
                lines.append(f"    WARN {w}")

    # top-10 most problematic
    top10 = sorted(
        [r for r in results if r["errs"] or r["warns"]],
        key=lambda r: len(r["errs"]) * 10 + len(r["warns"]),
        reverse=True,
    )[:10]
    if top10:
        lines.append(f"\n  ТОП-10 ПРОБЛЕМНИХ:\n")
        for r in top10:
            lines.append(
                f"  ERR={len(r['errs'])} WARN={len(r['warns'])}  [{r['id']}] {r['name']}"
            )

    lines += [
        f"\n{SEP}",
        "  ✗  ФАЙЛ МАЄ ПОМИЛКИ — потребує виправлення" if err_items
        else "  ✅  СТРУКТУРНИХ ПОМИЛОК НЕМАЄ",
        SEP,
    ]

    return "\n".join(lines), bool(err_items)


# ─── main ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Prom.ua XML/XLSX validator")
    ap.add_argument("file",      help="XML або XLSX файл")
    ap.add_argument("--no-warn", action="store_true", help="показувати тільки ERR")
    ap.add_argument("--out",     metavar="FILE",       help="зберегти звіт у файл")
    args = ap.parse_args()

    if not os.path.exists(args.file):
        print(f"Файл не знайдено: {args.file}", file=sys.stderr)
        sys.exit(1)

    ext = os.path.splitext(args.file)[1].lower()
    if ext in (".xlsx", ".xls"):
        items = parse_xlsx(args.file)
    elif ext in (".xml", ".yml"):
        items = parse_xml(args.file)
    else:
        print(f"Непідтримуваний формат: {ext}. Використовуйте .xml/.yml/.xlsx",
              file=sys.stderr)
        sys.exit(1)

    if not items:
        print("Товарів не знайдено у файлі.")
        sys.exit(0)

    report, has_errors = build_report(items, no_warn=args.no_warn)
    print(report)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"\nЗвіт збережено: {args.out}")

    sys.exit(1 if has_errors else 0)


if __name__ == "__main__":
    main()

````

### `tools/rozetka_xml_validator.py` — 634 рядків

````python
#!/usr/bin/env python3
"""
tools/rozetka_xml_validator.py
Universal validator for Rozetka seller XML (YML) feeds.

Sources:
  sellerhelp.rozetka.com.ua/p185-pricelist-requirements.html
  shared/knowledge_base/rozetka/xml_faq.txt
  docs/XML_VALIDATION_PLAN.md

Usage:
  python3 tools/rozetka_xml_validator.py [path_to_xml]
  python3 tools/rozetka_xml_validator.py data/katran_rozetka.xml
"""

import os
import re
import sys
import json
from collections import defaultdict
from datetime import datetime
from xml.etree import ElementTree as ET

# ─── constants ───────────────────────────────────────────────────────────────

DEFAULT_CATEGORY_ID = "25636737"   # Ручний інструмент (наш fallback — попередження)
MAX_URL_LEN         = 1999
MAX_NAME_LEN        = 255
WARN_NAME_LEN       = 150
MAX_ARTICLE_LEN     = 255
MIN_PARAMS          = 3
CYRILLIC_RE         = re.compile(r"[а-яА-ЯіІєЄїЇёЁ]")
URL_RE              = re.compile(r"^https?://", re.IGNORECASE)
HTTPS_RE            = re.compile(r"^https://", re.IGNORECASE)
FORBIDDEN_NAME_START = re.compile(r"^[!@#$%^&*()\[\]{}<>|\\/'\"~`]")
DIGIT_START_RE      = re.compile(r"^\d")

VENDOR_BLOCKLIST = {"no name", "noname", "no-name", "unknown", "без назви", ""}

# ─── issue model ─────────────────────────────────────────────────────────────

class Issue:
    __slots__ = ("level", "offer_id", "field", "message")

    def __init__(self, level: str, offer_id: str, field: str, message: str):
        self.level    = level     # "ERROR" | "WARN"
        self.offer_id = offer_id
        self.field    = field
        self.message  = message

    def to_dict(self) -> dict:
        return {
            "level":    self.level,
            "offer_id": self.offer_id,
            "field":    self.field,
            "message":  self.message,
        }


# ─── helpers ─────────────────────────────────────────────────────────────────

def _txt(el, tag: str, default: str = "") -> str:
    child = el.find(tag)
    if child is None or child.text is None:
        return default
    return child.text.strip()


def _all_txt(el, tag: str) -> list[str]:
    return [c.text.strip() for c in el.findall(tag) if c.text]


# ─── validator ───────────────────────────────────────────────────────────────

class RozetkaXMLValidator:
    def __init__(self, xml_path: str):
        self.xml_path   = xml_path
        self.issues: list[Issue] = []
        self.offers_data: list[dict] = []
        self.category_ids: set[str] = set()
        self.category_names: dict[str, str] = {}
        self.parse_ok  = False
        self.root      = None

    # ── error / warn shortcuts ────────────────────────────────────────────────

    def _err(self, offer_id: str, field: str, msg: str):
        self.issues.append(Issue("ERROR", offer_id, field, msg))

    def _warn(self, offer_id: str, field: str, msg: str):
        self.issues.append(Issue("WARN",  offer_id, field, msg))

    # ── 1. structural checks ─────────────────────────────────────────────────

    def _check_structure(self) -> bool:
        # 1a. XML syntax + UTF-8
        try:
            with open(self.xml_path, "rb") as f:
                raw = f.read()
        except OSError as e:
            self._err("FILE", "file", f"Не вдалось прочитати файл: {e}")
            return False

        if b"encoding" in raw[:200].lower() and b"utf-8" not in raw[:200].lower():
            self._err("FILE", "encoding", "XML декларує не UTF-8 кодування")

        try:
            self.root = ET.fromstring(raw)
        except ET.ParseError as e:
            self._err("FILE", "xml_syntax", f"Невалідний XML синтаксис: {e}")
            return False

        # 1b. Root tag
        if self.root.tag != "yml_catalog":
            self._err("FILE", "root", f"Кореневий тег має бути yml_catalog, знайдено: {self.root.tag}")
            return False

        # 1c. Required containers
        shop = self.root.find("shop")
        if shop is None:
            self._err("FILE", "shop", "Відсутній тег <shop>")
            return False

        for required in ("currencies", "categories", "offers"):
            if shop.find(required) is None:
                self._err("FILE", required, f"Відсутній тег <{required}>")

        return True

    def _load_categories(self):
        shop = self.root.find("shop")
        if shop is None:
            return
        cats_el = shop.find("categories")
        if cats_el is None:
            return
        for cat in cats_el.findall("category"):
            cid = cat.get("id", "").strip()
            name = (cat.text or "").strip()
            if cid:
                self.category_ids.add(cid)
                self.category_names[cid] = name

    # ── 2. per-offer checks ───────────────────────────────────────────────────

    def _check_offer(self, offer: ET.Element, seen_ids: set, name_counter: dict):
        oid = offer.get("id", "").strip()
        if not oid:
            self._err("?", "offer_id", "Оффер без атрибуту id")
            oid = "NOID"
        elif oid in seen_ids:
            self._err(oid, "offer_id", f"Дублікат offer id: {oid}")
        seen_ids.add(oid)

        result = {"id": oid, "errors": 0, "warns": 0}

        # price
        price_txt = _txt(offer, "price")
        try:
            price = float(price_txt)
            if price <= 0:
                self._err(oid, "price", f"price <= 0: {price}")
                result["errors"] += 1
        except ValueError:
            self._err(oid, "price", f"price не є числом: '{price_txt}'")
            result["errors"] += 1

        # currencyId
        currency = _txt(offer, "currencyId")
        if currency != "UAH":
            self._err(oid, "currencyId", f"currencyId має бути UAH, знайдено: '{currency}'")
            result["errors"] += 1

        # categoryId
        cat_id = _txt(offer, "categoryId")
        if not cat_id:
            self._err(oid, "categoryId", "Відсутній тег <categoryId>")
            result["errors"] += 1
        elif cat_id not in self.category_ids:
            self._err(oid, "categoryId", f"categoryId '{cat_id}' не оголошено в <categories>")
            result["errors"] += 1
        elif cat_id == DEFAULT_CATEGORY_ID:
            self._warn(oid, "categoryId", f"categoryId = {DEFAULT_CATEGORY_ID} (DEFAULT — 'Ручний інструмент'). Товар може бути відхилений.")
            result["warns"] += 1

        # pictures
        pics = _all_txt(offer, "picture")
        if not pics:
            self._err(oid, "picture", "Відсутнє хоча б одне фото <picture>")
            result["errors"] += 1
        for pic in pics:
            if not URL_RE.match(pic):
                self._err(oid, "picture", f"URL фото не починається з http: {pic[:80]}")
                result["errors"] += 1
            elif not HTTPS_RE.match(pic):
                self._warn(oid, "picture", f"URL фото HTTP замість HTTPS: {pic[:80]}")
                result["warns"] += 1
            if CYRILLIC_RE.search(pic):
                self._err(oid, "picture", f"URL фото містить кирилицю: {pic[:80]}")
                result["errors"] += 1
            if len(pic) > MAX_URL_LEN:
                self._err(oid, "picture", f"URL фото > {MAX_URL_LEN} символів ({len(pic)})")
                result["errors"] += 1

        # name / name_ua
        name    = _txt(offer, "name")
        name_ua = _txt(offer, "name_ua")
        effective_name = name_ua or name
        if not effective_name:
            self._err(oid, "name", "Відсутні тegi <name> і <name_ua>")
            result["errors"] += 1
        else:
            if len(effective_name) < 5:
                self._err(oid, "name", f"Назва коротша 5 символів: '{effective_name}'")
                result["errors"] += 1
            elif len(effective_name) > MAX_NAME_LEN:
                self._err(oid, "name", f"Назва > {MAX_NAME_LEN} символів ({len(effective_name)})")
                result["errors"] += 1
            if FORBIDDEN_NAME_START.match(effective_name):
                self._err(oid, "name", f"Назва починається з забороненого символу: '{effective_name[:30]}'")
                result["errors"] += 1
            elif DIGIT_START_RE.match(effective_name):
                self._warn(oid, "name", f"Назва починається з цифри: '{effective_name[:50]}'")
                result["warns"] += 1
            if len(effective_name) > WARN_NAME_LEN:
                self._warn(oid, "name", f"Назва довша {WARN_NAME_LEN} символів ({len(effective_name)})")
                result["warns"] += 1
            # duplicate name tracking
            name_counter[effective_name] += 1

        # vendor
        vendor = _txt(offer, "vendor")
        if not vendor or vendor.lower() in VENDOR_BLOCKLIST:
            self._err(oid, "vendor", f"vendor відсутній або недопустимий: '{vendor}'")
            result["errors"] += 1
        elif vendor.lower() in ("без бренду", "no brand", "nobrand"):
            self._warn(oid, "vendor", f"vendor = '{vendor}' (товар без бренду — ризик модерації)")
            result["warns"] += 1
        elif URL_RE.match(vendor):
            self._err(oid, "vendor", f"vendor виглядає як URL: '{vendor[:60]}'")
            result["errors"] += 1

        # article
        article = _txt(offer, "article")
        if not article:
            self._warn(oid, "article", "Відсутній тег <article> (рекомендовано)")
            result["warns"] += 1
        elif len(article) > MAX_ARTICLE_LEN:
            self._err(oid, "article", f"article > {MAX_ARTICLE_LEN} символів ({len(article)})")
            result["errors"] += 1
        if article and effective_name and article == effective_name and len(article) < 15:
            self._warn(oid, "name", f"Назва = артикул ('{article}') — рекомендується змістовна назва")
            result["warns"] += 1

        # stock_quantity
        sq_txt = _txt(offer, "stock_quantity")
        try:
            sq = int(float(sq_txt))
            if sq <= 0:
                self._err(oid, "stock_quantity", f"stock_quantity <= 0: {sq}")
                result["errors"] += 1
        except ValueError:
            self._err(oid, "stock_quantity", f"stock_quantity не є числом: '{sq_txt}'")
            result["errors"] += 1

        # params
        params = offer.findall("param")
        param_names = [p.get("name", "") for p in params]
        if len(params) < MIN_PARAMS:
            self._warn(oid, "param", f"Менше {MIN_PARAMS} характеристик <param>: знайдено {len(params)}")
            result["warns"] += 1
        for p in params:
            pname = p.get("name", "")
            pval  = (p.text or "").strip()
            if pname == "Гарантія" and pval in ("0", "0 міс", "0 місяців"):
                self._warn(oid, "param", "Гарантія = 0 міс — не виводити, Розетка не приймає нульову гарантію")
                result["warns"] += 1

        self.offers_data.append({
            "id":       oid,
            "cat_id":   cat_id,
            "name":     effective_name[:100] if effective_name else "",
            "vendor":   vendor,
            "price":    price_txt,
            "pics":     len(pics),
            "params":   len(params),
            "errors":   result["errors"],
            "warns":    result["warns"],
        })

    # ── 3. duplicate names (post-pass) ────────────────────────────────────────

    def _check_dup_names(self, name_counter: dict):
        for name, count in name_counter.items():
            if count > 1:
                self._warn("MULTIPLE", "name", f"Дублікат назви ({count} offerів): '{name[:70]}'")

    # ── 4. main entry ─────────────────────────────────────────────────────────

    def run(self) -> dict:
        print(f"\n{'='*65}")
        print(f"  Rozetka XML Validator")
        print(f"  Файл: {self.xml_path}")
        print(f"  Час : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*65}\n")

        # structural
        print("▶ Перевірка структури XML...")
        ok = self._check_structure()
        if not ok:
            print("  ✗ Критична структурна помилка — подальша перевірка неможлива\n")
            return self._build_report()

        self.parse_ok = True
        self._load_categories()
        print(f"  ✓ XML синтаксис: OK")
        print(f"  ✓ Категорій оголошено: {len(self.category_ids)}")

        # offers
        shop     = self.root.find("shop")
        offers_el = shop.find("offers")
        all_offers = offers_el.findall("offer") if offers_el is not None else []
        total = len(all_offers)
        print(f"  ✓ Офферів у файлі: {total}\n")

        print("▶ Перевірка офферів...")
        seen_ids     = set()
        name_counter = defaultdict(int)
        for offer in all_offers:
            self._check_offer(offer, seen_ids, name_counter)

        self._check_dup_names(name_counter)

        return self._build_report()

    # ── 5. reporting ──────────────────────────────────────────────────────────

    def _build_report(self) -> dict:
        errors = [i for i in self.issues if i.level == "ERROR"]
        warns  = [i for i in self.issues if i.level == "WARN"]
        total  = len(self.offers_data)

        # per-offer counts
        offers_with_error = sum(1 for o in self.offers_data if o["errors"] > 0)
        offers_clean      = total - offers_with_error
        pass_rate         = (offers_clean / total * 100) if total else 0

        # category distribution
        cat_dist = defaultdict(int)
        for o in self.offers_data:
            cat_dist[o["cat_id"]] += 1

        # top-10 worst offers
        worst = sorted(self.offers_data, key=lambda x: -(x["errors"] * 100 + x["warns"]))[:10]

        # issues by offer_id
        issues_by_offer = defaultdict(list)
        for iss in self.issues:
            issues_by_offer[iss.offer_id].append(iss)

        report = {
            "meta": {
                "file":        self.xml_path,
                "generated":   datetime.now().isoformat(),
                "parse_ok":    self.parse_ok,
            },
            "summary": {
                "total_offers":        total,
                "total_errors":        len(errors),
                "total_warnings":      len(warns),
                "offers_with_errors":  offers_with_error,
                "offers_clean":        offers_clean,
                "pass_rate_pct":       round(pass_rate, 1),
                "categories_count":    len(self.category_ids),
            },
            "category_distribution": dict(
                sorted(cat_dist.items(), key=lambda x: -x[1])
            ),
            "top10_worst_offers": worst,
            "all_issues": [i.to_dict() for i in self.issues],
        }

        self._print_report(report, errors, warns)
        return report

    def _print_report(self, report: dict, errors: list, warns: list):
        s = report["summary"]

        # category stats
        cat_lines = []
        for cid, cnt in list(report["category_distribution"].items())[:15]:
            name = self.category_names.get(cid, "?")
            marker = " ⚠ DEFAULT" if cid == DEFAULT_CATEGORY_ID else ""
            cat_lines.append(f"    {cnt:>5}  {cid:<12} {name[:35]}{marker}")

        # errors by field
        err_by_field = defaultdict(int)
        for e in errors:
            err_by_field[e.field] += 1
        warn_by_field = defaultdict(int)
        for w in warns:
            warn_by_field[w.field] += 1

        print(f"{'─'*65}")
        print(f"  ПІДСУМОК")
        print(f"{'─'*65}")
        print(f"  Офферів всього         : {s['total_offers']}")
        print(f"  Помилок (ERROR)        : {s['total_errors']}")
        print(f"  Попереджень (WARN)     : {s['total_warnings']}")
        print(f"  Офферів з помилками    : {s['offers_with_errors']}")
        print(f"  Офферів без помилок    : {s['offers_clean']}")
        print(f"  Відсоток валідних      : {s['pass_rate_pct']}%")
        print()

        if s["total_errors"] > 0:
            print(f"  ПОМИЛКИ по полях:")
            for field, cnt in sorted(err_by_field.items(), key=lambda x: -x[1])[:12]:
                print(f"    ✗ {field:<22} {cnt:>5}")
            print()

        if s["total_warnings"] > 0:
            print(f"  ПОПЕРЕДЖЕННЯ по полях:")
            for field, cnt in sorted(warn_by_field.items(), key=lambda x: -x[1])[:12]:
                print(f"    ⚠ {field:<22} {cnt:>5}")
            print()

        print(f"  РОЗПОДІЛ ПО КАТЕГОРІЯХ (топ-15):")
        for line in cat_lines:
            print(line)
        print()

        if report["top10_worst_offers"]:
            print(f"  ТОП-10 ПРОБЛЕМНИХ ОФФЕРІВ:")
            for o in report["top10_worst_offers"]:
                if o["errors"] == 0 and o["warns"] == 0:
                    break
                print(f"    [{o['id'][:20]:<20}] ERR={o['errors']} WARN={o['warns']}  {o['name'][:40]}")
            print()

        # final verdict
        if s["total_errors"] == 0:
            print(f"  ✅  СТРУКТУРНИХ ПОМИЛОК НЕМАЄ — файл може бути завантажений")
        else:
            print(f"  ✗  ФАЙЛ МАЄ {s['total_errors']} ПОМИЛОК — потребує виправлення")

        print(f"{'='*65}\n")

        # sample errors
        shown = 0
        for iss in errors[:20]:
            print(f"  ERROR [{iss.offer_id[:20]}] {iss.field}: {iss.message[:80]}")
            shown += 1
        if len(errors) > 20:
            print(f"  ... ще {len(errors) - 20} помилок (повний список у JSON/XLSX звіті)")
        if shown:
            print()


# ─── output writers ───────────────────────────────────────────────────────────

def write_json(report: dict, path: str):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    print(f"  JSON звіт: {path}")


def write_xlsx(report: dict, path: str):
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
    except ImportError:
        print("  ⚠ openpyxl не встановлено — XLSX звіт пропущено")
        return

    wb = openpyxl.Workbook()

    # ── Sheet 1: Summary ──────────────────────────────────────────────────────
    ws = wb.active
    ws.title = "Summary"
    hdr_font = Font(bold=True, color="FFFFFF")
    hdr_fill = PatternFill("solid", fgColor="2E4053")
    err_fill  = PatternFill("solid", fgColor="FADBD8")
    warn_fill = PatternFill("solid", fgColor="FEF9E7")
    ok_fill   = PatternFill("solid", fgColor="D5F5E3")

    s = report["summary"]
    rows = [
        ("Параметр", "Значення"),
        ("Файл",               report["meta"]["file"]),
        ("Дата перевірки",     report["meta"]["generated"][:19]),
        ("Офферів всього",     s["total_offers"]),
        ("Помилок (ERROR)",    s["total_errors"]),
        ("Попереджень (WARN)", s["total_warnings"]),
        ("Офферів з помилками",s["offers_with_errors"]),
        ("Офферів валідних",   s["offers_clean"]),
        ("Відсоток валідних",  f"{s['pass_rate_pct']}%"),
        ("Категорій",          s["categories_count"]),
    ]
    for i, (k, v) in enumerate(rows, 1):
        ws.cell(i, 1, k)
        ws.cell(i, 2, v)
        if i == 1:
            for c in (ws.cell(i, 1), ws.cell(i, 2)):
                c.font = hdr_font
                c.fill = hdr_fill
    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 40

    # ── Sheet 2: Issues ───────────────────────────────────────────────────────
    ws2 = wb.create_sheet("Issues")
    hdrs = ["Рівень", "Offer ID", "Поле", "Повідомлення"]
    for col, h in enumerate(hdrs, 1):
        c = ws2.cell(1, col, h)
        c.font = hdr_font
        c.fill = hdr_fill

    for row, iss in enumerate(report["all_issues"], 2):
        ws2.cell(row, 1, iss["level"])
        ws2.cell(row, 2, iss["offer_id"])
        ws2.cell(row, 3, iss["field"])
        ws2.cell(row, 4, iss["message"])
        fill = err_fill if iss["level"] == "ERROR" else warn_fill
        for col in range(1, 5):
            ws2.cell(row, col).fill = fill

    ws2.column_dimensions["A"].width = 8
    ws2.column_dimensions["B"].width = 25
    ws2.column_dimensions["C"].width = 18
    ws2.column_dimensions["D"].width = 80
    ws2.auto_filter.ref = f"A1:D{len(report['all_issues'])+1}"

    # ── Sheet 3: Categories ───────────────────────────────────────────────────
    ws3 = wb.create_sheet("Categories")
    for col, h in enumerate(["rz_id", "Назва категорії", "Офферів", "Примітка"], 1):
        c = ws3.cell(1, col, h)
        c.font = hdr_font
        c.fill = hdr_fill

    cat_names_map = {
        k: v for k, v in zip(
            report["category_distribution"].keys(),
            [report["meta"].get("cat_names", {}).get(k, "") for k in report["category_distribution"]]
        )
    }

    for row, (cid, cnt) in enumerate(report["category_distribution"].items(), 2):
        ws3.cell(row, 1, cid)
        ws3.cell(row, 2, report.get("_cat_names", {}).get(cid, ""))
        ws3.cell(row, 3, cnt)
        note = "DEFAULT — ризик відхилення" if cid == DEFAULT_CATEGORY_ID else ""
        ws3.cell(row, 4, note)
        if cid == DEFAULT_CATEGORY_ID:
            for col in range(1, 5):
                ws3.cell(row, col).fill = warn_fill

    ws3.column_dimensions["A"].width = 14
    ws3.column_dimensions["B"].width = 35
    ws3.column_dimensions["C"].width = 10
    ws3.column_dimensions["D"].width = 35

    # ── Sheet 4: Worst Offers ─────────────────────────────────────────────────
    ws4 = wb.create_sheet("Worst Offers")
    hdrs4 = ["Offer ID", "Помилок", "Попереджень", "Назва", "Категорія", "Вендор", "Фото", "Параметрів"]
    for col, h in enumerate(hdrs4, 1):
        c = ws4.cell(1, col, h)
        c.font = hdr_font
        c.fill = hdr_fill

    for row, o in enumerate(report["top10_worst_offers"], 2):
        ws4.cell(row, 1, o["id"])
        ws4.cell(row, 2, o["errors"])
        ws4.cell(row, 3, o["warns"])
        ws4.cell(row, 4, o["name"])
        ws4.cell(row, 5, o["cat_id"])
        ws4.cell(row, 6, o["vendor"])
        ws4.cell(row, 7, o["pics"])
        ws4.cell(row, 8, o["params"])
        if o["errors"] > 0:
            ws4.cell(row, 2).fill = err_fill
        elif o["warns"] > 0:
            ws4.cell(row, 3).fill = warn_fill

    for col, w in enumerate([20, 8, 12, 45, 14, 20, 6, 10], 1):
        ws4.column_dimensions[openpyxl.utils.get_column_letter(col)].width = w

    wb.save(path)
    print(f"  XLSX звіт: {path}")


# ─── entry point ─────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Rozetka XML Validator")
    parser.add_argument("xml_file", nargs="?", default=None, help="XML file to validate")
    parser.add_argument(
        "--no-xlsx", action="store_true",
        help="Skip Excel report (use on servers without AVX/openpyxl support)"
    )
    args = parser.parse_args()

    if args.xml_file:
        xml_path = args.xml_file
    else:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        xml_path = os.path.join(script_dir, "..", "data", "katran_rozetka.xml")

    if not os.path.isabs(xml_path):
        xml_path = os.path.join(os.getcwd(), xml_path)

    xml_path = os.path.normpath(xml_path)

    if not os.path.exists(xml_path):
        print(f"Файл не знайдено: {xml_path}")
        sys.exit(1)

    validator = RozetkaXMLValidator(xml_path)
    report    = validator.run()

    report["_cat_names"] = validator.category_names

    json_path = "/tmp/validation_report.json"
    print("▶ Зберігаю звіти...")
    write_json(report, json_path)
    if not args.no_xlsx:
        write_xlsx(report, "/tmp/validation_report.xlsx")
    print()

    errors = report["summary"]["total_errors"]
    sys.exit(0 if errors == 0 else 1)


if __name__ == "__main__":
    main()

````

### `tools/supplier_onboarding.py` — 882 рядків

````python
#!/usr/bin/env python3
"""
tools/supplier_onboarding.py — Інтерактивний wizard для підключення нового постачальника.

Usage:
  python3 tools/supplier_onboarding.py
  python3 tools/supplier_onboarding.py --resume katran
  python3 tools/supplier_onboarding.py --resume katran --step 3
  python3 tools/supplier_onboarding.py --no-color
"""

import argparse
import io
import json
import math
import os
import re
import subprocess
import sys
import zipfile
from datetime import datetime
from difflib import SequenceMatcher
from xml.etree import ElementTree as ET

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../.env"))

PROGRESS_DIR = "/tmp"
REPO_ROOT    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VALIDATOR    = os.path.join(REPO_ROOT, "tools", "rozetka_xml_validator.py")


# ─── Colors ───────────────────────────────────────────────────────────────────

try:
    from rich.console import Console
    from rich.table import Table
    from rich import print as rprint
    _console = Console()
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

class C:
    BLUE   = "\033[94m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    RED    = "\033[91m"
    CYAN   = "\033[96m"
    BOLD   = "\033[1m"
    DIM    = "\033[2m"
    RESET  = "\033[0m"

    @classmethod
    def disable(cls):
        for attr in ("BLUE","GREEN","YELLOW","RED","CYAN","BOLD","DIM","RESET"):
            setattr(cls, attr, "")


def ok(msg):   print(f"  {C.GREEN}✓{C.RESET}  {msg}")
def warn(msg): print(f"  {C.YELLOW}⚠{C.RESET}  {msg}")
def err(msg):  print(f"  {C.RED}✗{C.RESET}  {msg}")
def info(msg): print(f"  {C.DIM}→{C.RESET}  {msg}")


# ─── DB ───────────────────────────────────────────────────────────────────────

def get_db():
    from shared.utils.db import get_connection
    return get_connection()


def ensure_tables():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS suppliers (
            code        VARCHAR(50) PRIMARY KEY,
            name        VARCHAR(200),
            feed_url    TEXT,
            feed_format VARCHAR(20),
            marketplace VARCHAR(20),
            status      VARCHAR(20) DEFAULT 'active',
            created_at  TIMESTAMP DEFAULT now()
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS supplier_category_map (
            id                     SERIAL PRIMARY KEY,
            supplier_code          VARCHAR(50),
            supplier_category_id   VARCHAR(100),
            supplier_category_name VARCHAR(200),
            rz_id                  VARCHAR(50),
            rz_name                VARCHAR(200),
            commission_pct         NUMERIC(5,2) DEFAULT 7.0,
            created_at             TIMESTAMP DEFAULT now(),
            UNIQUE (supplier_code, supplier_category_id)
        )
    """)
    conn.commit()
    cur.close()
    conn.close()


def get_rozetka_categories():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT DISTINCT ON (rozetka_rz_id)
                rozetka_rz_id, rozetka_category, commission_pct
            FROM katran_categories
            WHERE rozetka_rz_id IS NOT NULL AND rozetka_category IS NOT NULL
            ORDER BY rozetka_rz_id, rozetka_category
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [
            (str(r["rozetka_rz_id"]), r["rozetka_category"], float(r["commission_pct"]))
            for r in rows
        ]
    except Exception as e:
        warn(f"БД недоступна (категорії Розетки): {e}")
        return []


# ─── Feed loading ──────────────────────────────────────────────────────────────

def load_feed_bytes(url_or_path, fmt):
    if url_or_path.startswith("http"):
        import requests
        info("Завантажую з URL...")
        r = requests.get(url_or_path, timeout=120)
        r.raise_for_status()
        return r.content
    else:
        with open(url_or_path, "rb") as f:
            return f.read()


def parse_xml_bytes(content, fmt):
    if fmt == "zip_xml":
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            xml_names = [n for n in zf.namelist() if n.lower().endswith(".xml")]
            if not xml_names:
                raise ValueError("Не знайдено XML у ZIP-архіві")
            with zf.open(xml_names[0]) as f:
                return ET.parse(f).getroot()
    elif fmt == "xml":
        return ET.fromstring(content)
    else:
        raise NotImplementedError(f"Формат {fmt} потребує openpyxl — запустіть на ноутбуці")


def detect_structure(root):
    """Повертає dict з метаінформацією про структуру XML."""
    # Katran / generic <products><product>
    products_el = root.find("products")
    if products_el is None and root.tag in ("products", "price"):
        products_el = root
    if products_el is not None:
        products = products_el.findall("product")
        if products:
            sample = products[0]
            fields = sorted({c.tag for c in sample})
            cats = {}
            for p in products[:300]:
                cid   = (p.findtext("categoryId") or p.findtext("category_id") or "").strip()
                cname = cid
                if cid and cid not in cats:
                    cats[cid] = cname
            # Try to get category names from <categories> block
            cats_el = root.find("categories")
            if cats_el is None and products_el is not None:
                cats_el = root.find(".//categories")
            if cats_el is not None:
                for c in cats_el.findall("category"):
                    cid = c.get("id", "")
                    if cid:
                        cats[cid] = c.text or cid
            return {
                "style": "katran",
                "product_tag": "product",
                "count": len(products),
                "fields": fields,
                "categories": cats,
                "sample": sample,
            }

    # YML catalog (Prom / Rozetka)
    offers_el = root.find(".//offers")
    if offers_el is not None:
        offers = offers_el.findall("offer")
        cats = {}
        cats_el = root.find(".//categories")
        if cats_el is not None:
            for c in cats_el.findall("category"):
                cats[c.get("id", "")] = c.text or ""
        sample = offers[0] if offers else None
        fields = sorted({c.tag for c in sample}) if sample else []
        return {
            "style": "yml",
            "product_tag": "offer",
            "count": len(offers),
            "fields": fields,
            "categories": cats,
            "sample": sample,
        }

    # Generic fallback
    first_tag = next((c.tag for c in root), None)
    if first_tag:
        items = root.findall(first_tag)
        sample = items[0] if items else None
        fields = sorted({c.tag for c in sample}) if sample else []
        return {
            "style": "generic",
            "product_tag": first_tag,
            "count": len(items),
            "fields": fields,
            "categories": {},
            "sample": sample,
        }

    raise ValueError(f"Не вдалося визначити структуру XML (root: <{root.tag}>)")


# ─── XML generator ─────────────────────────────────────────────────────────────

def xml_escape(text):
    return (str(text)
            .replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def parse_float(text):
    try:
        return float(str(text or "0").replace(",", ".").strip())
    except (ValueError, TypeError):
        return 0.0


def calc_price(price_rrc, commission_pct):
    if price_rrc <= 0:
        return 0
    return int(math.ceil(price_rrc * (1 + commission_pct / 100) / 10) * 10)


def is_in_stock(s):
    s = (s or "").lower().strip()
    return s.startswith("е") or s.startswith("є") or s in ("true", "1", "yes", "in stock")


def generate_xml(root, struct, mappings, field_map, output_file, supplier_name):
    """Генерує YML-XML з довільного XML фіду."""
    DEFAULT_RZ_ID = "25636737"

    # collect products
    if struct["style"] == "katran":
        products_el = root.find("products")
        products = (products_el if products_el is not None else root).findall("product")
    elif struct["style"] == "yml":
        products = root.findall(".//offer")
    else:
        products = root.findall(struct["product_tag"])

    cats_used = {}
    offers_out = []
    seen_ids = set()
    skipped = 0

    for p in products:
        code    = (p.findtext(field_map.get("code", "code")) or
                   p.findtext("artikul") or p.findtext("id") or "").strip()
        name    = (p.findtext(field_map.get("name", "name")) or "").strip()
        vendor  = (p.findtext(field_map.get("vendor", "vendor")) or "").strip()
        stock_s = (p.findtext(field_map.get("stock", "stock")) or "").strip()
        cat_id  = (p.findtext(field_map.get("category_id", "categoryId")) or "").strip()

        price_field = field_map.get("price", "price_rrc")
        price_rrc   = parse_float(p.findtext(price_field) or p.findtext("price_rrc") or "0")

        if not code or not name or not is_in_stock(stock_s):
            skipped += 1
            continue
        if code in seen_ids:
            skipped += 1
            continue
        seen_ids.add(code)

        mapping    = mappings.get(cat_id, {})
        rz_id      = mapping.get("rz_id", DEFAULT_RZ_ID)
        commission = mapping.get("commission", 7.0)
        rz_name    = mapping.get("rz_name", "Ручний інструмент")

        price = calc_price(price_rrc, commission)
        if price <= 0:
            skipped += 1
            continue

        if not vendor or vendor.lower() in ("no name", "noname", "no-name", "unknown"):
            vendor = "Без бренду"

        # photos
        pics = []
        imgs_el = p.find(field_map.get("images", "images"))
        if imgs_el is not None:
            for img in imgs_el:
                url = (img.text or img.get("url") or "").strip()
                if url.startswith("http"):
                    pics.append(url)
        elif p.findtext("image"):
            url = p.findtext("image").strip()
            if url.startswith("http"):
                pics.append(url)

        desc = re.sub(r"https?://\S+", "", (p.findtext(field_map.get("description", "description")) or "")).strip()
        warranty = (p.findtext(field_map.get("warranty", "warranty")) or "").strip()
        stock_qty = max(int(parse_float(p.findtext("stock_quantity") or "1")), 1)

        if rz_id not in cats_used:
            cats_used[rz_id] = rz_name

        lines = [f'      <offer id="{xml_escape(code)}" available="true">']
        lines.append(f"        <price>{price}</price>")
        lines.append("        <currencyId>UAH</currencyId>")
        lines.append(f"        <categoryId>{rz_id}</categoryId>")
        for pic in pics[:10]:
            lines.append(f"        <picture>{pic}</picture>")
        lines.append(f"        <vendor>{xml_escape(vendor)}</vendor>")
        lines.append(f"        <article>{xml_escape(code)}</article>")
        lines.append(f"        <stock_quantity>{stock_qty}</stock_quantity>")
        lines.append(f"        <name_ua>{xml_escape(name[:255])}</name_ua>")
        if desc:
            lines.append(f"        <description_ua><![CDATA[<p>{xml_escape(desc[:2000])}</p>]]></description_ua>")
        lines.append(f'        <param name="Бренд">{xml_escape(vendor)}</param>')
        if warranty and warranty != "0":
            lines.append(f'        <param name="Гарантія">{xml_escape(warranty)} міс</param>')
        lines.append(f'        <param name="Артикул">{xml_escape(code)}</param>')
        lines.append("      </offer>")
        offers_out.append("\n".join(lines))

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    xml_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<yml_catalog date="{now}">',
        "  <shop>",
        f"    <name>{xml_escape(supplier_name)}</name>",
        "    <company>FOP Oliinyk Serhii</company>",
        "    <url>https://seller.rozetka.com.ua/</url>",
        "    <currencies><currency id=\"UAH\" rate=\"1\"/></currencies>",
        "    <categories>",
    ] + [
        f'      <category id="{rid}">{xml_escape(rname)}</category>'
        for rid, rname in cats_used.items()
    ] + [
        "    </categories>",
        "    <offers>",
    ] + offers_out + [
        "    </offers>",
        "  </shop>",
        "</yml_catalog>",
    ]

    os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("\n".join(xml_lines))

    return {"total": len(offers_out), "skipped": skipped, "categories": len(cats_used)}


# ─── Wizard ────────────────────────────────────────────────────────────────────

class SupplierOnboarding:

    def __init__(self, supplier_code=None, no_color=False):
        if no_color or not sys.stdout.isatty():
            C.disable()
        self.state = {}
        self.progress_file = None
        if supplier_code:
            self.progress_file = f"{PROGRESS_DIR}/onboarding_{supplier_code}.json"
            self._load_progress()

    # ── persistence ──────────────────────────────────────────────────────────────

    def _load_progress(self):
        if self.progress_file and os.path.exists(self.progress_file):
            with open(self.progress_file) as f:
                self.state = json.load(f)
            done = self.state.get("completed_steps", [])
            if done:
                warn(f"Знайдено прогрес — завершено кроки: {done}")

    def _save(self):
        if not self.progress_file:
            self.progress_file = f"{PROGRESS_DIR}/onboarding_{self.state.get('code','unknown')}.json"
        with open(self.progress_file, "w") as f:
            json.dump(self.state, f, ensure_ascii=False, indent=2)

    def _done(self, step):
        return step in self.state.get("completed_steps", [])

    def _mark_done(self, step):
        done = self.state.setdefault("completed_steps", [])
        if step not in done:
            done.append(step)
        self._save()

    # ── UI ───────────────────────────────────────────────────────────────────────

    def header(self, step, title):
        bar = "─" * 56
        print(f"\n{C.BOLD}{C.BLUE}┌{bar}┐{C.RESET}")
        label = f"  КРОК {step}: {title}"
        print(f"{C.BOLD}{C.BLUE}│{label:<56}│{C.RESET}")
        print(f"{C.BOLD}{C.BLUE}└{bar}┘{C.RESET}\n")

    def prompt(self, text, default=None, required=True):
        hint = f" [{C.DIM}{default}{C.RESET}]" if default is not None else ""
        while True:
            val = input(f"  {C.CYAN}?{C.RESET} {text}{hint}: ").strip()
            if not val and default is not None:
                return default
            if val or not required:
                return val
            warn("Обов'язкове поле")

    def choose(self, text, options, default=None):
        opts_str = "/".join(
            f"{C.BOLD}{o.upper()}{C.RESET}" if o == default else o
            for o in options
        )
        while True:
            val = input(f"  {C.CYAN}?{C.RESET} {text} [{opts_str}]: ").strip().lower()
            if not val and default:
                return default
            if val in options:
                return val
            warn(f"Введіть одне з: {', '.join(options)}")

    def confirm(self, text, default="y"):
        hint = "Y/n" if default == "y" else "y/N"
        val = input(f"  {C.CYAN}?{C.RESET} {text} [{hint}]: ").strip().lower()
        return (val in ("y", "yes", "т", "так")) if val else (default == "y")

    # ── STEP 1: Basic info ──────────────────────────────────────────────────────

    def step1_basic_info(self):
        if self._done(1):
            ok(f"Крок 1 пропущено: {self.state.get('name')} ({self.state.get('code')})")
            return

        self.header(1, "Базова інформація")

        name    = self.prompt("Назва постачальника (напр. Катран)",   self.state.get("name"))
        code    = self.prompt("Код (латиниця, без пробілів)",         self.state.get("code"))
        code    = re.sub(r"[^a-z0-9_]", "_", code.lower())
        feed    = self.prompt("URL фіду або шлях до файлу",           self.state.get("feed_url"))
        fmt     = self.choose("Формат фіду", ["xml","zip_xml","xls","xlsx"],
                              default=self.state.get("feed_format", "xml"))
        market  = self.choose("Маркетплейс", ["rozetka","epicentr","prom","all"],
                              default=self.state.get("marketplace", "rozetka"))

        self.state.update({
            "name": name, "code": code,
            "feed_url": feed, "feed_format": fmt, "marketplace": market,
        })
        self.progress_file = f"{PROGRESS_DIR}/onboarding_{code}.json"
        self._mark_done(1)
        ok(f"Збережено: {name} ({code}), формат={fmt}, маркетплейс={market}")

    # ── STEP 2: Analyze feed ────────────────────────────────────────────────────

    def step2_analyze_feed(self):
        if self._done(2):
            ok(f"Крок 2 пропущено — {self.state.get('products_count','?')} товарів, "
               f"{len(self.state.get('categories',{}))} категорій")
            return

        self.header(2, "Аналіз фіду")

        fmt = self.state["feed_format"]
        if fmt in ("xls", "xlsx"):
            warn(f"Формат {fmt} потребує openpyxl (тільки на ноутбуці з AVX).")
            if not self.confirm("Продовжити без автоматичного аналізу?", default="n"):
                sys.exit(0)
            self.state.update({"products_count": 0, "categories": {}, "field_map": {}})
            self._mark_done(2)
            return

        info(f"Завантажую фід...")
        try:
            content = load_feed_bytes(self.state["feed_url"], fmt)
            ok(f"Завантажено {len(content):,} байт")
        except Exception as e:
            err(f"Помилка завантаження: {e}")
            sys.exit(1)

        info("Аналізую структуру XML...")
        try:
            root   = parse_xml_bytes(content, fmt)
            struct = detect_structure(root)
        except Exception as e:
            err(f"Помилка парсингу: {e}")
            sys.exit(1)

        print(f"\n  {C.BOLD}Виявлена структура:{C.RESET}")
        print(f"    Стиль    : {C.GREEN}{struct['style']}{C.RESET}")
        print(f"    Товарів  : {C.GREEN}{struct['count']:,}{C.RESET}")
        print(f"    Поля     : {', '.join(struct['fields'][:15])}")
        print(f"    Категорій: {len(struct['categories'])}")

        if struct["categories"]:
            print(f"\n  {C.BOLD}Перші 10 категорій постачальника:{C.RESET}")
            for i, (cid, cname) in enumerate(list(struct["categories"].items())[:10]):
                print(f"    {C.DIM}{cid:>10}{C.RESET}  {cname}")

        if struct["sample"] is not None:
            print(f"\n  {C.BOLD}Приклад товару (перші поля):{C.RESET}")
            for child in list(struct["sample"])[:10]:
                val = (child.text or "").strip()[:70]
                if val:
                    print(f"    {C.DIM}{child.tag:<22}{C.RESET} {val}")

        if not self.confirm("\n  Структура розпізнана правильно?"):
            warn("Перевірте URL / формат і запустіть знову")
            sys.exit(0)

        # Field mapping
        print(f"\n  {C.BOLD}Маппінг полів (Enter = залишити пропозицію):{C.RESET}")
        fields = struct["fields"]

        def auto(candidates, fallback):
            return next((f for f in candidates if f in fields), fallback)

        field_map = {
            "code":        self.prompt("  Артикул/code",     auto(["artikul","article","code","id","sku"], "code"), required=False) or "code",
            "name":        self.prompt("  Назва/name",       auto(["name","title","name_ua"], "name"), required=False) or "name",
            "vendor":      self.prompt("  Бренд/vendor",     auto(["vendor","brand","manufacturer"], "vendor"), required=False) or "vendor",
            "stock":       self.prompt("  Наявність/stock",  auto(["stock","availability","instock"], "stock"), required=False) or "stock",
            "category_id": self.prompt("  Категорія ID",     auto(["categoryId","category_id","category"], "categoryId"), required=False) or "categoryId",
            "price":       self.prompt("  Ціна RRC",         auto(["price_rrc","rrc","price","price_pdv"], "price_rrc"), required=False) or "price_rrc",
            "images":      self.prompt("  Фото/images",      auto(["images","photos","pictures"], "images"), required=False) or "images",
            "description": self.prompt("  Опис",             auto(["description","desc"], "description"), required=False) or "description",
            "warranty":    self.prompt("  Гарантія",         auto(["warranty","guarantee"], "warranty"), required=False) or "warranty",
        }

        self.state.update({
            "products_count": struct["count"],
            "categories":     struct["categories"],
            "field_map":      field_map,
            "feed_style":     struct["style"],
        })
        self._mark_done(2)
        ok(f"Аналіз завершено: {struct['count']:,} товарів, {len(struct['categories'])} категорій")

    # ── STEP 3: Category mapping ────────────────────────────────────────────────

    def step3_category_mapping(self):
        if self._done(3):
            mapped = sum(1 for v in self.state.get("mappings", {}).values() if v.get("rz_id") != "25636737")
            ok(f"Крок 3 пропущено — {mapped} категорій змапповано в реальні rz_id")
            return

        self.header(3, "Маппінг категорій")

        supplier_cats = self.state.get("categories", {})
        if not supplier_cats:
            warn("Немає категорій — пропускаю")
            self.state["mappings"] = {}
            self._mark_done(3)
            return

        info("Завантажую категорії Розетки з БД...")
        rz_cats = get_rozetka_categories()
        if not rz_cats:
            warn("Категорії Розетки не знайдені — використовуватиму DEFAULT (25636737)")
            rz_cats = [("25636737", "Ручний інструмент", 7.0)]
        else:
            ok(f"Знайдено {len(rz_cats)} унікальних категорій Розетки в БД")

        def best_matches(query):
            q = query.lower()
            q_words = set(q.split())
            scored = []
            for rz_id, rz_name, commission in rz_cats:
                n = rz_name.lower()
                n_words = set(n.split())
                seq_score  = SequenceMatcher(None, q, n).ratio()
                word_score = len(q_words & n_words) / max(len(q_words), 1)
                scored.append((rz_id, rz_name, max(seq_score, word_score * 0.85), commission))
            scored.sort(key=lambda x: -x[2])
            return scored[:3]

        mappings  = self.state.get("mappings", {})
        remaining = [(cid, cn) for cid, cn in supplier_cats.items() if cid not in mappings]
        total     = len(supplier_cats)

        print(f"\n  {C.BOLD}Маппінг {total} категорій постачальника → Розетка:{C.RESET}")
        if total > len(remaining):
            info(f"Вже змапповано: {total - len(remaining)}, залишилось: {len(remaining)}")
        print(f"  {C.DIM}Enter=#1  2/3=варіант  0=DEFAULT  числовий rz_id=вручну{C.RESET}\n")

        auto_threshold = 0.0
        if len(remaining) > 20:
            if self.confirm(f"  Категорій багато ({len(remaining)}). Авто-приймати оцінку ≥ 0.7?"):
                auto_threshold = 0.7

        for i, (cat_id, cat_name) in enumerate(remaining, 1):
            matches = best_matches(cat_name)
            b_id, b_name, b_score, b_comm = matches[0]

            print(f"  [{i}/{len(remaining)}] {C.BOLD}{cat_name}{C.RESET}  (id={cat_id})")

            if auto_threshold and b_score >= auto_threshold:
                print(f"    {C.GREEN}→ авто: {b_name} ({b_id}) [{b_score:.2f}]{C.RESET}")
                mappings[cat_id] = {
                    "supplier_name": cat_name,
                    "rz_id": b_id, "rz_name": b_name, "commission": b_comm,
                }
                if i % 15 == 0:
                    self.state["mappings"] = mappings
                    self._save()
                continue

            for j, (rid, rname, score, comm) in enumerate(matches, 1):
                sc = C.GREEN if score >= 0.6 else (C.YELLOW if score >= 0.3 else C.RED)
                print(f"    {j}. {rname} ({rid}) {sc}[{score:.2f}]{C.RESET} комісія={comm}%")

            val = input(f"    {C.CYAN}→{C.RESET} [Enter/2/3/0/rz_id]: ").strip()

            if val in ("", "1"):
                ch_id, ch_name, ch_comm = b_id, b_name, b_comm
            elif val == "2" and len(matches) >= 2:
                ch_id, ch_name, ch_comm = matches[1][0], matches[1][1], matches[1][3]
            elif val == "3" and len(matches) >= 3:
                ch_id, ch_name, ch_comm = matches[2][0], matches[2][1], matches[2][3]
            elif val == "0":
                ch_id, ch_name, ch_comm = "25636737", "Ручний інструмент", 7.0
            elif re.match(r"^\d{5,}$", val):
                ch_id    = val
                found    = next(((n, c) for rid, n, c in rz_cats if rid == val), None)
                ch_name  = found[0] if found else val
                ch_comm  = found[1] if found else 7.0
            else:
                ch_id, ch_name, ch_comm = b_id, b_name, b_comm

            comm_in = input(f"    {C.CYAN}?{C.RESET} Комісія [{C.DIM}{ch_comm}%{C.RESET}]: ").strip()
            if comm_in:
                try:
                    ch_comm = float(comm_in)
                except ValueError:
                    pass

            mappings[cat_id] = {
                "supplier_name": cat_name,
                "rz_id": ch_id, "rz_name": ch_name, "commission": ch_comm,
            }

            if i % 5 == 0:
                self.state["mappings"] = mappings
                self._save()

        self.state["mappings"] = mappings
        mapped_real = sum(1 for v in mappings.values() if v.get("rz_id") != "25636737")
        self._mark_done(3)
        ok(f"Маппінг завершено: {mapped_real}/{total} категорій в реальних rz_id")

    # ── STEP 4: Generate XML ────────────────────────────────────────────────────

    def step4_generate_xml(self):
        if self._done(4):
            ok(f"Крок 4 пропущено — XML: {self.state.get('output_xml')}")
            return

        self.header(4, "Генерація XML")

        fmt       = self.state["feed_format"]
        code      = self.state["code"]
        mappings  = self.state.get("mappings", {})
        field_map = self.state.get("field_map", {})
        out_file  = os.path.join(REPO_ROOT, "data", f"{code}_rozetka.xml")

        info("Завантажую фід для генерації XML...")
        content = load_feed_bytes(self.state["feed_url"], fmt)
        root    = parse_xml_bytes(content, fmt)
        struct  = detect_structure(root)

        info(f"Генерую {out_file}...")
        stats = generate_xml(root, struct, mappings, field_map, out_file, self.state["name"])

        print(f"\n  {C.BOLD}Результат:{C.RESET}")
        ok(f"Офферів:   {stats['total']}")
        ok(f"Категорій: {stats['categories']}")
        info(f"Пропущено: {stats['skipped']} (немає в наявності / ціна=0 / дублі)")
        ok(f"Збережено: {out_file}")

        self.state["output_xml"]  = out_file
        self.state["xml_stats"]   = stats
        self._mark_done(4)

    # ── STEP 5: Validate ────────────────────────────────────────────────────────

    def step5_validate(self):
        if self._done(5):
            ok("Крок 5 пропущено — валідація вже виконана")
            return

        self.header(5, "Валідація XML")

        xml_path = self.state.get("output_xml")
        if not xml_path or not os.path.exists(xml_path):
            err("XML файл не знайдено. Спочатку виконайте крок 4.")
            sys.exit(1)

        info("Запускаю tools/rozetka_xml_validator.py...")
        print()
        result = subprocess.run([sys.executable, VALIDATOR, "--no-xlsx", xml_path])
        print()

        self.state["validation_ok"] = result.returncode == 0
        self._mark_done(5)

        if result.returncode == 0:
            ok("Валідація успішна — немає структурних помилок")
        else:
            warn("Є структурні помилки (деталі вище)")

    # ── STEP 6: Save to DB ──────────────────────────────────────────────────────

    def step6_save_to_db(self):
        if self._done(6):
            ok("Крок 6 пропущено — дані вже в БД")
            return

        self.header(6, "Збереження в базу даних")

        try:
            ensure_tables()
        except Exception as e:
            warn(f"БД недоступна: {e}. Пропускаю крок 6.")
            self._mark_done(6)
            return

        code     = self.state["code"]
        mappings = self.state.get("mappings", {})

        try:
            conn = get_db()
            cur  = conn.cursor()

            cur.execute("""
                INSERT INTO suppliers (code, name, feed_url, feed_format, marketplace, status)
                VALUES (%s, %s, %s, %s, %s, 'active')
                ON CONFLICT (code) DO UPDATE SET
                    name=EXCLUDED.name, feed_url=EXCLUDED.feed_url,
                    feed_format=EXCLUDED.feed_format, marketplace=EXCLUDED.marketplace
            """, (code, self.state["name"], self.state["feed_url"],
                  self.state["feed_format"], self.state["marketplace"]))
            ok(f"suppliers: '{self.state['name']}' ({code}) збережено")

            saved = 0
            for cat_id, m in mappings.items():
                cur.execute("""
                    INSERT INTO supplier_category_map
                        (supplier_code, supplier_category_id, supplier_category_name,
                         rz_id, rz_name, commission_pct)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (supplier_code, supplier_category_id) DO UPDATE SET
                        rz_id=EXCLUDED.rz_id, rz_name=EXCLUDED.rz_name,
                        commission_pct=EXCLUDED.commission_pct
                """, (code, cat_id, m.get("supplier_name",""),
                      m.get("rz_id","25636737"), m.get("rz_name",""),
                      m.get("commission", 7.0)))
                saved += 1

            conn.commit()
            cur.close()
            conn.close()
            ok(f"supplier_category_map: {saved} маппінгів збережено")

        except Exception as e:
            err(f"Помилка запису в БД: {e}")

        self._mark_done(6)

    # ── STEP 7: Report ──────────────────────────────────────────────────────────

    def step7_report(self):
        self.header(7, "Підсумковий звіт")

        code      = self.state.get("code", "?")
        name      = self.state.get("name", "?")
        products  = self.state.get("products_count", 0)
        mappings  = self.state.get("mappings", {})
        xml_stats = self.state.get("xml_stats", {})
        out_xml   = self.state.get("output_xml", "?")
        val_ok    = self.state.get("validation_ok", False)

        mapped_real  = sum(1 for v in mappings.values() if v.get("rz_id") != "25636737")
        mapped_total = len(mappings)

        val_str = f"{C.GREEN}✓ OK{C.RESET}" if val_ok else f"{C.YELLOW}⚠ є попередження{C.RESET}"

        print(f"  {'─'*54}")
        print(f"  {C.BOLD}Постачальник   :{C.RESET} {name} ({code})")
        print(f"  {C.BOLD}Фід            :{C.RESET} {self.state.get('feed_url','?')[:52]}")
        print(f"  {C.BOLD}Товарів у фіді :{C.RESET} {products:,}")
        print(f"  {C.BOLD}Категорій      :{C.RESET} {mapped_real}/{mapped_total} в реальних rz_id")
        print(f"  {C.BOLD}Офферів у XML  :{C.RESET} {xml_stats.get('total','?')}")
        print(f"  {C.BOLD}XML файл       :{C.RESET} {out_xml}")
        print(f"  {C.BOLD}Валідація      :{C.RESET} {val_str}")
        print(f"  {'─'*54}")

        print(f"\n  {C.BOLD}{C.CYAN}Команди для подальшої роботи:{C.RESET}")
        print(f"  {C.DIM}# Продовжити onboarding з будь-якого кроку:{C.RESET}")
        print(f"    python3 tools/supplier_onboarding.py --resume {code} --step 3")
        print(f"\n  {C.DIM}# Запустити валідатор:{C.RESET}")
        print(f"    python3 tools/rozetka_xml_validator.py {out_xml}")
        print(f"\n  {C.DIM}# Повний pipeline Катрана (якщо постачальник = katran):{C.RESET}")
        print(f"    python3 tools/katran_pipeline.py --categories ALL --push")

        print(f"\n  {C.DIM}Прогрес збережено: {self.progress_file}{C.RESET}\n")

        self._mark_done(7)
        self._save()

    # ── Run ──────────────────────────────────────────────────────────────────────

    def run(self, start_from=1):
        steps = [
            self.step1_basic_info,
            self.step2_analyze_feed,
            self.step3_category_mapping,
            self.step4_generate_xml,
            self.step5_validate,
            self.step6_save_to_db,
            self.step7_report,
        ]
        for i, fn in enumerate(steps, 1):
            if i < start_from:
                continue
            fn()


# ─── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Wizard для підключення нового постачальника в дропшипінг-систему"
    )
    parser.add_argument(
        "--resume", metavar="CODE",
        help="Продовжити онбординг по коду постачальника (напр. katran)"
    )
    parser.add_argument(
        "--step", type=int, default=1, choices=range(1, 8),
        help="Почати з конкретного кроку 1-7"
    )
    parser.add_argument(
        "--no-color", action="store_true",
        help="Вимкнути кольоровий вивід (ANSI)"
    )
    args = parser.parse_args()

    print(f"\n{C.BOLD}{C.BLUE}{'='*58}{C.RESET}")
    print(f"{C.BOLD}{C.BLUE}  Supplier Onboarding Wizard — Dropshipping Agent System{C.RESET}")
    print(f"{C.BOLD}{C.BLUE}  Версія: 2026-06-07{C.RESET}")
    print(f"{C.BOLD}{C.BLUE}{'='*58}{C.RESET}")

    wizard = SupplierOnboarding(
        supplier_code=args.resume,
        no_color=args.no_color,
    )
    wizard.run(start_from=args.step)


if __name__ == "__main__":
    main()

````

### `tools/watchdog.py` — 265 рядків

````python
#!/usr/bin/env python3
"""
tools/watchdog.py — моніторинг здоров'я системи.

Запускається кожні 10 хвилин через cron:
  */10 * * * * cd /home/tek/agent-system && /home/tek/agent-system/venv/bin/python3 tools/watchdog.py >> /tmp/watchdog.log 2>&1

Перевіряє:
  1. Git uncommitted changes — авто-коміт локально (push — тільки розробник вручну)
  2. Crontab — правильні шляхи (cd /home/tek/agent-system)
  3. Сервіси systemd — перезапускає якщо впали
  4. rozetka_sync_cron.log — FAILED alert
  5. Telegram звіт кожні 6 годин
"""

import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

# ── config ───────────────────────────────────────────────────────────────────

REPO_DIR = "/home/tek/agent-system"
load_dotenv(dotenv_path=os.path.join(REPO_DIR, ".env"))

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TG_BOT_TOKEN")
CHAT_ID   = (
    os.getenv("TELEGRAM_ADMIN_ID")
    or os.getenv("TELEGRAM_CHAT_ID")
    or os.getenv("TG_CHAT_ID")
)

SERVICES        = ["rozetka-order-agent", "tg-dispatcher"]
REPORT_INTERVAL = timedelta(hours=6)
STATE_FILE      = "/tmp/watchdog_last_report.txt"
SYNC_LOG        = "/tmp/rozetka_sync_cron.log"
CRON_FLAG       = "/tmp/watchdog_cron_warned.flag"

CRON_CHECKS = [
    ("rozetka_github_sync.py", "cd /home/tek/agent-system"),
    ("price_updater.py",       "cd /home/tek/agent-system"),
    ("feed_sync.py",           "cd /home/tek/agent-system"),
]

# systemctl --user потребує XDG_RUNTIME_DIR в cron
_uid = os.getuid()
os.environ.setdefault("XDG_RUNTIME_DIR",        f"/run/user/{_uid}")
os.environ.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path=/run/user/{_uid}/bus")


# ── helpers ───────────────────────────────────────────────────────────────────

def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def run(cmd: str, cwd: str = REPO_DIR) -> tuple:
    """Returns (returncode, stdout, stderr)."""
    try:
        r = subprocess.run(
            cmd, shell=True, cwd=cwd,
            capture_output=True, text=True, timeout=60,
        )
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return 1, "", "timeout"
    except Exception as e:
        return 1, "", str(e)


def tg(msg: str):
    if not BOT_TOKEN or not CHAT_ID:
        log(f"[tg] не налаштовано BOT_TOKEN/CHAT_ID")
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception as e:
        log(f"[tg] помилка: {e}")


# ── check 1: git ──────────────────────────────────────────────────────────────

def check_git() -> dict:
    rc, stdout, _ = run("git status --porcelain")
    if rc != 0:
        return {"ok": False, "msg": "git status failed"}

    if not stdout:
        log("[git] репо чисте")
        return {"ok": True, "msg": "clean"}

    changed = len(stdout.splitlines())
    log(f"[git] {changed} змінених файлів — авто-коміт...")

    ts  = datetime.now().strftime("%Y-%m-%d %H:%M")
    rc2, _, err2 = run(f'git add -A && git commit -m "auto: watchdog sync {ts}"')
    if rc2 != 0:
        log(f"[git] commit failed: {err2}")
        return {"ok": False, "msg": f"commit failed: {err2[:80]}"}

    # Push виконує тільки розробник вручну — watchdog лише комітить локально
    log(f"[git] авто-коміт (без push): {changed} файлів")
    return {"ok": True, "msg": f"auto-committed {changed} files (no push)"}


# ── check 2: crontab ──────────────────────────────────────────────────────────

def check_cron() -> dict:
    rc, crontab, _ = run("crontab -l")
    if rc != 0:
        return {"ok": True, "msg": "no crontab"}

    issues = []
    for script, required in CRON_CHECKS:
        lines = [
            l for l in crontab.splitlines()
            if script in l and not l.strip().startswith("#")
        ]
        for line in lines:
            if required not in line:
                issues.append(f"{script} — відсутній '{required}'")
                log(f"[cron] WARN: {script} не має '{required}'")

    if issues:
        if not os.path.exists(CRON_FLAG):
            tg("⚠️ <b>Watchdog cron</b>: некоректні шляхи\n" + "\n".join(issues))
            Path(CRON_FLAG).write_text(str(time.time()))
        return {"ok": False, "msg": "; ".join(issues)}

    if os.path.exists(CRON_FLAG):
        os.remove(CRON_FLAG)
    log("[cron] всі шляхи OK")
    return {"ok": True, "msg": "ok"}


# ── check 3: services ─────────────────────────────────────────────────────────

def check_services() -> dict:
    statuses   = {}
    restarted  = []
    failed     = []

    for svc in SERVICES:
        rc, out, _ = run(f"systemctl --user is-active {svc}")
        active = out.strip() == "active"
        statuses[svc] = active

        if not active:
            log(f"[svc] {svc} не активний ('{out}') — перезапускаю...")
            rc2, _, err2 = run(f"systemctl --user restart {svc}")
            if rc2 == 0:
                restarted.append(svc)
                log(f"[svc] {svc} перезапущено")
                tg(f"⚠️ <b>Watchdog</b>: <code>{svc}</code> впав — перезапущено ✅")
            else:
                failed.append(svc)
                log(f"[svc] {svc} НЕ вдалось перезапустити: {err2}")
                tg(f"🚨 <b>ALARM Watchdog</b>: <code>{svc}</code> не запускається!\n<code>{err2[:200]}</code>")

    all_ok = not failed
    return {"ok": all_ok, "services": statuses, "restarted": restarted, "failed": failed}


# ── check 4: sync log ─────────────────────────────────────────────────────────

def check_sync_log() -> dict:
    if not os.path.exists(SYNC_LOG):
        return {"ok": True, "msg": "no log yet"}

    try:
        lines = Path(SYNC_LOG).read_text(errors="replace").splitlines()
        lines = [l.strip() for l in lines if l.strip()]
        if not lines:
            return {"ok": True, "msg": "empty"}

        last = lines[-1]
        if "FAILED" in last.upper() or ("ERROR" in last.upper() and "WARNING" not in last.upper()):
            log(f"[sync] FAILED виявлено: {last}")
            tg(f"🚨 <b>Watchdog</b>: rozetka_sync_cron FAILED!\n<code>{last[:200]}</code>")
            return {"ok": False, "msg": last[:80]}

        return {"ok": True, "msg": last[:80]}
    except Exception as e:
        return {"ok": True, "msg": f"read error: {e}"}


# ── report every 6h ───────────────────────────────────────────────────────────

def should_report() -> bool:
    if not os.path.exists(STATE_FILE):
        return True
    try:
        last = float(Path(STATE_FILE).read_text().strip())
        return (time.time() - last) >= REPORT_INTERVAL.total_seconds()
    except Exception:
        return True


def save_report_ts():
    Path(STATE_FILE).write_text(str(time.time()))


def send_report(git_r: dict, svc_r: dict, cron_r: dict, sync_r: dict):
    ts = datetime.now().strftime("%d.%m %H:%M")

    svc_parts  = [f"{'✅' if active else '❌'} {svc}" for svc, active in svc_r.get("services", {}).items()]
    git_ok     = git_r["ok"]
    sync_ok    = sync_r["ok"]
    svc_ok     = svc_r["ok"]
    all_ok     = svc_ok and git_ok and sync_ok and cron_r["ok"]

    if all_ok:
        status_line = "  ".join(svc_parts) + ("  ✅ sync" if sync_ok else "  ❌ sync")
        msg = f"🔔 <b>Watchdog OK</b> [{ts}]\n{status_line}"
    else:
        problems = []
        for svc, active in svc_r.get("services", {}).items():
            if not active:
                problems.append(f"❌ {svc}")
        if not git_ok:
            problems.append(f"❌ git sync ({git_r['msg'][:40]})")
        if not sync_ok:
            problems.append(f"❌ rozetka sync ({sync_r['msg'][:40]})")
        if not cron_r["ok"]:
            problems.append(f"⚠️ cron ({cron_r['msg'][:40]})")
        msg = f"🚨 <b>Watchdog</b> [{ts}]\n" + "\n".join(problems)

    save_report_ts()
    tg(msg)
    log(f"[report] 6h звіт ({'OK' if all_ok else 'PROBLEMS'}) відправлено в Telegram")


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    log("=== Watchdog START ===")

    git_r  = check_git()
    cron_r = check_cron()
    svc_r  = check_services()
    sync_r = check_sync_log()

    log(f"[git]  ok={git_r['ok']}  {git_r['msg']}")
    log(f"[cron] ok={cron_r['ok']} {cron_r['msg']}")
    log(f"[svc]  ok={svc_r['ok']}  {svc_r.get('services')}")
    log(f"[sync] ok={sync_r['ok']} {sync_r['msg']}")

    if should_report():
        send_report(git_r, svc_r, cron_r, sync_r)

    log("=== Watchdog END ===")


if __name__ == "__main__":
    main()

````

### `tools/web_api_explorer.py` — 908 рядків

````python
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
const QUICK = {{ quick_json | safe }};
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
  const bases = {{ base_urls_json | safe }};
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
  const btn = event.target;
  const orig = btn.textContent;
  try {
    if (navigator.clipboard && location.protocol === 'https:') {
      navigator.clipboard.writeText(text).then(() => {
        btn.textContent = '✅ Скопійовано';
        setTimeout(() => btn.textContent = orig, 2000);
      });
    } else {
      const t = document.createElement('textarea');
      t.value = text; document.body.appendChild(t); t.select();
      document.execCommand('copy'); document.body.removeChild(t);
      btn.textContent = '✅ Скопійовано';
      setTimeout(() => btn.textContent = orig, 2000);
    }
  } catch(e) {
    btn.textContent = orig;
  }
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

````

### `epicentr_postprocess.py` — 56 рядків

````python
import re, os

src = 'exports/carvol_epicentr_new.xml'
dst = 'exports/carvol_epicentr.xml'

with open(src, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Фільтр фото + розбивка на офери
header, rest = content.split('<offers>', 1)
body, footer = rest.rsplit('</offers>', 1)

offers_raw = re.findall(r'<offer[^>]*>.*?</offer>', body, re.DOTALL)
print('Всього офферів:', len(offers_raw))

# 2. Залишаємо тільки з фото
with_photo = [o for o in offers_raw if '<picture>' in o]
print('З фото:', len(with_photo))

# 3. Замінюємо 2883 → 2848
fixed = []
for o in with_photo:
    o = o.replace('code="2883">LED-світло для автомобіля', 'code="2848">Аксесуари для автосигналізацій')
    fixed.append(o)

# 4. Дедупліація по id
seen_ids = set()
deduped = []
for o in fixed:
    m = re.search(r'<offer id="([^"]+)"', o)
    if m:
        oid = m.group(1)
        if oid not in seen_ids:
            seen_ids.add(oid)
            deduped.append(o)
print('Після дедуп:', len(deduped), '(видалено дублів:', len(fixed) - len(deduped), ')')

# 5. Обрізаємо назви > 150 символів
result = []
for o in deduped:
    def trim_name(m):
        tag, text, close = m.group(1), m.group(2), m.group(3)
        if len(text) > 150:
            text = text[:147] + '...'
        return tag + text + close
    o = re.sub(r'(<name[^>]*>)([^<]{151,})(</name>)', trim_name, o)
    result.append(o)

# 6. Виправляємо подвійне закриття в кінці
new_content = header + '<offers>\n' + '\n'.join(result) + '\n</offers>\n</yml_catalog>'

with open(dst, 'w', encoding='utf-8') as f:
    f.write(new_content)

size_mb = os.path.getsize(dst) / 1024 / 1024
print('Збережено:', dst, '(%d KB)' % (size_mb * 1024))

````

### `agents/orders/epicentr_xml_generator.py` — 398 рядків

````python
"""
agents/orders/epicentr_xml_generator.py
==========================================
Генератор XML для імпорту товарів в Єпіцентр.

Формат: yml_catalog (власний формат Єпіцентру, НЕ Prom/Rozetka)
Документація: template (5).xml від Євгенія Тамбовського

Структура XML:
  <offer id="SKU" available="true">
    <price>ціна</price>
    <category code="ID">Назва</category>
    <attribute_set code="ID">Назва</attribute_set>
    <name lang="ua">Назва УА</name>
    <name lang="ru">Назва РУ</name>
    <picture>URL</picture>
    <description lang="ua">Опис</description>
    <vendor code="hash">TOPTUL</vendor>
    <country_of_origin code="twn">Тайвань</country_of_origin>
    <param paramcode="measure" valuecode="measure_pcs">шт.</param>
    <param paramcode="ratio">1</param>
    <param paramcode="brand">TOPTUL</param>
    <width>0</width>
    <height>0</height>
  </offer>

Запуск:
    # Всі товари (один XML файл)
    python3 epicentr_xml_generator.py --output /tmp/epicentr_import.xml

    # По категоріях (окремий файл на кожну)
    python3 epicentr_xml_generator.py --by-category --output-dir /tmp/epicentr_xml/

    # Тільки топ категорії
    python3 epicentr_xml_generator.py --limit 100 --output /tmp/epicentr_test.xml
"""

import os, sys, xml.etree.ElementTree as ET
from xml.dom import minidom
from datetime import datetime
from loguru import logger

sys.path.append('/home/tek/agent-system')
from dotenv import load_dotenv; load_dotenv('/home/tek/agent-system/.env')
from shared.utils.db import get_connection

# =============================================
# КОНСТАНТИ
# =============================================

# Фіксовані значення для всіх TOPTUL товарів
VENDOR_NAME = 'TOPTUL'
VENDOR_CODE = 'bj0nbzkpfibrajom'
COUNTRY_NAME_UA = 'Тайвань'
COUNTRY_NAME_RU = 'Тайвань'
COUNTRY_CODE = 'twn'

# Обов'язкові param для всіх категорій інструментів
COMMON_PARAMS = [
    # paramcode, valuecode, name_ua, value_ua, is_cdata
    ('measure', 'measure_pcs', 'Міра виміру та кількість', 'шт.', False),
    ('ratio',   None,          'Мінімальна кратність товару', '1', True),
    ('brand',   'bj0nbzkpfibrajom', 'Бренд', 'TOPTUL', False),
    ('country_of_origin', 'twn', 'Країна-виробник', 'Тайвань', False),
]

# Базові розміри якщо немає в БД
DEFAULT_WIDTH  = 0
DEFAULT_HEIGHT = 0
DEFAULT_WEIGHT = 0


# =============================================
# ЗАВАНТАЖЕННЯ ФІДУ TOPTUL (для фото і опису)
# =============================================

_feed_cache = {}

def load_feed_data() -> dict:
    """Завантажує фід TOPTUL для отримання фото і описів."""
    global _feed_cache
    if _feed_cache:
        return _feed_cache

    import requests, xml.etree.ElementTree as ET
    TOPTUL_FEED = (
        'https://toptul.online/products_feed.xml?'
        'hash_tag=442309995a1416e3104d287504a1846f'
        '&label_ids=3882792&html_description=1&languages=uk,ru'
    )
    try:
        logger.info('Завантажуємо фід TOPTUL для фото і описів...')
        resp = requests.get(TOPTUL_FEED, timeout=120)
        root = ET.fromstring(resp.content)
        for offer in root.find('shop').find('offers').findall('offer'):
            sku_el = offer.find('vendorCode')
            sku = (sku_el.text or '').strip().upper() if sku_el is not None else ''
            if not sku:
                continue

            # Фото
            pictures = [p.text for p in offer.findall('picture') if p.text]

            # Описи
            desc_ua = desc_ru = ''
            for desc in offer.findall('description'):
                lang = desc.get('lang', '')
                if lang == 'uk' or lang == 'ua':
                    desc_ua = (desc.text or '').strip()
                elif lang == 'ru':
                    desc_ru = (desc.text or '').strip()

            # Назви
            name_ua = name_ru = ''
            for name in offer.findall('name'):
                lang = name.get('lang', '')
                if lang == 'uk' or lang == 'ua':
                    name_ua = (name.text or '').strip()
                elif lang == 'ru':
                    name_ru = (name.text or '').strip()

            _feed_cache[sku] = {
                'pictures': pictures,
                'desc_ua': desc_ua,
                'desc_ru': desc_ru,
                'name_ua': name_ua,
                'name_ru': name_ru,
            }

        logger.success(f'Фід завантажено: {len(_feed_cache)} товарів')
    except Exception as e:
        logger.error(f'Помилка завантаження фіду: {e}')

    return _feed_cache


# =============================================
# ГЕНЕРАТОР XML
# =============================================

def generate_xml(
    output_path: str,
    category_filter: str = None,
    limit: int = None,
    confidence_filter: list = None
) -> int:
    """
    Генерує XML файл для імпорту в Єпіцентр.

    Args:
        output_path: шлях для збереження XML
        category_filter: фільтр по назві категорії
        limit: максимальна кількість товарів
        confidence_filter: список рівнів впевненості ['high','medium','low']

    Returns:
        Кількість товарів в XML
    """
    if confidence_filter is None:
        confidence_filter = ['high', 'medium', 'low']

    # Завантажуємо дані фіду
    feed = load_feed_data()

    # Отримуємо товари з БД
    conn = get_connection()
    cur  = conn.cursor()

    conditions = [
        'epicentr_category_id IS NOT NULL',
        'price_our > 0',
        f"epicentr_confidence IN ({','.join(['%s']*len(confidence_filter))})"
    ]
    params = list(confidence_filter)

    if category_filter:
        conditions.append('epicentr_category_name ILIKE %s')
        params.append(f'%{category_filter}%')

    sql = f'''
        SELECT
            mp.sku,
            mp.name_uk,
                mp.price_our,
            mp.price_supplier,
            mp.epicentr_category_id,
            mp.epicentr_category_name,
            mp.epicentr_confidence
        FROM my_products mp
        WHERE {' AND '.join(conditions)}
        ORDER BY mp.epicentr_category_name, mp.sku
    '''
    if limit:
        sql += f' LIMIT {limit}'

    cur.execute(sql, params)
    products = cur.fetchall()
    cur.close(); conn.close()

    logger.info(f'Генеруємо XML для {len(products)} товарів → {output_path}')

    # Будуємо XML
    root = ET.Element('yml_catalog')
    root.set('date', datetime.now().strftime('%Y-%m-%d %H:%M'))
    offers_el = ET.SubElement(root, 'offers')

    count = 0
    for p in products:
        sku      = p['sku']
        name_uk  = p['name_uk'] or sku
        name_ru  = name_uk  # немає окремої RU назви в БД
        price    = float(p['price_our'])
        cat_id   = str(p['epicentr_category_id'])
        cat_name = p['epicentr_category_name'] or ''

        # Дані з фіду
        feed_data = feed.get(sku.upper(), {})
        pictures  = feed_data.get('pictures', [])
        desc_ua   = feed_data.get('desc_ua', '')
        desc_ru   = feed_data.get('desc_ru', '')
        # Якщо є фідові назви — вони кращі
        if feed_data.get('name_ua'):
            name_uk = feed_data['name_ua']
        name_ru = feed_data.get('name_ru') or name_uk

        # offer елемент
        offer = ET.SubElement(offers_el, 'offer')
        offer.set('id', sku)
        offer.set('available', 'true')

        # Ціна
        price_el = ET.SubElement(offer, 'price')
        price_el.text = str(price)

        # Наявність (availability має пріоритет над available)
        avail_el = ET.SubElement(offer, 'availability')
        avail_el.text = 'in_stock'

        # Стара ціна (ціна фіду якщо більша)
        if p['price_supplier'] and float(p['price_supplier']) > price:
            old_el = ET.SubElement(offer, 'price_old')
            old_el.text = str(float(p['price_supplier']))

        # Категорія
        cat_el = ET.SubElement(offer, 'category')
        cat_el.set('code', cat_id)
        cat_el.text = cat_name

        # Набір атрибутів (той самий код що і категорія)
        attr_el = ET.SubElement(offer, 'attribute_set')
        attr_el.set('code', cat_id)
        attr_el.text = cat_name

        # Назви
        name_ua_el = ET.SubElement(offer, 'name')
        name_ua_el.set('lang', 'ua')
        name_ua_el.text = name_uk

        name_ru_el = ET.SubElement(offer, 'name')
        name_ru_el.set('lang', 'ru')
        name_ru_el.text = name_ru

        # Фото (max 10)
        for pic_url in pictures[:10]:
            if pic_url:
                pic_el = ET.SubElement(offer, 'picture')
                pic_el.text = pic_url

        # Описи
        if desc_ua:
            desc_ua_el = ET.SubElement(offer, 'description')
            desc_ua_el.set('lang', 'ua')
            desc_ua_el.text = desc_ua[:3000]  # обмеження

        if desc_ru:
            desc_ru_el = ET.SubElement(offer, 'description')
            desc_ru_el.set('lang', 'ru')
            desc_ru_el.text = desc_ru[:3000]

        # Виробник
        vendor_el = ET.SubElement(offer, 'vendor')
        vendor_el.set('code', VENDOR_CODE)
        vendor_el.text = VENDOR_NAME

        # Країна
        country_el = ET.SubElement(offer, 'country_of_origin')
        country_el.set('code', COUNTRY_CODE)
        country_el.text = COUNTRY_NAME_UA

        # Обов'язкові параметри
        for paramcode, valuecode, name, value, is_cdata in COMMON_PARAMS:
            param_el = ET.SubElement(offer, 'param')
            param_el.set('name', name)
            param_el.set('paramcode', paramcode)
            if valuecode:
                param_el.set('valuecode', valuecode)
            if is_cdata:
                param_el.text = value  # minidom загорне в CDATA якщо треба
            else:
                param_el.text = value

        # Габарити вже додані через COMMON_PARAMS як param

        count += 1

    # Форматуємо і зберігаємо
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)

    xml_str = ET.tostring(root, encoding='unicode', xml_declaration=False)
    # Красиве форматування
    pretty = minidom.parseString(
        '<?xml version="1.0" encoding="UTF-8"?>' + xml_str
    ).toprettyxml(indent='  ', encoding='UTF-8')

    with open(output_path, 'wb') as f:
        f.write(pretty)

    size_kb = os.path.getsize(output_path) // 1024
    logger.success(f'XML збережено: {output_path} ({count} товарів, {size_kb} KB)')
    return count


def generate_by_category(output_dir: str, confidence_filter: list = None) -> dict:
    """
    Генерує окремий XML файл для кожної категорії.
    Зручно для покрокового завантаження в кабінет.
    """
    os.makedirs(output_dir, exist_ok=True)

    conn = get_connection()
    cur  = conn.cursor()
    cur.execute('''
        SELECT epicentr_category_name, COUNT(*) as cnt
        FROM my_products
        WHERE epicentr_category_id IS NOT NULL
          AND price_our > 0
          AND epicentr_confidence IN ('high','medium','low')
        GROUP BY epicentr_category_name
        ORDER BY cnt DESC
    ''')
    categories = cur.fetchall()
    cur.close(); conn.close()

    results = {}
    for cat in categories:
        cat_name = cat['epicentr_category_name']
        safe_name = cat_name.replace('/', '_').replace(' ', '_')[:50]
        output_path = os.path.join(output_dir, f'{safe_name}.xml')

        count = generate_xml(
            output_path=output_path,
            category_filter=cat_name,
            confidence_filter=confidence_filter
        )
        results[cat_name] = {'count': count, 'file': output_path}

    logger.success(f'Згенеровано {len(results)} XML файлів → {output_dir}')
    return results


# =============================================
# CLI
# =============================================

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Генератор XML для Єпіцентру')
    parser.add_argument('--output', type=str, default='/tmp/epicentr_import.xml',
                       help='Шлях для збереження XML')
    parser.add_argument('--output-dir', type=str,
                       help='Папка для XML файлів по категоріях')
    parser.add_argument('--by-category', action='store_true',
                       help='Генерувати окремий файл на кожну категорію')
    parser.add_argument('--category', type=str,
                       help='Фільтр по назві категорії')
    parser.add_argument('--limit', type=int,
                       help='Максимальна кількість товарів')
    parser.add_argument('--confidence', type=str, default='high,medium,low',
                       help='Рівні впевненості (high,medium,low)')
    args = parser.parse_args()

    confidence = [c.strip() for c in args.confidence.split(',')]

    if args.by_category:
        output_dir = args.output_dir or '/tmp/epicentr_xml'
        results = generate_by_category(output_dir, confidence)
        print(f'\nЗгенеровано категорій: {len(results)}')
        for cat, info in list(results.items())[:10]:
            print(f'  {info["count"]:4} товарів | {cat}')
    else:
        count = generate_xml(
            output_path=args.output,
            category_filter=args.category,
            limit=args.limit,
            confidence_filter=confidence
        )
        print(f'\n✅ XML готовий: {args.output} ({count} товарів)')
        print(f'Завантаж в Єпіцентр: Імпорт → Завантажити файл → вибрати XML')

````

### `agents/orders/rozetka_feed_sync.py` — 296 рядків

````python
"""
rozetka_feed_sync_v2.py
=======================
Генерує XML для Розетки:
1. Структура і категорії — з /data/carvol_rozetka.xml (пройшов перевірку Розетки)
2. Ціни і наявність — з Carvol Prom фіду (реальний час)
3. Комісія Розетки — по категоріях з БД
"""
import sys, os, requests, math
import xml.etree.ElementTree as ET
from xml.dom import minidom
from datetime import datetime
from loguru import logger
sys.path.append('/home/tek/agent-system')
from dotenv import load_dotenv; load_dotenv('/home/tek/agent-system/.env')
from shared.utils.db import get_connection

CARVOL_FEED = (
    'https://carvol.prom.ua/rozetka_feed.xml'
    '?rozetka_hash_tag=2251d0779efad97117ac08d7efd82c2f'
    '&product_ids=&label_ids=28618299&languages=uk%2Cru&group_ids='
)
TEMPLATE_PATH = '/home/tek/agent-system/data/carvol_rozetka.xml'
OUTPUT_PATH   = '/home/tek/agent-system/shared/feeds/rozetka_feed.xml'
TG_BOT_TOKEN  = os.getenv('TG_BOT_TOKEN')
TG_CHAT_ID    = os.getenv('TG_CHAT_ID')

# Комісії Розетки по нашим category_id (з тарифу)
# Автоелектроніка: 18% базова, знижується з ціною
# Автосвітло/запчастини: 13% базова
CPA_RULES = {
    '1':  [( 0,   5999, 0.18), (6000, 9999, 0.12), (10000, 19999, 0.07), (20000, 9e9, 0.05)],  # Камери
    '2':  [( 0,   5999, 0.18), (6000, 9999, 0.12), (10000, 19999, 0.07), (20000, 9e9, 0.05)],  # Штатні пристрої
    '3':  [( 0,   5999, 0.18), (6000, 9999, 0.12), (10000, 19999, 0.07), (20000, 9e9, 0.05)],  # Кабелі
    '4':  [( 0,   5999, 0.18), (6000, 9999, 0.12), (10000, 19999, 0.07), (20000, 9e9, 0.05)],  # Перехідні рамки
    '5':  [( 0,   5999, 0.18), (6000, 9999, 0.12), (10000, 19999, 0.07), (20000, 9e9, 0.05)],  # Антени
    '6':  [( 0,   5999, 0.18), (6000, 9999, 0.12), (10000, 19999, 0.07), (20000, 9e9, 0.05)],  # Реєстратори
    '7':  [( 0,   2999, 0.18), (3000, 9999, 0.12), (10000, 19999, 0.07), (20000, 9e9, 0.05)],  # Кронштейни
    '8':  [( 0,   2999, 0.13), (3000, 9999, 0.07), (10000, 19999, 0.05), (20000, 9e9, 0.03)],  # Оптика
    '9':  [( 0,   2999, 0.18), (3000, 9999, 0.12), (10000, 19999, 0.07), (20000, 9e9, 0.05)],  # Проводка
    '10': [( 0,   2999, 0.13), (3000, 9999, 0.07), (10000, 19999, 0.05), (20000, 9e9, 0.03)],  # LED лампи
    '12': [( 0,   2999, 0.13), (3000, 9999, 0.07), (10000, 19999, 0.05), (20000, 9e9, 0.03)],  # Фари
    '14': [( 0,   2999, 0.18), (3000, 9999, 0.12), (10000, 19999, 0.07), (20000, 9e9, 0.05)],  # Запобіжники
    '15': [( 0,   2999, 0.18), (3000, 9999, 0.12), (10000, 19999, 0.07), (20000, 9e9, 0.05)],  # Дефлектори
    '16': [( 0,   2999, 0.18), (3000, 9999, 0.12), (10000, 19999, 0.07), (20000, 9e9, 0.05)],  # Мото
}


def tg(msg: str):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        return
    try:
        requests.post(
            f'https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage',
            json={'chat_id': TG_CHAT_ID, 'text': msg, 'parse_mode': 'HTML'},
            timeout=10
        )
    except Exception as e:
        logger.warning(f'TG: {e}')


def calc_price(price: float, cat_id: str) -> float:
    """Розраховує ціну для Розетки з урахуванням CPA тиру."""
    rules = CPA_RULES.get(str(cat_id), [(0, 9e9, 0.18)])
    for low, high, rate in rules:
        if low <= price <= high:
            return math.ceil(price * (1 + rate) / 10) * 10
    return math.ceil(price * 1.18 / 10) * 10


def fetch_carvol_live() -> dict:
    """
    Завантажує живий фід Carvol і повертає:
    {article: {price, qty, available}}
    """
    logger.info('Завантажуємо живий фід Carvol...')
    r = requests.get(CARVOL_FEED, timeout=120)
    root = ET.fromstring(r.content)
    offers = root.find('shop').find('offers').findall('offer')

    data = {}
    for offer in offers:
        art_el = offer.find('article')
        if art_el is None:
            continue
        article = (art_el.text or '').strip()
        price_el = offer.find('price')
        qty_el   = offer.find('stock_quantity')
        qty      = int(qty_el.text or 0) if qty_el is not None else 0
        price    = float(price_el.text or 0) if price_el is not None else 0
        available = offer.get('available', 'false').lower() == 'true' and qty > 0

        data[article] = {
            'price':     price,
            'qty':       qty,
            'available': available,
        }

    logger.info(f'Живий фід: {len(data)} SKU, в наявності: {sum(1 for v in data.values() if v["available"])}')
    return data


def generate_feed(live_data: dict) -> tuple:
    """
    Генерує XML на основі шаблону carvol_rozetka.xml
    але з живими цінами і наявністю з Carvol фіду.
    """
    # Читаємо шаблон (структура що пройшла перевірку Розетки)
    template = ET.parse(TEMPLATE_PATH)
    tmpl_root = template.getroot()
    tmpl_shop = tmpl_root.find('shop')

    # Будуємо новий XML
    root = ET.Element('yml_catalog')
    root.set('date', datetime.now().strftime('%Y-%m-%d %H:%M'))
    shop = ET.SubElement(root, 'shop')

    # Копіюємо метадані
    for tag in ['name', 'company', 'url']:
        el = tmpl_shop.find(tag)
        if el is not None:
            new_el = ET.SubElement(shop, tag)
            new_el.text = el.text

    # Копіюємо валюти
    currencies = tmpl_shop.find('currencies')
    if currencies is not None:
        shop.append(currencies)

    # Копіюємо категорії (з rz_id — вже правильні!)
    categories = tmpl_shop.find('categories')
    if categories is not None:
        shop.append(categories)

    # Оновлюємо товари з живими цінами
    offers_el = ET.SubElement(shop, 'offers')

    stats = {'total': 0, 'in_stock': 0, 'out_stock': 0,
             'not_in_live': 0, 'price_examples': []}

    tmpl_offers = tmpl_shop.find('offers').findall('offer')

    for tmpl_offer in tmpl_offers:
        art_el = tmpl_offer.find('article')
        article = (art_el.text or '').strip() if art_el is not None else ''
        cat_el  = tmpl_offer.find('categoryId')
        cat_id  = (cat_el.text or '').strip() if cat_el is not None else '1'

        # Беремо живі дані
        live = live_data.get(article)
        if not live:
            stats['not_in_live'] += 1
            available = False
            price_carvol = 0.0
            qty = 0
        else:
            available    = live['available']
            price_carvol = live['price']
            qty          = live['qty']

        # Розраховуємо ціну з комісією
        rz_price = calc_price(price_carvol, cat_id) if price_carvol > 0 else 0

        # Будуємо offer
        o = ET.SubElement(offers_el, 'offer')
        o.set('id', tmpl_offer.get('id', ''))
        o.set('available', 'true' if available else 'false')

        ET.SubElement(o, 'price').text = str(rz_price) if rz_price > 0 else str(price_carvol)
        ET.SubElement(o, 'currencyId').text = 'UAH'

        # Категорія
        if cat_el is not None:
            new_cat = ET.SubElement(o, 'categoryId')
            new_cat.text = cat_id

        # Фото (з шаблону)
        for pic in tmpl_offer.findall('picture'):
            p = ET.SubElement(o, 'picture')
            p.text = (pic.text or '').strip()

        # Vendor
        vendor_el = tmpl_offer.find('vendor')
        if vendor_el is not None:
            ET.SubElement(o, 'vendor').text = vendor_el.text or ''

        # Article
        if art_el is not None:
            ET.SubElement(o, 'article').text = article

        # Кількість
        ET.SubElement(o, 'stock_quantity').text = str(qty)

        # Назви
        for tag in ['name_ua', 'name']:
            el = tmpl_offer.find(tag)
            if el is not None:
                new_el = ET.SubElement(o, tag)
                new_el.text = el.text or ''

        # Опис
        desc_el = tmpl_offer.find('description_ua')
        if desc_el is not None and desc_el.text:
            d = ET.SubElement(o, 'description_ua')
            d.text = desc_el.text

        # Params
        for param in tmpl_offer.findall('param'):
            p = ET.SubElement(o, 'param')
            p.set('name', param.get('name', ''))
            p.text = param.text or ''

        stats['total'] += 1
        if available:
            stats['in_stock'] += 1
        else:
            stats['out_stock'] += 1

        # Приклади для перевірки
        if len(stats['price_examples']) < 5 and price_carvol > 0:
            rules = CPA_RULES.get(str(cat_id), [(0, 9e9, 0.18)])
            rate = next((r for lo, hi, r in rules if lo <= price_carvol <= hi), 0.18)
            stats['price_examples'].append({
                'article':  article,
                'cat_id':   cat_id,
                'carvol':   price_carvol,
                'rz_price': rz_price,
                'rate':     rate,
                'qty':      qty,
            })

    return root, stats


def main():
    logger.add('/tmp/rozetka_feed_sync.log', rotation='10 MB', level='INFO')
    start = datetime.now()
    logger.info('=== Rozetka Feed Sync v2 ===')

    try:
        # 1. Живі дані з Carvol
        live = fetch_carvol_live()

        # 2. Генеруємо XML
        root, stats = generate_feed(live)

        # 3. Зберігаємо
        xml_bytes = minidom.parseString(
            ET.tostring(root, encoding='unicode')
        ).toprettyxml(indent='  ', encoding='UTF-8')

        os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
        with open(OUTPUT_PATH, 'wb') as f:
            f.write(xml_bytes)

        size_kb = os.path.getsize(OUTPUT_PATH) // 1024
        duration = (datetime.now() - start).seconds

        # Виводимо приклади цін
        print('\n=== ПЕРЕВІРКА ЦІН ===')
        print(f'{"Article":20} | {"Cat":4} | {"Carvol":8} | {"Розетка":8} | {"Комісія":8} | {"Qty":5}')
        print('-'*70)
        for ex in stats['price_examples']:
            print(
                f'{ex["article"][:20]:20} | '
                f'{ex["cat_id"]:4} | '
                f'{ex["carvol"]:8.0f} | '
                f'{ex["rz_price"]:8.0f} | '
                f'+{ex["rate"]*100:.0f}%      | '
                f'{ex["qty"]:5}'
            )

        print(f'\n=== РЕЗУЛЬТАТ ===')
        print(f'Всього товарів:     {stats["total"]}')
        print(f'В наявності:        {stats["in_stock"]}')
        print(f'Відсутні:           {stats["out_stock"]}')
        print(f'Немає в живому фіді:{stats["not_in_live"]}')
        print(f'Файл: {OUTPUT_PATH} ({size_kb} KB)')
        print(f'Час: {duration}с')

        msg = (
            f'🔄 <b>Rozetka Feed Sync v2</b> ({duration}с)\n'
            f'Всього: {stats["total"]} | В наявності: {stats["in_stock"]}\n'
            f'Файл: {size_kb} KB\n'
            f'URL: https://usa1.tail3a617f.ts.net/rozetka_feed.xml'
        )
        tg(msg)

    except Exception as e:
        logger.error(f'Помилка: {e}')
        tg(f'❌ <b>Rozetka Feed Sync помилка:</b> {e}')
        raise


if __name__ == '__main__':
    main()

````

### `agents/orders/fetch_prom_categories.py` — 266 рядків

````python
"""
agents/orders/fetch_prom_categories.py
=======================================
Одноразовий скрипт (і щотижнева підтримка):
- Проходить всі товари через Prom API /products/list
- Зберігає group.name і category.caption в my_products
- Додає колонку prom_category_name якщо не існує
- Показує маппінг на prom_cpa_rates

Запуск:
    python3 agents/orders/fetch_prom_categories.py
    python3 agents/orders/fetch_prom_categories.py --dry-run   # без запису в БД
    python3 agents/orders/fetch_prom_categories.py --stats     # тільки статистика

Час: ~5-10 хвилин для 5908 товарів (rate limit Prom: ~3 req/sec)
"""
import os, sys, time, requests, json, argparse
from loguru import logger

sys.path.append('/home/tek/agent-system')
from dotenv import load_dotenv
load_dotenv('/home/tek/agent-system/.env')
from shared.utils.db import get_connection

PROM_TOKEN = os.getenv('PROM_API_TOKEN')
PROM_HEADERS = {'Authorization': f'Bearer {PROM_TOKEN}'}
PROM_BASE = 'https://my.prom.ua/api/v1'

TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_ADMIN = os.getenv('TELEGRAM_ADMIN_ID')


def tg(text: str):
    try:
        requests.post(
            f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage',
            json={'chat_id': TELEGRAM_ADMIN, 'text': text, 'parse_mode': 'HTML'},
            timeout=10
        )
    except Exception as e:
        logger.error(f'Telegram: {e}')


def ensure_columns():
    """Додає колонки prom_category_name і prom_group_id якщо не існують"""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('''
        ALTER TABLE my_products
        ADD COLUMN IF NOT EXISTS prom_category_name VARCHAR(255),
        ADD COLUMN IF NOT EXISTS prom_group_name VARCHAR(255),
        ADD COLUMN IF NOT EXISTS prom_group_id BIGINT
    ''')
    conn.commit()
    cur.close()
    conn.close()
    logger.info('Колонки prom_category_name, prom_group_name, prom_group_id — готові')


def fetch_all_prom_products() -> list:
    """
    Завантажує всі товари з Prom API з пагінацією.
    Повертає список з полями: id, sku, group, category
    """
    all_products = []
    last_id = None
    page = 0

    logger.info('Завантажуємо товари з Prom API...')

    while True:
        page += 1
        params = {'limit': 100}
        if last_id:
            params['last_id'] = last_id

        try:
            resp = requests.get(
                f'{PROM_BASE}/products/list',
                headers=PROM_HEADERS,
                params=params,
                timeout=30
            )
            resp.raise_for_status()
            products = resp.json().get('products', [])
        except Exception as e:
            logger.error(f'Prom API помилка (сторінка {page}): {e}')
            time.sleep(5)
            continue

        if not products:
            break

        for p in products:
            group = p.get('group') or {}
            category = p.get('category') or {}
            all_products.append({
                'prom_id': p.get('id'),
                'sku': p.get('sku', '').strip(),
                'prom_group_id': group.get('id'),
                'prom_group_name': group.get('name_multilang', {}).get('uk') or group.get('name', ''),
                'prom_category_name': category.get('caption', ''),
            })

        last_id = products[-1]['id']
        logger.info(f'Сторінка {page}: {len(all_products)} товарів завантажено')

        if len(products) < 100:
            break

        time.sleep(0.4)  # rate limit: ~2.5 req/sec

    logger.success(f'Всього з Prom API: {len(all_products)} товарів')
    return all_products


def save_to_db(products: list, dry_run: bool = False) -> dict:
    """
    Зберігає group і category в my_products.
    Оновлює тільки товари де є SKU.

    Returns:
        dict: статистика {'updated': N, 'skipped': N, 'no_sku': N}
    """
    stats = {'updated': 0, 'skipped': 0, 'no_sku': 0, 'no_match': 0}

    if dry_run:
        logger.info('[DRY RUN] Тільки перегляд — без запису в БД')

    conn = get_connection()
    cur = conn.cursor()

    for p in products:
        sku = p.get('sku', '').strip()
        if not sku:
            stats['no_sku'] += 1
            continue

        group_name = p.get('prom_group_name', '') or ''
        category_name = p.get('prom_category_name', '') or ''
        group_id = p.get('prom_group_id')

        if not dry_run:
            cur.execute('''
                UPDATE my_products
                SET
                    prom_group_name = %s,
                    prom_group_id = %s,
                    prom_category_name = %s
                WHERE sku = %s
            ''', (group_name, group_id, category_name, sku))

            if cur.rowcount > 0:
                stats['updated'] += 1
            else:
                stats['no_match'] += 1
        else:
            logger.debug(f'  {sku}: group="{group_name}" | category="{category_name}"')
            stats['updated'] += 1

    if not dry_run:
        conn.commit()

    cur.close()
    conn.close()
    return stats


def show_cpa_mapping_stats():
    """
    Показує скільки товарів матчиться з prom_cpa_rates через group_name.
    Допомагає зрозуміти якість маппінгу.
    """
    conn = get_connection()
    cur = conn.cursor()

    # Розподіл по group_name
    cur.execute('''
        SELECT prom_group_name, COUNT(*) as cnt
        FROM my_products
        WHERE prom_group_name IS NOT NULL AND prom_group_name != ''
        GROUP BY prom_group_name
        ORDER BY cnt DESC
        LIMIT 30
    ''')
    rows = cur.fetchall()
    logger.info('\n=== Топ-30 груп товарів Prom ===')
    for r in rows:
        logger.info(f'  {r["cnt"]:4d} × {r["prom_group_name"]}')

    # Перевіряємо маппінг на prom_cpa_rates
    cur.execute('''
        SELECT
            COUNT(*) as total,
            COUNT(CASE WHEN prom_category_name IS NOT NULL THEN 1 END) as with_category,
            COUNT(CASE WHEN prom_group_name IS NOT NULL THEN 1 END) as with_group
        FROM my_products
        WHERE price_our > 0
    ''')
    row = cur.fetchone()
    logger.info(f'\n=== Покриття категорій ===')
    logger.info(f'  Всього товарів з ціною: {row["total"]}')
    logger.info(f'  З prom_category_name:   {row["with_category"]}')
    logger.info(f'  З prom_group_name:      {row["with_group"]}')

    # Топ категорій Prom
    cur.execute('''
        SELECT prom_category_name, COUNT(*) as cnt
        FROM my_products
        WHERE prom_category_name IS NOT NULL AND prom_category_name != ''
        GROUP BY prom_category_name
        ORDER BY cnt DESC
        LIMIT 20
    ''')
    rows = cur.fetchall()
    if rows:
        logger.info('\n=== Топ-20 категорій Prom ===')
        for r in rows:
            logger.info(f'  {r["cnt"]:4d} × {r["prom_category_name"]}')

    cur.close()
    conn.close()


def run(dry_run: bool = False, stats_only: bool = False):
    logger.info('=== Fetch Prom Categories — старт ===')

    if stats_only:
        show_cpa_mapping_stats()
        return

    # Крок 1: додаємо колонки
    ensure_columns()

    # Крок 2: завантажуємо з Prom API
    products = fetch_all_prom_products()

    if not products:
        logger.error('Не отримано жодного товару з Prom API')
        return

    # Крок 3: зберігаємо в БД
    stats = save_to_db(products, dry_run=dry_run)

    # Крок 4: статистика маппінгу
    if not dry_run:
        show_cpa_mapping_stats()

    msg = f'''✅ <b>Prom Categories оновлено</b>
Оброблено: {len(products)}
Оновлено: {stats["updated"]}
Без SKU: {stats["no_sku"]}
Не знайдено в БД: {stats["no_match"]}'''

    logger.success(msg.replace('<b>', '').replace('</b>', ''))
    if not dry_run:
        tg(msg)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Fetch Prom product categories')
    parser.add_argument('--dry-run', action='store_true', help='Тільки перегляд без запису')
    parser.add_argument('--stats', action='store_true', help='Тільки статистика маппінгу')
    args = parser.parse_args()

    run(dry_run=args.dry_run, stats_only=args.stats)

````

### `agents/orders/feed_sync.py` — 251 рядків

````python
"""
feed_sync.py — Синхронізація цін і наявності для Єпіцентру
===========================================================
Що робить:
1. Скачує фід TOPTUL
2. Порівнює наявність з БД
3. Оновлює epicentr_price при зміні цін
4. Генерує XML для автооновлення Єпіцентру
5. Зберігає в shared/feeds/epicentr_update.xml

Запуск:
    python3 agents/orders/feed_sync.py

Cron (кожні 4 год):
    0 */4 * * * cd /home/tek/agent-system && venv/bin/python3 agents/orders/feed_sync.py
"""
import sys, os, requests, json, math
import xml.etree.ElementTree as ET
from xml.dom import minidom
from datetime import datetime
from loguru import logger
sys.path.append('/home/tek/agent-system')
from dotenv import load_dotenv; load_dotenv('/home/tek/agent-system/.env')
from shared.utils.db import get_connection

TOPTUL_FEED = (
    'https://toptul.online/products_feed.xml?'
    'hash_tag=442309995a1416e3104d287504a1846f'
    '&label_ids=3882792&html_description=1&languages=uk,ru'
)
OUTPUT_PATH  = '/home/tek/agent-system/shared/feeds/epicentr_update.xml'
TG_BOT_TOKEN = os.getenv('TG_BOT_TOKEN')
TG_CHAT_ID   = os.getenv('TG_CHAT_ID')


def tg(msg: str):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        return
    try:
        requests.post(
            f'https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage',
            json={'chat_id': TG_CHAT_ID, 'text': msg, 'parse_mode': 'HTML'},
            timeout=10
        )
    except Exception as e:
        logger.warning(f'TG: {e}')


def epicentr_price(price_our: float, category_name: str) -> float:
    """Розраховує ціну для Єпіцентру = наша ціна + CPA."""
    cpa = 1.10 if any(x in (category_name or '').lower()
                      for x in ['компресор', 'верстак', 'станок']) else 1.15
    return math.ceil(price_our * cpa / 10) * 10


def fetch_feed() -> dict:
    """Скачує фід і повертає {sku: {available, price, name}}."""
    logger.info('Завантажуємо фід TOPTUL...')
    r = requests.get(TOPTUL_FEED, timeout=120)
    root = ET.fromstring(r.content)
    offers = root.find('shop').find('offers').findall('offer')
    data = {}
    for offer in offers:
        sku_el = offer.find('vendorCode')
        if sku_el is None:
            continue
        sku = (sku_el.text or '').strip().upper()
        price_el   = offer.find('price')
        name_ua_el = offer.find('name_ua') or offer.find('name')
        data[sku] = {
            'available': offer.get('available', 'false').lower() == 'true',
            'price':     float(price_el.text or 0) if price_el is not None else 0,
            'name':      (name_ua_el.text or '') if name_ua_el is not None else '',
        }
    logger.info(f'Фід: {len(data)} SKU')
    return data


def sync_with_db(feed: dict) -> dict:
    """
    Синхронізує фід з БД:
    - Оновлює price_supplier і epicentr_price при зміні ціни
    - Повертає статистику змін
    """
    conn = get_connection()
    cur  = conn.cursor()

    # Отримуємо всі товари з маппінгом
    cur.execute('''
        SELECT p.sku, p.price_supplier, p.price_our, p.epicentr_price,
               p.epicentr_category_name, m.epicentr_article
        FROM my_products p
        JOIN epicentr_sku_mapping m ON m.our_sku = p.sku
        WHERE p.epicentr_category_id IS NOT NULL AND p.price_our > 0
    ''')
    db_products = cur.fetchall()

    price_changed   = 0
    avail_changed   = 0
    price_updated   = []

    for p in db_products:
        sku       = p['sku'].upper()
        feed_item = feed.get(sku)
        if not feed_item:
            continue

        feed_price = feed_item['price']
        old_price  = float(p['price_supplier'] or 0)

        # Якщо ціна постачальника змінилась — оновлюємо
        if abs(feed_price - old_price) > 0.01 and feed_price > 0:
            new_price_our  = feed_price  # ціна постачальника = наша ціна (маржа від постачальника)
            new_epi_price  = epicentr_price(new_price_our, p['epicentr_category_name'])
            cur.execute('''
                UPDATE my_products
                SET price_supplier = %s,
                    price_our = %s,
                    epicentr_price = %s
                WHERE sku = %s
            ''', (feed_price, new_price_our, new_epi_price, p['sku']))
            price_changed += 1
            price_updated.append({
                'sku':       sku,
                'article':   p['epicentr_article'],
                'old_price': old_price,
                'new_price': new_price_our,
                'epi_price': new_epi_price,
            })

    conn.commit()
    cur.close(); conn.close()

    logger.info(f'Оновлено цін: {price_changed}')
    return {
        'price_changed': price_changed,
        'price_updated': price_updated[:5],  # перші 5 для логу
    }


def generate_update_xml(feed: dict) -> tuple:
    """
    Генерує XML для автооновлення Єпіцентру.
    Формат: тільки offer id + price + availability (мінімальний)
    """
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute('''
        SELECT m.epicentr_article, p.epicentr_price, p.sku,
               p.epicentr_category_name
        FROM epicentr_sku_mapping m
        JOIN my_products p ON p.sku = m.our_sku
        WHERE p.epicentr_category_id IS NOT NULL AND p.epicentr_price > 0
    ''')
    rows = cur.fetchall()
    cur.close(); conn.close()

    root   = ET.Element('yml_catalog')
    root.set('date', datetime.now().strftime('%Y-%m-%d %H:%M'))
    offers = ET.SubElement(root, 'offers')

    in_stock = 0
    out_of_stock = 0

    for r in rows:
        sku       = r['sku'].upper()
        feed_item = feed.get(sku, {})
        available = feed_item.get('available', False)

        o = ET.SubElement(offers, 'offer')
        o.set('id', r['epicentr_article'])
        o.set('available', 'true' if available else 'false')
        ET.SubElement(o, 'price').text = str(r['epicentr_price'])
        ET.SubElement(o, 'availability').text = 'in_stock' if available else 'out_of_stock'

        if available:
            in_stock += 1
        else:
            out_of_stock += 1

    xml_bytes = minidom.parseString(
        ET.tostring(root, encoding='unicode')
    ).toprettyxml(indent='  ', encoding='UTF-8')

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, 'wb') as f:
        f.write(xml_bytes)

    size_kb = os.path.getsize(OUTPUT_PATH) // 1024
    logger.info(f'XML: {OUTPUT_PATH} ({size_kb} KB), в наявності: {in_stock}, відсутні: {out_of_stock}')
    return in_stock, out_of_stock



def git_push() -> bool:
    import subprocess
    cwd = '/home/tek/agent-system'
    try:
        subprocess.run(['git', 'add', 'shared/feeds/epicentr_update.xml'], check=True, capture_output=True, cwd=cwd)
        result = subprocess.run(['git', 'diff', '--cached', '--quiet'], capture_output=True, cwd=cwd)
        if result.returncode == 0:
            logger.info('Git: файл не змінився')
            return True
        subprocess.run(['git', 'commit', '-m', 'sync: epicentr availability auto'], check=True, capture_output=True, cwd=cwd)
        subprocess.run(['git', 'push', '--force-with-lease'], check=True, capture_output=True, cwd=cwd)
        logger.success('Git push: OK')
        return True
    except Exception as e:
        logger.error(f'Git push: FAILED {e}')
        return False

def main():
    logger.add('/tmp/feed_sync.log', rotation='10 MB', level='INFO')
    start = datetime.now()
    logger.info('=== Feed Sync запущено ===')

    try:
        # 1. Скачуємо фід
        feed = fetch_feed()

        # 2. Синхронізуємо ціни в БД
        changes = sync_with_db(feed)

        # 3. Генеруємо XML для автооновлення
        in_stock, out_stock = generate_update_xml(feed)
        git_ok = git_push()

        duration = (datetime.now() - start).seconds
        msg = (
            f'🔄 <b>Feed Sync завершено</b> ({duration}с)\n'
            f'В наявності: {in_stock}\n'
            f'Відсутні: {out_stock}\n'
            f'Змінилось цін: {changes["price_changed"]}'
        )
        if changes['price_updated']:
            msg += '\n\nЗміни цін:'
            for p in changes['price_updated']:
                msg += f'\n  {p["sku"]}: {p["old_price"]:.0f}→{p["new_price"]:.0f} грн (Єп: {p["epi_price"]:.0f})'

        logger.success(f'Завершено за {duration}с')
        git_status = "✅ OK" if git_ok else "❌ FAILED"
        print(f"OK: in_stock={in_stock}, out_of_stock={out_stock}, price_changes={changes["price_changed"]}, git={git_status}")

    except Exception as e:
        logger.error(f'Feed Sync помилка: {e}')
        tg(f'❌ <b>Feed Sync помилка:</b> {e}')
        raise


if __name__ == '__main__':
    main()

````

### `agents/orders/carvol_epicentr_sync.py` — 243 рядків

````python
"""
agents/orders/carvol_epicentr_sync.py
======================================
Оновлює ТІЛЬКИ ціни та наявність в exports/carvol_epicentr.xml
з живого фіду https://carvol.prom.ua/rozetka_feed.xml

Що змінюється:
  <offer available="true/false">
    <price>НОВА_ЦІНА</price>

Формула: math.ceil(carvol_price / (1 - 0.15) / 10) * 10

Cron (раз на добу о 7:00):
0 7 * * * cd /home/tek/agent-system && venv/bin/python3 agents/orders/carvol_epicentr_sync.py
"""
import sys, os, math, requests, subprocess
import xml.etree.ElementTree as ET
from datetime import datetime
from loguru import logger

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE_DIR)
from dotenv import load_dotenv; load_dotenv(os.path.join(BASE_DIR, '.env'))

CARVOL_FEED = (
    'https://carvol.prom.ua/rozetka_feed.xml'
    '?rozetka_hash_tag=2251d0779efad97117ac08d7efd82c2f'
    '&product_ids=&label_ids=&languages=uk%2Cru&group_ids='
)
XML_PATH    = os.path.join(BASE_DIR, 'exports', 'carvol_epicentr.xml')
REPO_PATH   = BASE_DIR
COMMISSION  = 0.15

TG_BOT_TOKEN = os.getenv('TG_BOT_TOKEN')
TG_CHAT_ID   = os.getenv('TG_CHAT_ID')


def tg(msg: str):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        return
    try:
        requests.post(
            f'https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage',
            json={'chat_id': TG_CHAT_ID, 'text': msg, 'parse_mode': 'HTML'},
            timeout=10,
        )
    except Exception as e:
        logger.warning(f'TG: {e}')


def calc_price(carvol_price: float) -> float:
    """Gross-up ціни Carvol на комісію Єпіцентру 15%, округлення вгору до 10."""
    return math.ceil(carvol_price / (1 - COMMISSION) / 10) * 10


def fetch_carvol_live() -> dict:
    """Повертає {article: {price, available}} з живого фіду Carvol."""
    logger.info('Завантажуємо Carvol фід...')
    r = requests.get(CARVOL_FEED, timeout=120)
    root = ET.fromstring(r.content)
    shop = root.find('shop')
    if shop is None:
        shop = root
    offers_el = shop.find('offers')
    if offers_el is None:
        offers_el = root
    offers = offers_el.findall('offer')

    data = {}
    for offer in offers:
        art_el = offer.find('article')
        if art_el is None:
            art_el = offer.find('vendorCode')
        if art_el is None:
            continue
        article = (art_el.text or '').strip()
        if not article:
            continue

        price_el = offer.find('price')
        qty_el   = offer.find('stock_quantity')
        price    = float(price_el.text or 0) if price_el is not None else 0.0
        qty      = int(qty_el.text or 0)     if qty_el   is not None else 0
        avail    = offer.get('available', 'false').lower() == 'true'
        data[article] = {'price': price, 'available': avail and qty > 0}

    in_stock = sum(1 for v in data.values() if v['available'])
    logger.info(f'Carvol: {len(data)} SKU, в наявності: {in_stock}')
    return data


def update_xml(live: dict) -> dict:
    """
    Читає exports/carvol_epicentr.xml, оновлює ТІЛЬКИ:
    - offer[@available]
    - <price>
    Все інше (структура, категорії, назви, фото, описи) — незмінне!
    """
    tree = ET.parse(XML_PATH)
    root = tree.getroot()
    root.set('date', datetime.now().strftime('%Y-%m-%d %H:%M'))

    offers = root.find('offers').findall('offer')

    stats = {
        'updated': 0, 'not_found': 0,
        'in_stock': 0, 'out_stock': 0,
        'price_changed': 0, 'examples': [],
    }

    for offer in offers:
        article = offer.get('id', '').strip()
        if not article:
            continue

        live_item = live.get(article)

        if not live_item:
            offer.set('available', 'false')
            stats['not_found'] += 1
            stats['out_stock'] += 1
            continue

        available    = live_item['available']
        price_carvol = live_item['price']

        offer.set('available', 'true' if available else 'false')

        if price_carvol > 0:
            ep_price  = calc_price(price_carvol)
            price_el  = offer.find('price')
            if price_el is not None:
                old_price = price_el.text
                new_price = f'{ep_price:.2f}'
                price_el.text = new_price
                if old_price != new_price:
                    stats['price_changed'] += 1

            if len(stats['examples']) < 5 and available:
                stats['examples'].append({
                    'article':  article,
                    'carvol':   price_carvol,
                    'epicentr': calc_price(price_carvol),
                    'available': available,
                })

        stats['updated'] += 1
        if available:
            stats['in_stock'] += 1
        else:
            stats['out_stock'] += 1

    tree.write(XML_PATH, encoding='unicode', xml_declaration=False)
    with open(XML_PATH, 'r+', encoding='utf-8') as f:
        content = f.read()
        f.seek(0)
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n' + content)

    return stats


def git_reset_to_origin() -> bool:
    """Скидає локальний репо до стану origin/main перед оновленням XML."""
    try:
        for cmd in [
            ['git', 'fetch', 'origin'],
            ['git', 'reset', '--hard', 'origin/main'],
        ]:
            r = subprocess.run(cmd, cwd=REPO_PATH, capture_output=True, text=True)
            if r.returncode != 0:
                logger.error(f'{" ".join(cmd)}: {r.stderr[:200]}')
                return False
        logger.info('Git: reset to origin/main OK')
        return True
    except Exception as e:
        logger.error(f'Git reset: {e}')
        return False


def git_push() -> bool:
    """Пушить оновлений XML в GitHub (без rebase — завжди поверх origin/main)."""
    msg = f'sync: epicentr prices+availability {datetime.now().strftime("%Y-%m-%d %H:%M")}'
    try:
        for cmd in [
            ['git', 'add', 'exports/carvol_epicentr.xml'],
            ['git', 'commit', '-m', msg],
            ['git', 'push'],
        ]:
            r = subprocess.run(cmd, cwd=REPO_PATH, capture_output=True, text=True)
            if r.returncode != 0:
                if 'nothing to commit' in r.stdout + r.stderr:
                    logger.info('Git: немає змін')
                    return True
                logger.error(f'{cmd[1]}: {r.stderr[:200]}')
                return False
        logger.success('Git push OK')
        return True
    except Exception as e:
        logger.error(f'Git: {e}')
        return False


def main():
    logger.add('/tmp/carvol_epicentr_sync.log', rotation='10 MB', level='INFO')
    start = datetime.now()
    logger.info('=== Carvol → Єпіцентр Sync ===')

    try:
        # Спочатку синхронізуємось з origin щоб уникнути конфліктів
        git_reset_to_origin()

        live   = fetch_carvol_live()
        stats  = update_xml(live)
        pushed = git_push()

        duration = (datetime.now() - start).seconds

        print('\n=== ПЕРЕВІРКА ЦІН (перші 5 в наявності) ===')
        print(f'{"Артикул":25} | {"Carvol":9} | {"Єпіцентр":10}')
        print('-' * 55)
        for ex in stats['examples']:
            print(f'{ex["article"][:25]:25} | {ex["carvol"]:9.2f} | {ex["epicentr"]:10.2f}')

        print(f'\n=== РЕЗУЛЬТАТ ===')
        print(f'Оновлено:         {stats["updated"]}')
        print(f'В наявності:      {stats["in_stock"]}')
        print(f'Відсутні:         {stats["out_stock"]}')
        print(f'Змінилось цін:    {stats["price_changed"]}')
        print(f'Нема у фіді:      {stats["not_found"]}')
        print(f'Git push:         {"✅ OK" if pushed else "❌ FAILED"}')
        print(f'Час:              {duration}с')

        if not pushed:
            tg('❌ <b>Carvol→Єпіцентр Sync</b>: git push FAILED')

    except Exception as e:
        logger.error(f'Помилка: {e}')
        tg(f'❌ <b>Carvol→Єпіцентр Sync:</b> {e}')
        raise


if __name__ == '__main__':
    main()

````

### `agents/orders/rozetka_github_sync.py` — 264 рядків

````python
"""
rozetka_github_sync.py
======================
Оновлює ТІЛЬКИ ціни та наявність в data/carvol_rozetka.xml
Структура файлу (категорії, назви, фото, описи) — незмінна!

Що змінюється:
  <offer available="true/false">
    <price>НОВА_ЦІНА</price>
    <stock_quantity>КІЛЬКІСТЬ</stock_quantity>

Cron (раз на добу о 7:00):
0 7 * * * cd /home/tek/agent-system && source venv/bin/activate && python3 agents/orders/rozetka_github_sync.py
"""
import sys, os, requests, math, subprocess
import xml.etree.ElementTree as ET
from datetime import datetime
from loguru import logger
sys.path.append('/home/tek/agent-system')
from dotenv import load_dotenv; load_dotenv('/home/tek/agent-system/.env')

CARVOL_FEED = (
    'https://carvol.prom.ua/rozetka_feed.xml'
    '?rozetka_hash_tag=2251d0779efad97117ac08d7efd82c2f'
    '&product_ids=&label_ids=28618299&languages=uk%2Cru&group_ids='
)
XML_PATH  = '/home/tek/agent-system/data/carvol_rozetka.xml'
REPO_PATH = '/home/tek/agent-system'
TG_BOT_TOKEN = os.getenv('TG_BOT_TOKEN')
TG_CHAT_ID   = os.getenv('TG_CHAT_ID')

# Комісії Розетки по category_id (наші ID 1-16)
CPA_RULES = {
    '1':  [(0,5999,0.18),(6000,9999,0.12),(10000,19999,0.07),(20000,9e9,0.05)],
    '2':  [(0,5999,0.18),(6000,9999,0.12),(10000,19999,0.07),(20000,9e9,0.05)],
    '3':  [(0,5999,0.18),(6000,9999,0.12),(10000,19999,0.07),(20000,9e9,0.05)],
    '4':  [(0,5999,0.18),(6000,9999,0.12),(10000,19999,0.07),(20000,9e9,0.05)],
    '5':  [(0,5999,0.18),(6000,9999,0.12),(10000,19999,0.07),(20000,9e9,0.05)],
    '6':  [(0,5999,0.18),(6000,9999,0.12),(10000,19999,0.07),(20000,9e9,0.05)],
    '7':  [(0,2999,0.18),(3000,9999,0.12),(10000,19999,0.07),(20000,9e9,0.05)],
    '8':  [(0,2999,0.13),(3000,9999,0.07),(10000,19999,0.05),(20000,9e9,0.03)],
    '9':  [(0,2999,0.18),(3000,9999,0.12),(10000,19999,0.07),(20000,9e9,0.05)],
    '10': [(0,2999,0.13),(3000,9999,0.07),(10000,19999,0.05),(20000,9e9,0.03)],
    '12': [(0,2999,0.13),(3000,9999,0.07),(10000,19999,0.05),(20000,9e9,0.03)],
    '14': [(0,2999,0.18),(3000,9999,0.12),(10000,19999,0.07),(20000,9e9,0.05)],
    '15': [(0,2999,0.18),(3000,9999,0.12),(10000,19999,0.07),(20000,9e9,0.05)],
    '16': [(0,2999,0.18),(3000,9999,0.12),(10000,19999,0.07),(20000,9e9,0.05)],
}


def tg(msg: str):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        return
    try:
        requests.post(
            f'https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage',
            json={'chat_id': TG_CHAT_ID, 'text': msg, 'parse_mode': 'HTML'},
            timeout=10
        )
    except Exception as e:
        logger.warning(f'TG: {e}')


def calc_price(opt: float, cat_id: str) -> float:
    """Gross-up OPT ціни щоб покрити комісію Розетки.

    Rozetka знімає commission з sell_price, тому:
      sell * (1 - rate) >= opt  →  sell = ceil(opt / (1 - rate) / 10) * 10

    Тір визначається за sell_price (не за opt). Якщо breakeven виходить
    за межі тиру — піднімаємось до мінімуму наступного (вигіднішого) тиру.
    """
    rules = sorted(CPA_RULES.get(str(cat_id), [(0, 9e9, 0.18)]), key=lambda x: x[0])
    for low, high, rate in rules:
        breakeven = math.ceil(opt / (1 - rate) / 10) * 10
        if breakeven <= high:
            # breakeven вписується в цей або нижчий тір
            return max(breakeven, math.ceil(low / 10) * 10)
    # opt перевищує всі тіри — використовуємо останній (найнижча комісія)
    _, _, rate = rules[-1]
    return math.ceil(opt / (1 - rate) / 10) * 10


def fetch_carvol_live() -> dict:
    """Повертає {article: {price, qty, available}} з живого фіду."""
    logger.info('Завантажуємо Carvol фід...')
    r = requests.get(CARVOL_FEED, timeout=120)
    root = ET.fromstring(r.content)
    offers = root.find('shop').find('offers').findall('offer')
    data = {}
    for offer in offers:
        art_el = offer.find('article')
        if art_el is None:
            continue
        article  = (art_el.text or '').strip()
        price_el = offer.find('price')
        qty_el   = offer.find('stock_quantity')
        qty      = int(qty_el.text or 0) if qty_el is not None else 0
        price    = float(price_el.text or 0) if price_el is not None else 0
        available = offer.get('available','false').lower() == 'true' and qty > 0
        data[article] = {'price': price, 'qty': qty, 'available': available}
    logger.info(f'Carvol: {len(data)} SKU, в наявності: {sum(1 for v in data.values() if v["available"])}')
    return data


def update_prices_only(live: dict) -> dict:
    """
    Читає XML, оновлює ТІЛЬКИ:
    - offer[@available]
    - <price>
    - <stock_quantity>
    Все інше (структура, категорії, назви, фото) — незмінне!
    """
    # Читаємо як текст щоб зберегти форматування
    tree = ET.parse(XML_PATH)
    root = tree.getroot()

    # Оновлюємо дату генерації
    root.set('date', datetime.now().strftime('%Y-%m-%d %H:%M'))

    shop   = root.find('shop')
    offers = shop.find('offers').findall('offer')

    stats = {'updated': 0, 'not_found': 0, 'in_stock': 0,
             'out_stock': 0, 'price_changed': 0, 'examples': []}

    for offer in offers:
        art_el  = offer.find('article')
        cat_el  = offer.find('categoryId')
        article = (art_el.text or '').strip() if art_el is not None else ''
        cat_id  = (cat_el.text or '1').strip() if cat_el is not None else '1'

        live_item = live.get(article)

        if not live_item:
            # Товару немає в живому фіді — ставимо відсутній
            offer.set('available', 'false')
            qty_el = offer.find('stock_quantity')
            if qty_el is not None:
                qty_el.text = '0'
            stats['not_found'] += 1
            stats['out_stock'] += 1
            continue

        available    = live_item['available']
        price_carvol = live_item['price']
        qty          = live_item['qty']

        # 1. Оновлюємо available атрибут
        offer.set('available', 'true' if available else 'false')

        # 2. Оновлюємо ціну (тільки якщо є ціна від постачальника)
        if price_carvol > 0:
            rz_price = calc_price(price_carvol, cat_id)
            price_el = offer.find('price')
            if price_el is not None:
                old_price = price_el.text
                price_el.text = str(int(rz_price))
                if old_price != str(int(rz_price)):
                    stats['price_changed'] += 1

        # 3. Оновлюємо кількість
        qty_el = offer.find('stock_quantity')
        if qty_el is not None:
            qty_el.text = str(qty)

        stats['updated'] += 1
        if available:
            stats['in_stock'] += 1
        else:
            stats['out_stock'] += 1

        # Зберігаємо приклади для перевірки
        if len(stats['examples']) < 5 and price_carvol > 0:
            rz_price = calc_price(price_carvol, cat_id)
            rules = CPA_RULES.get(cat_id, [(0, 9e9, 0.18)])
            rate = next((r for lo, hi, r in rules if lo <= price_carvol <= hi), 0.18)
            stats['examples'].append({
                'article': article, 'cat': cat_id,
                'carvol': price_carvol, 'rz': rz_price,
                'rate': rate, 'qty': qty,
                'available': available,
            })

    # Записуємо XML зберігаючи структуру
    tree.write(XML_PATH, encoding='unicode', xml_declaration=False)
    # Додаємо UTF-8 declaration
    with open(XML_PATH, 'r+', encoding='utf-8') as f:
        content = f.read()
        f.seek(0)
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n' + content)

    return stats


def git_push() -> bool:
    """Пушить оновлений файл в GitHub."""
    msg = f'sync: prices+availability {datetime.now().strftime("%Y-%m-%d %H:%M")}'
    try:
        for cmd in [
            ['git', 'add', 'data/carvol_rozetka.xml'],
            ['git', 'commit', '-m', msg],
            ['git', 'pull', '--rebase'], ['git', 'push'],
        ]:
            r = subprocess.run(cmd, cwd=REPO_PATH, capture_output=True, text=True)
            if r.returncode != 0:
                if 'nothing to commit' in r.stdout + r.stderr:
                    logger.info('Git: немає змін')
                    return True
                logger.error(f'{cmd[1]}: {r.stderr[:200]}')
                return False
        logger.success('Git push OK')
        return True
    except Exception as e:
        logger.error(f'Git: {e}')
        return False


def main():
    logger.add('/tmp/rozetka_github_sync.log', rotation='10 MB', level='INFO')
    start = datetime.now()
    logger.info('=== Rozetka GitHub Sync ===')

    try:
        # 1. Живі дані Carvol
        live = fetch_carvol_live()

        # 2. Оновлюємо ТІЛЬКИ ціни та наявність
        stats = update_prices_only(live)

        # 3. Git push
        pushed = git_push()

        duration = (datetime.now() - start).seconds

        # Виводимо результат
        print('\n=== ПЕРЕВІРКА ЦІН (перші 5) ===')
        print(f'{"Article":20} | {"Cat":3} | {"Carvol":7} | {"Розетка":7} | {"Rate":5} | {"Qty":4} | {"Avail"}')
        print('-' * 70)
        for ex in stats['examples']:
            avail = '✅' if ex['available'] else '❌'
            print(f'{ex["article"][:20]:20} | {ex["cat"]:3} | {ex["carvol"]:7.0f} | {ex["rz"]:7.0f} | +{ex["rate"]*100:.0f}%  | {ex["qty"]:4} | {avail}')

        print(f'\n=== РЕЗУЛЬТАТ ===')
        print(f'Оновлено:         {stats["updated"]}')
        print(f'В наявності:      {stats["in_stock"]}')
        print(f'Відсутні:         {stats["out_stock"]}')
        print(f'Змінилось цін:    {stats["price_changed"]}')
        print(f'Нема у фіді:      {stats["not_found"]}')
        print(f'Git push:         {"✅ OK" if pushed else "❌ FAILED"}')
        print(f'Час:              {duration}с')
        print(f'URL: https://raw.githubusercontent.com/klatch1shop-ai/affilate_aggent/main/data/carvol_rozetka.xml')

        if not pushed:
            tg(f'❌ <b>Rozetka GitHub Sync</b>: git push FAILED')

    except Exception as e:
        logger.error(f'Помилка: {e}')
        tg(f'❌ <b>Rozetka GitHub Sync:</b> {e}')
        raise


if __name__ == '__main__':
    main()

````

### `agents/orders/katran_github_sync.py` — 126 рядків

````python
"""
katran_github_sync.py
=====================
Щогодинна синхронізація фіду Катрана → GitHub.

Cron (кожну годину на сервері):
0 * * * * /home/tek/agent-system/venv/bin/python3 /home/tek/agent-system/agents/orders/katran_github_sync.py >> /tmp/katran_sync_cron.log 2>&1
"""
import sys, os, subprocess, requests
from datetime import datetime
from loguru import logger

# Визначаємо корінь проекту відносно цього файлу
REPO_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, REPO_PATH)

from dotenv import load_dotenv
load_dotenv(os.path.join(REPO_PATH, ".env"))

XML_RELATIVE = "data/katran_rozetka.xml"
XML_PATH = os.path.join(REPO_PATH, XML_RELATIVE)
LOG_FILE = "/tmp/katran_github_sync.log"

TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TG_ADMIN = os.getenv("TELEGRAM_ADMIN_ID")


def tg_error(msg: str):
    """Надсилає повідомлення адміну тільки при помилці."""
    if not TG_TOKEN or not TG_ADMIN:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_ADMIN, "text": msg, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception as e:
        logger.warning(f"[Sync] TG send error: {e}")


def git_push(stats: dict) -> bool:
    """Робить git add + commit + push. Повертає True якщо успішно або немає змін."""
    commit_msg = (
        f"sync: katran feed {datetime.now().strftime('%Y-%m-%d %H:%M')} "
        f"({stats['in_stock']} offers)"
    )
    try:
        for cmd in [
            ["git", "add", "-f", XML_RELATIVE],
            ["git", "commit", "-m", commit_msg],
            ["git", "pull", "--rebase"],
            ["git", "push"],
        ]:
            r = subprocess.run(cmd, cwd=REPO_PATH, capture_output=True, text=True)
            if r.returncode != 0:
                combined = r.stdout + r.stderr
                if "nothing to commit" in combined:
                    logger.info("[Sync] Git: немає змін у файлі")
                    return True
                logger.error(f"[Sync] Git {cmd[1]} failed: {combined[:300]}")
                return False
        logger.success("[Sync] Git push OK")
        return True
    except Exception as e:
        logger.error(f"[Sync] Git exception: {e}")
        return False


def main():
    logger.add(LOG_FILE, rotation="10 MB", level="INFO", enqueue=True)
    start = datetime.now()
    logger.info("=== Katran GitHub Sync START ===")

    try:
        # 1. Генеруємо XML з фіду Катрана
        from agents.orders.katran_xml_generator import generate_xml
        file, count, stats = generate_xml(output_file=XML_PATH)

        logger.info(
            f"[Sync] XML готовий: {count} офферів "
            f"(пропущено: наявність={stats['skipped_stock']}, "
            f"ціна={stats['skipped_price']})"
        )

        # 2. Git push
        pushed = git_push(stats)

        duration = (datetime.now() - start).seconds

        if not pushed:
            tg_error(
                f"❌ <b>Katran GitHub Sync: git push failed</b>\n"
                f"Офферів: {count}\n"
                f"Час: {duration}с\n"
                f"Лог: {LOG_FILE}"
            )
            sys.exit(1)

        logger.info(
            f"=== Katran GitHub Sync DONE: {count} офферів, {duration}с ==="
        )

        # Статистика в stdout (видна в cron лозі)
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] "
              f"katran_github_sync: OK | "
              f"offers={count} | "
              f"total={stats['total']} | "
              f"skipped_stock={stats['skipped_stock']} | "
              f"skipped_price={stats['skipped_price']} | "
              f"categories={stats['categories']} | "
              f"duration={duration}s")

    except Exception as e:
        duration = (datetime.now() - start).seconds
        logger.error(f"[Sync] Критична помилка: {e}")
        tg_error(
            f"❌ <b>Katran GitHub Sync: помилка</b>\n"
            f"<code>{str(e)[:500]}</code>\n"
            f"Час: {duration}с"
        )
        raise


if __name__ == "__main__":
    main()

````

### `agents/orders/order_agent.py` — 512 рядків

````python
"""
Агент обробки замовлень — дропшипінг TOPTUL
============================================
Цикл:
1. Отримати нові замовлення з Prom API
2. Перевірити наявність у фіді TOPTUL (реальний час)
3. Підтвердити замовлення на Prom
4. Сформувати Excel бланк → відправити на opt@grandinstrument.ua
ТТН — постачальник сам надсилає, вручну вносимо в систему
"""
import os, sys, json, time, requests, smtplib
import xml.etree.ElementTree as ET
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from loguru import logger
import xlsxwriter

sys.path.append('/home/tek/agent-system')
from dotenv import load_dotenv; load_dotenv('/home/tek/agent-system/.env')
from shared.utils.db import get_connection

# === КОНСТАНТИ ===
PROM_TOKEN = os.getenv('PROM_API_TOKEN')
PROM_HEADERS = {'Authorization': f'Bearer {PROM_TOKEN}'}
PROM_BASE = 'https://my.prom.ua/api/v1'

TOPTUL_FEED = (
    'https://toptul.online/products_feed.xml?'
    'hash_tag=442309995a1416e3104d287504a1846f'
    '&label_ids=3882792&html_description=1&languages=uk,ru'
)

SUPPLIER_EMAIL = 'opt@grandinstrument.ua'
SUPPLIER_CODE = '000160594'

SMTP_USER = os.getenv('SMTP_USER')
SMTP_PASS = os.getenv('SMTP_PASS')
SMTP_HOST = os.getenv('SMTP_HOST', 'smtp.gmail.com')
SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))

def parse_price(val) -> float:
    """Парсить ціну з будь-якого формату: '490 грн', 490, '1 000 грн', '1,000.00'"""
    if val is None:
        return 0.0
    s = str(val)
    s = s.replace(' грн', '').replace('грн', '')  # прибираємо 'грн'
    s = s.replace('\xa0', '').replace('\u00a0', '')  # non-breaking space
    # Якщо формат '1 000' або '1 000.50' — прибираємо пробіли між цифрами
    import re
    s = re.sub(r'(\d)\s+(\d)', r'\1\2', s)  # '1 000' → '1000'
    s = s.replace(',', '.').strip()
    # Беремо перший числовий токен
    match = re.search(r'[\d]+(?:\.[\d]+)?', s)
    return float(match.group()) if match else 0.0



# === КЕШ ФІДУ ===
_feed_cache = {'data': {}, 'updated': 0}

# =============================================
# 1. ЗАВАНТАЖЕННЯ ФІДУ TOPTUL
# =============================================
def load_feed():
    """Завантажує фід TOPTUL і кешує на 1 годину"""
    if time.time() - _feed_cache['updated'] < 3600 and _feed_cache['data']:
        return _feed_cache['data']
    
    logger.info('Завантажуємо фід TOPTUL...')
    try:
        resp = requests.get(TOPTUL_FEED, timeout=120)
        root = ET.fromstring(resp.content)
        offers = root.find('shop').find('offers').findall('offer')
        
        cache = {}
        for offer in offers:
            # SKU з vendorCode
            sku_el = offer.find('vendorCode')
            sku = (sku_el.text or '').strip() if sku_el is not None else ''
            if not sku:
                sku = (offer.get('id') or '').upper()
            
            available = offer.get('available', 'true') == 'true'
            stock = getattr(offer.find('stock_quantity'), 'text', '*')
            price_el = offer.find('price')
            price = float(price_el.text) if price_el is not None else 0
            name_el = offer.find('name')
            name = name_el.text if name_el is not None else ''
            
            cache[sku] = {
                'available': available,
                'stock': stock,       # *, **, ***, ****
                'price': price,       # ціна фіду
                'zakupka': round(price * 0.88, 2),  # наша закупочна
                'name': name,
            }
        
        _feed_cache['data'] = cache
        _feed_cache['updated'] = time.time()
        logger.success(f'Фід завантажено: {len(cache)} товарів')
        return cache
    except Exception as e:
        logger.error(f'Помилка фіду: {e}')
        return {}

def check_availability(sku: str) -> dict | None:
    """Перевіряємо наявність конкретного SKU"""
    feed = load_feed()
    return feed.get(sku.upper())

# =============================================
# 2. PROM API — ЗАМОВЛЕННЯ
# =============================================
def get_new_orders() -> list:
    """Отримуємо нові замовлення зі статусом pending"""
    try:
        resp = requests.get(
            f'{PROM_BASE}/orders/list',
            headers=PROM_HEADERS,
            params={'limit': 50},
            timeout=30
        )
        all_orders = resp.json().get('orders', [])
        from datetime import datetime, timedelta, timezone
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        orders = []
        for o in all_orders:
            if o.get('status') not in ('pending', 'paid'):
                continue
            try:
                d = datetime.fromisoformat(o.get('date_created','').replace('Z','+00:00'))
                if d > cutoff:
                    orders.append(o)
            except:
                pass
        logger.info(f'Нових замовлень: {len(orders)} з {len(all_orders)}')
        return orders
    except Exception as e:
        logger.error(f'Prom API помилка: {e}')
        return []

def confirm_order(order_id: int) -> bool:
    """Підтверджуємо замовлення на Prom"""
    try:
        resp = requests.post(
            f'{PROM_BASE}/orders/set_status',
            headers=PROM_HEADERS,
            json={'ids': [order_id], 'status': 'accepted'},
            timeout=30
        )
        ok = resp.status_code == 200
        if ok:
            logger.success(f'Замовлення #{order_id} підтверджено на Prom')
        else:
            logger.error(f'Помилка підтвердження #{order_id}: {resp.text}')
        return ok
    except Exception as e:
        logger.error(f'Помилка: {e}')
        return False

# =============================================
# 3. БАЗА ДАНИХ — ЗБЕРІГАЄМО ЗАМОВЛЕННЯ
# =============================================
def init_db():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS orders (
        id SERIAL PRIMARY KEY,
        prom_order_id BIGINT UNIQUE NOT NULL,
        status VARCHAR(50) DEFAULT 'new',
        customer_name VARCHAR(200),
        customer_phone VARCHAR(50),
        delivery_city VARCHAR(100),
        delivery_warehouse TEXT,
        delivery_type VARCHAR(100),
        total_price NUMERIC(12,2),
        items JSONB,
        all_available BOOLEAN DEFAULT FALSE,
        supplier_email_sent BOOLEAN DEFAULT FALSE,
        ttn VARCHAR(50),
        notes TEXT,
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW()
    )''')
    conn.commit()
    cur.close(); conn.close()

def save_order(order: dict, items_info: list, all_available: bool):
    conn = get_connection()
    cur = conn.cursor()
    
    # Delivery може бути рядком або словником
    delivery_raw = order.get('delivery_address', '') or ''
    if isinstance(delivery_raw, str):
        delivery_str = delivery_raw
    else:
        city_d = (delivery_raw.get('city') or {}).get('name', '')
        wh_d = (delivery_raw.get('warehouse') or {}).get('description', '')
        delivery_str = f'{city_d} {wh_d}'.strip()
    
    cur.execute('''
        INSERT INTO orders 
        (prom_order_id, status, customer_name, customer_phone,
         delivery_city, delivery_warehouse, delivery_type,
         total_price, items, all_available)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (prom_order_id) DO UPDATE SET
            status=EXCLUDED.status, updated_at=NOW()
        RETURNING id
    ''', (
        order['id'],
        'confirmed' if all_available else 'check_needed',
        f"{order.get('client_last_name','')} {order.get('client_first_name','')}".strip(),
        order.get('phone', '') or order.get('client_phone', ''),
        delivery_str,
        '',
        'Нова Пошта',
        parse_price(order.get('price', 0)),
        json.dumps(items_info, ensure_ascii=False),
        all_available
    ))
    conn.commit()
    cur.close(); conn.close()

# =============================================
# 4. EXCEL БЛАНК ЗАМОВЛЕННЯ
# =============================================
def create_order_excel(order: dict, items_info: list) -> str:
    """Формат бланку Гранд Інструмент"""
    filename = f'/tmp/order_{order["id"]}_{datetime.now().strftime("%Y%m%d_%H%M")}.xlsx'
    
    wb = xlsxwriter.Workbook(filename)
    ws = wb.add_worksheet('Замовлення')
    
    # Формати
    bold = wb.add_format({'bold': True, 'font_size': 11})
    header_fmt = wb.add_format({'bold': True, 'bg_color': '#1F4E79', 'font_color': 'white', 
                                 'border': 1, 'align': 'center'})
    cell_fmt = wb.add_format({'border': 1})
    sku_fmt = wb.add_format({'border': 1, 'bold': True})
    red_bold = wb.add_format({'bold': True, 'font_color': 'red'})
    wrap_fmt = wb.add_format({'text_wrap': True})
    
    # Ширина стовпців
    ws.set_column('A:A', 5)
    ws.set_column('B:B', 22)
    ws.set_column('C:C', 55)
    ws.set_column('D:D', 14)
    
    # Дані замовлення
    delivery_raw = order.get('delivery_address', '') or ''
    if isinstance(delivery_raw, str):
        delivery_str = delivery_raw
    else:
        city_d = (delivery_raw.get('city') or {}).get('name', '')
        wh_d = (delivery_raw.get('warehouse') or {}).get('description', '')
        delivery_str = f'{city_d} {wh_d}'.strip()
    customer = f"{order.get('client_last_name','')} {order.get('client_first_name','')}".strip()
    phone = order.get('phone', '') or order.get('client_phone', '')
    total = parse_price(order.get('price', 0))
    
    # Шапка
    ws.write('A1', 'Перевозчик', bold)
    ws.write('C1', 'Новая Почта')
    ws.write('A2', 'Оплата', bold)
    ws.write('C2', f'Наложенным платежом {total:.0f} грн')
    ws.write('A3', 'Коментарий', bold)
    ws.write('C3', f'{customer}  {phone}\n{delivery_str}', wrap_fmt)
    ws.set_row(2, 35)
    marketplace = order.get('marketplace', 'Prom')
    ws.write('A4', f'Замовлення {marketplace} #{order["id"]}')
    ws.write('C4', f'Дата: {datetime.now().strftime("%d.%m.%Y %H:%M")}')
    ws.write('A5', f'Код клієнта: {SUPPLIER_CODE}', red_bold)
    
    # Заголовки таблиці
    row = 6
    for col, h in enumerate(['№', 'Артикул', 'Наименование', 'Количество']):
        ws.write(row, col, h, header_fmt)
    
    # Товари
    for i, item in enumerate(items_info):
        row += 1
        ws.write(row, 0, i+1, cell_fmt)
        ws.write(row, 1, item['sku'], sku_fmt)
        ws.write(row, 2, item['name'][:80], cell_fmt)
        ws.write(row, 3, item['quantity'], cell_fmt)
    
    wb.close()
    logger.success(f'Excel бланк: {filename}')
    return filename

# =============================================
# 5. ВІДПРАВКА EMAIL ПОСТАЧАЛЬНИКУ
# =============================================
def send_to_supplier(order: dict, excel_path: str, items_info: list):
    """Відправляємо замовлення на opt@grandinstrument.ua"""
    delivery_raw = order.get('delivery_address', '') or ''
    if isinstance(delivery_raw, str):
        delivery_str = delivery_raw
    else:
        city_d = (delivery_raw.get('city') or {}).get('name', '')
        wh_d = (delivery_raw.get('warehouse') or {}).get('description', '')
        delivery_str = f'{city_d} {wh_d}'.strip()
    customer = f"{order.get('client_last_name','')} {order.get('client_first_name','')}".strip()
    phone = order.get('phone', '') or order.get('client_phone', '')
    total = parse_price(order.get('price', 0))
    payment = order.get('payment_option') or {}
    payment_name = payment.get('name', '') if isinstance(payment, dict) else str(payment)
    is_prepaid = any(w in payment_name.lower() for w in ['пром-оплата', 'онлайн', 'картк'])
    marketplace = order.get('marketplace', 'Prom')
    payment_str = f'Передоплата ({marketplace}) {total:.0f} грн' if is_prepaid else f'Наложенным платежом {total:.0f} грн'
    
    items_text = '\n'.join([
        f"{i+1}. {it['sku']} | {it['name'][:50]} | {it['quantity']} шт."
        for i, it in enumerate(items_info)
    ])
    
    body = f"""Добрый день!

Заказ #{order['id']}
Код клиента: {SUPPLIER_CODE}

Товары:
{items_text}

Получатель: {customer}
Телефон: {phone}
Доставка: {delivery_str}
Оплата: {payment_str}

Детали в приложении (Excel).

С уважением,
klatch1.shop"""
    
    msg = MIMEMultipart()
    msg['From'] = SMTP_USER
    msg['To'] = SUPPLIER_EMAIL
    msg['Subject'] = f'Заказ #{order["id"]} от {datetime.now().strftime("%d.%m.%Y")}'
    msg.attach(MIMEText(body, 'plain', 'utf-8'))
    
    with open(excel_path, 'rb') as f:
        part = MIMEBase('application', 'octet-stream')
        part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header('Content-Disposition',
            f'attachment; filename="{os.path.basename(excel_path)}"')
        msg.attach(part)
    
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
        s.starttls()
        s.login(SMTP_USER, SMTP_PASS)
        s.send_message(msg)
    
    # Оновлюємо БД
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        'UPDATE orders SET supplier_email_sent=TRUE, updated_at=NOW() WHERE prom_order_id=%s',
        (order['id'],)
    )
    conn.commit()
    cur.close(); conn.close()
    logger.success(f'Email відправлено на {SUPPLIER_EMAIL}')

# =============================================
# TELEGRAM СПОВІЩЕННЯ
# =============================================
TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_ADMIN = os.getenv('TELEGRAM_ADMIN_ID')

def tg(text: str, emoji: str = ''):
    """Відправляємо повідомлення в Telegram"""
    try:
        requests.post(
            f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage',
            json={'chat_id': TELEGRAM_ADMIN, 'text': f'{emoji} {text}'.strip(), 'parse_mode': 'HTML'},
            timeout=10
        )
    except Exception as e:
        logger.error(f'Telegram помилка: {e}')

def notify_new_order(order: dict, items_info: list, payment_type: str):
    """Сповіщення про нове замовлення"""
    items_text = '\n'.join([
        f"  • {i['sku']} x{i['quantity']} — {'✅ є' if i['feed_available'] else '❌ немає'}"
        for i in items_info
    ])
    
    is_prepaid = any(w in payment_type.lower() for w in ['пром-оплата', 'онлайн', 'картк', 'liqpay'])
    
    if is_prepaid:
        zakupka_total = sum(i.get('zakupka',0) * i.get('quantity',1) for i in items_info)
        tg(f"""⚠️ <b>ПРОМ-ОПЛАТА!</b> Замовлення #{order['id']}
Покупець вже заплатив — потрібна передплата постачальнику!

👤 {order.get('client_last_name','')} {order.get('client_first_name','')}
💰 Сума: {order.get('price','')} грн
💳 Оплата: {payment_type}
📦 Товари:
{items_text}

🏦 Перекажи постачальнику: ~{zakupka_total:.0f} грн\nopt@grandinstrument.ua""")
    else:
        all_ok = all(i['feed_available'] for i in items_info)
        status = '✅ Всі в наявності' if all_ok else '⚠️ Є проблеми з наявністю'
        tg(f"""🛒 <b>Нове замовлення #{order['id']}</b>
👤 {order.get('client_last_name','')} {order.get('client_first_name','')}
💰 {order.get('price','')} грн | {payment_type}
📦 Товари:
{items_text}
{status}""")

def notify_stock_problem(order_id: int, missing_skus: list):
    """Сповіщення коли товар відсутній"""
    tg(f"""❌ <b>Замовлення #{order_id} — товар відсутній!</b>
Відсутні артикули:
{chr(10).join(f'  • {s}' for s in missing_skus)}

Перевір наявність вручну і прийми рішення.""")

def notify_order_sent(order_id: int, excel_file: str):
    """Сповіщення що замовлення відправлено постачальнику"""
    tg(f"""📧 <b>Замовлення #{order_id} відправлено постачальнику</b>
Email: {SUPPLIER_EMAIL}
Excel: {os.path.basename(excel_file)}
✅ Чекай підтвердження від Русанова""")
# =============================================
# 6. ГОЛОВНИЙ ЦИКЛ
# =============================================
def process_orders():
    init_db()
    logger.info('=== Обробка замовлень Prom ===')
    
    orders = get_new_orders()
    if not orders:
        logger.info('Нових замовлень немає')
        return
    
    # Фільтруємо вже оброблені з БД
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('SELECT prom_order_id FROM orders WHERE supplier_email_sent=TRUE')
    processed = {r['prom_order_id'] for r in cur.fetchall()}
    cur.close(); conn.close()
    orders = [o for o in orders if o['id'] not in processed]
    logger.info(f'До обробки (нові): {len(orders)}')
    if not orders:
        logger.info('Всі замовлення вже оброблені')
        return
    
    for order in orders:
        oid = order['id']
        logger.info(f'--- Замовлення #{oid} ---')
        
        products = order.get('products', [])
        items_info = []
        all_available = True
        
        for product in products:
            sku = (product.get('sku') or '').strip()
            qty = product.get('quantity', 1)
            avail = check_availability(sku)
            
            info = {
                'sku': sku,
                'name': product.get('name', ''),
                'quantity': qty,
                'prom_price': float(str(product.get('price', 0)).replace(' грн','').replace(',','.').split()[0]),
                'feed_available': avail['available'] if avail else False,
                'feed_stock': avail['stock'] if avail else '—',
                'zakupka': avail['zakupka'] if avail else 0,
            }
            items_info.append(info)
            
            if not avail or not avail['available']:
                all_available = False
                logger.warning(f'  ❌ {sku} — немає в наявності!')
            else:
                logger.info(f'  ✅ {sku} — є ({avail["stock"]})')
        
        # Тип оплати
        payment = order.get('payment_option') or {}
        payment_type = payment.get('name', 'Накладений платіж') if isinstance(payment, dict) else str(payment)
        
        # Зберігаємо в БД
        save_order(order, items_info, all_available)
        
        # Telegram сповіщення
        notify_new_order(order, items_info, payment_type)
        
        if all_available:
            # Підтверджуємо на Prom
            if confirm_order(oid):
                try:
                    excel = create_order_excel(order, items_info)
                    send_to_supplier(order, excel, items_info)
                    notify_order_sent(oid, excel)
                    logger.success(f'✅ Замовлення #{oid} — оброблено повністю')
                except Exception as e:
                    logger.error(f'Помилка відправки: {e}')
        else:
            missing = [i['sku'] for i in items_info if not i['feed_available']]
            notify_stock_problem(oid, missing)
            logger.warning(f'⚠️ Замовлення #{oid} — відсутні: {missing}')

if __name__ == '__main__':
    process_orders()


````

### `agents/orders/order_agent_daemon.py` — 51 рядків

````python
"""
Order Agent Daemon — нескінченний цикл з watchdog
Запускається через systemd, перезапускається автоматично
"""
import sys, os, time, requests, traceback
sys.path.append('/home/tek/agent-system')
from dotenv import load_dotenv; load_dotenv('/home/tek/agent-system/.env')
from loguru import logger

TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_ADMIN = os.getenv('TELEGRAM_ADMIN_ID')
INTERVAL = 300  # 5 хвилин

def tg(text: str):
    try:
        requests.post(
            f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage',
            json={'chat_id': TELEGRAM_ADMIN, 'text': text, 'parse_mode': 'HTML'},
            timeout=10
        )
    except:
        pass

def main():
    tg('🟢 <b>Order Agent запущено</b>\nАвтоматична обробка замовлень активна\nІнтервал: 5 хвилин')
    logger.info('=== Order Agent Daemon старт ===')
    
    consecutive_errors = 0
    
    while True:
        try:
            from agents.orders.order_agent import process_orders
            process_orders()
            consecutive_errors = 0
            
        except Exception as e:
            consecutive_errors += 1
            error_msg = traceback.format_exc()
            logger.error(f'Помилка #{consecutive_errors}: {e}')
            
            tg(f'⚠️ <b>Order Agent помилка #{consecutive_errors}</b>\n{str(e)[:200]}')
            
            if consecutive_errors >= 5:
                tg('🔴 <b>Order Agent критична помилка!</b>\n5 помилок підряд — перезапуск через systemd')
                sys.exit(1)  # systemd перезапустить
        
        logger.info(f'Очікуємо {INTERVAL} сек...')
        time.sleep(INTERVAL)

if __name__ == '__main__':
    main()

````

### `agents/orders/price_updater.py` — 393 рядків

````python
"""
agents/orders/price_updater.py
================================
Щоденне оновлення цін на Prom.ua

Алгоритм:
1. Завантажує XML фід TOPTUL
2. Порівнює ціни фіду з БД
3. Для кожного зміненого товару — бере реальну CPA з prom_cpa_rates
   (через prom_category_name або prom_group_name → fuzzy match)
4. Розраховує нову ціну: РРЦ / (1 - CPA)
5. Оновлює змінені ціни на Prom через API батчами по 100
6. Telegram звіт

Запуск:
    python3 agents/orders/price_updater.py              # стандартний
    python3 agents/orders/price_updater.py --force      # переоцінити всі товари
    python3 agents/orders/price_updater.py --dry-run    # без запису змін
    python3 agents/orders/price_updater.py --limit 100  # тільки N товарів

Cron: 0 8 * * * (щодня о 8:00)
"""
import os, sys, requests, json, time, argparse
import xml.etree.ElementTree as ET
from loguru import logger

sys.path.append('/home/tek/agent-system')
from dotenv import load_dotenv
load_dotenv('/home/tek/agent-system/.env')
from shared.utils.db import get_connection
from shared.utils.pricing import calc_price, get_prom_cpa, DEFAULT_PROM_CPA

PROM_TOKEN = os.getenv('PROM_API_TOKEN')
PROM_HEADERS = {'Authorization': f'Bearer {PROM_TOKEN}'}
PROM_BASE = 'https://my.prom.ua/api/v1'

TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_ADMIN = os.getenv('TELEGRAM_ADMIN_ID')

TOPTUL_FEED = (
    'https://toptul.online/products_feed.xml?'
    'hash_tag=442309995a1416e3104d287504a1846f'
    '&label_ids=3882792&html_description=1&languages=uk,ru'
)

MIN_PRICE = 40.0
ROUND_TO = 10


def tg(text: str):
    try:
        requests.post(
            f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage',
            json={'chat_id': TELEGRAM_ADMIN, 'text': text, 'parse_mode': 'HTML'},
            timeout=10
        )
    except Exception as e:
        logger.error(f'Telegram: {e}')


# =============================================
# 1. ФІД TOPTUL
# =============================================

def load_feed() -> dict:
    """Завантажує XML фід TOPTUL. SKU береться з <vendorCode>."""
    logger.info('Завантажуємо фід TOPTUL...')
    try:
        resp = requests.get(TOPTUL_FEED, timeout=120)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        offers = root.find('shop').find('offers').findall('offer')

        feed = {}
        for offer in offers:
            sku_el = offer.find('vendorCode')
            sku = (sku_el.text or '').strip() if sku_el is not None else ''
            if not sku:
                sku = (offer.get('id') or '').upper()
            if not sku:
                continue

            price_el = offer.find('price')
            price = float(price_el.text) if price_el is not None else 0.0
            available = offer.get('available', 'true') == 'true'
            stock_el = offer.find('stock_quantity')
            stock = stock_el.text if stock_el is not None else '*'

            feed[sku.upper()] = {
                'price': price,
                'available': available,
                'stock': stock,
            }

        logger.success(f'Фід завантажено: {len(feed)} товарів')
        return feed

    except Exception as e:
        logger.error(f'Помилка завантаження фіду: {e}')
        return {}


# =============================================
# 2. PROM API — ЗАВАНТАЖЕННЯ ТОВАРІВ
# =============================================

def load_prom_map() -> dict:
    """
    Завантажує всі товари з Prom API.
    Повертає dict: SKU → {id, price}
    """
    logger.info('Завантажуємо товари з Prom API...')
    prom_map = {}
    last_id = None

    while True:
        params = {'limit': 100}
        if last_id:
            params['last_id'] = last_id

        try:
            resp = requests.get(
                f'{PROM_BASE}/products/list',
                headers=PROM_HEADERS,
                params=params,
                timeout=30
            )
            resp.raise_for_status()
            products = resp.json().get('products', [])
        except Exception as e:
            logger.error(f'Prom API помилка: {e}')
            break

        if not products:
            break

        for p in products:
            sku = (p.get('sku') or '').strip().upper()
            if sku:
                prom_map[sku] = {
                    'id': p.get('id'),
                    'price': float(p.get('price') or 0),
                }

        last_id = products[-1]['id']
        if len(products) < 100:
            break

        time.sleep(0.35)

    logger.success(f'Prom API: {len(prom_map)} товарів з SKU')
    return prom_map


# =============================================
# 3. БД — ЗАВАНТАЖЕННЯ ТОВАРІВ
# =============================================

def load_db_products(limit: int = None, force: bool = False) -> list:
    """
    Завантажує товари з БД.

    Args:
        limit: обмеження кількості (None = всі)
        force: True = всі товари, False = тільки ті де ціна фіду змінилась

    Returns:
        list of dicts: id, sku, price_supplier, price_our,
                       prom_category_name, prom_group_name, prom_id
    """
    conn = get_connection()
    cur = conn.cursor()

    # Перевіряємо чи є колонки категорій (можуть бути відсутні до fetch_prom_categories)
    cur.execute('''
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'my_products'
        AND column_name IN ('prom_category_name', 'prom_group_name', 'prom_id')
    ''')
    existing_cols = {r['column_name'] for r in cur.fetchall()}

    select_extra = ''
    if 'prom_category_name' in existing_cols:
        select_extra += ', prom_category_name'
    if 'prom_group_name' in existing_cols:
        select_extra += ', prom_group_name'
    if 'prom_id' in existing_cols:
        select_extra += ', prom_id'

    query = f'''
        SELECT id, sku, price_supplier, price_our{select_extra}
        FROM my_products
        WHERE price_supplier IS NOT NULL AND price_supplier > 0
    '''

    if limit:
        query += f' LIMIT {int(limit)}'

    cur.execute(query)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    logger.info(f'БД: завантажено {len(rows)} товарів')
    return [dict(r) for r in rows]


# =============================================
# 4. ГОЛОВНА ЛОГІКА ОНОВЛЕННЯ ЦІН
# =============================================

def run(force: bool = False, dry_run: bool = False, limit: int = None):
    logger.info('=== Price Updater старт ===')
    if force:
        logger.info('Режим --force: переоцінюємо всі товари')
    if dry_run:
        logger.info('Режим --dry-run: без запису змін')

    # Завантажуємо дані
    feed = load_feed()
    if not feed:
        tg('⚠️ <b>Price Updater</b>: не вдалось завантажити фід TOPTUL')
        return

    prom_map = load_prom_map()
    db_products = load_db_products(limit=limit)

    conn = get_connection()
    cur = conn.cursor()

    changed = []        # список змін для звіту
    price_updates = []  # список для Prom API батч-оновлення
    cpa_used = {}       # статистика яких CPA використано

    for product in db_products:
        sku = (product.get('sku') or '').strip().upper()
        if not sku:
            continue

        feed_info = feed.get(sku)
        if not feed_info:
            continue  # товар є в БД але не в фіді — пропускаємо

        new_feed_price = feed_info['price']
        old_feed_price = float(product.get('price_supplier') or 0)
        old_our_price = float(product.get('price_our') or 0)

        # Перевіряємо чи змінилась ціна фіду (або force режим)
        price_changed = abs(new_feed_price - old_feed_price) >= 0.5
        if not force and not price_changed:
            continue

        # Визначаємо CPA для цього товару
        # Пріоритет: prom_category_name → prom_group_name → DEFAULT
        prom_category = (product.get('prom_category_name') or '').strip()
        prom_group = (product.get('prom_group_name') or '').strip()

        cpa_source = 'default'
        if prom_category:
            cpa = get_prom_cpa(prom_category)
            if cpa != DEFAULT_PROM_CPA:
                cpa_source = f'category:{prom_category}'
            elif prom_group:
                cpa = get_prom_cpa(prom_group)
                if cpa != DEFAULT_PROM_CPA:
                    cpa_source = f'group:{prom_group}'
        elif prom_group:
            cpa = get_prom_cpa(prom_group)
            if cpa != DEFAULT_PROM_CPA:
                cpa_source = f'group:{prom_group}'
        else:
            cpa = DEFAULT_PROM_CPA

        # Рахуємо нову ціну
        new_our_price = calc_price(new_feed_price, cpa)

        # Перевіряємо чи змінилась наша ціна
        if not force and abs(new_our_price - old_our_price) < 1.0:
            continue

        diff_pct = ((new_feed_price - old_feed_price) / old_feed_price * 100) if old_feed_price > 0 else 0

        change = {
            'sku': sku,
            'old_feed': old_feed_price,
            'new_feed': new_feed_price,
            'old_our': old_our_price,
            'new_our': new_our_price,
            'diff_pct': diff_pct,
            'cpa': cpa,
            'cpa_source': cpa_source,
        }
        changed.append(change)

        # Статистика CPA
        cpa_key = f'{cpa*100:.2f}%'
        cpa_used[cpa_key] = cpa_used.get(cpa_key, 0) + 1

        if not dry_run:
            # Оновлюємо БД
            cur.execute(
                'UPDATE my_products SET price_supplier=%s, price_our=%s WHERE sku=%s',
                (new_feed_price, new_our_price, product['sku'])
            )

            # Готуємо для Prom API
            prom_info = prom_map.get(sku)
            if prom_info and abs(prom_info['price'] - new_our_price) >= 1.0:
                price_updates.append({'id': prom_info['id'], 'price': new_our_price})

    if not dry_run:
        conn.commit()

    cur.close()
    conn.close()

    logger.info(f'Змін цін: {len(changed)}')
    logger.info(f'CPA розподіл: {cpa_used}')

    if not changed:
        logger.success('Ціни актуальні — змін немає')
        return

    # Оновлюємо ціни на Prom батчами
    updated_prom = 0
    if not dry_run and price_updates:
        logger.info(f'Оновлюємо {len(price_updates)} цін на Prom...')
        for i in range(0, len(price_updates), 100):
            batch = price_updates[i:i+100]
            try:
                resp = requests.post(
                    f'{PROM_BASE}/products/edit',
                    headers=PROM_HEADERS,
                    json=batch,
                    timeout=30
                )
                if resp.status_code == 200:
                    processed = resp.json().get('processed_ids', [])
                    updated_prom += len(processed)
                    logger.success(f'Prom батч {i//100+1}: оновлено {len(processed)}')
                else:
                    logger.error(f'Prom API помилка: {resp.status_code} {resp.text[:200]}')
            except Exception as e:
                logger.error(f'Prom API батч помилка: {e}')
            time.sleep(0.5)

    # Звіт
    up = [c for c in changed if c['diff_pct'] > 0]
    down = [c for c in changed if c['diff_pct'] < 0]
    forced = [c for c in changed if c['diff_pct'] == 0]

    cpa_stat_str = ', '.join([f'{k}:{v}шт' for k, v in sorted(cpa_used.items())])

    msg = f'''📊 <b>Price Updater — звіт</b>

Всього змін: {len(changed)}
📈 Подорожчало: {len(up)}
📉 Подешевшало: {len(down)}
🔄 Переоцінено: {len(forced)}
✅ Оновлено на Prom: {updated_prom}

📌 CPA: {cpa_stat_str}'''

    if dry_run:
        msg += '\n\n⚠️ DRY RUN — зміни не застосовані'

    # Топ змін
    if up:
        top_up = sorted(up, key=lambda x: -abs(x['diff_pct']))[:3]
        msg += '\n\n📈 Подорожчало (топ 3):'
        for c in top_up:
            msg += f'\n  {c["sku"]}: {c["old_our"]:.0f}→{c["new_our"]:.0f} грн ({c["diff_pct"]:+.1f}%) CPA={c["cpa"]*100:.1f}%'

    if down:
        top_down = sorted(down, key=lambda x: abs(x['diff_pct']))[:3]
        msg += '\n\n📉 Подешевшало (топ 3):'
        for c in top_down:
            msg += f'\n  {c["sku"]}: {c["old_our"]:.0f}→{c["new_our"]:.0f} грн ({c["diff_pct"]:+.1f}%) CPA={c["cpa"]*100:.1f}%'

    logger.success(msg.replace('<b>', '').replace('</b>', ''))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Price Updater — оновлення цін на Prom')
    parser.add_argument('--force', action='store_true',
                        help='Переоцінити всі товари (навіть якщо ціна не змінилась)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Показати зміни без запису')
    parser.add_argument('--limit', type=int, default=None,
                        help='Обмеження кількості товарів (для тесту)')
    args = parser.parse_args()

    run(force=args.force, dry_run=args.dry_run, limit=args.limit)

````
