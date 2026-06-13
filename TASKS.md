# TASKS.md — живий список задач
Оновлено: 2026-06-13. Читати на початку кожної сесії разом з CLAUDE.md.

---

## ЗРОБЛЕНО ✅

### Єпіцентр — Carvol
- [x] `tools/carvol_epicentr_generator.py` — SpreadsheetML прайс → Єпіцентр XML (7081 офер)
- [x] `tools/epicentr_pim_explorer.py` — PIM API explorer, кеш 54370 брендів в БД
- [x] `tools/epicentr_quality_checker.py` — SEO скоринг XML (avg 73/100)
- [x] Бренди в XML: валідні valuecodes з epicentr_brand_map + fallback "Інше" (827b4a70...)
- [x] Фільтр фото: 8171 → 7081 (видалено без фото)
- [x] Опис з Rozetka фіду (7011 real + 1160 auto-generated)

### Інфраструктура
- [x] `infrastructure/api_methods.sql` — 123 API методи в БД (marketplace_api_methods)
- [x] `shared/knowledge_base/api_reference.md` — markdown довідник
- [x] `tools/watchdog.py` — виправлено: більше не робить git push (тільки локальний commit)
- [x] Crontab: feed_sync змінено з `0 */4` → `0 7` (щодня о 7:00)
- [x] DB: таблиці epicentr_brand_cache, epicentr_brand_map, epicentr_quality_log

---

## В ПРОЦЕСІ 🔄

- [ ] **Завантажити `exports/carvol_epicentr.xml` в кабінет Єпіцентру**
      Файл готовий: 7081 офер, 37MB, avg score 73/100
      URL кабінету: merchant.epicentrk.ua

- [ ] **Перевірити TOPTUL чернетки в Єпіцентрі** (~5893)
      Які не пройшли модерацію? Які потрібно виправити?

- [ ] **Налаштувати авто-оновлення наявності Carvol для Єпіцентру**
      Зараз XML генерується вручну. Потрібен cron аналогічно Rozetka.

---

## НАСТУПНІ ЗАДАЧІ 📋

### Висока пріоритетність (блокують продажі)
- [ ] Реєстрація бренду QIV через менеджера Єпіцентру
      → підніме score з 73 → ~93, зачіпає 6110 офер
- [ ] Логін/пароль Розетки в .env виправити
      (hyper_store/Tovarka2025Rivne → incorrect_username_password)
- [ ] Налаштувати друге GitHub посилання для Катрана в кабінеті Розетки
      (через менеджера Софію Івановську)

### SEO та якість контенту
- [ ] SEO покращення назв через Claude API (haiku-4-5)
      `python3 tools/epicentr_quality_checker.py --enhance-names --limit 500`
- [ ] Видалити "телефон" зі 1276 описів
      `python3 tools/epicentr_quality_checker.py --fix --output exports/carvol_epicentr_fixed.xml`
- [ ] AI Enrich pipeline для TOPTUL (товари без характеристик)

### Нові агенти
- [ ] `agents/orders/prom_order_agent.py` — агент замовлень Prom.ua (не існує)
- [ ] `agents/orders/katran_order_agent.py` — агент замовлень Катран (пізніше)
- [ ] `agents/orders/katran_xml_generator.py` — Катран → Розетка XML

### Катран — маппінг категорій (~55% залишилось)
- [ ] Підтвердити в PriceCreator або через bt.rozetka.com.ua/c{id}/:
      Смартфони, Планшети, Кабелі(80329), USB(80333), Картриджі(80296),
      Корпуси ПК(80038), Кулери(80049), Чорнила(73126), Чохли(4638562),
      LED лампи(4638153), USB Hub(80339), Контролери PCI(80052)
- [ ] Виправити Молотки/Біти/Набори пневмо/Мультиметри для Єпіцентру

### Інфраструктура
- [ ] Перевірити XML katran_rozetka.xml через валідатор Розетки
      URL: seller.rozetka.com.ua/gomer/pricevalidate/check/index
- [ ] NotebookLM бази знань SEO для кожного маркетплейсу

---

## КОРИСНІ КОМАНДИ

```bash
# Генерація Єпіцентр XML (на ноутбуці, з файлом прайсу)
python3 tools/carvol_epicentr_generator.py data/carvol_opt_YYYYMMDD.xml

# SEO звіт
ssh tek@100.82.24.112 "cd /home/tek/agent-system && source venv/bin/activate && python3 tools/epicentr_quality_checker.py --xml exports/carvol_epicentr.xml --report"

# Пошук бренду в Єпіцентрі
ssh tek@100.82.24.112 "cd /home/tek/agent-system && source venv/bin/activate && EPICENTR_TOKEN=$(grep EPICENTR_TOKEN .env | cut -d= -f2) python3 tools/epicentr_pim_explorer.py find-brand 'QIV'"

# БД — стан брендів
docker exec agent_postgres psql -U agentadmin agentdb -c "SELECT DISTINCT brand_name, value_ua FROM epicentr_brand_map ORDER BY brand_name;"

# Перевірка API методів що не реалізовані
docker exec agent_postgres psql -U agentadmin agentdb -c "SELECT marketplace, method_name, endpoint, priority FROM marketplace_api_methods WHERE NOT is_implemented ORDER BY priority, marketplace;"
```
