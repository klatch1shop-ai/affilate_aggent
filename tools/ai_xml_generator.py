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
    <category code="2866">Автомагнітоли</category>
    <attribute_set code="2866">Автомагнітоли</attribute_set>
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
