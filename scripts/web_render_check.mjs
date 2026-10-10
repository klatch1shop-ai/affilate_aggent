import fs from 'fs';
const src = fs.readFileSync('./web/app.js', 'utf8');
const D = JSON.parse(fs.readFileSync('./web/data.json', 'utf8'));
const C = JSON.parse(fs.readFileSync('./web/commands.json', 'utf8'));

const made = {};
const mk = (id) => ({
  id, innerHTML: '', textContent: '', dataset: {}, classList: {
    toggle: () => {}, remove: () => {}, add: () => {}, contains: () => false },
  append: () => {}, setAttribute: () => {}, removeAttribute: () => {},
  getAttribute: () => '', onclick: null, querySelectorAll: () => [],
  closest: () => null,
});
global.document = {
  documentElement: { dataset: {}, removeAttribute(){} },
  createElement: () => mk('tmp'),
  getElementById: (id) => (made[id] ||= mk(id)),
  querySelector: (s) => (made[s] ||= mk(s)),
  querySelectorAll: () => [],
  body: { style: {} },
};
global.location = { hash: '' };
global.addEventListener = () => {};
global.matchMedia = () => ({ matches: false });
global.localStorage = { getItem: () => null, setItem: () => {} };
global.navigator = {};
global.window = global;
global.fetch = (p) => Promise.resolve({ json: () => Promise.resolve(p.includes('commands') ? C : D) });
global.scrollTo = () => {};
global.Intl = Intl;

// витягуємо тіло без автозапуску boot()
import vm from 'vm';
globalThis.__D = D; globalThis.__C = C;
vm.runInThisContext(src.replace(/^boot\(\);\s*$/m, '') + '\nD=globalThis.__D;C=globalThis.__C;globalThis.__f={drawHero,drawMarkets,drawOrders,drawCards,drawKeys,drawCommands,drawAudit,drawBoard};globalThis.D=D;globalThis.C=C;');
const F=globalThis.__f;

const checks = [
  ['drawHero', () => F.drawHero()],
  ['drawMarkets', () => F.drawMarkets()],
  ['drawOrders', () => F.drawOrders()],
  ['drawCards', () => F.drawCards()],
  ['drawKeys', () => F.drawKeys()],
  ['drawCommands', () => F.drawCommands()],
  ['drawAudit', () => F.drawAudit()],
  ['drawBoard', () => F.drawBoard()],
];
globalThis.D = D; globalThis.C = C;
let bad = 0;
for (const [name, fn] of checks) {
  try {
    fn();
    const out = Object.values(made).map(m => m.innerHTML).join('');
    if (/undefined|NaN|\[object Object\]/.test(out)) {
      console.log(`  ✗ ${name}: у розмітці є undefined/NaN`);
      const m = out.match(/.{0,60}(undefined|NaN|\[object Object\]).{0,40}/);
      console.log('      ' + (m ? m[0].replace(/\s+/g, ' ') : ''));
      bad++;
      Object.values(made).forEach(x => x.innerHTML = '');
    } else console.log(`  ✓ ${name}`);
  } catch (e) { console.log(`  ✗ ${name}: ${e.message}`); bad++; }
}
console.log(bad ? `\nпомилок: ${bad}` : '\nусі сторінки малюються без помилок');
