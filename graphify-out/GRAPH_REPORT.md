# Graph Report - agent-system  (2026-09-05)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 2574 nodes · 4824 edges · 195 communities (143 shown, 28 thin omitted)
- Extraction: 98% EXTRACTED · 2% INFERRED · 0% AMBIGUOUS · INFERRED: 73 edges (avg confidence: 0.85)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `1bbef26e`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- Community 0
- Community 1
- Community 2
- Community 3
- Community 4
- Community 5
- Community 6
- Community 7
- Community 8
- Community 9
- Community 10
- Community 11
- Community 12
- Community 13
- Community 14
- Community 15
- Community 16
- Community 17
- Community 18
- Community 19
- Community 20
- Community 21
- Community 22
- Community 23
- Community 24
- Community 25
- Community 26
- Community 27
- Community 28
- Community 29
- Community 30
- Community 31
- Community 32
- Community 33
- Community 34
- Community 35
- Community 36
- Community 37
- Community 38
- Community 39
- Community 40
- Community 41
- Community 42
- Community 43
- Community 44
- Community 45
- Community 46
- Community 47
- Community 48
- Community 49
- Community 50
- Community 51
- Community 52
- Community 53
- Community 54
- Community 55
- Community 56
- Community 57
- Community 58
- Community 59
- Community 60
- Community 61
- Community 62
- Community 63
- Community 64
- Community 65
- Community 66
- Community 67
- Community 68
- Community 69
- Community 70
- Community 71
- Community 72
- Community 73
- Community 74
- Community 75
- Community 76
- Community 77
- Community 78
- Community 79
- Community 80
- Community 81
- Community 82
- Community 83
- Community 84
- Community 85
- Community 86
- Community 87
- Community 88
- Community 89
- Community 90
- Community 91
- Community 92
- Community 93
- Community 94
- Community 95
- Community 96
- Community 97
- Community 98
- Community 99
- Community 100
- Community 101
- Community 102
- Community 103
- Community 104
- Community 105
- Community 106
- Community 107
- Community 108
- Community 109
- Community 110
- Community 111
- Community 112
- Community 113
- Community 114
- Community 115
- Community 116
- Community 117
- Community 118
- Community 119
- Community 120
- Community 121
- Community 122
- Community 123
- Community 124
- Community 125
- Community 126
- Community 127
- Community 128
- Community 129
- Community 130
- Community 131
- Community 132
- Community 133
- Community 134
- Community 135
- Community 136
- Community 137
- Community 138
- Community 139
- Community 140
- Community 141
- Community 142
- Community 143
- Community 144
- Community 145
- Community 146
- Community 147
- Community 148
- Community 149
- Community 150
- Community 151
- Community 152
- Community 153
- Community 154
- Community 155
- Community 156
- Community 157
- Community 158
- Community 161
- Community 162
- Community 163
- Community 167
- Community 168
- Community 169
- Community 170
- Community 171
- Community 174
- Community 175
- Community 176
- Community 177

## God Nodes (most connected - your core abstractions)
1. `get_connection()` - 310 edges
2. `extract_all_params()` - 41 edges
3. `generate()` - 33 edges
4. `generate()` - 32 edges
5. `PlaywrightBase` - 31 edges
6. `generate()` - 31 edges
7. `ru_words()` - 25 edges
8. `update_agent_status()` - 24 edges
9. `log_event()` - 23 edges
10. `request_llm()` - 22 edges

## Surprising Connections (you probably didn't know these)
- `cmd_learn()` --uses--> `InstructionParser`  [INFERRED]
  tg_dispatcher/main.py → agents/interfaces/instruction_parser.py
- `handle_document()` --indirect_call--> `get_order_details()`  [INFERRED]
  tg_dispatcher/main.py → agents/orders/rozetka_order_agent.py
- `handle_document()` --indirect_call--> `change_status()`  [INFERRED]
  tg_dispatcher/main.py → agents/orders/rozetka_order_agent.py
- `handle_document()` --indirect_call--> `set_ttn()`  [INFERRED]
  tg_dispatcher/main.py → agents/orders/rozetka_order_agent.py
- `is_already_processed()` --calls--> `get_connection()`  [EXTRACTED]
  agents/orders/rozetka_order_agent.py → shared/utils/db.py

## Import Cycles
- None detected.

## Communities (195 total, 28 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.05
Nodes (62): build(), load(), main(), name_phrase(), natural(), Рід іменника за закінченням: досить точно для узгодження прикметника., Найточніший тип товару з наших характеристик, або порожньо., Перші слова назви — вже граматично узгоджена фраза, беремо як є. (+54 more)

### Community 1 - "Community 1"
Cohesion: 0.05
Nodes (54): decide(), login(), main(), Приводить значення до форми, якої чекає атрибут даного типу., _wrap(), decide(), login(), main() (+46 more)

### Community 2 - "Community 2"
Cohesion: 0.05
Nodes (59): brand_cyr(), Кириличне написання бренду або порожньо, якщо його не існує., calc_price(), cdata(), esc(), fit_params(), fix_caps(), generate() (+51 more)

### Community 3 - "Community 3"
Cohesion: 0.06
Nodes (58): ensure_table(), extract_all_params(), extract_clothing_size(), extract_color(), extract_diameter_mm(), extract_length_mm(), extract_material(), extract_mode_count() (+50 more)

### Community 4 - "Community 4"
Cohesion: 0.07
Nodes (48): _best_match(), calc_sell_price(), _cell_value(), _detect_cam_resolution(), _detect_cam_view(), detect_car_brands_from_name(), detect_columns(), _detect_din() (+40 more)

### Community 5 - "Community 5"
Cohesion: 0.07
Nodes (36): build_col_index(), count_before_unit(), drive_square(), ean13_from_article(), extract_model_code(), find_col(), first_num(), h_bity() (+28 more)

### Community 6 - "Community 6"
Cohesion: 0.06
Nodes (32): analyze_all(), Аналізує всі товари і виводить статистику, Оцінює картку товару від 0 до 100, score_card(), escape_xml(), generate_xml(), parse_and_import(), parse_and_import() (+24 more)

### Community 7 - "Community 7"
Cohesion: 0.07
Nodes (44): DataFrame, build_description(), load_opts(), main(), material_of(), purpose_of(), Матеріал за тканиною в назві або описі. `fallback=True` дає «тканина», коли…, Шаблонний опис для одягу. Для цієї категорії 80 % рішення про покупку — це… (+36 more)

### Community 8 - "Community 8"
Cohesion: 0.08
Nodes (46): bad_forms(), classify(), feed_ids(), _guess_name(), main(), Чи пройшов би оффер решту перевірок генератора, якби категорія була. Порядок і…, Назва відхиленої здогадки — щоб у звіті було видно, ЩО саме відхилено., Те саме рішення, що й у генераторі, тільки з назвою причини. (+38 more)

### Community 9 - "Community 9"
Cohesion: 0.09
Nodes (37): load_live(), main(), manager_categories(), tools/epicentr_mapping_apply.py ================================ Вносить у БД…, attributeSetCode → кількість карток NOIRE у кабінеті., Повертає epicentr_category_mapping до стану з резервної копії. Потрібне тому,…, revert(), load() (+29 more)

### Community 10 - "Community 10"
Cohesion: 0.10
Nodes (43): apply_fixes(), ask(), audit(), batches(), budget_for(), check(), check_word(), collect() (+35 more)

### Community 11 - "Community 11"
Cohesion: 0.10
Nodes (34): InstructionParser, agents/interfaces/instruction_parser.py…, Зберігає лог в таблицю skill_updates., Повертає історію /learn команд., Визначає який файл скіла оновити по тексту інструкції., Форматує інструкцію як markdown блок., Застосовує /learn інструкцію: 1. Визначає файл 2. Дописує правило 3. Зберігає в…, cmd_alerts() (+26 more)

### Community 12 - "Community 12"
Cohesion: 0.14
Nodes (20): C, calc_price(), detect_structure(), ensure_tables(), err(), generate_xml(), get_db(), get_rozetka_categories() (+12 more)

### Community 13 - "Community 13"
Cohesion: 0.11
Nodes (34): bad_words(), main(), Російські слова перекладу, крім артикулів, перенесених незмінними. Без цього…, collect(), ensure(), esc(), main(), Один рядок TSV. Зворотна операція — `unesc()` у завантажувачі. (+26 more)

### Community 14 - "Community 14"
Cohesion: 0.09
Nodes (35): audit_feed(), _by_head_noun(), _by_rules(), _emit(), extract(), faces_in(), is_set(), _keep_known() (+27 more)

### Community 15 - "Community 15"
Cohesion: 0.12
Nodes (33): accept_order(), build_message(), cycle(), decide(), ensure_table(), get_details(), get_orders(), item_sku() (+25 more)

### Community 16 - "Community 16"
Cohesion: 0.08
Nodes (25): App(), CTASection(), cardVariants, containerVariants, Feature, Features, Footer(), LEGAL_LINKS (+17 more)

### Community 17 - "Community 17"
Cohesion: 0.14
Nodes (33): check_carvol_rozetka_feed(), check_cron(), check_git(), check_noire_feed(), check_noire_prom_feed(), check_noire_rozetka_feed(), check_rozetka_messages(), check_services() (+25 more)

### Community 18 - "Community 18"
Cohesion: 0.10
Nodes (31): _brand_country(), clean_pics(), esc(), fix_volume(), generate(), group_key(), lingerie_type(), load_derived_params() (+23 more)

### Community 19 - "Community 19"
Cohesion: 0.11
Nodes (29): check_availability(), confirm_order(), create_order_excel(), main(), Order Agent Daemon — нескінченний цикл з watchdog Запускається через systemd,…, tg(), get_new_orders(), init_db() (+21 more)

### Community 20 - "Community 20"
Cohesion: 0.11
Nodes (26): load_db_products(), load_feed(), load_prom_map(), agents/orders/price_updater.py ================================ Щоденне…, Завантажує всі товари з Prom API. Повертає dict: SKU → {id, price}, Завантажує товари з БД. Args: limit: обмеження кількості (None = всі) force:…, Завантажує XML фід TOPTUL. SKU береться з <vendorCode>., run() (+18 more)

### Community 21 - "Community 21"
Cohesion: 0.12
Nodes (14): main(), ProductChecker, Element, QualityReport, tools/epicentr_quality_checker.py Інструмент перевірки якості XML-фіду для…, 1 фото → 5, 2-3 → 10, 4+ → 15; score: 0-15, measure є → +4, ratio є → +3, brand є → +3; score: 0-10, weight>0 → +3, всі габарити → +4, weight 50-50000 → +3; score: 0-10 (+6 more)

### Community 22 - "Community 22"
Cohesion: 0.12
Nodes (27): allowed_roots(), brand_of(), build_prompt(), call_ollama(), check_text(), clean_output(), count_occurrences(), dedupe_mention() (+19 more)

### Community 23 - "Community 23"
Cohesion: 0.11
Nodes (26): accept_order(), cancel_order(), create_order_excel(), get_feed_data(), get_new_orders(), get_order_details(), is_already_processed(), main() (+18 more)

### Community 24 - "Community 24"
Cohesion: 0.11
Nodes (26): cleanup_old_history(), load_config(), load_db_products(), load_feed(), load_previous_prices(), load_prom_map(), process_products(), agents/orders/price_engine.py ============================== Головний двигун… (+18 more)

### Community 25 - "Community 25"
Cohesion: 0.11
Nodes (26): add_order_comment(), add_order_ttn(), find_delivery_office(), get_attribute_options(), get_cancel_reasons(), get_categories(), get_delivery_invoice(), get_order() (+18 more)

### Community 26 - "Community 26"
Cohesion: 0.12
Nodes (25): calc_sell_price(), country_code(), escape_xml(), generate_xml(), load_brand_cache(), load_brand_map(), load_category_mapping(), load_country_estimated() (+17 more)

### Community 27 - "Community 27"
Cohesion: 0.10
Nodes (25): create_order_excel(), delete_from_db(), get_carvol_feed(), _get_db_processed_at(), get_db_status(), get_noire_articles(), main(), _order_recipient_info() (+17 more)

### Community 28 - "Community 28"
Cohesion: 0.14
Nodes (24): build_brand_map(), _cache_brands(), explore_category(), find_brand(), _get(), get_atset_attributes(), get_attribute_options(), get_category_atset() (+16 more)

### Community 29 - "Community 29"
Cohesion: 0.14
Nodes (22): cmd_report(), ensure_table(), main(), pending(), Ділимо по межах тегів/речень, щоб не розірвати розмітку., Порожній рядок = придатний переклад; інакше — причина., SKU з описом лише українською і без готового перекладу., split_chunks() (+14 more)

### Community 30 - "Community 30"
Cohesion: 0.13
Nodes (23): Рядки для Telegram-звіту. Порожньо, якщо порушень немає., tg_lines(), check_antidumping(), fetch_xls(), full_sync(), main(), parse_price(), publish_github() (+15 more)

### Community 31 - "Community 31"
Cohesion: 0.18
Nodes (22): check_marketplace(), fix_types(), get_products(), get_settings(), get_stats(), mark_read(), mask_token(), page_chat() (+14 more)

### Community 32 - "Community 32"
Cohesion: 0.13
Nodes (20): NamedTuple, can_cover(), get_name_ua(), main(), Повертає джерело даних у sexopt_products або '—'., check_offer(), fetch_required_attrs_api(), Issue (+12 more)

### Community 33 - "Community 33"
Cohesion: 0.13
Nodes (19): fix_name_ua(), generate_description_ua(), process_card(), Перекладає параметри з російської на українську, Виправляє назву за вимогами Розетки, Генерує опис українською через Ollama, Обробляє одну картку товару і повертає готовий offer, translate_params() (+11 more)

### Community 34 - "Community 34"
Cohesion: 0.18
Nodes (20): claim_check(), ensure(), facts_for(), generate(), limit_for(), main(), Структуровані факти: назва, категорія, характеристики фіду й кабінету., Ліміт символів за кількістю фактів. Рішення власника 17.08.2026. Сенс: не дати… (+12 more)

### Community 35 - "Community 35"
Cohesion: 0.12
Nodes (11): EpicentrCabinet, main(), agents/scraper/epicentr_cabinet.py =====================================…, Перевіряє авторизацію і логінить якщо треба., Скачує XLS всіх товарів з кабінету Єпіцентру. Повертає шлях до збереженого…, Парсить XLS і витягує маппінг: наш_SKU ↔ артикул_Єпіцентру. Зберігає в таблицю…, Завантажує XLS з оновленими цінами/наявністю в Єпіцентр., Проходить по всіх розділах кабінету і перехоплює XHR запити. Повертає список… (+3 more)

### Community 36 - "Community 36"
Cohesion: 0.10
Nodes (10): PlaywrightBase, Зберігає поточну сесію в БД., Перевіряє чи сесія активна в БД., Повертає текст елемента., Парсить HTML таблицю в список dict., Виконує JS на сторінці., Починає запис XHR/fetch запитів., Витягує Bearer token з localStorage або cookies. (+2 more)

### Community 37 - "Community 37"
Cohesion: 0.44
Nodes (20): blue(), bold(), C, check_marketplaces(), color(), create_skill_interactive(), cyan(), gray() (+12 more)

### Community 38 - "Community 38"
Cohesion: 0.20
Nodes (19): audit(), fix_digit_token(), fix_digits(), fix_text(), fix_token(), is_mixed(), leftovers(), _longest_cyr_run() (+11 more)

### Community 39 - "Community 39"
Cohesion: 0.20
Nodes (19): calc_price(), clean_text(), fix_name(), fix_vendor(), generate_category_xml(), get_category_map(), get_katran_feed(), is_in_stock() (+11 more)

### Community 40 - "Community 40"
Cohesion: 0.18
Nodes (8): _all_txt(), Issue, main(), Element, RozetkaXMLValidator, _txt(), write_json(), write_xlsx()

### Community 41 - "Community 41"
Cohesion: 0.16
Nodes (18): git_push(), main(), katran_github_sync.py ===================== Щогодинна синхронізація фіду…, Надсилає повідомлення адміну тільки при помилці., Робить git add + commit + push. Повертає True якщо успішно або немає змін., tg_error(), calc_price(), clean_text() (+10 more)

### Community 42 - "Community 42"
Cohesion: 0.14
Nodes (12): BaseHttpScraper, ensure_schema(), EpicentrPublicScraper, main(), BeautifulSoup, Шукає товари за запитом і повертає список карток. parse_cards=True — додатково…, Парсер публічних сторінок epicentrk.ua. Сайт: Nuxt.js SSR, без Cloudflare з…, Шукає товари на epicentrk.ua і повертає список URL з apteka.epicentrk.ua.… (+4 more)

### Community 43 - "Community 43"
Cohesion: 0.16
Nodes (19): decode_html_entities(), format_name(), main(), process(), Path, Видаляє offers чиї категорії містять будь-яке з ключових слів (без урахування…, Перекладає назви категорій за словником. Повертає кількість перекладених., Видаляє всі offer що не мають жодного тегу <picture>. Повертає кількість… (+11 more)

### Community 44 - "Community 44"
Cohesion: 0.15
Nodes (18): cancel_order(), change_status(), confirm_order(), get_new_orders(), get_order_details(), get_orders_by_status(), get_token(), is_already_processed() (+10 more)

### Community 45 - "Community 45"
Cohesion: 0.18
Nodes (17): message, outer_middleware, cmd_learn(), cmd_orders(), cmd_prices(), cmd_start(), cmd_status(), handle_text() (+9 more)

### Community 46 - "Community 46"
Cohesion: 0.20
Nodes (15): allowed(), _load(), _log(), main(), shared/utils/consent.py ======================== Запобіжник на дії, які власник…, Чи є чинний дозвіл. Невідома дія — не заблокована (не наша справа)., Зупиняє програму, якщо дозволу немає. Друкує, що саме зробила б., require() (+7 more)

### Community 47 - "Community 47"
Cohesion: 0.16
Nodes (18): brand_cyr(), build(), _echoes(), load(), main(), name_phrase(), natural(), Кириличне написання бренду або порожньо, якщо його не існує. (+10 more)

### Community 48 - "Community 48"
Cohesion: 0.18
Nodes (18): analyse(), cmd_report(), ensure_tables(), load_our_data(), main(), match_level(), model_tokens(), price_of() (+10 more)

### Community 49 - "Community 49"
Cohesion: 0.20
Nodes (18): analyse(), api(), char_titles(), dump_ours(), fetch(), load_gaps(), main(), norm() (+10 more)

### Community 50 - "Community 50"
Cohesion: 0.19
Nodes (18): bad(), build_report(), cases(), control_old_text(), head_version(), live_report(), load_watchdog(), main() (+10 more)

### Community 51 - "Community 51"
Cohesion: 0.20
Nodes (16): generate_and_save_skill(), get_agents_status(), get_system_snapshot(), listen_loop(), process_command(), Автоматично генерує новий скіл через LLM і зберігає в файл + Qdrant., route_task(), save_system_snapshot() (+8 more)

### Community 52 - "Community 52"
Cohesion: 0.24
Nodes (14): flat(), main(), flat(), main(), near_hit(), Значення поряд зі словом своєї характеристики — і як ціле слово. Без межі слова…, aroma_map(), flat() (+6 more)

### Community 53 - "Community 53"
Cohesion: 0.22
Nodes (13): Client, audit_product(), fetch_all_products(), main(), print_top(), Problem, ProductReport, prom_client() (+5 more)

### Community 54 - "Community 54"
Cohesion: 0.26
Nodes (14): clr(), confirm_row(), count_confirmed(), count_pending(), get_pending(), load_epicentr(), main(), normalize() (+6 more)

### Community 55 - "Community 55"
Cohesion: 0.22
Nodes (14): main(), Позитивний контроль: перевірка, яка нічого не ловить, дає нуль, не помиляючись.…, Артикул із назви геть — з тієї самої причини, що й BRAND_PARAMS. `build_name()`…, Бренд, дописаний `build_name()` у хвіст назви, — теж не привід. Той самий…, scan(), selftest(), _show(), strip_article() (+6 more)

### Community 56 - "Community 56"
Cohesion: 0.22
Nodes (15): apteka_cards_for_brand(), clean_brand(), extract_datalayer(), get_page(), is_match(), keyword_overlap(), main(), normalize() (+7 more)

### Community 57 - "Community 57"
Cohesion: 0.19
Nodes (14): audit_prices(), load_db_products(), load_feed(), agents/orders/price_audit.py ============================= Аудит цін: порівнює…, Завантажує всі товари з my_products. Повертає list of dicts., Порівнює поточні ціни з новими розрахованими. Returns: tuple: (all_results,…, Записує результати у CSV файл., Відправляє текстове повідомлення в Telegram. (+6 more)

### Community 58 - "Community 58"
Cohesion: 0.24
Nodes (14): build_stealth_context(), ensure_table(), get_total_pages(), human_delay(), human_scroll(), main(), _parse_api_goods(), parse_page() (+6 more)

### Community 59 - "Community 59"
Cohesion: 0.23
Nodes (14): _get(), get_brand_options_from_cache(), get_options(), init_db(), main(), print_report(), tools/epicentr_attrs_explorer.py ================================= Отримує всі…, Бренди вже кешовані в epicentr_brand_cache (54370 брендів). Якщо кеш порожній —… (+6 more)

### Community 60 - "Community 60"
Cohesion: 0.28
Nodes (14): accept_cookies(), brand_of(), classify(), code_matches(), description_of(), ensure_table(), grab(), main() (+6 more)

### Community 61 - "Community 61"
Cohesion: 0.23
Nodes (11): analyze_code(), handle_task(), listen_loop(), write_code(), get_redis(), ollama_generate(), Прямий виклик Ollama API, Відправити запит до Ollama через чергу. Викликається з агентів замість прямого… (+3 more)

### Community 62 - "Community 62"
Cohesion: 0.21
Nodes (13): calc_price(), fetch_carvol_live(), git_push(), git_reset_to_origin(), main(), agents/orders/carvol_epicentr_sync.py ======================================…, Готує ТІЛЬКИ свій XML до стану origin/main. Решту репозиторію не чіпає. Раніше…, Пушить оновлений XML в GitHub (без rebase — завжди поверх origin/main). (+5 more)

### Community 63 - "Community 63"
Cohesion: 0.22
Nodes (13): calc_price(), fetch_carvol_live(), _git(), git_push(), main(), rozetka_github_sync.py ====================== Оновлює ТІЛЬКИ ціни та наявність…, Читає XML, оновлює ТІЛЬКИ: - offer[@available] - <price> - <stock_quantity> Все…, Публікує прайс у GitHub. True означає, що вміст справді доїхав. Порядок кроків… (+5 more)

### Community 64 - "Community 64"
Cohesion: 0.16
Nodes (7): Клік з Self-Healing: якщо елемент не знайдено — шукаємо альтернативний селектор., Заповнення поля з Self-Healing., Аналізує DOM і намагається знайти новий селектор. Шукає по тексту, placeholder,…, Робить скріншот і зберігає в logs/screenshots/., Клікає на посилання і чекає на завантаження файлу., Відправляє Telegram повідомлення і файл скріншоту., Записує дію в browser_action_log.

### Community 65 - "Community 65"
Cohesion: 0.24
Nodes (13): cmd_clear(), cmd_list(), cmd_set(), commission_at(), ensure_table(), main(), Ставка, яку Rozetka утримає з цієї ціни продажу., Товари під фільтр. Порожній фільтр свідомо не дозволяємо. (+5 more)

### Community 66 - "Community 66"
Cohesion: 0.27
Nodes (12): do_login(), logged_in(), main(), open_browser(), Звичайний, НЕ постійний контекст. З persistent_context клік по «Вход /…, Ознака входу — зник напис «поиск доступен после регистрации»., search(), ensure() (+4 more)

### Community 67 - "Community 67"
Cohesion: 0.31
Nodes (10): check_result(), create_skill_from_failure(), handle_task(), listen_loop(), Автоматично створює новий skill коли агент провалив задачу, get_context_for_task(), save_memory(), search_memory() (+2 more)

### Community 68 - "Community 68"
Cohesion: 0.32
Nodes (10): analyze_with_llm(), calculate_dropship_margin(), get_products_stats(), get_usd_rate(), listen_loop(), run_margin_calc(), run_weekly_report(), weekly_report() (+2 more)

### Community 69 - "Community 69"
Cohesion: 0.23
Nodes (12): epicentr_price(), fetch_feed(), generate_update_xml(), git_push(), main(), feed_sync.py — Синхронізація цін і наявності для Єпіцентру…, Генерує XML для автооновлення Єпіцентру. Формат: тільки offer id + price +…, Розраховує ціну для Єпіцентру = наша ціна + CPA. (+4 more)

### Community 70 - "Community 70"
Cohesion: 0.19
Nodes (11): call_tool(), fmt(), list_tools(), prom_get(), prom_post(), call_tool, list_tools, shared/mcp_servers/prom_mcp.py ================================ MCP сервер для… (+3 more)

### Community 71 - "Community 71"
Cohesion: 0.23
Nodes (12): best_match(), fetch_epicentr_categories(), fetch_toptul_categories(), main(), normalize(), print_table(), tools/epicentr_category_mapper.py Fuzzy-match TOPTUL XML categories → Epicentr…, Lowercase + collapse whitespace. Works across Cyrillic dialects. (+4 more)

### Community 72 - "Community 72"
Cohesion: 0.27
Nodes (12): api_commands(), api_methods(), api_proxy(), api_save_log(), api_tokens(), get_db(), index(), init_db() (+4 more)

### Community 73 - "Community 73"
Cohesion: 0.24
Nodes (11): ensure_columns(), fetch_all_prom_products(), agents/orders/fetch_prom_categories.py =======================================…, Зберігає group і category в my_products. Оновлює тільки товари де є SKU.…, Показує скільки товарів матчиться з prom_cpa_rates через group_name. Допомагає…, Додає колонки prom_category_name і prom_group_id якщо не існують, Завантажує всі товари з Prom API з пагінацією. Повертає список з полями: id,…, run() (+3 more)

### Community 74 - "Community 74"
Cohesion: 0.23
Nodes (11): get_ttn_info(), match_order_by_np_data(), _normalize_phone(), _price_score(), Search rozetka_processed_orders with 3-level priority: 1. exact phone -> score…, Track a Nova Poshta waybill via TrackingDocument/getStatusDocuments. Returns:…, _similarity(), _fmt_source_info() (+3 more)

### Community 75 - "Community 75"
Cohesion: 0.24
Nodes (10): call_tool(), fmt(), get_rozetka_token(), list_tools(), call_tool, list_tools, shared/mcp_servers/rozetka_mcp.py =================================== MCP…, Отримує або оновлює Bearer токен Розетки (живе 24 години). (+2 more)

### Community 76 - "Community 76"
Cohesion: 0.29
Nodes (11): _bot(), check_xml(), _emoji_width(), is_valid_pic_url(), main(), print_report(), Друкує звіт і повертає True якщо файл готовий до імпорту., Повертає приблизну display-ширину рядка (emoji = 2 cols). (+3 more)

### Community 77 - "Community 77"
Cohesion: 0.27
Nodes (9): classify(), classify_product(), get_connection(), main(), Повертає {attr_code: (attr_name, valuecode, label_ua)} для всіх застосовних…, report(), Rule, run_classification() (+1 more)

### Community 78 - "Community 78"
Cohesion: 0.29
Nodes (11): cmd_diff(), cmd_freeze(), cmd_status(), cmd_unfreeze(), ensure_table(), main(), parse_feed(), Що змінилося б, якби картку не було заморожено. (+3 more)

### Community 79 - "Community 79"
Cohesion: 0.29
Nodes (11): cmd_report(), cmd_scan(), ensure_table(), fetch_one(), _hamming(), main(), Частка білого тла й розміри предмета в кадрі, у відсотках. Дає змогу відрізнити…, Типи кодів на зображенні та ознака QR. Дрібний QR на скані упаковки не… (+3 more)

### Community 80 - "Community 80"
Cohesion: 0.24
Nodes (11): check(), load_catalog(), main(), open_session(), items: [(sku, name, price_retail)] → результат звірки. Порушенням вважаємо лише…, Назва товару → слаг у тій самій транслітерації, що вживає Хорошоп., Сесія з пройденим челенджем. None, якщо сайт недоступний., слаг → URL для всіх карток сайту (одна сторінка sitemap). (+3 more)

### Community 81 - "Community 81"
Cohesion: 0.29
Nodes (11): call(), cmd_health(), cmd_sync(), cmd_test_write(), ensure_table(), _headers(), main(), Перевірка прав на запис БЕЗ фактичної зміни даних. Надсилаємо той самий… (+3 more)

### Community 82 - "Community 82"
Cohesion: 0.33
Nodes (10): db(), main(), cat_names(), feed_usage(), load_cache(), main(), Наші назви, яких Rozetka не знає, поруч із її ПОХОЖОЮ назвою. Це той самий…, назва характеристики -> (is_filter, unit) для категорії Rozetka (+2 more)

### Community 83 - "Community 83"
Cohesion: 0.27
Nodes (10): calc_sell_price(), cmd_apply(), cmd_generate(), fetch_feed(), load_xml_cat_map(), main(), agents/orders/rozetka_price_manager.py =======================================…, Gross-up: sell = ceil(rrc / (1 - rate) / 10) * 10. Tier-crossing: якщо… (+2 more)

### Community 84 - "Community 84"
Cohesion: 0.25
Nodes (10): _extract_recipient_block(), _extract_ttn(), match_order_by_ttn_data(), normalize_phone(), parse_ttn_pdf(), Search rozetka_processed_orders for orders matching parsed TTN data. Returns…, Normalize +380XXXXXXXXX or 380XXXXXXXXX to 0XXXXXXXXX., NP waybill: pdfplumber merges two columns left-to-right per line. Layout per… (+2 more)

### Community 85 - "Community 85"
Cohesion: 0.45
Nodes (9): button_handler(), get_system_status(), handle_text(), is_admin(), main(), main_keyboard(), start(), get_queue_length() (+1 more)

### Community 86 - "Community 86"
Cohesion: 0.29
Nodes (10): collage_panels(), has_person(), login(), main(), pose(), → ознаки зображення або None, якщо не вдалось прочитати. Перевірки взяті з…, Людина або частина тіла в кадрі. Це виявилось головною ознакою після ручного…, Скільки окремих панелей у кадрі. Колаж «товар + модель + схема» має суцільні… (+2 more)

### Community 87 - "Community 87"
Cohesion: 0.27
Nodes (10): analyse_name_order(), build_pattern(), collect_urls(), ensure_tables(), main(), Патерн категорії: що заповнено у більшості карток., Чи закінчується назва на Колір і Розмір, чи є артикул у дужках., Посилання на картки з видачі категорії — звичайним запитом. (+2 more)

### Community 88 - "Community 88"
Cohesion: 0.35
Nodes (10): accept_cookies(), brand_of(), classify(), grab(), main(), Значущі латинські токени назви (кирилиця відкидається)., → (match_type, missing_tokens), Бренд + перші латинські токени моделі. (+2 more)

### Community 89 - "Community 89"
Cohesion: 0.44
Nodes (8): analyze_with_llm(), get_google_trends(), get_related_queries(), listen_loop(), run_competitor_analysis(), run_trends_analysis(), save_report(), update_agent_status()

### Community 90 - "Community 90"
Cohesion: 0.29
Nodes (9): calc_price(), fetch_carvol_live(), generate_feed(), main(), rozetka_feed_sync_v2.py ======================= Генерує XML для Розетки: 1.…, Генерує XML на основі шаблону carvol_rozetka.xml але з живими цінами і…, Розраховує ціну для Розетки з урахуванням CPA тиру., Завантажує живий фід Carvol і повертає: {article: {price, qty, available}} (+1 more)

### Community 91 - "Community 91"
Cohesion: 0.47
Nodes (9): build_stealth_context(), handle_task(), human_delay(), human_scroll(), listen_loop(), parse_prom(), parse_rozetka(), prom_api_get_products() (+1 more)

### Community 92 - "Community 92"
Cohesion: 0.31
Nodes (9): ensure_tables(), _is_all_caps(), load_expected(), load_rrc(), main(), Бал 0-100 і перелік того, чого бракує., Те саме визначення, що у валідаторі Prom — інакше бали розійдуться., portal_category_id → множина портальних характеристик категорії. Знаменник для… (+1 more)

### Community 93 - "Community 93"
Cohesion: 0.36
Nodes (8): api(), get_owox_id(), load_current_prices(), main(), agents/orders/rozetka_price_corrector.py…, Знаходить owox_id товару за артикулом., Читає поточні ціни з Rozetka XML {article: price}., update_price()

### Community 94 - "Community 94"
Cohesion: 0.33
Nodes (8): build_prompt(), classify(), classify_batch(), find_candidates(), AI Класифікатор категорій товарів для Єпіцентру і Розетки v3: qwen2.5:7b +…, Пошук категорій в БД. Точний збіг на початку → починається з → містить., Пошук кандидатів — 4 стратегії по черзі., search_db()

### Community 95 - "Community 95"
Cohesion: 0.28
Nodes (8): analyze_and_update(), calculate_our_price(), get_competitor_prices(), get_cpa_rate(), Отримує ціни конкурентів з Prom для артикулу, Аналізує ціни і оновлює БД, Повертає CPA ставку для категорії з БД, Розраховує нашу ціну з урахуванням реального CPA

### Community 96 - "Community 96"
Cohesion: 0.31
Nodes (7): call_tool(), dt_fix(), get_db(), get_redis(), list_tools(), call_tool, list_tools

### Community 97 - "Community 97"
Cohesion: 0.31
Nodes (8): get_prom_categories(), Prom.ua Feed Validator Перевіряє файл товарів на відповідність вимогам Prom.ua, Головна функція валідації файлу., Завантажити всі category_id з БД., Валідує один рядок товару. Повертає список помилок., save_to_db(), validate_file(), validate_product()

### Community 98 - "Community 98"
Cohesion: 0.42
Nodes (8): classify(), detect_article_col(), detect_brand_col(), main(), Повертає назву колонки-кандидата для артикула., read_xlsx(), save_xlsx(), top_brands()

### Community 99 - "Community 99"
Cohesion: 0.33
Nodes (8): ensure_columns(), main(), _num(), parse(), _range(), Стара і нова редакції живуть поруч — файл містить обидві., «1400-3999» → (1400, 3999); «-» або порожньо → None (базова ставка)., → {cat_id: {'name', 'old': [(lo,hi,rate)], 'new': [...]}}

### Community 100 - "Community 100"
Cohesion: 0.43
Nodes (6): analyze_performance(), collect_system_metrics(), detect_anomalies(), listen_loop(), run_efficiency_check(), pop_task()

### Community 101 - "Community 101"
Cohesion: 0.32
Nodes (7): generate_by_category(), generate_xml(), load_feed_data(), agents/orders/epicentr_xml_generator.py…, Генерує XML файл для імпорту в Єпіцентр. Args: output_path: шлях для збереження…, Генерує окремий XML файл для кожної категорії. Зручно для покрокового…, Завантажує фід TOPTUL для отримання фото і описів.

### Community 102 - "Community 102"
Cohesion: 0.25
Nodes (6): call_tool(), list_tools(), call_tool, list_tools, shared/mcp_servers/browser_mcp.py ==================================== MCP…, Роутить виклики до відповідних Playwright агентів. Агенти запускаються в…

### Community 103 - "Community 103"
Cohesion: 0.32
Nodes (7): get_model(), tg_dispatcher/ai_brain/voice_handler.py…, Завантажує модель один раз при старті., Синхронна транскрибація (запускається в окремому потоці)., Асинхронна обгортка — запускає STT в окремому потоці щоб не блокувати Telegram…, transcribe_audio_async(), _transcribe_sync()

### Community 104 - "Community 104"
Cohesion: 0.50
Nodes (7): api_chat(), api_generate(), api_start(), build_context_message(), call_ai(), index(), route

### Community 105 - "Community 105"
Cohesion: 0.43
Nodes (7): boost(), brand_country(), extract_qty(), extract_volume(), first_match(), main(), Характеристики, яких ще немає у товару.

### Community 106 - "Community 106"
Cohesion: 0.25
Nodes (8): apply_aliases(), fit_params(), _match_value(), Голе число — у формах, які знає довідник Rozetka. Постачальник зберігає обʼєм…, Підібрати значення зі списку довідника. Постачальник часто дає складені…, Привести назви постачальника до довідника цієї категорії., Лишити тільки те, що Rozetka справді покаже. Суворість тут асиметрична, і це не…, _unit_candidates()

### Community 107 - "Community 107"
Cohesion: 0.43
Nodes (7): canon(), convert(), from_name(), main(), Доказ із назви товару: «діаметр 3,5 см» → 35 мм., → (значення в канонічній одиниці, чим доведено) або (None, причина).…, unit_in_field()

### Community 108 - "Community 108"
Cohesion: 0.52
Nodes (6): ensure_collections(), index_skills(), listen(), process_embed_request(), process_search_request(), Embedding Service — запускається на НОУТБУЦІ. Слухає Redis чергу…

### Community 109 - "Community 109"
Cohesion: 0.29
Nodes (5): call_tool(), list_tools(), call_tool, list_tools, File System MCP сервер — дає агентам доступ до документації Аналог ідеї з PDF:…

### Community 110 - "Community 110"
Cohesion: 0.29
Nodes (7): build_name(), _model_from(), Модель — латинська частина назви без бренду, розміру й кольору., Тип · Виробник · Модель · Розмір · Колір · (Артикул), без ком., Короткий опис із назви та вже підтверджених характеристик., size_label(), synth_description()

### Community 111 - "Community 111"
Cohesion: 0.48
Nodes (6): collect(), compare(), ensure(), main(), Наш контент проти конкурентів на тих самих артикулах., shop_of()

### Community 112 - "Community 112"
Cohesion: 0.48
Nodes (6): brandy(), ensure(), harvest(), main(), pure(), Фраза справді тією мовою, за яку її видають.

### Community 113 - "Community 113"
Cohesion: 0.43
Nodes (6): ensure(), main(), one_query(), Беремо картки з фіду: артикул, назва, широка фраза з keywords., Свіжий браузер на запит; повертає (переглянуто карток, позиція, стор.). Читаємо…, sample()

### Community 114 - "Community 114"
Cohesion: 0.47
Nodes (5): check_name_unique(), fix_pic_url(), parse_and_import(), Виправляє URL фото з Prom CDN на прямий, Робить назву унікальною якщо є дублі

### Community 115 - "Community 115"
Cohesion: 0.53
Nodes (5): fetch_all_products(), get_our_skus(), import_to_db(), main(), Отримуємо SKU які є в нашій БД

### Community 116 - "Community 116"
Cohesion: 0.33
Nodes (3): Перехід на URL з очікуванням завантаження., Випадкова затримка для анти-бот поведінки., Скрол вниз для нескінченного скролу.

### Community 117 - "Community 117"
Cohesion: 0.33
Nodes (5): get_model(), list_models(), shared/utils/model_selector.py ================================ Вибір моделі…, Повертає назву моделі для задачі. Використання: from…, Виводить всі налаштовані моделі.

### Community 118 - "Community 118"
Cohesion: 0.53
Nodes (5): clean_url(), extract(), main(), tools/epicentr_support_crawl.py ================================ Зберігає…, slug()

### Community 119 - "Community 119"
Cohesion: 0.53
Nodes (5): ensure(), main(), norm(), num(), Назви атрибутів Prom плутають апострофи: «Об`єм» у Лубрикантах записаний…

### Community 120 - "Community 120"
Cohesion: 0.60
Nodes (5): cmd_report(), ensure_table(), fetch(), main(), parse()

### Community 122 - "Community 122"
Cohesion: 0.50
Nodes (4): extract_params_from_name(), process_without_params(), Витягує параметри з назви товару, Обробляє товари без параметрів

### Community 124 - "Community 124"
Cohesion: 0.80
Nodes (4): login(), main(), options(), ua()

### Community 125 - "Community 125"
Cohesion: 0.60
Nodes (4): login(), main(), tools/epicentr_enrich_audit.py =============================== Для кожної…, ua()

### Community 126 - "Community 126"
Cohesion: 0.70
Nodes (4): check(), main(), [(правило, пояснення)] — усе, що виглядає суперечливо., txt()

### Community 127 - "Community 127"
Cohesion: 0.60
Nodes (4): login(), main(), tools/epicentr_products_dump.py ================================ Вивантажує всі…, title()

### Community 128 - "Community 128"
Cohesion: 0.50
Nodes (3): load_dicts(), main(), {cat: {paramcode: [valuecode, …]}} з локального кешу опцій. Форма атрибутів…

### Community 129 - "Community 129"
Cohesion: 0.60
Nodes (4): ensure_columns(), main(), parse(), Розширюємо наявну таблицю, не ламаючи Toptul-рядки.

### Community 130 - "Community 130"
Cohesion: 0.50
Nodes (4): find_category(), get_all_categories(), Category Mapper — знаходить відповідну категорію Prom по назві, Знаходить найближчі категорії по назві.

### Community 131 - "Community 131"
Cohesion: 0.60
Nodes (4): harvest(), main(), ngrams(), Частотні n-грами з назв товарів у видачі Prom за запитом.

### Community 132 - "Community 132"
Cohesion: 0.60
Nodes (4): ensure_table(), from_report(), main(), Витягти назви виробників зі звіту імпорту (xlsx або csv).

### Community 133 - "Community 133"
Cohesion: 0.60
Nodes (4): crawl(), main(), parse_links(), (section_id, назва, кількість) з фільтра поточної сторінки.

### Community 134 - "Community 134"
Cohesion: 0.83
Nodes (3): fetch_specs(), get_product_to_process(), start()

### Community 135 - "Community 135"
Cohesion: 0.83
Nodes (3): ask_ollama(), fetch_precise_data(), process()

### Community 136 - "Community 136"
Cohesion: 0.83
Nodes (3): login(), main(), ua()

### Community 137 - "Community 137"
Cohesion: 0.67
Nodes (3): main(), tools/epicentr_required_audit.py ================================= Звіряє фід…, title()

### Community 138 - "Community 138"
Cohesion: 0.83
Nodes (3): cmd_list(), ensure(), main()

### Community 139 - "Community 139"
Cohesion: 0.50
Nodes (4): load_easytoys(), _nl(), Нідерландське значення (можливо складене) → українське., sku → {характеристика: українське значення} з точних збігів EasyToys.

### Community 140 - "Community 140"
Cohesion: 0.83
Nodes (3): load_prices(), main(), validate()

### Community 141 - "Community 141"
Cohesion: 0.83
Nodes (3): ensure_table(), main(), parse()

### Community 142 - "Community 142"
Cohesion: 0.83
Nodes (3): collisions(), main(), shorten_head()

### Community 143 - "Community 143"
Cohesion: 0.67
Nodes (3): build(), main(), {rz_id: {назва: {paramid, unit, values: {value_name: value_id}}}}

### Community 153 - "Community 153"
Cohesion: 0.67
Nodes (3): _first_match(), params_from_name(), Характеристики з назви; для окремих — ще й з опису. Опис читається лише для…

## Knowledge Gaps
- **20 isolated node(s):** `C`, `Feature`, `containerVariants`, `cardVariants`, `NAV_LINKS` (+15 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 800 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **28 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `get_connection()` connect `Community 6` to `Community 0`, `Community 1`, `Community 2`, `Community 4`, `Community 7`, `Community 8`, `Community 9`, `Community 10`, `Community 11`, `Community 12`, `Community 13`, `Community 15`, `Community 18`, `Community 19`, `Community 20`, `Community 21`, `Community 23`, `Community 24`, `Community 26`, `Community 27`, `Community 29`, `Community 30`, `Community 31`, `Community 32`, `Community 33`, `Community 34`, `Community 35`, `Community 36`, `Community 37`, `Community 38`, `Community 39`, `Community 41`, `Community 42`, `Community 44`, `Community 45`, `Community 48`, `Community 51`, `Community 52`, `Community 54`, `Community 55`, `Community 56`, `Community 57`, `Community 58`, `Community 61`, `Community 64`, `Community 65`, `Community 66`, `Community 68`, `Community 69`, `Community 71`, `Community 73`, `Community 74`, `Community 78`, `Community 79`, `Community 80`, `Community 81`, `Community 82`, `Community 84`, `Community 85`, `Community 87`, `Community 89`, `Community 90`, `Community 91`, `Community 92`, `Community 94`, `Community 95`, `Community 97`, `Community 99`, `Community 100`, `Community 101`, `Community 105`, `Community 111`, `Community 112`, `Community 113`, `Community 114`, `Community 115`, `Community 119`, `Community 120`, `Community 122`, `Community 123`, `Community 129`, `Community 130`, `Community 132`, `Community 138`, `Community 141`, `Community 176`?**
  _High betweenness centrality (0.402) - this node is a cross-community bridge._
- **Why does `check_offer()` connect `Community 32` to `Community 12`, `Community 5`?**
  _High betweenness centrality (0.028) - this node is a cross-community bridge._
- **Why does `main()` connect `Community 32` to `Community 6`, `Community 7`?**
  _High betweenness centrality (0.018) - this node is a cross-community bridge._
- **What connects `C`, `Feature`, `containerVariants` to the rest of the system?**
  _20 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Community 0` be split into smaller, more focused modules?**
  _Cohesion score 0.05311676909569798 - nodes in this community are weakly interconnected._
- **Should `Community 1` be split into smaller, more focused modules?**
  _Cohesion score 0.053763440860215055 - nodes in this community are weakly interconnected._
- **Should `Community 2` be split into smaller, more focused modules?**
  _Cohesion score 0.05136612021857923 - nodes in this community are weakly interconnected._