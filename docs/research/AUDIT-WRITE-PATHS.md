# Аудит: що може змінити дані назовні

## Коротко (5 рядків для власника)

1. Є прямі записи без режиму дозволу: MCP Prom змінює ціни, наявність і відповідає покупцю (`shared/mcp_servers/prom_mcp.py:501`, `shared/mcp_servers/prom_mcp.py:527`, `shared/mcp_servers/prom_mcp.py:573`).
2. Захист `output/noire_epicentr_phase1.xml` не глобальний: файл замінюється в `tools/noire_stock_sync.py:443`; заборона існує окремо в `research/veto.py:10`.
3. Єдиного цінового бар'єра немає: прямий PUT приймає передану ціну (`agents/orders/rozetka_price_corrector.py:51`), а CSV потрапляє у фід без звірки порогу (`agents/orders/rozetka_price_manager.py:234`).
4. `integrations/` читає дані; POST Нової Пошти — читання статусу, не створення ТТН (`integrations/prom.py:17`, `integrations/rozetka.py:98`, `integrations/novaposhta.py:31`).
5. Реальні, але локальні обмеження: згода на публікацію Епіцентру (`tools/noire_stock_sync.py:700`), режим листів TOPTUL (`agents/orders/toptul_supplier.py:59`), `--create` для ТТН (`tools/np_create_ttn.py:225`).

## Таблиця дій

Аудит статичний, стан робочої копії на 20.09.2026. «Немає» означає відсутність у наведеному шляху програмної перевірки дозволу власника/режиму, а не доведений запуск на сервері. Авторизація API, таймаут, успішний HTTP-код і журналювання самі по собі не є дозволом на бізнес-дію. Приклад різниці: `helper/confirm.py:160` перевіряє підтвердження, тоді як `shared/mcp_servers/prom_mcp.py:69` лише відправляє POST.

### Прямі записи до маркетплейсів, постачальників і пошти

| Файл:рядок | Що робить | Майданчик | Стримування і його межа |
|---|---|---|---|
| `shared/mcp_servers/prom_mcp.py:426` | POST зміни статусів замовлень | Prom | Немає test/live або підтвердження в обробнику; payload формується з аргументів |
| `shared/mcp_servers/prom_mcp.py:443` | POST прив'язки ТТН | Prom | Немає перевірки дозволу власника |
| `shared/mcp_servers/prom_mcp.py:501` | POST цін пачками | Prom | Лише непорожній список/пачки; немає порогу ціни |
| `shared/mcp_servers/prom_mcp.py:527` | POST наявності пачками | Prom | Немає перевірки доказу відсутності або режиму |
| `shared/mcp_servers/prom_mcp.py:573` | POST відповіді покупцю | Prom | Немає draft/live, підтвердження або маскування в цьому обробнику |
| `shared/mcp_servers/rozetka_mcp.py:269` | POST статусу замовлення | Rozetka | Немає test/live або підтвердження |
| `shared/mcp_servers/epicentr_mcp.py:220` | POST прийняття/підтвердження/відправлення/скасування | Епіцентр | `allowed-statuses` перевіряється при HTTP 200 (`:201`); це допустимість переходу, не дозвіл власника |
| `shared/mcp_servers/epicentr_mcp.py:255` | POST ТТН; fallback PATCH `:259`, POST статусу `:268` | Епіцентр | Формат 14 цифр для НП (`:248`); немає режиму |
| `shared/mcp_servers/epicentr_mcp.py:303` | POST контактів клієнта | Епіцентр | Немає test/live або підтвердження |
| `shared/mcp_servers/epicentr_mcp.py:336` | POST даних доставки | Епіцентр | Немає test/live або підтвердження |
| `shared/mcp_servers/epicentr_mcp.py:358` | POST коментаря до замовлення | Епіцентр | Немає test/live або підтвердження |
| `agents/orders/order_agent.py:173` | POST підтвердження замовлення | Prom | Пряма функція без режиму; сценарій перевіряє товар перед викликами (`:561`, `:575`) |
| `agents/orders/order_agent.py:381` | SMTP-лист постачальнику з Excel | Пошта/TOPTUL | Немає режиму off/test/live у цій функції; окремий TOPTUL-модуль не захищає цей SMTP |
| `agents/orders/epicentr_order_agent.py:168` | POST прийняття | Епіцентр | Перевірка дозволених статусів (`:162`); немає режиму власника |
| `agents/orders/epicentr_order_agent.py:183` | POST скасування | Епіцентр | Пряма функція без режиму; сценарій викликає при `out_of_stock` (`:468`) |
| `agents/orders/epicentr_order_agent.py:365` | SMTP-лист постачальнику | Пошта/Carvol | Немає off/test/live у функції; виклик сценарію `:507` |
| `agents/orders/noire_order_notifier.py:192` | POST підтвердження наявності замовлення | Епіцентр/NOIRE | Перевірка допустимого статусу (`:186`), але немає test/live; це не лише сповіщувач |
| `agents/orders/rozetka_order_agent.py:246` | PATCH довільного переданого статусу | Rozetka | У `change_status` немає whitelist або режиму |
| `agents/orders/rozetka_order_agent.py:276` | POST додавання ТТН; fallback PATCH `:293` | Rozetka | Немає режиму власника у `set_ttn` |
| `agents/orders/rozetka_order_agent.py:346` | PATCH переходу в обробку | Rozetka | Перевірка доступних статусів (`:336`), без test/live |
| `agents/orders/rozetka_order_agent.py:414` | PATCH підтвердження; fallback PUT кабінету `:484` | Rozetka | Whitelist переходів у `confirm_order` (`:405`); не поширюється на `change_status` |
| `agents/orders/rozetka_order_agent.py:507` | PATCH скасування | Rozetka | Немає режиму у функції; рішення сценарію — окремий рівень |
| `agents/orders/rozetka_order_agent.py:794` | Telegram sendDocument: Excel постачальнику | Carvol | Немає test/live у функції; автоматичні виклики `:1234`, `:1260` |
| `agents/orders/rozetka_order_agent.py:857` | SMTP-лист Carvol | Пошта/Carvol | Перевіряє наявність SMTP-конфігурації (`:836`), не згоду; fallback після невдалого Telegram (`:1261`) |
| `agents/orders/toptul_supplier.py:217` | SMTP-лист із замовленням | Пошта/TOPTUL | `off/test/live`, default та невідоме значення → `test` (`:59`); test реально надсилає на власну скриньку (`:204`) |
| `agents/orders/price_updater.py:331` | POST цін товарів | Prom | `dry_run` (`:326`), default False (`:212`); формула імпортується з pricing (`:31`), окремого дозволу live немає |
| `agents/orders/price_engine.py:566` | POST цін товарів | Prom | `dry_run` (`:544`), default False (`:541`); прямий `update_prom_prices` не перевіряє поріг переданої ціни |
| `agents/orders/rozetka_price_corrector.py:53` | PUT price-stock | Rozetka | `--dry-run` лише в CLI (`:137`); прямий `update_price` не перевіряє floor |
| `tools/prom_api.py:158` | POST edit_by_external_id з поточним group_id | Prom | Явна команда test-write (`:141`), очікує незмінність полів після GET; це реальний POST, не mock |
| `tools/web_api_explorer.py:871` | Проксіює метод/path/body, включно з DELETE | Майданчики з конфігурації | Відомий майданчик (`:834`), але немає whitelist лише читання, test/live чи бізнес-валідації |
| `sync/epicentr_offers.py:211` | POST `/v1/offers` через переданий транспорт | Епіцентр | `run` default off (`:235`), live потрібен (`:271`); поріг перевіряється лише коли він відомий (`:51`); прямий `submit` (`:228`) обходить `run` |
| `tools/np_create_ttn.py:230` | POST Counterparty.save | Нова Пошта | Лише після `--create` (`:225`); без прапорця розрахунок |
| `tools/np_create_ttn.py:247` | POST InternetDocument.save, повтори `:251`, `:257` | Нова Пошта | `--create`, перевірки доставки/одержувача; fallback може створити без післяплати (`:256`) |
| `tools/np_create_ttn.py:118` | PATCH ТТН і статусу замовлення | Rozetka | У helper-функції немає режиму; викликається сценарієм створення ТТН |
| `tools/np_create_ttn.py:290` | GET друку наклейки нової ТТН | Нова Пошта | Частина сценарію створення; GET друку не слід автоматично вважати безпобічним, див. `agents/orders/np_label.py:55` |
| `agents/orders/np_label.py:62` | GET друку наклейки | Нова Пошта | Перевірка свого документа та Printed/StateId (`:50`–`:58`); код прямо пояснює ризик блокування редагування після друку |
| `tools/smtm_crm.py:109` | Клік додавання товару в кошик | SMTM CRM | Вибір SKU; немає test/live; CLI `add` викликає дію (`:164`) |
| `tools/smtm_crm.py:123` | Редагування кількості в кошику | SMTM CRM | Немає підтвердження власника; не доведено оформлення замовлення |
| `agents/scraper/epicentr_cabinet.py:283` | Завантаження XLS цін/наявності, submit `:295` | Кабінет Епіцентру | Вхід у кабінет і перевірка завантаження; немає test/live/порогу; MCP-вхід `shared/mcp_servers/browser_mcp.py:491` |

### Зміст карток і модерація Епіцентру

| Файл:рядок | Що робить | Майданчик | Стримування і його межа |
|---|---|---|---|
| `tools/epicentr_classify_cosmetics.py:216` | PUT категорії/атрибутів | PIM Епіцентру | `--plan` (`:127`), повторна перевірка enrich (`:195`); без plan запис |
| `tools/epicentr_classify_specs.py:337` | PUT категорії/атрибутів | PIM Епіцентру | `--plan` (`:254`), enrich (`:317`) |
| `tools/epicentr_classify_devices.py:340` | PUT категорії/атрибутів | PIM Епіцентру | `--plan` (`:253`), enrich (`:319`) |
| `tools/epicentr_classify_rest.py:239` | PUT категорії/атрибутів | PIM Епіцентру | `--plan` (`:153`), enrich (`:219`) |
| `tools/epicentr_classify_accessories.py:212` | PUT категорії/атрибутів | PIM Епіцентру | `--plan` (`:126`), enrich (`:191`) |
| `tools/epicentr_classify_toys.py:199` | PUT категорії/атрибутів | PIM Епіцентру | `--plan` (`:115`), enrich (`:178`) |
| `tools/epicentr_classify_rules.py:284` | PUT категорії/атрибутів | PIM Епіцентру | `--plan` (`:197`), enrich (`:263`) |
| `tools/epicentr_fill_binary.py:158` | PUT атрибутів | PIM Епіцентру | `--plan` (`:70`), enrich (`:116`) |
| `tools/epicentr_fill_numeric.py:153` | PUT числових атрибутів | PIM Епіцентру | `--plan` (`:79`), enrich (`:126`) |
| `tools/epicentr_fill_from_prom.py:206` | PUT картки на основі Prom | PIM Епіцентру | `--plan` (`:96`), відбір enrich і місяця створення (`:131`); немає єдиного live-дозволу |
| `tools/epicentr_attr_fill.py:147` | PUT атрибуту за map/cat/attr | PIM Епіцентру | `--dry` (`:128`) та явна карта; без dry виконує запис |
| `tools/epicentr_attr_fill_multi.py:133` | PUT кількох атрибутів | PIM Епіцентру | Вхідні map/cat/limit (`:64`); немає dry або підтвердження в CLI |
| `tools/epicentr_to_moderation.py:88` | PATCH статусів пачкою | PIM Епіцентру | `consent_require('epicentr_moderate')` (`:83`) |
| `tools/epicentr_drafts_to_review.py:92` | PATCH чернеток, повтор `:95` | PIM Епіцентру | `consent_require` (`:85`) |
| `tools/epicentr_moderate_ready.py:100` | PATCH готових карток на модерацію | PIM Епіцентру | `consent_require` (`:95`) |

### Фіди та публікація

Запис XML — окрема дія від його завантаження майданчиком. Наприклад, `tools/noire_stock_sync.py:443` змінює локальний фід, а `tools/noire_stock_sync.py:318` публікує його через Git. Саме доступність цього файлу для реального імпортера без мережі не підтверджена.

| Файл:рядок | Що робить | Майданчик | Стримування і його межа |
|---|---|---|---|
| `tools/noire_stock_sync.py:443` | Замінює `output/noire_epicentr_phase1.xml` | Епіцентр/NOIRE | Генератор має завершитися успішно (`:408`); FAIL валідатора лише рахується (`:433`), не блокує move; згода тільки у CLI publish (`:700`) |
| `tools/noire_stock_sync.py:494` | Замінює `output/noire_rozetka.xml` | Rozetka/NOIRE | Генерація/валідація в `regenerate_rozetka_feed` (`:458`); немає загального test/live |
| `tools/noire_stock_sync.py:596` | Замінює `output/noire_prom.xml` | Prom/NOIRE | Перевірки у `regenerate_prom_feed` (`:509`); немає загального test/live |
| `tools/noire_stock_sync.py:318` | Git push --force origin main з окремого каталогу публікації | GitHub → майданчики | Прямий `publish_github` (`:290`) не має consent; лише гілка основного Epicentr publish має згоду (`:700`), Rozetka/Prom/stock — окремі гілки (`:716`, `:724`, `:754`) |
| `tools/noire_epicentr_stock_feed.py:86` | XML ціни/наявності | Епіцентр/NOIRE | Окремий генератор stock-фіду; файл пишеться без підтвердження |
| `tools/noire_epicentr_generator.py:1789` | Повний XML; default exports, довільний `--output` | Епіцентр/NOIRE | Немає заборони protected path; параметр `--output` (`:1829`) |
| `tools/noire_rozetka_generator.py:1554` | Повний XML | Rozetka/NOIRE | Заморожені картки беруться зі snapshot (`:1403`, `:1423`, `:1520`); це не файловий whitelist і не live-дозвіл |
| `tools/noire_prom_generator.py:1767` | Повний XML | Prom/NOIRE | Прямий запис вихідного файлу; немає загального consent |
| `tools/toptul_rozetka_generator.py:934` | Повний XML | Rozetka/TOPTUL | Прямий запис після генерації; немає загального consent на файловому записі |
| `tools/dropoffice_rozetka_generator.py:1039` | Atomic replace згенерованого XML | Rozetka/DropOffice | Тимчасовий файл (`:1037`); атомарність не є дозволом власника |
| `tools/carvol_epicentr_generator.py:937` | Повний XML Carvol | Епіцентр/Carvol | `output_file` (`:753`), default exports (`:30`); немає глобального блокування джерела Carvol |
| `tools/prom_xml_generator.py:280` | XML Prom | Prom | Запис переданого вихідного шляху |
| `tools/supplier_onboarding.py:369` | XML постачальника | Фід маркетплейсу | Прямий запис XML; не тотожний імпорту в кабінет |
| `tools/katran_category_xml.py:346` | Категорійний XML | Rozetka/Katran | Прямий файловий запис |
| `tools/katran_pipeline.py:104` | Merge XML у спільний фід | Rozetka/Katran | Перевірки pipeline; публікація окремо |
| `tools/katran_pipeline.py:116` | Git push | GitHub/Rozetka | Явний `--push` (`:143`), виклик `:265` |
| `agents/orders/katran_xml_generator.py:256` | Повний XML | Rozetka/Katran | Прямий файловий запис |
| `agents/orders/katran_github_sync.py:53` | Git push після генерації | GitHub/Rozetka | Сценарій генерує (`:78`) і публікує (`:87`), без test/live |
| `agents/orders/epicentr_xml_generator.py:316` | Повний XML | Епіцентр | Прямий файловий запис |
| `agents/scraper/xml_generator.py:243` | Повний XML | Фід маркетплейсу | Прямий файловий запис |
| `agents/scraper/generate_carvol_xml.py:107` | XML Carvol | Rozetka/Carvol | Прямий запис, немає глобального veto Carvol |
| `agents/orders/carvol_epicentr_sync.py:153` | Перезапис XML ціни/наявності; заголовок `:157` | Епіцентр/Carvol | Локальні розрахунки; немає test/live |
| `agents/orders/carvol_epicentr_sync.py:203` | Git push фіду | GitHub/Епіцентр | Автоматичний виклик `:230`, без consent |
| `agents/orders/rozetka_github_sync.py:210` | Перезапис XML; заголовок `:215` | Rozetka/Carvol | Розрахунок ціни `:78`; немає test/live |
| `agents/orders/rozetka_github_sync.py:267` | Git push, повтор `:275` | GitHub/Rozetka | Автоматичний виклик `:315`, без consent |
| `agents/orders/rozetka_price_manager.py:241` | Ціни з CSV у XML; заголовок `:245` | Rozetka | Явний apply (`:282`), але ціна з CSV не звіряється з порогом (`:234`) |
| `agents/orders/rozetka_price_manager.py:265` | Git push після apply | GitHub/Rozetka | Той самий apply, немає додаткової перевірки ціни |
| `agents/orders/feed_sync.py:187` | XML наявності у shared/feeds | Епіцентр | Прямий файловий запис |
| `agents/orders/feed_sync.py:205` | Git push --force-with-lease | GitHub/Епіцентр | Автоматичний виклик `:226`, без consent |
| `agents/orders/rozetka_feed_sync.py:254` | XML у shared/feeds | Rozetka | Прямий файловий запис; окремий шлях від output |
| `epicentr_postprocess.py:53`, `tools/epicentr_postprocess.py:53` | Перезапис XML після обробки | Епіцентр | Немає загальної перевірки замороження/дозволу перед write |
| `tools/fix_rozetka_xml.py:456`, `tools/fix_rozetka_xml.py:464`, `tools/fix_rozetka_xml.py:471` | Збереження виправленого XML | Rozetka | Обраний режим/шлях; не глобальний захист заморожених карток |
| `tools/epicentr_apparel_enrich.py:282` | Збереження збагаченого XML | Епіцентр | Явний out; також викликається регенератором (`tools/noire_stock_sync.py:418`) |
| `tools/epicentr_valuecode_audit.py:117`, `tools/epicentr_logic_audit.py:139`, `tools/epicentr_keep_valid.py:85` | Збереження виправленого/відфільтрованого XML | Епіцентр | Обраний out; назва audit не означає лише читання |
| `tools/prom_content_fix.py:333`, `tools/prom_params_fill.py:208`, `tools/prom_units_normalize.py:192`, `tools/prom_marker_step.py:66` | Переписують зміст XML | Prom | Явний `--write`; не перевіряють власницький live-дозвіл на публікацію |
| `tools/prom_kw_rebuild.py:81` | Запис XML із перебудованими ключами | Prom | Явний out |
| `tools/prom_postprocess.py:81` | Move обробленого XML в destination | Prom | `--dry-run` (`:72`), backup при inplace (`:79`) |
| `tools/prom_search.py:117`, `tools/prom_search.py:153` | Оновлює локальний XML для пошуку/каталогу | Prom | Умова застарілості/відсутності; назва search не означає відсутність файлових записів |
| `tools/prom_visibility_remeasure.py:136` | Замінює локальний Prom XML | Prom | Завантаження опублікованого фіду, якщо відсутній або старший за 12 год (`tools/prom_visibility_remeasure.py:134`); це оновлення локального кешу |

### Telegram та інші вихідні транспорти

Тут повідомлення власнику також вважається зовнішньою дією. Обмежений chat_id — обмеження адресата, а не test/live; лист покупцю через Prom наведений окремо (`shared/mcp_servers/prom_mcp.py:573`).

| Файл:рядок | Що робить | Майданчик | Стримування і його межа |
|---|---|---|---|
| `helper_bot/main.py:108` | sendMessage: картки inbox, нагадування, дайджест | Telegram власника | Фіксований ADMIN_ID (`:104`); підтвердження кожного повідомлення немає |
| `helper_bot/main.py:298`, `helper_bot/main.py:313`, `helper_bot/main.py:328`, `helper_bot/main.py:384` | Відповіді та callback acknowledgements | Telegram | Контроль доступу обробників; відповідь покупцю окремо заглушена (`:311`) |
| `tg_dispatcher/main.py:67`, `tg_dispatcher/main.py:68`, `tg_dispatcher/main.py:90`, `tg_dispatcher/main.py:284`, `tg_dispatcher/main.py:331`, `tg_dispatcher/main.py:358` | Копіювання повідомлення, повідомлення/результати обробки документів; message.answer та edit_text (`tg_dispatcher/main.py:377`) | Telegram | Middleware допускає ADMIN і окремі повідомлення Carvol (`tg_dispatcher/main.py:54`); не загальний режим off/test/live |
| `tg_dispatcher/main.py:207`, `tg_dispatcher/main.py:326`, `tg_dispatcher/main.py:481` | Обгортки запису ТТН/статусів за командою, текстом або PDF | Rozetka через Telegram | Whitelist ADMIN/Carvol у middleware (`tg_dispatcher/main.py:54`); команда/зіставлення замовлення; текстова гілка розрізняє auto і confirm (`:311`), PDF має окремий шлях |
| `agents/interfaces/telegram_gateway.py:370`, `agents/interfaces/telegram_gateway.py:379` | sendMessage/sendPhoto | Telegram власника | Кнопки підтвердження опціональні (`:368`), саме сповіщення надсилається одразу |
| `orchestrator/telegram_bot.py:58`, `orchestrator/telegram_bot.py:79`, `orchestrator/telegram_bot.py:125` | reply_text/edit_message_text, callback answer `:75` | Telegram | Інтерактивні обробники; немає test/live для повідомлень |
| `agents/scraper/playwright_base.py:479`, `agents/scraper/playwright_base.py:486` | POST повідомлення та фото про браузерні дії | Telegram | Повідомлення діагностики; без підтвердження кожного відправлення |
| `agents/orders/order_agent.py:403`, `agents/orders/order_agent_daemon.py:16`, `agents/orders/epicentr_order_agent.py:54`, `agents/orders/rozetka_order_agent.py:62`, `agents/orders/noire_order_notifier.py:64` | POST sendMessage зі сценаріїв замовлень | Telegram | Налаштований адресат, не дозвіл на кожне повідомлення |
| `agents/orders/price_engine.py:74`, `agents/orders/price_engine.py:86`, `agents/orders/price_audit.py:60`, `agents/orders/price_audit.py:77`, `agents/orders/price_updater.py:52` | POST звітів/документів | Telegram | Налаштований адресат; у price_engine частину викликів стримує dry (`:765`) |
| `agents/orders/feed_sync.py:40`, `agents/orders/rozetka_feed_sync.py:53`, `agents/orders/carvol_epicentr_sync.py:42`, `agents/orders/rozetka_github_sync.py:55`, `agents/orders/katran_github_sync.py:33`, `agents/orders/fetch_prom_categories.py:35` | POST сповіщень про синхронізації | Telegram | Налаштований адресат; не загальний test/live |
| `tools/noire_stock_sync.py:60`, `tools/watchdog.py:144`, `tools/toptul_ttn_reconcile.py:28`, `ops/run_pg_backup.py:50` | POST службових сповіщень | Telegram | Локальні умови/прапорці сценарію, не підтвердження кожного повідомлення |
| `tools/np_create_ttn.py:97`, `tools/np_create_ttn.py:104` | sendDocument/sendMessage | Telegram | Частина сценарію ТТН; прямі helper-функції не перевіряють create |
| `shared/utils/llm_router.py:75`, `shared/utils/llm_router.py:106`, `shared/utils/llm_router.py:127` | POST prompt до маршрутизатора/Gemini/Ollama | LLM | Вибір провайдера, не власницький test/live; передавання тексту назовні залежить від URL |
| `tools/nvidia_nim.py:86`, `tools/toptul_translate.py:229`, `tools/toptul_desc_translate.py:292`, `tools/toptul_rozetka_validate.py:96` | POST chat completions | NVIDIA/API LLM | Наявність ключа/умови сценарію; не дозвіл на кожну передачу |
| `shared/utils/ollama_worker.py:20`, `mass_enrich.py:44`, `enrich_with_ai.py:57`, `test_agent.py:40` | POST генерації | Ollama | HTTP-виклик навіть у файлі з назвою test; сервер залежить від конфігурації |
| `agents/scraper/category_classifier.py:308`, `tools/noire_desc_generator.py:266`, `tools/noire_ru_translate.py:121`, `tools/prom_desc_rewrite.py:197`, `tools/prom_kw_calibrate.py:144`, `tools/toptul_rozetka_llm.py:89` | POST генерації/перекладу | Ollama | Не змінює кабінет безпосередньо, але виконує запит і може живити подальший запис БД |
| `shared/utils/redis_queue.py:17`, `shared/utils/memory.py:29`, `shared/utils/memory.py:47` | Ставить завдання в Redis | Внутрішні агенти | Черга, не згода; виконання залежить від споживача |
| `embedding_service.py:30`, `embedding_service.py:42` | Створення колекції/upsert | Qdrant | Внутрішній запис індексу, не БД маркетплейсу |
| `shared/mcp_servers/filesystem_mcp.py:79` | Запис knowledge-файлу | Файлова система | filename приєднується без нормалізації (`:77`); немає перевірки виходу з каталогу, тому потенційний обхід обмеження шляху |

### Сесії та допоміжні точки входу

| Файл:рядок | Що робить | Майданчик | Стримування і його межа |
|---|---|---|---|
| `shared/mcp_servers/rozetka_mcp.py:52` | POST отримання сесії | Rozetka | Облікові дані/кеш; не зміна товару і не власницький live-дозвіл |
| `tools/epicentr_attr_fill.py:34`, `tools/epicentr_attr_fill_multi.py:31`, `tools/epicentr_classify_accessories.py:93`, `tools/epicentr_classify_cosmetics.py:66`, `tools/epicentr_classify_devices.py:240`, `tools/epicentr_classify_rest.py:140`, `tools/epicentr_classify_rules.py:124`, `tools/epicentr_classify_specs.py:241`, `tools/epicentr_classify_toys.py:69`, `tools/epicentr_comments_scan.py:29`, `tools/epicentr_drafts_to_review.py:39`, `tools/epicentr_enrich_audit.py:39`, `tools/epicentr_fill_binary.py:51`, `tools/epicentr_fill_from_prom.py:48`, `tools/epicentr_fill_numeric.py:49`, `tools/epicentr_moderate_ready.py:32`, `tools/epicentr_photo_audit.py:105`, `tools/epicentr_products_dump.py:24`, `tools/epicentr_to_moderation.py:34`, `tools/epicentr_valuecode_audit.py:44` | POST логіну для наступних читань або записів | Кабінет Епіцентру | Вхід у сесію; сам логін не доводить зміну картки |
| `tools/sexopt_portal.py:107`, `tools/sexopt_portal.py:108` | Заповнення форми входу | SexOpt | Сесійна дія, не створення замовлення |
| `tools/smtm_crm.py:63` | Submit входу | SMTM | Окремо від реальних змін кошика, наведених вище |
| `start_all.sh:11`, `start_all.sh:16`, `start_laptop_services.sh:22`, `start_laptop_services.sh:28` | Запускають оркестратор, бот, LLM-worker та embedding-worker | Локальні процеси → їхні транспорти | Це точки запуску, не додатковий бар'єр перед зовнішньою дією |

### Локальні БД: джерела наступних зовнішніх змін

Це індекс SQL-записів власної системи, а не перелік SQL-з'єднань із БД маркетплейсів. Він включає довідники, стани замовлень, черги, журнали й картки. Зокрема, зміна `my_products` може передувати Prom POST (`agents/orders/price_updater.py:302`, `agents/orders/price_updater.py:331`), а snapshots впливають на заморожений XML (`tools/noire_rozetka_generator.py:1403`). Для кожного модуля наведені перші місця запису та таблиці; це допоміжний індекс, не доказ зовнішнього ефекту кожної таблиці.

| Файл:рядок запису | Таблиці власної БД | Стримування / межа висновку |
|---|---|---|
| `agents/efficiency/efficiency_agent.py:147` | `event_logs` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `agents/finance/finance_agent.py:157` | `event_logs` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `agents/interfaces/instruction_parser.py:143` | `skill_updates` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `agents/marketing/marketing_agent.py:83` | `event_logs` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `agents/orders/epicentr_order_agent.py:213` | `epicentr_processed_orders` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `agents/orders/noire_order_notifier.py:106` |  | Локальні умови: `agents/orders/noire_order_notifier.py:285`, `agents/orders/noire_order_notifier.py:291`; охоплення кожного SQL не доведено |
| `agents/orders/order_agent.py:230`, `agents/orders/order_agent.py:387` | `orders` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `agents/orders/price_engine.py:126`, `agents/orders/price_engine.py:484`, `agents/orders/price_engine.py:519` | `my_products`, `price_engine_config`, `price_history` | Локальні умови: `agents/orders/price_engine.py:474`, `agents/orders/price_engine.py:544`; охоплення кожного SQL не доведено |
| `agents/orders/price_updater.py:302` | `my_products` | Локальні умови: `agents/orders/price_updater.py:216`, `agents/orders/price_updater.py:299`; охоплення кожного SQL не доведено |
| `agents/orders/rozetka_order_agent.py:571`, `agents/orders/rozetka_order_agent.py:597`, `agents/orders/rozetka_order_agent.py:618` | `rozetka_processed_orders` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `agents/orders/toptul_supplier.py:230`, `agents/orders/toptul_supplier.py:297`, `agents/orders/toptul_supplier.py:303` | `toptul_supplier_orders` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `agents/scraper/category_classifier.py:361` | `my_products` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `agents/scraper/epicentr_cabinet.py:252` | `epicentr_sku_mapping` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `agents/scraper/generate_params_from_name.py:119` | `carvol_products` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `agents/scraper/import_carvol.py:103` | `carvol_products` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `agents/scraper/import_from_prom.py:120`, `agents/scraper/import_from_prom.py:139` | `my_products` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `agents/scraper/import_from_prom_xml.py:111`, `agents/scraper/import_from_prom_xml.py:133` | `my_products` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `agents/scraper/import_supplier_feed.py:82` | `my_products` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `agents/scraper/market_price_analyzer.py:151`, `agents/scraper/market_price_analyzer.py:163` | `market_prices`, `my_products` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `agents/scraper/playwright_base.py:185`, `agents/scraper/playwright_base.py:507` | `browser_action_log`, `browser_sessions` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `agents/scraper/run_night_processing.py:39` | `my_products` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `agents/scraper/scraper_agent.py:238` | `scraped_products` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `cli.py:139` | `alerts` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `dashboard/api.py:120` | `alerts` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `helper/ack.py:34`, `helper/ack.py:52` | `acknowledgements` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `helper/confirm.py:51`, `helper/confirm.py:71`, `helper/confirm.py:91` | `confirmations` | Локальні умови: `helper/confirm.py:176`; охоплення кожного SQL не доведено |
| `helper/inbox_cycle.py:27`, `helper/inbox_cycle.py:39` | `delivery_queue` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `ingest_prices.py:50` | `products` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `research/hypotheses.py:74`, `research/hypotheses.py:118` | `hypotheses` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `shared/mcp_servers/agent_mcp_server.py:80`, `shared/mcp_servers/agent_mcp_server.py:116`, `shared/mcp_servers/agent_mcp_server.py:139` | `SET`, `alerts`, `event_logs`, `products` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `shared/utils/action_log.py:78` |  | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `shared/utils/db.py:29`, `shared/utils/db.py:44`, `shared/utils/db.py:59` | `agents`, `alerts`, `event_logs` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `sync/epicentr_offers.py:143`, `sync/epicentr_offers.py:168`, `sync/epicentr_offers.py:174` | `pending`, `sent` | Локальні умови: `sync/epicentr_offers.py:269`; охоплення кожного SQL не доведено |
| `test_agent.py:71` | `products` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `tg_dispatcher/inbox/store.py:46`, `tg_dispatcher/inbox/store.py:56`, `tg_dispatcher/inbox/store.py:101` | `cursors`, `messages`, `reminder_state`, `tg_links` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `tg_dispatcher/main.py:492` | `rozetka_processed_orders` | Локальні умови: `tg_dispatcher/main.py:321`; охоплення кожного SQL не доведено |
| `tools/competitor_scraper.py:384` | `competitor_products` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `tools/desc_save.py:16`, `tools/desc_save.py:31` | `sexopt_generated_descriptions` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `tools/epicentr_attrs_explorer.py:139`, `tools/epicentr_attrs_explorer.py:256` | `epicentr_brand_cache`, `epicentr_required_attrs` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `tools/epicentr_category_mapper.py:88` | `toptul_epicentr_category_map` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `tools/epicentr_competitor_scraper.py:281` | `competitor_prices` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `tools/epicentr_mapping_apply.py:195`, `tools/epicentr_mapping_apply.py:196`, `tools/epicentr_mapping_apply.py:201` | `epicentr_intimate_categories` | Локальні умови: `tools/epicentr_mapping_apply.py:186`; охоплення кожного SQL не доведено |
| `tools/epicentr_pim_explorer.py:219`, `tools/epicentr_pim_explorer.py:267`, `tools/epicentr_pim_explorer.py:359` | `epicentr_brand_cache`, `epicentr_brand_map`, `epicentr_country_cache` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `tools/epicentr_quality_checker.py:251` | `epicentr_quality_log` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `tools/fetch_sexopt_attr_sets.py:113` | `epicentr_required_attrs_sexopt` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `tools/listing_pattern_analyzer.py:230`, `tools/listing_pattern_analyzer.py:240` | `listing_patterns`, `listing_samples` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `tools/moderator_findings.py:118` | `moderator_findings` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `tools/noire_classifier.py:1140` | `sexopt_extracted_params` | Локальні умови: `tools/noire_classifier.py:1125`, `tools/noire_classifier.py:1129`; охоплення кожного SQL не доведено |
| `tools/noire_country_scraper.py:199` | `sexopt_country_lookup` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `tools/noire_desc_generator.py:403` | `sexopt_generated_descriptions` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `tools/noire_epicentr_generator.py:717` | `sexopt_country_lookup` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `tools/noire_feed_scorer.py:326`, `tools/noire_feed_scorer.py:331` | `feed_score_items`, `feed_score_runs` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `tools/noire_freeze_snapshot.py:115`, `tools/noire_freeze_snapshot.py:177` | `rozetka_published_snapshot` | Локальні умови: `tools/noire_freeze_snapshot.py:108`; охоплення кожного SQL не доведено |
| `tools/noire_lingerie_scraper.py:265` | `sexopt_easytoys_specs` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `tools/noire_param_boost.py:207` | `sexopt_extracted_params` | Локальні умови: `tools/noire_param_boost.py:202`; охоплення кожного SQL не доведено |
| `tools/noire_param_extractor.py:640` | `sexopt_extracted_params` | Локальні умови: `tools/noire_param_extractor.py:670`, `tools/noire_param_extractor.py:715`; охоплення кожного SQL не доведено |
| `tools/noire_photo_audit.py:200` | `noire_photo_audit` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `tools/noire_price_override.py:146`, `tools/noire_price_override.py:224` | `sexopt_price_override` | Локальні умови: `tools/noire_price_override.py:143`, `tools/noire_price_override.py:219`; охоплення кожного SQL не доведено |
| `tools/noire_rozetka_generator.py:1312` | `noire_param_assumptions` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `tools/noire_ru_translate.py:205` | `noire_ru_translation` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `tools/noire_stock_sync.py:118`, `tools/noire_stock_sync.py:128`, `tools/noire_stock_sync.py:133` | `sexopt_products` | Локальні умови: `tools/noire_stock_sync.py:117`, `tools/noire_stock_sync.py:127`; охоплення кожного SQL не доведено |
| `tools/prom_actual_categories.py:95` | `prom_actual_category` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `tools/prom_api.py:58`, `tools/prom_api.py:219`, `tools/prom_api.py:242` | `api_test_log`, `prom_product_state`, `prom_state_history` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `tools/prom_attributes_import.py:146` | `prom_category_attributes` | Локальні умови: `tools/prom_attributes_import.py:138`, `tools/prom_attributes_import.py:139`; охоплення кожного SQL не доведено |
| `tools/prom_attrs_import.py:83`, `tools/prom_attrs_import.py:90` | `prom_attribute_values`, `prom_category_attributes` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `tools/prom_category_map_init.py:253` | `prom_category_mapping` | Локальні умови: `tools/prom_category_map_init.py:246`; охоплення кожного SQL не доведено |
| `tools/prom_commission_import.py:140`, `tools/prom_commission_import.py:147` | `prom_cpa_rates` | Локальні умови: `tools/prom_commission_import.py:134`; охоплення кожного SQL не доведено |
| `tools/prom_competitors.py:91`, `tools/prom_competitors.py:100` | `prom_competitor_offers`, `prom_competitors` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `tools/prom_desc_rewrite.py:254` | `prom_rewritten_desc` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `tools/prom_feed_converter/scripts/validator.py:222`, `tools/prom_feed_converter/scripts/validator.py:225` | `prom_feed_validator_log` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `tools/prom_serp_baseline.py:335`, `tools/prom_serp_baseline.py:370`, `tools/prom_serp_baseline.py:380` | `category_ideal_template`, `serp_baseline`, `serp_coverage`, `serp_summary` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `tools/prom_supplier_params.py:179` | `prom_derived_params` | Локальні умови: `tools/prom_supplier_params.py:175`; охоплення кожного SQL не доведено |
| `tools/prom_tag_harvest.py:164` | `prom_category_tags` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `tools/prom_unknown_vendors_load.py:103`, `tools/prom_unknown_vendors_load.py:141` | `prom_unknown_vendors` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `tools/prom_visibility_check.py:168` | `prom_visibility` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `tools/rozetka_cat_params.py:125` | `rozetka_derived_params` | Локальні умови: `tools/rozetka_cat_params.py:121`; охоплення кожного SQL не доведено |
| `tools/rozetka_lingerie_params.py:133` | `rozetka_derived_params` | Локальні умови: `tools/rozetka_lingerie_params.py:129`; охоплення кожного SQL не доведено |
| `tools/rozetka_lube_params.py:182` | `rozetka_derived_params` | Локальні умови: `tools/rozetka_lube_params.py:178`; охоплення кожного SQL не доведено |
| `tools/rozetka_photo_conflicts.py:131` | `rozetka_photo_conflicts` | Локальні умови: `tools/rozetka_photo_conflicts.py:127`; охоплення кожного SQL не доведено |
| `tools/rozetka_tariff_import.py:189` | `rozetka_cpa_rates` | Локальні умови: `tools/rozetka_tariff_import.py:139`, `tools/rozetka_tariff_import.py:174`; охоплення кожного SQL не доведено |
| `tools/sexopt_prices.py:176` | `sexopt_dropship_price` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `tools/sexopt_ru_import.py:108` | `sexopt_products_ru` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `tools/supplier_onboarding.py:756`, `tools/supplier_onboarding.py:768` | `supplier_category_map`, `suppliers` | Локальні умови: `tools/supplier_onboarding.py:488`, `tools/supplier_onboarding.py:528`; охоплення кожного SQL не доведено |
| `tools/toptul_desc_translate.py:655`, `tools/toptul_desc_translate.py:705`, `tools/toptul_desc_translate.py:1063` | `toptul_desc_translation`, `toptul_translation` | Локальні умови: `tools/toptul_desc_translate.py:1387`; охоплення кожного SQL не доведено |
| `tools/toptul_homoglyph_normalize.py:120` | `toptul_translation` | Локальні умови: `tools/toptul_homoglyph_normalize.py:115`; охоплення кожного SQL не доведено |
| `tools/toptul_param_rename_apply.py:104` | `toptul_translation` | Локальні умови: `tools/toptul_param_rename_apply.py:93`; охоплення кожного SQL не доведено |
| `tools/toptul_rozetka_map.py:268` | `toptul_rozetka_category_map` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |
| `tools/toptul_translate.py:351` | `toptul_translation` | Локальні умови: `tools/toptul_translate.py:335`; охоплення кожного SQL не доведено |
| `tools/toptul_translate_load.py:175` | `toptul_translation` | Локальні умови: `tools/toptul_translate_load.py:169`; охоплення кожного SQL не доведено |
| `tools/web_api_explorer.py:802` | `api_test_log` | У наведених SQL немає перевірки власницького live-дозволу; інші умови сценарію окремі |

## Дії без стримувань

Головний ризик — наведені нижче функції виконують дію при виклику, без власницького дозволу. Умови на кшталт «товар знайдено» чи «API дозволяє статус» обмежують дані, але не закривають цей ризик.

- **Ціни, наявність, повідомлення покупцям і замовлення через MCP Prom:** `shared/mcp_servers/prom_mcp.py:426`, `shared/mcp_servers/prom_mcp.py:443`, `shared/mcp_servers/prom_mcp.py:501`, `shared/mcp_servers/prom_mcp.py:527`, `shared/mcp_servers/prom_mcp.py:573`.
- **Статус через MCP Rozetka та контакти/доставка/коментар Епіцентру:** `shared/mcp_servers/rozetka_mcp.py:269`, `shared/mcp_servers/epicentr_mcp.py:303`, `shared/mcp_servers/epicentr_mcp.py:336`, `shared/mcp_servers/epicentr_mcp.py:358`. Решта записів Epicentr MCP має лише перевірки формату/переходу (`:220`, `:248`).
- **Прямі статуси й ТТН Rozetka, скасування Епіцентру:** `agents/orders/rozetka_order_agent.py:246`, `agents/orders/rozetka_order_agent.py:276`, `agents/orders/rozetka_order_agent.py:507`, `agents/orders/epicentr_order_agent.py:183`. Whitelist `confirm_order` не охоплює ці окремі функції (`agents/orders/rozetka_order_agent.py:405`).
- **Листи постачальникам і документ Carvol без test/live:** `agents/orders/order_agent.py:381`, `agents/orders/epicentr_order_agent.py:365`, `agents/orders/rozetka_order_agent.py:794`, `agents/orders/rozetka_order_agent.py:857`. Режим TOPTUL захищає тільки інший SMTP-виклик (`agents/orders/toptul_supplier.py:201`).
- **Універсальний вихід у API, імпорт XLS, кошик CRM:** `tools/web_api_explorer.py:871`, `agents/scraper/epicentr_cabinet.py:283`, `tools/smtm_crm.py:109`, `tools/smtm_crm.py:123`. Їх не обмежує `research/veto.check`, який лише повертає список проблем (`research/veto.py:16`, `research/veto.py:72`).
- **Запис атрибутів без dry/підтвердження:** `tools/epicentr_attr_fill_multi.py:133`; map/cat/limit не є дозволом (`:64`). Інші classify/fill мають планувальні режими, але запис за замовчуванням (наприклад `tools/epicentr_classify_rules.py:197`, `:284`).
- **Обхід цінового бар'єра через прямі функції:** `agents/orders/rozetka_price_corrector.py:51`, `agents/orders/price_engine.py:536`, `sync/epicentr_offers.py:228`. CLI dry/run не захищає довільний прямий виклик.
- **Автоматична публікація фідів без live-consent:** `agents/orders/feed_sync.py:205`, `agents/orders/carvol_epicentr_sync.py:203`, `agents/orders/rozetka_github_sync.py:267`, `agents/orders/katran_github_sync.py:53`; прямий `tools/noire_stock_sync.py:290` теж не перевіряє згоду.
- **Заміна захищеного фіду та довільний вихідний шлях:** `tools/noire_stock_sync.py:443`, `tools/noire_epicentr_generator.py:1788`. Навіть FAIL валідатора не зупиняє саме цей move (`tools/noire_stock_sync.py:433`).

### Розбіжності з правилами

- «Carvol — тільки читання» закодовано як правило аналізатора (`research/veto.py:9`, `research/veto.py:46`), проте Carvol-фід переписується і публікується (`agents/orders/carvol_epicentr_sync.py:153`, `:203`), а Carvol отримує документ (`agents/orders/rozetka_order_agent.py:794`). Це здатність коду, а не доказ запуску всупереч поточному рішенню власника.
- «Зміст після модерації заморожений» перевіряє veto (`research/veto.py:42`); NOIRE Rozetka має snapshot (`tools/noire_rozetka_generator.py:1403`). Але XML-редактор `tools/fix_rozetka_xml.py:456` і довільний `--output` генератора (`tools/noire_epicentr_generator.py:1829`) не мають загального зв'язку з цим правилом.
- Docstring регенерації обіцяє перевірку валідатором (`tools/noire_stock_sync.py:379`); код отримує FAIL-лічильник (`:433`) і все одно виконує move (`:443`). Перевірка відбулась, але це не блокування помилкового результату.
- TASK-27 вимагає protected file (`docs/tasks/TASK-27-veto.md:16`), а регенератор його замінює (`tools/noire_stock_sync.py:443`). Аналізатор не є обов'язковим транспортним бар'єром.

## Лише читання

Тут «читання» стосується бізнес-даних зовнішньої системи. Завантаження кешу, журнал або локальна БД можуть змінюватися окремо; назва `audit`, `search` чи `test` сама цього не гарантує (`tools/prom_search.py:117`, `tools/prom_api.py:158`).

| Модуль/операція | Доказ і межа |
|---|---|
| Адаптер Prom | `integrations/prom.py:17`: транспорт GET; messages/orders (`:37`, `:43`), без write-методів |
| Адаптер Rozetka | `integrations/rozetka.py:98`: GET; замовлення, чати, повернення, відгуки, баланс, лічильники (`:126`, `:162`, `:202`, `:223`, `:226`, `:237`) |
| Адаптер Нової Пошти | `integrations/novaposhta.py:23`: лише ttn_status; POST TrackingDocument.getStatusDocuments (`:31`) |
| Старий NP helper | `agents/orders/np_api.py:50`: той самий getStatusDocuments; зіставлення замовлень (`:108`) не створює ТТН |
| Читання листів постачальника | `tools/supplier_ttn_mail.py:66`: IMAP BODY.PEEK; `:101` — POST читання статусу НП, не SMTP-відправлення |
| План відповіді inbox | `tg_dispatcher/inbox/reply.py:11`: будує план; навіть action=send не відправляє (`:34`); runtime має заглушку (`helper_bot/main.py:311`) |
| Veto | `research/veto.py:16`, `research/veto.py:72`: повертає порушення; не застосовує зміни і не перехоплює довільні записи |
| Цінове ядро TOPTUL | `tools/price_engine_toptul.py:66`: розрахунок floor/price, не HTTP-відправлення |
| Оцінка картки | `agents/marketing/card_optimizer.py:8`: score_card обчислює оцінку, не редагує картку в кабінеті |
| JS через browser MCP | `shared/mcp_servers/browser_mcp.py:571`: заглушка; не плутати з реальною функцією імпорту XLS (`:491`) |
| Валідація XML Rozetka через POST | `shared/mcp_servers/rozetka_mcp.py:292`: відправляє URL на перевірку, не містить операції зміни товару; побічні ефекти сервісу не перевірені |
| Службові адаптери retry/errors | `integrations/retry.py:4`, `integrations/errors.py:7`: обгортка повторів і типи помилок, не власні write endpoints |

POST логіну — окрема сесійна дія, не редагування товару: наприклад `shared/mcp_servers/rozetka_mcp.py:52`, `tools/epicentr_comments_scan.py:29`, `tools/epicentr_products_dump.py:24`. Тому збіг слова POST не є сам по собі доказом бізнес-запису. Для класифікаторів таблиця вище показує саме PUT після логіну (`tools/epicentr_classify_rules.py:284`).

## Перевірка трьох тверджень

1. **«Жоден модуль не пише у `output/noire_epicentr_phase1.xml`» — неправда.** FEED визначений у `tools/noire_stock_sync.py:247`; `regenerate_feed` створює XML у тимчасовому файлі (`:395`) і замінює FEED через `shutil.move` (`:443`). Згода `:700` стоїть у CLI-публікації, не в регенераторі. Додатково генератор приймає довільний `--output` (`tools/noire_epicentr_generator.py:1829`) і пише туди (`:1788`).
2. **«Усі адаптери в `integrations/` — тільки читання» — правда щодо реалізованих бізнес-операцій.** Prom і Rozetka використовують GET (`integrations/prom.py:17`, `integrations/rozetka.py:98`), NP — POST лише getStatusDocuments (`integrations/novaposhta.py:31`). Це твердження не поширюється на `shared/mcp_servers/`: Prom MCP реально відповідає покупцю (`shared/mcp_servers/prom_mcp.py:573`). Семантика довільно підставленого транспортного callback поза межами цих адаптерів не гарантується.
3. **«Ціна ніде не може піти нижче порогу, бо перевірка одна й та сама» — неправда.** TOPTUL має `max(rrp, loss_floor)` (`tools/price_engine_toptul.py:67`); загальна формула повертає `max(rounded, min_price)` (`shared/utils/pricing.py:409`); NOIRE override звіряє net з retail (`tools/noire_price_override.py:175`); sync порівнює лише непорожній floor (`sync/epicentr_offers.py:51`). Це різні перевірки. Прямий Prom MCP відправляє batch без floor (`shared/mcp_servers/prom_mcp.py:501`), Rozetka PUT — передану ціну (`agents/orders/rozetka_price_corrector.py:53`), CSV — значення без повторної перевірки (`agents/orders/rozetka_price_manager.py:234`). Доведена можливість обходу в коді; реальний продаж нижче порогу цим аудитом не встановлений.

## Не перевірено і чому

- Мережа, сервер, кабінети, поточний cron, права токенів, SMTP-доставка та фактичний стан live не перевірялися: TASK-33 вимагає локального дослідження (`docs/tasks/TASK-33-audit-writes.md:30`), AGENTS забороняє зовнішні API (`AGENTS.md:31`). Наявність виклику в коді не доводить його доступність чи запуск.
- Секрети, `.env`, сесійні файли, живі БД, покупецькі дані не відкривалися (`AGENTS.md:30`). Отже, зокрема значення TOPTUL_SEND_MODE і consent-store невідомі; можна підтвердити лише defaults/механізм (`agents/orders/toptul_supplier.py:59`, `shared/utils/consent.py:70`).
- Прямого SQL-доступу до **БД, що належить маркетплейсу**, в описаних шляхах не встановлено. `products`, `my_products`, `noire_products` — репозиторні таблиці, а запис у кабінет іде HTTP/браузером: приклади `shared/mcp_servers/agent_mcp_server.py:139`, `agents/orders/price_updater.py:302`, `agents/orders/price_updater.py:331`. Реальний хост БД без конфігурації не встановлювався.
- Файли резервних версій не вважалися підтверджено підключеними runtime-модулями. Їхні окремі write-sites наведені нижче; запуск старої копії може відновити старий запис, але чинний маршрут імпорту/cron для копій не підтверджений.
- Документація API та сторонній приклад PHP не дорівнюють активній інтеграції: наприклад `shared/knowledge_base/novaposhta/api_v2_reference/lis-dev_NovaPoshtaApi2.php:1`. Бібліотеки venv, Git-об'єкти, бінарні exports і вміст даних не використовувалися як виконувані власні модулі. Повнота щодо динамічно сформованого стороннього коду не гарантується; в репозиторії є генерація коду (`agents/dev/dev_agent.py:65`) та запуск скриптів (`shared/mcp_servers/browser_mcp.py:372`).

### Резервні копії з потенційними діями

Посилання нижче підтверджують наявність коду в копіях, а не його активність. Розширення `.bak` не робить код безпечним при явному запуску інтерпретатором. Для копій наведені характерні точки кожного типу дії; повну еквівалентність чинним модулям не припущено.

| Файл:рядок і тип дії | Стримування / статус |
|---|---|
| HTTP/пошта/Telegram: `agents/orders/order_agent.py.bak-20260909:148`, `agents/orders/order_agent.py.bak-20260909:356`, `agents/orders/order_agent.py.bak-20260909:378`; файловий запис: `agents/orders/order_agent.py.bak-20260909:266`, `agents/orders/order_agent.py.bak-20260909:267`, `agents/orders/order_agent.py.bak-20260909:268`, `agents/orders/order_agent.py.bak-20260909:269` (та інші збіги); SQL-зміни: `agents/orders/order_agent.py.bak-20260909:205`, `agents/orders/order_agent.py.bak-20260909:362` | Архівна копія; підключення та захист не підтверджено, автоматично не успадковує захист чинного модуля |
| HTTP/пошта/Telegram: `agents/orders/rozetka_order_agent.py.bak:60`, `agents/orders/rozetka_order_agent.py.bak:195`, `agents/orders/rozetka_order_agent.py.bak:225`, `agents/orders/rozetka_order_agent.py.bak:242` (та інші збіги); файловий запис: `agents/orders/rozetka_order_agent.py.bak:503`, `agents/orders/rozetka_order_agent.py.bak:504`, `agents/orders/rozetka_order_agent.py.bak:505`, `agents/orders/rozetka_order_agent.py.bak:506` (та інші збіги); SQL-зміни: `agents/orders/rozetka_order_agent.py.bak:412`, `agents/orders/rozetka_order_agent.py.bak:433` | Архівна копія; підключення та захист не підтверджено, автоматично не успадковує захист чинного модуля |
| HTTP/пошта/Telegram: `agents/orders/rozetka_order_agent.py.bak-20260909:60`, `agents/orders/rozetka_order_agent.py.bak-20260909:244`, `agents/orders/rozetka_order_agent.py.bak-20260909:274`, `agents/orders/rozetka_order_agent.py.bak-20260909:291` (та інші збіги); файловий запис: `agents/orders/rozetka_order_agent.py.bak-20260909:578`, `agents/orders/rozetka_order_agent.py.bak-20260909:579`, `agents/orders/rozetka_order_agent.py.bak-20260909:580`, `agents/orders/rozetka_order_agent.py.bak-20260909:581` (та інші збіги); SQL-зміни: `agents/orders/rozetka_order_agent.py.bak-20260909:461`, `agents/orders/rozetka_order_agent.py.bak-20260909:487`, `agents/orders/rozetka_order_agent.py.bak-20260909:508` | Архівна копія; підключення та захист не підтверджено, автоматично не успадковує захист чинного модуля |
| HTTP/пошта/Telegram: `agents/orders/rozetka_order_agent.py.bak-20260918:60`, `agents/orders/rozetka_order_agent.py.bak-20260918:244`, `agents/orders/rozetka_order_agent.py.bak-20260918:274`, `agents/orders/rozetka_order_agent.py.bak-20260918:291` (та інші збіги); файловий запис: `agents/orders/rozetka_order_agent.py.bak-20260918:686`, `agents/orders/rozetka_order_agent.py.bak-20260918:687`, `agents/orders/rozetka_order_agent.py.bak-20260918:688`, `agents/orders/rozetka_order_agent.py.bak-20260918:689` (та інші збіги); SQL-зміни: `agents/orders/rozetka_order_agent.py.bak-20260918:569`, `agents/orders/rozetka_order_agent.py.bak-20260918:595`, `agents/orders/rozetka_order_agent.py.bak-20260918:616`, `agents/orders/rozetka_order_agent.py.bak-20260918:871` | Архівна копія; підключення та захист не підтверджено, автоматично не успадковує захист чинного модуля |
| HTTP/пошта/Telegram: `agents/orders/rozetka_order_agent.py.bak2:59`, `agents/orders/rozetka_order_agent.py.bak2:194`, `agents/orders/rozetka_order_agent.py.bak2:224`, `agents/orders/rozetka_order_agent.py.bak2:241` (та інші збіги); файловий запис: `agents/orders/rozetka_order_agent.py.bak2:456`, `agents/orders/rozetka_order_agent.py.bak2:457`, `agents/orders/rozetka_order_agent.py.bak2:458`, `agents/orders/rozetka_order_agent.py.bak2:459` (та інші збіги); SQL-зміни: `agents/orders/rozetka_order_agent.py.bak2:386` | Архівна копія; підключення та захист не підтверджено, автоматично не успадковує захист чинного модуля |
| файловий запис: `backups/prom_20260912/noire_prom_generator.py:1357` | Архівна копія; підключення та захист не підтверджено, автоматично не успадковує захист чинного модуля |
| файловий запис: `backups/prom_20260912/noire_prom_generator.py.before_0913:1603` | Архівна копія; підключення та захист не підтверджено, автоматично не успадковує захист чинного модуля |
| файловий запис: `backups/prom_20260912/noire_prom_generator.py.before_homoglyph:1554` | Архівна копія; підключення та захист не підтверджено, автоматично не успадковує захист чинного модуля |
| файловий запис: `backups/prom_20260912/prom_content_fix.py:326` | Архівна копія; підключення та захист не підтверджено, автоматично не успадковує захист чинного модуля |
| HTTP/пошта/Telegram: `backups/rozetka_agent_20260913/rozetka_order_agent.py.bak:60`, `backups/rozetka_agent_20260913/rozetka_order_agent.py.bak:244`, `backups/rozetka_agent_20260913/rozetka_order_agent.py.bak:274`, `backups/rozetka_agent_20260913/rozetka_order_agent.py.bak:291` (та інші збіги); файловий запис: `backups/rozetka_agent_20260913/rozetka_order_agent.py.bak:578`, `backups/rozetka_agent_20260913/rozetka_order_agent.py.bak:579`, `backups/rozetka_agent_20260913/rozetka_order_agent.py.bak:580`, `backups/rozetka_agent_20260913/rozetka_order_agent.py.bak:581` (та інші збіги); SQL-зміни: `backups/rozetka_agent_20260913/rozetka_order_agent.py.bak:461`, `backups/rozetka_agent_20260913/rozetka_order_agent.py.bak:487`, `backups/rozetka_agent_20260913/rozetka_order_agent.py.bak:508`, `backups/rozetka_agent_20260913/rozetka_order_agent.py.bak:763` | Архівна копія; підключення та захист не підтверджено, автоматично не успадковує захист чинного модуля |
| HTTP/пошта/Telegram: `backups/tg_20260913/noire_stock_sync.py.bak:57`; файловий запис: `backups/tg_20260913/noire_stock_sync.py.bak:440`, `backups/tg_20260913/noire_stock_sync.py.bak:491`, `backups/tg_20260913/noire_stock_sync.py.bak:593`; SQL-зміни: `backups/tg_20260913/noire_stock_sync.py.bak:115`, `backups/tg_20260913/noire_stock_sync.py.bak:125`, `backups/tg_20260913/noire_stock_sync.py.bak:130`, `backups/tg_20260913/noire_stock_sync.py.bak:140` (та інші збіги) | Архівна копія; підключення та захист не підтверджено, автоматично не успадковує захист чинного модуля |
| HTTP/пошта/Telegram: `backups/tg_20260913/watchdog.py.bak:141`; файловий запис: `backups/tg_20260913/watchdog.py.bak:315`, `backups/tg_20260913/watchdog.py.bak:429`, `backups/tg_20260913/watchdog.py.bak:473`, `backups/tg_20260913/watchdog.py.bak:511` (та інші збіги) | Архівна копія; підключення та захист не підтверджено, автоматично не успадковує захист чинного модуля |
| HTTP/пошта/Telegram: `tg_dispatcher/main.py.bak:240`, `tg_dispatcher/main.py.bak:244` | Архівна копія; підключення та захист не підтверджено, автоматично не успадковує захист чинного модуля |
| HTTP/пошта/Telegram: `tg_dispatcher/main.py.bak-20260909:240`, `tg_dispatcher/main.py.bak-20260909:244`; SQL-зміни: `tg_dispatcher/main.py.bak-20260909:347` | Архівна копія; підключення та захист не підтверджено, автоматично не успадковує захист чинного модуля |
| HTTP/пошта/Telegram: `tg_dispatcher/main.py.bak-20260918:253`, `tg_dispatcher/main.py.bak-20260918:257`; SQL-зміни: `tg_dispatcher/main.py.bak-20260918:366` | Архівна копія; підключення та захист не підтверджено, автоматично не успадковує захист чинного модуля |
| файловий запис: `tools/carvol_epicentr_generator.py.bak:624` | Архівна копія; підключення та захист не підтверджено, автоматично не успадковує захист чинного модуля |
| файловий запис: `tools/noire_prom_generator.py.bak-0811:506` | Архівна копія; підключення та захист не підтверджено, автоматично не успадковує захист чинного модуля |
| файловий запис: `tools/noire_rozetka_generator.py.bak-0811:901` | Архівна копія; підключення та захист не підтверджено, автоматично не успадковує захист чинного модуля |
| HTTP/пошта/Telegram: `tools/np_create_ttn.py.bak-20260916:67`, `tools/np_create_ttn.py.bak-20260916:92`, `tools/np_create_ttn.py.bak-20260916:99`, `tools/np_create_ttn.py.bak-20260916:113`; файловий запис: `tools/np_create_ttn.py.bak-20260916:277` | Архівна копія; підключення та захист не підтверджено, автоматично не успадковує захист чинного модуля |
| SQL-зміни: `tools/prom_api.py.bak-20260909:58`, `tools/prom_api.py.bak-20260909:177` | Архівна копія; підключення та захист не підтверджено, автоматично не успадковує захист чинного модуля |
| файловий запис: `tools/prom_marker_check.py.bak:82`, `tools/prom_marker_check.py.bak:84` | Архівна копія; підключення та захист не підтверджено, автоматично не успадковує захист чинного модуля |
| файловий запис: `tools/prom_marker_step.py.bak:56` | Архівна копія; підключення та захист не підтверджено, автоматично не успадковує захист чинного модуля |
| файловий запис: `tools/toptul_rozetka_generator.py.bak-20260911:657` | Архівна копія; підключення та захист не підтверджено, автоматично не успадковує захист чинного модуля |
