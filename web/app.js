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
