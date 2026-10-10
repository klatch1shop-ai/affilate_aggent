/* Оболонка: маршрутизація по хешу, малювання сторінок з data.json
   і commands.json. Жодне число не зашите в розмітку — усе з даних,
   інакше сторінка тихо розійдеться з дійсністю, як це вже було з
   описом системи. */

const NAV = [
  { g: 'Огляд' },
  { id: 'oglyad',      t: 'Головна' },
  { id: 'majdanchyky', t: 'Майданчики' },
  { g: 'Операції' },
  { id: 'zamovlennya', t: 'Замовлення' },
  { id: 'kartky',      t: 'Картки товарів' },
  { id: 'klyuchi',     t: 'Ключові слова' },
  { g: 'Керування' },
  { id: 'pult',        t: 'Пульт' },
  { id: 'zavdannya',   t: 'Дошка завдань' },
  { id: 'chat',        t: 'Чат' },
  { id: 'komandy',     t: 'Команди API' },
  { g: 'Система' },
  { id: 'audyt',       t: 'Аудит коду' },
  { id: 'doshka',      t: 'Дошка' },
];

const el = (h) => { const d = document.createElement('div'); d.innerHTML = h.trim(); return d.firstChild; };
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const nf = (n) => new Intl.NumberFormat('uk-UA').format(n);

let D = null, C = null;

/* ── тема ─────────────────────────────────────────────────── */
function initTheme() {
  let t = null;
  try { t = localStorage.getItem('theme'); } catch (e) { /* приватне вікно */ }
  if (t) document.documentElement.dataset.theme = t;
  else document.documentElement.removeAttribute('data-theme');
  document.getElementById('theme').onclick = () => {
    const cur = document.documentElement.dataset.theme;
    const dark = cur ? cur === 'dark'
      : matchMedia('(prefers-color-scheme: dark)').matches;
    const next = dark ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem('theme', next); } catch (e) {}
  };
}

/* ── панель і маршрути ────────────────────────────────────── */
function buildNav() {
  const n = document.getElementById('nav');
  NAV.forEach(it => {
    if (it.g) { n.append(el(`<div class="rail__group">${esc(it.g)}</div>`)); return; }
    const a = el(`<a class="navlink" href="#${it.id}"><span class="dot"></span>${esc(it.t)}<span class="n" data-n="${it.id}"></span></a>`);
    n.append(a);
  });
}

function route() {
  const id = (location.hash || '#oglyad').slice(1);
  const target = document.getElementById('v-' + id) ? id : 'oglyad';
  document.querySelectorAll('.view').forEach(v => v.classList.toggle('is-on', v.id === 'v-' + target));
  document.querySelectorAll('.navlink').forEach(a => {
    const on = a.getAttribute('href') === '#' + target;
    on ? a.setAttribute('aria-current', 'page') : a.removeAttribute('aria-current');
  });
  document.getElementById('rail').classList.remove('is-open');
  window.scrollTo({ top: 0, behavior: 'instant' in document.body.style ? 'instant' : 'auto' });
}

/* ── сторінки ─────────────────────────────────────────────── */
function fig(v, k, n) {
  return `<div><div class="fig__v">${esc(v)}</div><div class="fig__k">${esc(k)}</div>${n ? `<div class="fig__n">${esc(n)}</div>` : ''}</div>`;
}
function head(eyebrow, h2, p) {
  return `<div class="sec__head"><div class="eyebrow">${esc(eyebrow)}</div><h2>${esc(h2)}</h2>${p ? `<p>${p}</p>` : ''}</div>`;
}
function sec(inner) { return `<section class="sec">${inner}</section>`; }

function drawHero() {
  const s = D.система, k = D.картки_єпіцентр;
  document.getElementById('hero-figs').innerHTML =
    fig(nf(s.файлів_py), 'файлів коду', `${s.у_cron_або_службі} працюють самі`) +
    fig(String(D.конвеєри.length), 'конвеєри замовлень', 'за розкладом, без людини') +
    fig(nf(k.усього), 'карток на Єпіцентрі', `${nf(k.склад[0].скільки)} наших`) +
    fig(nf(D.майданчики.reduce((a, m) => a + m.методів_використовуємо, 0)), 'методів API задіяно',
        `з ${nf(D.майданчики.reduce((a, m) => a + m.методів_api, 0))} доступних`);
  document.getElementById('b-date').textContent =
    D.оновлено.split('-').reverse().join('.');
  document.getElementById('stamp').textContent = 'зріз ' + D.оновлено.slice(5).split('-').reverse().join('.');

  document.getElementById('t-audit').innerHTML =
    `<thead><tr><th>Що</th><th>Деталі</th><th>Стан</th></tr></thead><tbody>` +
    D.аудит_знайшов.map(a => `<tr><td>${esc(a.що)}</td><td>${esc(a.деталі)}</td>
      <td><span class="pill ${a.стан === 'виправлено' ? 'ok' : 'warn'}">${esc(a.стан)}</span></td></tr>`).join('') +
    `</tbody></table>`;
}

function drawMarkets() {
  const v = document.querySelector('#v-majdanchyky .sec');
  const cards = D.майданчики.map(m => {
    const part = m.методів_api ? Math.round(m.методів_використовуємо / m.методів_api * 100) : 0;
    return `<div class="card">
      <div style="display:flex;align-items:center;gap:12px;margin-bottom:8px">
        <h3 style="margin:0">${esc(m.назва)}</h3>
        <span class="pill ${m.стан.startsWith('продає') ? 'ok' : 'cool'}">${esc(m.стан)}</span>
      </div>
      <dl class="kv">
        <dt>постачальники</dt><dd>${m.постачальники.length ? m.постачальники.map(esc).join(', ') : '—'}</dd>
        <dt>замовлення</dt><dd>${esc(m.замовлення)}</dd>
        <dt>методи API</dt><dd>${m.методів_api ? `задіяно ${m.методів_використовуємо} з ${m.методів_api}
          <div class="bar"><i style="width:${Math.max(part, 2)}%"></i></div>` : 'немає доступу'}</dd>
      </dl>
      <div class="note" style="margin-bottom:0">${esc(m.примітка)}</div>
    </div>`;
  }).join('');
  v.innerHTML = head('Де ми продаємо', 'Чотири майданчики, різні правила',
    'Кожен має свій API, свої статуси й свою логіку оплати. Спільне тільки ядро накладних.')
    + `<div class="grid g2">${cards}</div>`
    + sec(head('Чому важливо', 'Методів доступно набагато більше, ніж ми беремо',
      'Це не докір: більшість методів нам не потрібні. Але серед невикористаних є ті, що прямо впливають на гроші — створення накладних самим майданчиком і відповіді на відгуки.'));
}

function drawOrders() {
  const v = document.querySelector('#v-zamovlennya .sec');
  v.innerHTML = head('Конвеєри', 'Замовлення веде розклад, а не людина',
    'Хвилини розведені навмисно: кошик у CRM постачальника один на акаунт, і два конвеєри одночасно зіпсували б закупівлю.')
    + `<div class="tablewrap"><table><thead><tr><th>Конвеєр</th><th>Розклад</th><th>Файл</th></tr></thead><tbody>`
    + D.конвеєри.map(c => `<tr><td>${esc(c.назва)}</td><td>${esc(c.розклад)}</td><td><code>${esc(c.файл)}</code></td></tr>`).join('')
    + `</tbody></table></div>`
    + sec(head('Постійні служби', 'Що крутиться безперервно', '')
      + `<div class="tablewrap"><table><thead><tr><th>Служба</th><th>Призначення</th><th>Стан</th></tr></thead><tbody>`
      + D.служби.map(s => `<tr><td><code>${esc(s.назва)}</code></td><td>${esc(s.що)}</td>
          <td><span class="pill ${s.стан === 'працює' ? 'ok' : 'warn'}">${esc(s.стан)}</span></td></tr>`).join('')
      + `</tbody></table></div>`
      + `<div class="note"><b>Три стани наявності, а не два.</b> «Є», «немає» і «не знаю» —
         різні речі. Порожній фід постачальника означає «не знаю», і за ним не можна
         скасовувати замовлення: саме так колись скасували те, що було в наявності.</div>`);
}

function drawCards() {
  const v = document.querySelector('#v-kartky .sec');
  const k = D.картки_єпіцентр;
  const max = Math.max(...k.noire_за_статусом.map(s => s.скільки));
  v.innerHTML = head('Єпіцентр', 'Де насправді наші картки',
    `У кабінеті ${nf(k.усього)} карток, але наших із них ${nf(k.склад[0].скільки)}. Решта — постачальники, які тут лише щоб їх не видалили.`)
    + `<div class="figs" style="margin-top:0">`
    + fig(nf(k.склад[0].скільки), 'карток NOIRE', `з фіду на ${nf(k.фід_позицій)} позицій`)
    + fig(nf(k.noire_за_статусом[0].скільки), 'опубліковано', k.noire_за_статусом[0].частка + '% від наших')
    + fig(nf(k.не_опубліковано), 'не продаються', 'найбільший шматок — модерація')
    + fig(nf(k.позицій_без_картки), 'позицій без картки', 'товару на майданчику немає')
    + `</div>`
    + sec(head('Розклад за статусом', 'Що саме заважає продавати',
      'Модерація — це не робота, це час: картки вже подані. Реальна робота менша, ніж здається.')
      + `<div class="tablewrap"><table><thead><tr><th>Статус</th><th class="num">Карток</th><th style="width:42%">Частка</th></tr></thead><tbody>`
      + k.noire_за_статусом.map(s => `<tr><td>${esc(s.статус)}</td><td class="num">${nf(s.скільки)}</td>
          <td>${s.частка}%<div class="bar ${s.статус === 'опубліковано' ? '' : 'cool'}"><i style="width:${Math.round(s.скільки / max * 100)}%"></i></div></td></tr>`).join('')
      + `</tbody></table></div>`)
    + sec(head('Склад кабінету', 'Чому карток так багато', '')
      + `<div class="tablewrap"><table><thead><tr><th>Кому належать</th><th class="num">Карток</th></tr></thead><tbody>`
      + k.склад.map(s => `<tr><td>${esc(s.хто)}</td><td class="num">${nf(s.скільки)}</td></tr>`).join('')
      + `</tbody></table></div>`
      + `<div class="note"><b>Пастка, на якій легко помилитись.</b> Фід Єпіцентру — ${nf(k.фід_позицій)} позицій,
         фід Rozetka — 4147. Це різні сукупності; звірка карток Єпіцентру з фідом Rozetka
         дає 3862 замість ${nf(k.склад[0].скільки)}, тобто втричі меншу картину.</div>`);
}

function drawKeys() {
  const v = document.querySelector('#v-klyuchi .sec');
  const p = D.prom_ключі, last = p[p.length - 1];
  v.innerHTML = head('Prom', 'Картки перестали конкурувати самі з собою',
    'Той самий ключ на тисячі карток означає, що жодна не виграє. Переробка двома мовами на 5400 картках коштувала $0,46 за 532 картки.')
    + `<div class="figs" style="margin-top:0">`
    + fig(last.кабінет + '%', 'карток без унікального ключа', 'у кабінеті, було 65,8%')
    + fig(last.фід + '%', 'те саме у фіді', 'кабінет наздоганяє нічним імпортом')
    + `</div>`
    + sec(head('Як рухалось', 'Три заміри', '')
      + `<div class="tablewrap"><table><thead><tr><th>Дата</th><th class="num">Кабінет</th><th class="num">Фід</th><th style="width:38%"></th></tr></thead><tbody>`
      + p.map(r => `<tr><td>${esc(r.дата)}</td><td class="num">${r.кабінет}%</td><td class="num">${r.фід}%</td>
          <td><div class="bar"><i style="width:${r.кабінет}%"></i></div></td></tr>`).join('')
      + `</tbody></table></div>`
      + `<div class="note"><b>Чого ми не знаємо.</b> Що ключі стали унікальні — доведено.
         Що картки стали знаходитись — ні: у Prom API немає жодного методу статистики,
         перевірено дванадцять варіантів шляху проти негативного контролю. Єдине джерело —
         кабінет власника.</div>`);
}

function drawCommands() {
  const v = document.querySelector('#v-komandy .sec');
  const groups = [...new Set(C.команди.map(c => c.майданчик))];
  v.innerHTML = head('СУПЕРБОТ', 'Вісімнадцять команд через Telegram',
    'Кожна команда — це метод API майданчика. Читання виконується одразу. Зміна даних і витрата грошей проходять через підтвердження з показом параметрів.')
    + `<div class="tabs" id="cmdtabs">`
    + `<button class="tab is-on" data-f="всі">усі · ${C.команди.length}</button>`
    + groups.map(g => `<button class="tab" data-f="${esc(g)}">${esc(g)} · ${C.команди.filter(c => c.майданчик === g).length}</button>`).join('')
    + `</div><div id="cmdlist"></div>`;

  const list = document.getElementById('cmdlist');
  const render = (f) => {
    const rows = C.команди.filter(c => f === 'всі' || c.майданчик === f);
    list.innerHTML = rows.map(c => `
      <div class="cmd">
        <div class="cmd__h">
          <span class="cmd__n">${esc(c.команда)}</span>
          <span class="pill cool">${esc(c.майданчик)}</span>
          <span class="pill ${c.ризик === 'R0' ? 'ok' : c.ризик === 'R2' ? 'warn' : 'bad'}">${esc(c.ризик)} · ${esc(c.ризик_що)}</span>
          ${c.підтвердження ? '<span class="pill warn">потрібне підтвердження</span>' : ''}
        </div>
        <div class="cmd__b">
          <div>${esc(c.що)}</div>
          ${c.параметри.length ? `<div style="margin-top:10px;font-size:13.5px;color:var(--ink-3)">параметри:
             ${c.параметри.map(p => `<code>${esc(p)}</code>`).join(' · ')}</div>` : ''}
          ${c.api ? `<div style="margin-top:8px;font-size:13px;color:var(--ink-3)">метод: <code>${esc(c.api)}</code></div>` : ''}
          ${(c.фрази || []).map(f => `<div class="say"><b>як сказати:</b> ${esc(f)}</div>`).join('')}
        </div>
      </div>`).join('');
  };
  render('всі');
  document.getElementById('cmdtabs').onclick = (e) => {
    const b = e.target.closest('.tab'); if (!b) return;
    document.querySelectorAll('#cmdtabs .tab').forEach(t => t.classList.toggle('is-on', t === b));
    render(b.dataset.f);
  };
}

function drawAudit() {
  const v = document.querySelector('#v-audyt .sec');
  const s = D.система;
  v.innerHTML = head('Аудит коду', 'Що є в коді й що з нього живе',
    'Міряно інструментом, а не руками: текстовий опис застаріває тихо, а розбіжність у коді мовчки коштує замовлень.')
    + `<div class="figs" style="margin-top:0">`
    + fig(nf(s.файлів_py), 'файлів Python', 'без окремого підпроєкту')
    + fig(String(s.у_cron_або_службі), 'працюють самі', `${s.служб} служб, ${s.записів_cron} записів cron`)
    + fig(nf(s.рядків_було_поза_git), 'рядків було поза git', 'знайдено й виправлено')
    + fig(String(s.покинутої_архітектури), 'файлів покинутої архітектури', 'нічим не запускаються')
    + `</div>`
    + sec(head('Склад', 'Файли за категоріями', '')
      + `<div class="tablewrap"><table><tbody>
          <tr><td>у cron або службі</td><td class="num">${s.у_cron_або_службі}</td><td>працює саме</td></tr>
          <tr><td>імпортується іншими</td><td class="num">${s.імпортується}</td><td>бібліотеки</td></tr>
          <tr><td>ручний інструмент</td><td class="num">${s.ручних_інструментів}</td><td>запускається руками</td></tr>
          <tr><td>тести</td><td class="num">${s.тестів}</td><td></td></tr>
        </tbody></table></div>`
      + `<div class="note"><b>326 «ручних» — це не мертвий код.</b> Більшість — одноразові
         утиліти, і вони потрібні саме тоді, коли потрібні. Називати це число дефектом було б
         неправдою. Мертве шукається інакше — за датою останньої зміни, і так знайдено 81 файл
         покинутої архітектури з березня-квітня.</div>`)
    + sec(head('Знахідки', 'Що виправлено цим аудитом', '')
      + `<div class="tablewrap"><table><thead><tr><th>Що</th><th>Деталі</th><th>Стан</th></tr></thead><tbody>`
      + D.аудит_знайшов.map(a => `<tr><td>${esc(a.що)}</td><td>${esc(a.деталі)}</td>
          <td><span class="pill ${a.стан === 'виправлено' ? 'ok' : 'warn'}">${esc(a.стан)}</span></td></tr>`).join('')
      + `</tbody></table></div>`);
}

function drawBoard() {
  const v = document.querySelector('#v-doshka .sec');
  const k = D.katran;
  v.innerHTML = head('Дошка', 'Напрями, гіпотези й відкриті рішення',
    'Чотири різні питання живуть у чотирьох різних місцях: куди йдемо, що запущено, що в коді, що лише припускаємо.')
    + `<div class="grid g2">
        <div class="card"><h3>Напрями</h3><p>Сім файлів за одним зразком: мета, де зараз,
          зроблено, відкрито, чекає рішення. Маркер <code>[!]</code> означає, що рішення за
          власником.</p></div>
        <div class="card"><h3>Гіпотези</h3><p>Сім припущень зі способом перевірки. Гіпотеза,
          яку <b>нічим</b> перевірити, записується саме так — інакше вона повертається
          щомісяця.</p></div>
      </div>`
    + sec(head('Найближче рішення', 'KATRAN: продавати за РРЦ чи ні',
      'Порахувано на 2541 товарі — це вже не гіпотеза, а замір.')
      + `<div class="tablewrap"><table><thead><tr><th>Група</th><th class="num">Комісія</th><th>Результат за РРЦ</th></tr></thead><tbody>
          <tr><td>дрібна техніка</td><td class="num">${k.комісія_дрібна}%</td>
            <td><span class="pill bad">${k.дрібна_техніка_збиткових_відсоток}% позицій у мінус</span></td></tr>
          <tr><td>велика техніка</td><td class="num">${k.комісія_велика}%</td>
            <td><span class="pill ok">+674…+1688 ₴, майже без збиткових</span></td></tr>
        </tbody></table></div>`
      + `<div class="note">Фід на ${nf(k.позицій_у_фіді)} позицій у ${k.категорій} категоріях зібрано й
         перевірено, але <b>не подано</b> — і це правильно: після подачі зміст заморожується,
         а ${k.без_придатного_фото} карток досі без придатного фото.</div>`);
}

/* ── запуск ───────────────────────────────────────────────── */
async function boot() {
  initTheme();
  buildNav();
  const [d, c] = await Promise.all([
    fetch('data.json').then(r => r.json()),
    fetch('commands.json').then(r => r.json()),
  ]);
  D = d; C = c;
  drawHero(); drawMarkets(); drawOrders(); drawCards();
  drawKeys(); drawCommands(); drawAudit(); drawBoard();
  drawPult(); drawTasks(); drawChat();

  // Чи є бекенд. Статичні сторінки мають працювати й без нього, тому
  // це не помилка, а стан — показуємо його в підвалі панелі.
  try {
    const st = await API.get('/status');
    LIVE = true;
    document.getElementById('stamp').textContent =
      `живе · ${st.команд} команд`;
    const n = (st.дошка || {}).усього || 0;
    const el2 = document.querySelector('[data-n="zavdannya"]');
    if (el2) el2.textContent = n || '';
  } catch (e) {
    LIVE = false;
    document.getElementById('stamp').textContent += ' · офлайн';
  }

  document.querySelector('[data-n="komandy"]').textContent = C.команди.length;
  document.querySelector('[data-n="majdanchyky"]').textContent = D.майданчики.length;
  document.querySelector('[data-n="zamovlennya"]').textContent = D.конвеєри.length;

  addEventListener('hashchange', route);
  route();
  document.getElementById('burger').onclick =
    () => document.getElementById('rail').classList.toggle('is-open');

  if ('serviceWorker' in navigator) {
    addEventListener('load', () => navigator.serviceWorker.register('sw.js').catch(() => {}));
  }
}
boot();

/* ══ Інтерактивна частина ══════════════════════════════════════
   Панель звертається до бекенда (panel/server.py) на тій самій
   адресі. Якщо бекенда немає — статичні сторінки працюють далі,
   а інтерактивні чесно кажуть, що офлайн, замість тиші.      */

const API = {
  async call(path, opts = {}) {
    const r = await fetch('/api' + path, {
      headers: { 'content-type': 'application/json' }, ...opts,
    });
    if (!r.ok) throw new Error(`${r.status} ${await r.text().catch(() => '')}`.slice(0, 200));
    return r.json();
  },
  get: (p) => API.call(p),
  post: (p, body) => API.call(p, { method: 'POST', body: JSON.stringify(body) }),
  patch: (p, body) => API.call(p, { method: 'PATCH', body: JSON.stringify(body) }),
};

let LIVE = false;
const offline = (what) => `<div class="note"><b>Бекенд не відповідає.</b>
  ${esc(what)} працює лише коли запущено <code>panel/server.py</code> на ноутбуці.
  Решта сторінок — статичні, вони показуються й без нього.</div>`;

/* ── Пульт ─────────────────────────────────────────────────── */
function drawPult() {
  const v = document.querySelector('#v-pult .sec');
  v.innerHTML = head('Пульт', 'Виконати команду',
    'Напишіть фразу так, як сказали б у Telegram, або виберіть команду зі списку. Читання виконується одразу. Ризиковані дії панель лише ПРОПОНУЄ — підтвердження приходить у бот.')
    + `<div class="card" style="margin-bottom:16px">
         <div style="display:flex;gap:8px;flex-wrap:wrap">
           <input id="p-say" placeholder="наприклад: відгуки розетки"
             style="flex:1;min-width:240px;padding:10px 14px;border:1px solid var(--line-2);
                    border-radius:8px;background:var(--surface);color:var(--ink);font:inherit">
           <button class="tab is-on" id="p-go" style="padding:10px 20px">Виконати</button>
         </div>
         <div id="p-hint" style="margin-top:10px;font-size:13.5px;color:var(--ink-3)"></div>
       </div>
       <div id="p-out"></div>
       <div class="sec"><div class="eyebrow">Швидкі команди</div><div id="p-quick" class="grid g3" style="margin-top:16px"></div></div>
       <div class="sec"><div class="eyebrow">Останні запуски</div><div id="p-runs" style="margin-top:16px"></div></div>`;

  const out = document.getElementById('p-out');
  const hint = document.getElementById('p-hint');
  const say = document.getElementById('p-say');

  const show = (html) => { out.innerHTML = html; };
  const pretty = (o) => esc(JSON.stringify(o, null, 1)).slice(0, 4000);

  async function runCommand(command, params = {}) {
    show(`<div class="card">виконую <code>${esc(command)}</code>…</div>`);
    try {
      const r = await API.post('/run', { command, params });
      if (r.передано_в_telegram) {
        show(`<div class="card"><h3>Потрібне підтвердження</h3>
          <p>Команда <code>${esc(r.команда)}</code> має рівень <b>${esc(r.ризик)}</b>,
             тому панель її не виконує. Прохання вже у вашому Telegram — підтвердьте там.</p>
          <div class="note" style="margin-bottom:0">${esc(r.пояснення)}</div></div>`);
      } else if (r.збій) {
        show(`<div class="card"><h3>Збій</h3><pre class="mono" style="white-space:pre-wrap;color:var(--bad)">${esc(r.збій)}</pre></div>`);
      } else {
        show(`<div class="card"><h3>Готово</h3>
          <pre class="mono" style="white-space:pre-wrap;max-height:420px;overflow:auto">${pretty(r.результат)}</pre>
          <div style="margin-top:10px;font-size:13px;color:var(--ink-3)">те саме надіслано в Telegram</div></div>`);
      }
      loadRuns();
    } catch (e) { show(`<div class="card">${offline('Виконання команд')}</div>`); }
  }

  async function go() {
    const text = say.value.trim();
    if (!text) return;
    try {
      const p = await API.post('/parse', { text });
      if (!p.command) {
        hint.innerHTML = 'Не розпізнав. Спробуйте фразу зі списку нижче.';
        return;
      }
      hint.innerHTML = `розпізнано: <code>${esc(p.command)}</code>`;
      if ((p.брак || []).length) {
        hint.innerHTML += ` · бракує: ${esc((p.брак || []).join(', '))}`;
        return;
      }
      runCommand(p.command, p.params || {});
    } catch (e) { show(`<div class="card">${offline('Розбір фрази')}</div>`); }
  }
  document.getElementById('p-go').onclick = go;
  say.onkeydown = (e) => { if (e.key === 'Enter') go(); };

  const quick = (C.команди || []).filter(c => c.ризик === 'R0');
  document.getElementById('p-quick').innerHTML = quick.map(c => `
    <div class="card" style="cursor:pointer" data-cmd="${esc(c.команда)}">
      <div class="cmd__n">${esc(c.команда)}</div>
      <div style="margin-top:6px;font-size:14px;color:var(--ink-2)">${esc(c.що)}</div>
      <span class="pill cool" style="margin-top:10px">${esc(c.майданчик)}</span>
    </div>`).join('');
  document.getElementById('p-quick').onclick = (e) => {
    const card = e.target.closest('[data-cmd]');
    if (card) runCommand(card.dataset.cmd, {});
  };

  async function loadRuns() {
    try {
      const rows = await API.get('/runs?limit=12');
      document.getElementById('p-runs').innerHTML = rows.length
        ? `<div class="tablewrap"><table><thead><tr><th>Коли</th><th>Команда</th><th>Стан</th></tr></thead><tbody>`
          + rows.map(r => `<tr><td class="mono">${new Date(r.created * 1000).toLocaleTimeString('uk-UA')}</td>
              <td><code>${esc(r.command)}</code></td>
              <td><span class="pill ${r.state === 'виконано' ? 'ok' : r.state === 'збій' ? 'bad' : 'warn'}">${esc(r.state)}</span></td></tr>`).join('')
          + `</tbody></table></div>`
        : '<p>Поки нічого не запускали.</p>';
    } catch (e) { document.getElementById('p-runs').innerHTML = offline('Журнал запусків'); }
  }
  loadRuns();
}

/* ── Дошка завдань ─────────────────────────────────────────── */
const STATUSES = ['нове', 'в роботі', 'чекає рішення', 'зроблено', 'відкинуто'];

function drawTasks() {
  const v = document.querySelector('#v-zavdannya .sec');
  v.innerHTML = head('Дошка', 'Живі завдання та ідеї',
    'Сюди ви додаєте ідеї з телефона чи ноутбука, я їх забираю на обговорення й повертаю з висновком. Статичні напрями в docs/ лишаються окремо — тут лише те, що в роботі зараз.')
    + `<div class="card" style="margin-bottom:20px">
         <div style="display:flex;gap:8px;flex-wrap:wrap">
           <input id="b-title" placeholder="нова ідея або завдання"
             style="flex:1;min-width:220px;padding:10px 14px;border:1px solid var(--line-2);
                    border-radius:8px;background:var(--surface);color:var(--ink);font:inherit">
           <select id="b-kind" style="padding:10px 12px;border:1px solid var(--line-2);
                    border-radius:8px;background:var(--surface);color:var(--ink);font:inherit">
             <option>ідея</option><option>завдання</option><option>рішення</option>
           </select>
           <button class="tab is-on" id="b-add" style="padding:10px 20px">Додати</button>
         </div>
         <textarea id="b-body" rows="2" placeholder="подробиці, якщо потрібні"
           style="width:100%;margin-top:8px;padding:10px 14px;border:1px solid var(--line-2);
                  border-radius:8px;background:var(--surface);color:var(--ink);font:inherit;resize:vertical"></textarea>
       </div>
       <div class="tabs" id="b-tabs">
         <button class="tab is-on" data-s="всі">усі</button>
         ${STATUSES.map(s => `<button class="tab" data-s="${esc(s)}">${esc(s)}</button>`).join('')}
       </div>
       <div id="b-list"></div>`;

  let filter = 'всі';
  async function load() {
    try {
      const rows = await API.get('/board');
      const show = rows.filter(r => filter === 'всі' || r.status === filter);
      document.getElementById('b-list').innerHTML = show.length ? show.map(r => `
        <div class="cmd">
          <div class="cmd__h">
            <span class="pill cool">${esc(r.kind)}</span>
            <span style="font-weight:500">${esc(r.title)}</span>
            <span class="pill ${r.status === 'зроблено' ? 'ok' : r.status === 'чекає рішення' ? 'warn' : ''}">${esc(r.status)}</span>
            ${r.author === 'claude' ? '<span class="pill">від Claude</span>' : ''}
            ${r.обговорено ? '<span class="pill ok">забрано на обговорення</span>' : ''}
          </div>
          <div class="cmd__b">
            ${r.body ? `<div style="margin-bottom:10px">${esc(r.body)}</div>` : ''}
            <div style="display:flex;gap:6px;flex-wrap:wrap">
              ${STATUSES.filter(s => s !== r.status).map(s =>
                `<button class="tab" data-id="${r.id}" data-st="${esc(s)}" style="font-size:13px;padding:5px 11px">${esc(s)}</button>`).join('')}
            </div>
          </div>
        </div>`).join('') : '<p>Порожньо.</p>';
    } catch (e) { document.getElementById('b-list').innerHTML = offline('Дошка'); }
  }

  document.getElementById('b-add').onclick = async () => {
    const title = document.getElementById('b-title').value.trim();
    if (!title) return;
    try {
      await API.post('/board', { title, kind: document.getElementById('b-kind').value,
                                 body: document.getElementById('b-body').value.trim() });
      document.getElementById('b-title').value = '';
      document.getElementById('b-body').value = '';
      load();
    } catch (e) { alert('Бекенд не відповідає — ідею не збережено'); }
  };
  document.getElementById('b-tabs').onclick = (e) => {
    const b = e.target.closest('.tab'); if (!b) return;
    document.querySelectorAll('#b-tabs .tab').forEach(t => t.classList.toggle('is-on', t === b));
    filter = b.dataset.s; load();
  };
  document.getElementById('b-list').onclick = async (e) => {
    const b = e.target.closest('[data-st]'); if (!b) return;
    try { await API.patch('/board/' + b.dataset.id, { status: b.dataset.st }); load(); }
    catch (err) { alert('Не вдалось оновити'); }
  };
  load();
}

/* ── Чат ───────────────────────────────────────────────────── */
function drawChat() {
  const v = document.querySelector('#v-chat .sec');
  v.innerHTML = head('Чат', 'Листування зі мною',
    'Повідомлення лягає в базу й одразу дублюється вам у Telegram. Я читаю його, коли працюю, і відповідаю сюди ж.')
    + `<div class="note"><b>Чесно про затримку.</b> Це не миттєвий чат: із сесією, що відкрита
         в терміналі, веб говорити не може — це різні процеси. Тому відповідь приходить тоді,
         коли я працюю. Миттєвий варіант можливий окремо, але він коштує грошей за токени —
         рішення за вами.</div>
       <div id="c-list" style="margin:20px 0;max-height:52vh;overflow:auto"></div>
       <div style="display:flex;gap:8px;flex-wrap:wrap">
         <textarea id="c-text" rows="2" placeholder="напишіть повідомлення"
           style="flex:1;min-width:240px;padding:10px 14px;border:1px solid var(--line-2);
                  border-radius:8px;background:var(--surface);color:var(--ink);font:inherit;resize:vertical"></textarea>
         <button class="tab is-on" id="c-send" style="padding:10px 20px">Надіслати</button>
       </div>`;

  async function load() {
    try {
      const rows = await API.get('/chat?limit=60');
      document.getElementById('c-list').innerHTML = rows.length ? rows.map(m => `
        <div style="margin-bottom:14px;${m.role === 'claude' ? '' : 'padding-left:0'}">
          <div style="font-size:12px;color:var(--ink-3);margin-bottom:4px">
            ${m.role === 'claude' ? 'Claude' : 'ви'} · ${new Date(m.created * 1000).toLocaleString('uk-UA')}
          </div>
          <div style="background:${m.role === 'claude' ? 'var(--brand-wash)' : 'var(--surface-2)'};
               border-radius:12px;padding:12px 14px;white-space:pre-wrap">${esc(m.text)}</div>
        </div>`).join('') : '<p>Поки порожньо.</p>';
      const l = document.getElementById('c-list'); l.scrollTop = l.scrollHeight;
    } catch (e) { document.getElementById('c-list').innerHTML = offline('Чат'); }
  }
  document.getElementById('c-send').onclick = async () => {
    const t = document.getElementById('c-text');
    if (!t.value.trim()) return;
    try { await API.post('/chat', { text: t.value.trim() }); t.value = ''; load(); }
    catch (e) { alert('Бекенд не відповідає — повідомлення не надіслано'); }
  };
  load();
  setInterval(() => { if (location.hash === '#chat') load(); }, 15000);
}
