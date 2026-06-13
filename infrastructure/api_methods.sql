-- ============================================================
-- База знань API методів всіх маркетплейсів та служб доставки
-- Таблиця: marketplace_api_methods
-- Оновлено: 2026-06-13
-- ============================================================

CREATE TABLE IF NOT EXISTS marketplace_api_methods (
    id SERIAL PRIMARY KEY,
    marketplace VARCHAR(20) NOT NULL,       -- prom / rozetka / epicentr / nova_poshta
    domain VARCHAR(30) NOT NULL,            -- orders / products / delivery / pim / auth / analytics
    method_name VARCHAR(100) NOT NULL,
    http_method VARCHAR(10),
    endpoint TEXT,
    description_ua TEXT,
    input_params JSONB,
    output_example JSONB,
    is_implemented BOOLEAN DEFAULT false,
    mcp_tool_name VARCHAR(100),
    priority INTEGER DEFAULT 5,             -- 1=критично, 5=звичайне, 10=низький пріоритет
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_api_marketplace ON marketplace_api_methods(marketplace);
CREATE INDEX IF NOT EXISTS idx_api_domain      ON marketplace_api_methods(domain);
CREATE INDEX IF NOT EXISTS idx_api_implemented ON marketplace_api_methods(is_implemented);

-- ============================================================
-- PROM.UA — https://my.prom.ua/api/v1
-- Base URL: https://my.prom.ua/api/v1
-- Auth: Bearer PROM_API_TOKEN
-- ============================================================

INSERT INTO marketplace_api_methods
    (marketplace, domain, method_name, http_method, endpoint, description_ua, input_params, output_example, is_implemented, mcp_tool_name, priority, notes)
VALUES

-- PROM: ЗАМОВЛЕННЯ
('prom', 'orders', 'get_orders_list', 'GET', '/api/v1/orders/list',
 'Список замовлень з фільтрацією по статусу та даті',
 '{"status": "pending|paid|accepted|delivered|cancelled|declined", "limit": 20, "date_from": "ISO date"}',
 '{"orders": [{"id": 123, "status": "pending", "price": "1500.00", "client_first_name": "Іван", "phone": "380671234567", "products": []}]}',
 true, 'prom_get_orders', 1, 'Статуси: pending=нові, accepted=прийняті, delivered=доставлені, cancelled/declined=скасовані'),

('prom', 'orders', 'get_order_detail', 'GET', '/api/v1/orders/{order_id}',
 'Деталі конкретного замовлення',
 '{"order_id": 123}',
 '{"order": {"id": 123, "status": "accepted", "price": "1500.00", "products": [], "delivery_address": {}}}',
 true, 'prom_get_order', 1, NULL),

('prom', 'orders', 'set_order_status', 'POST', '/api/v1/orders/set_status',
 'Змінити статус замовлень (масово)',
 '{"ids": [123, 456], "status": "accepted|delivered|cancelled|declined", "cancellation_reason": "optional"}',
 '{"processed_ids": [123, 456]}',
 true, 'prom_set_order_status', 1, 'Можна змінювати кілька замовлень одразу'),

('prom', 'orders', 'save_declaration_id', 'POST', '/api/v1/delivery/save_declaration_id',
 'Зберегти ТТН Нової Пошти до замовлення',
 '{"order_id": 123, "declaration_id": "20451450921650", "delivery_type": "nova_poshta"}',
 '{"status": "ok"}',
 true, 'prom_save_ttn', 1, 'Після збереження покупець отримує сповіщення з трекінгом'),

-- PROM: ТОВАРИ
('prom', 'products', 'get_products_list', 'GET', '/api/v1/products/list',
 'Список товарів магазину з пагінацією',
 '{"limit": 100, "last_id": 0, "sku": "optional"}',
 '{"products": [{"id": 1, "sku": "ABC-001", "name": "Ключ", "price": 150, "presence": "available"}]}',
 true, 'prom_get_products', 2, NULL),

('prom', 'products', 'get_product_detail', 'GET', '/api/v1/products/{product_id}',
 'Деталі конкретного товару',
 '{"product_id": 1}',
 '{"product": {"id": 1, "name": "Ключ", "price": 150, "description": "..."}}',
 false, NULL, 5, NULL),

('prom', 'products', 'edit_products', 'POST', '/api/v1/products/edit',
 'Масове оновлення цін та наявності товарів (до 100 за раз)',
 '[{"id": 1, "price": 155}, {"id": 2, "presence": "not_available"}]',
 '{"processed_ids": [1, 2]}',
 true, 'prom_update_prices / prom_update_presence', 1, 'Один ендпоінт для цін і наявності'),

('prom', 'products', 'import_products', 'POST', '/api/v1/products/import',
 'Імпорт товарів з XLS/CSV файлу',
 '{"import_type": "prices", "url": "https://..."}',
 '{"status": "accepted", "import_id": 1}',
 false, NULL, 7, NULL),

('prom', 'products', 'get_product_groups', 'GET', '/api/v1/groups/list',
 'Список груп товарів (категорій магазину)',
 '{"limit": 100}',
 '{"groups": [{"id": 1, "name": "Ключі"}]}',
 false, NULL, 7, NULL),

-- PROM: ПОВІДОМЛЕННЯ
('prom', 'messages', 'get_messages_list', 'GET', '/api/v1/messages/list',
 'Список повідомлень від покупців',
 '{"limit": 20}',
 '{"messages": [{"thread_id": 1, "text": "Привіт", "is_read": false}]}',
 true, 'prom_get_messages', 3, NULL),

('prom', 'messages', 'reply_message', 'POST', '/api/v1/messages/reply',
 'Відповісти покупцю в гілці повідомлень',
 '{"thread_id": 1, "text": "Доброго дня!"}',
 '{"status": "ok"}',
 true, 'prom_reply_message', 3, NULL),

-- PROM: АНАЛІТИКА
('prom', 'analytics', 'get_shop_stats', 'GET', '/api/v1/orders/list',
 'Статистика магазину (агрегація з orders/list)',
 '{"limit": 100}',
 '{"total_orders": 50, "total_revenue": 75000, "today_orders": 3}',
 true, 'prom_get_shop_stats', 4, 'Реалізовано через агрегацію orders/list, нативного stats ендпоінту немає'),

-- PROM: ВІДГУКИ
('prom', 'reviews', 'get_reviews', 'GET', '/api/v1/reviews/list',
 'Список відгуків покупців',
 '{"limit": 20, "status": "pending|published"}',
 '{"reviews": [{"id": 1, "text": "...", "rating": 5}]}',
 false, NULL, 6, NULL),

('prom', 'reviews', 'reply_review', 'POST', '/api/v1/reviews/reply',
 'Відповісти на відгук покупця',
 '{"review_id": 1, "text": "Дякуємо!"}',
 '{"status": "ok"}',
 false, NULL, 6, NULL),

-- PROM: ФІДИ
('prom', 'feeds', 'get_feeds', 'GET', '/api/v1/company/get_last_import_file',
 'Статус останнього імпорту фіду',
 '{}',
 '{"status": "ok", "last_updated": "2026-06-13T10:00:00"}',
 false, NULL, 5, NULL),

-- ============================================================
-- ROZETKA — https://api-seller.rozetka.com.ua
-- Auth: Bearer ROZETKA_API_TOKEN (статичний gapi_... або через POST /sites)
-- ВАЖЛИВО: SSL verify=False (старий сервер Celeron)
-- ВАЖЛИВО: api-seller з ДЕФІСОМ (api.seller без дефісу → 404)
-- ============================================================

-- ROZETKA: АВТОРИЗАЦІЯ
('rozetka', 'auth', 'get_token', 'POST', '/sites',
 'Отримати Bearer токен авторизації (живе 24 години)',
 '{"username": "login", "password": "pass"}',
 '{"content": {"access_token": "Bearer ....", "expired_in": 86400}}',
 true, NULL, 1, 'Кешується 23 год. Статичний gapi_... токен теж підтримується'),

('rozetka', 'auth', 'get_shop_info', 'GET', '/sites/current',
 'Інформація про поточний магазин',
 '{}',
 '{"content": {"name": "Моя крамниця", "status": "active"}}',
 true, 'rozetka_get_shop_info', 4, NULL),

-- ROZETKA: ЗАМОВЛЕННЯ
('rozetka', 'orders', 'get_new_orders', 'GET', '/orders/search',
 'Нові замовлення (types=4)',
 '{"types": 4}',
 '{"content": {"orders": []}}',
 true, 'rozetka_get_orders', 1, 'types=4 — саме нові замовлення'),

('rozetka', 'orders', 'get_orders_by_status', 'GET', '/orders/search',
 'Замовлення за статусом',
 '{"status": 2, "page": 1, "per_page": 20}',
 '{"content": {"orders": []}}',
 true, 'rozetka_get_orders', 1, 'Статуси: 2=підтверджено, 3=відправлено, 6=скасовано, 61=ТТН додано'),

('rozetka', 'orders', 'get_order_detail', 'GET', '/orders/{id}',
 'Деталі замовлення. expand=status_available — доступні статуси',
 '{"order_id": 12345, "expand": "status_available"}',
 '{"content": {"id": 12345, "status": 2, "ttn": "", "items": []}}',
 true, 'rozetka_get_order', 1, 'Використовується для верифікації ТТН після set_ttn'),

('rozetka', 'orders', 'confirm_order', 'PATCH', '/orders/{id}',
 'Підтвердити замовлення (status=2)',
 '{"status": 2}',
 '{"content": {"status": 2}}',
 true, NULL, 1, 'Реалізовано в rozetka_order_agent.py::change_status'),

('rozetka', 'orders', 'ship_order', 'PATCH', '/orders/{id}',
 'Передати в доставку (status=3)',
 '{"status": 3}',
 '{"content": {"status": 3}}',
 true, NULL, 1, NULL),

('rozetka', 'orders', 'cancel_order', 'PATCH', '/orders/{id}',
 'Скасувати замовлення (status=6)',
 '{"status": 6}',
 '{"content": {"status": 6}}',
 true, NULL, 2, NULL),

('rozetka', 'orders', 'add_ttn_primary', 'POST', '/orders/add-ttn',
 'Додати ТТН до замовлення (основний метод)',
 '{"order_id": 12345, "ttn": "20451450921650", "delivery_service_id": 1}',
 '{"content": {"status": 61}}',
 true, NULL, 1, 'Після успіху статус стає 61 автоматично. delivery_service_id=1 — Нова Пошта'),

('rozetka', 'orders', 'add_ttn_fallback', 'PATCH', '/orders/{id}',
 'Встановити ТТН fallback через PATCH (якщо add-ttn не спрацював)',
 '{"ttn": "20451450921650"}',
 '{"content": {"ttn": "20451450921650"}}',
 true, NULL, 1, 'Fallback якщо POST /orders/add-ttn повертає помилку'),

-- ROZETKA: ТОВАРИ
('rozetka', 'products', 'search_items', 'GET', '/items/search',
 'Пошук товару за артикулом (отримати owox_id)',
 '{"article": "GCAD1212", "page": 1}',
 '{"content": {"items": [{"id": 999888, "article": "GCAD1212", "status": 3}]}}',
 false, NULL, 3, 'owox_id потрібен для update-price-stock'),

('rozetka', 'products', 'get_item_detail', 'GET', '/items/{id}',
 'Деталі товару з moderation_status',
 '{"item_id": 999888}',
 '{"content": {"id": 999888, "moderation_status": 3, "price": 1500}}',
 false, NULL, 4, 'moderation_status: 0=новий, 1=очікує, 2=на модерації, 3=схвалено, 4=відхилено, 5=архів'),

('rozetka', 'products', 'update_price_stock', 'PUT', '/items/update-price-stock/{id}',
 'Оновлення ціни/наявності в реальному часі (до 800мс)',
 '{"stock_quantity": 15, "price": 1500}',
 '{"content": {"status": "ok"}}',
 false, NULL, 2, 'ВАЖЛИВО: тільки 1 товар на запит, batch НЕ підтримується'),

('rozetka', 'products', 'get_items_counts', 'GET', '/items/counts',
 'Лічильники товарів (всього, на модерації тощо)',
 '{}',
 '{"content": {"total": 1250, "moderation": 3, "active": 1200}}',
 false, NULL, 5, NULL),

('rozetka', 'products', 'get_moderation_statuses', 'GET', '/items/statuses-moderation',
 'Список статусів модерації',
 '{}',
 '{"content": [{"id": 3, "name": "Схвалено"}]}',
 false, NULL, 8, NULL),

('rozetka', 'products', 'export_items_create', 'GET', '/items/create-export-file',
 'Ініціювати експорт товарів в XLS',
 '{"marketId": 1}',
 '{"content": {"status": "ok"}}',
 false, NULL, 7, NULL),

('rozetka', 'products', 'export_items_download', 'GET', '/items/download-export-file',
 'Завантажити XLS файл з товарами',
 '{"marketId": 1}',
 NULL,
 false, NULL, 7, NULL),

-- ROZETKA: XML ФІД
('rozetka', 'feeds', 'get_xml_status', 'GET', '/prices',
 'Статус XML прайсу: остання синхронізація, кількість товарів, помилки',
 '{}',
 '{"content": [{"url": "https://...", "last_sync": "2026-06-13T10:00:00", "items_count": 1250}]}',
 true, 'rozetka_get_xml_status', 2, NULL),

('rozetka', 'feeds', 'create_price_update', 'POST', '/item-price-updates/create',
 'Ініціювати завантаження XML фіду (асинхронно)',
 '{"url": "https://raw.githubusercontent.com/..."}',
 '{"content": {"status": "accepted"}}',
 false, NULL, 3, 'Система сама зчитує файл за посиланням'),

('rozetka', 'feeds', 'get_price_updates_status', 'GET', '/item-price-updates/search',
 'Статус завантаження фіду',
 '{}',
 '{"content": [{"id": 1, "status": "done", "errors": []}]}',
 false, NULL, 3, NULL),

('rozetka', 'feeds', 'validate_xml', 'POST', 'https://seller.rozetka.com.ua/gomer/pricevalidate/check/index',
 'Валідація XML перед завантаженням',
 '{"url": "https://raw.githubusercontent.com/..."}',
 NULL,
 true, 'rozetka_validate_xml', 2, 'Окремий домен, не seller API'),

-- ROZETKA: КАТЕГОРІЇ
('rozetka', 'categories', 'search_categories', 'GET', 'https://api.seller.rozetka.com.ua/market-categories/search',
 'Пошук категорій для маппінгу',
 '{"parent_id": 0, "page": 1}',
 '{"marketCategorys": [{"id": 80011, "name": "Телевізори", "parent_id": 0}]}',
 false, NULL, 4, 'УВАГА: тут api.seller БЕЗ дефісу (legacy endpoint)'),

('rozetka', 'categories', 'get_category_options', 'GET', 'https://api.seller.rozetka.com.ua/market-categories/category-options',
 'Характеристики (параметри) категорії',
 '{"category_id": 80011}',
 '{"content": [{"name": "Роздільна здатність", "type": "select", "values": []}]}',
 false, NULL, 4, NULL),

('rozetka', 'categories', 'bind_categories', 'POST', '/price-markets/create-bindings-categories',
 'Маппінг категорій фіду на категорії Розетки',
 '{"bindings": [{"feed_category": "...", "market_category_id": 80011}]}',
 '{"content": {"status": "ok"}}',
 false, NULL, 6, NULL),

-- ============================================================
-- ЄПІЦЕНТР OMS — https://api.epicentrm.com.ua
-- Auth: Bearer EPICENTR_TOKEN
-- Версії: v1, v2, v3, v5 (різні для різних ендпоінтів!)
-- ============================================================

-- ЄПІЦЕНТР: ЗАМОВЛЕННЯ OMS
('epicentr', 'orders', 'get_orders_list', 'GET', '/v3/oms/orders',
 'Список замовлень з фільтрацією',
 '{"limit": 100, "statusCode": "new|confirmed_by_merchant|confirmed|sent|delivered|completed|canceled_by_merchant", "dateFrom": "2026-05-01T00:00:00", "dateTo": "2026-06-01T00:00:00"}',
 '{"items": [{"id": "uuid", "externalId": 12345, "statusCode": "new", "totalPrice": 1500}]}',
 true, 'search_orders', 1, 'Статуси: new→confirmed_by_merchant→confirmed→sent→delivered→completed'),

('epicentr', 'orders', 'get_orders_total', 'GET', '/v3/oms/orders/total',
 'Загальна кількість замовлень (для пагінації)',
 '{"statusCode": "new"}',
 '{"total": 42}',
 true, 'search_orders', 3, 'Викликається паралельно з get_orders_list'),

('epicentr', 'orders', 'get_order_detail', 'GET', '/v5/oms/orders/{order_id}',
 'Повні деталі замовлення: клієнт, доставка, товари, ТТН',
 '{"order_id": "uuid-...-..."}',
 '{"id": "uuid", "statusCode": "confirmed", "client": {}, "delivery": {"ttn": ""}, "items": []}',
 true, 'get_order', 1, 'v5! Не v2 або v3. Повертає всю інформацію включно з delivery.ttn'),

('epicentr', 'orders', 'get_allowed_statuses', 'GET', '/v2/oms/orders/{order_id}/allowed-statuses',
 'Дозволені наступні статуси для замовлення',
 '{"order_id": "uuid"}',
 '{"items": [{"code": "confirmed_by_merchant", "title": "Підтверджено продавцем"}]}',
 true, 'update_order_status', 2, 'Перевіряємо перед зміною статусу щоб уникнути помилки'),

('epicentr', 'orders', 'change_order_status', 'POST', '/v2/oms/orders/{order_id}/change-status/to/{status}',
 'Змінити статус замовлення',
 '{"order_id": "uuid", "status": "confirmed_by_merchant", "comment": "optional", "reason_code": "for_cancel"}',
 '{"success": true}',
 true, 'update_order_status', 1, 'ЗАБОРОНЕНО пропускати статуси! Послідовність: new→confirmed_by_merchant→confirmed→sent'),

('epicentr', 'orders', 'add_ttn_primary', 'POST', '/v3/oms/orders/{order_id}/shipping/{provider}',
 'Додати ТТН до замовлення (основний метод)',
 '{"order_id": "uuid", "provider": "nova_poshta", "number": "20451450921650"}',
 '{"success": true}',
 true, 'add_order_ttn', 1, 'Після успіху автоматично змінюємо статус на sent'),

('epicentr', 'orders', 'add_ttn_fallback', 'PATCH', '/v1/oms/orders/{order_id}/shipment-number',
 'Встановити ТТН fallback (якщо v3 не спрацював)',
 '{"provider": "nova_poshta", "number": "20451450921650"}',
 '{"success": true}',
 true, 'add_order_ttn', 1, 'Fallback якщо основний endpoint повертає помилку'),

('epicentr', 'orders', 'update_client_data', 'POST', '/v3/oms/orders/{order_id}/client-data',
 'Оновити дані клієнта (ПІБ, телефон, email)',
 '{"firstName": "Іван", "lastName": "Петренко", "phone": "380671234567", "email": "test@test.ua"}',
 '{"success": true}',
 true, 'update_order_client', 3, NULL),

('epicentr', 'orders', 'update_delivery_data', 'POST', '/v3/oms/orders/{order_id}/delivery-data/{provider}',
 'Оновити адресу доставки',
 '{"settlementId": "uuid-city", "officeId": "uuid-office", "address": "вул. Шевченка 1"}',
 '{"success": true}',
 true, 'update_order_delivery', 3, NULL),

('epicentr', 'orders', 'add_comment', 'POST', '/v2/oms/orders/{order_id}/comments',
 'Додати коментар до замовлення',
 '{"text": "Покупець просить зателефонувати перед доставкою"}',
 '{"id": "comment-uuid"}',
 true, 'add_order_comment', 4, NULL),

('epicentr', 'orders', 'get_cancel_reasons', 'GET', '/v2/oms/order-cancel-reasons/customer',
 'Список причин скасування замовлення',
 '{}',
 '{"items": [{"code": "out_of_stock", "title": "Немає в наявності"}]}',
 true, 'get_cancel_reasons', 5, NULL),

-- ЄПІЦЕНТР: ДОСТАВКА
('epicentr', 'delivery', 'find_settlements', 'GET', '/v3/deliveries/providers/{provider}/participants/{participant}/settlements',
 'Знайти місто/населений пункт для служби доставки',
 '{"provider": "nova_poshta", "participant": "np", "search": "Рівне", "limit": 5}',
 '{"items": [{"id": "uuid", "title": "Рівне"}]}',
 true, 'find_delivery_office', 3, 'participant: np=НП, up=УкрПошта, meest=Meest'),

('epicentr', 'delivery', 'find_offices', 'GET', '/v3/deliveries/providers/{provider}/participants/{participant}/settlements/{settlement_id}/offices',
 'Знайти відділення в місті',
 '{"limit": 20}',
 '{"items": [{"id": "uuid", "number": 1, "address": "вул. Київська 1"}]}',
 true, 'find_delivery_office', 3, NULL),

('epicentr', 'delivery', 'get_invoice_info', 'GET', '/v3/deliveries/{provider}/companies/{company_id}/invoice/{invoice_number}',
 'Інформація по накладній (ТТН)',
 '{"provider": "nova_poshta", "company_id": "uuid", "invoice_number": "20451450921650"}',
 '{"status": "Доставлено", "recipient": {}}',
 true, 'get_delivery_invoice', 4, NULL),

-- ЄПІЦЕНТР: PIM (КАТАЛОГ)
('epicentr', 'pim', 'get_categories', 'GET', '/v2/pim/categories',
 'Список категорій Єпіцентру для XML імпорту',
 '{"limit": 20, "page": 1, "search": "optional"}',
 '{"items": [{"code": "2618", "translations": [{"languageCode": "ua", "title": "Воротки та ключі"}]}]}',
 true, 'get_categories', 2, '108 сторінок категорій. code використовується в XML фіді'),

('epicentr', 'pim', 'get_attribute_options', 'GET', '/v2/pim/attribute-sets/{set_code}/attributes/{attr_code}/options',
 'Допустимі значення атрибуту товару для XML',
 '{"attribute_set_code": "2618", "attribute_code": "brand", "limit": 100}',
 '{"items": [{"code": "toptul", "translations": [{"languageCode": "ua", "value": "TOPTUL"}]}]}',
 true, 'get_attribute_options', 2, 'Код значення підставляється в <value_code> XML фіду'),

-- ============================================================
-- НОВА ПОШТА — https://api.novaposhta.ua/v2.0/json/
-- Auth: apiKey в тілі JSON
-- Всі запити: POST з JSON body
-- ============================================================

('nova_poshta', 'tracking', 'track_ttn', 'POST', '/v2.0/json/',
 'Відстежити статус посилки по ТТН',
 '{"apiKey": "...", "modelName": "TrackingDocument", "calledMethod": "getStatusDocuments", "methodProperties": {"Documents": [{"DocumentNumber": "20451450921650"}]}}',
 '{"data": [{"StatusCode": "7", "Status": "Одержано", "RecipientFullName": "Петренко", "PhoneRecipient": "380671234567", "CashPaymentAmount": "1500.00"}]}',
 true, NULL, 1, 'Реалізовано в np_api.py::get_ttn_info'),

('nova_poshta', 'address', 'get_cities', 'POST', '/v2.0/json/',
 'Пошук міст/населених пунктів',
 '{"apiKey": "...", "modelName": "Address", "calledMethod": "getCities", "methodProperties": {"FindByString": "Рівне"}}',
 '{"data": [{"Ref": "uuid", "Description": "Рівне", "Area": "Рівненська"}]}',
 false, NULL, 4, NULL),

('nova_poshta', 'address', 'get_warehouses', 'POST', '/v2.0/json/',
 'Пошук відділень НП за містом',
 '{"apiKey": "...", "modelName": "Address", "calledMethod": "getWarehouses", "methodProperties": {"CityRef": "uuid-city", "FindByString": ""}}',
 '{"data": [{"Ref": "uuid", "Description": "Відділення №1", "Number": "1"}]}',
 false, NULL, 4, NULL),

('nova_poshta', 'document', 'create_ttn', 'POST', '/v2.0/json/',
 'Створити ТТН Нової Пошти',
 '{"apiKey": "...", "modelName": "InternetDocument", "calledMethod": "save", "methodProperties": {"PayerType": "Recipient", "PaymentMethod": "Cash", "CargoType": "Parcel", "Weight": "0.5", "ServiceType": "WarehouseWarehouse", "SeatsAmount": "1", "Description": "Інструмент", "Cost": "1500", "CitySender": "uuid", "Sender": "uuid", "SenderAddress": "uuid", "ContactSender": "uuid", "SendersPhone": "380671234567", "CityRecipient": "uuid", "Recipient": "uuid", "RecipientAddress": "uuid", "ContactRecipient": "uuid", "RecipientsPhone": "380671234567"}}',
 '{"data": [{"Ref": "uuid", "IntDocNumber": "20451450921650", "EstimatedDeliveryDate": "2026-06-14"}]}',
 false, NULL, 5, 'Потребує налаштування відправника'),

('nova_poshta', 'document', 'delete_ttn', 'POST', '/v2.0/json/',
 'Видалити ТТН (до прийому НП)',
 '{"apiKey": "...", "modelName": "InternetDocument", "calledMethod": "delete", "methodProperties": {"DocumentRefs": ["uuid-ttn"]}}',
 '{"success": true}',
 false, NULL, 7, NULL),

('nova_poshta', 'document', 'get_document_price', 'POST', '/v2.0/json/',
 'Розрахувати вартість доставки',
 '{"apiKey": "...", "modelName": "InternetDocument", "calledMethod": "getDocumentPrice", "methodProperties": {"CitySender": "uuid", "CityRecipient": "uuid", "ServiceType": "WarehouseWarehouse", "Weight": "1", "Cost": "1500"}}',
 '{"data": [{"Cost": 75, "AssessedCost": 15}]}',
 false, NULL, 6, NULL),

('nova_poshta', 'counterparty', 'get_counterparties', 'POST', '/v2.0/json/',
 'Список контрагентів (відправник/отримувач)',
 '{"apiKey": "...", "modelName": "CounterpartyGeneral", "calledMethod": "getCounterparties", "methodProperties": {"CounterpartyProperty": "Sender"}}',
 '{"data": [{"Ref": "uuid", "Description": "ФОП Петренко"}]}',
 false, NULL, 6, NULL),

('nova_poshta', 'tracking', 'match_order_by_np', 'POST', '/v2.0/json/',
 'Отримати дані отримувача для матчингу з замовленням',
 '{"apiKey": "...", "modelName": "TrackingDocument", "calledMethod": "getStatusDocuments", "methodProperties": {"Documents": [{"DocumentNumber": "20451450921650"}]}}',
 '{"data": [{"PhoneRecipient": "380671234567", "RecipientFullName": "Петренко Іван", "CityRecipient": "Рівне", "WarehouseRecipient": "Відділення 1", "CashPaymentAmount": "1500.00"}]}',
 true, NULL, 1, 'Реалізовано в np_api.py::match_order_by_np_data — матчинг по телефону/ПІБ/сумі');

-- ============================================================
-- Оновлення: позначити реалізовані методи агентів
-- (rozetka_order_agent.py, tg_dispatcher, epicentr_order_agent)
-- ============================================================

-- Підсумкова статистика
DO $$
DECLARE
    total_count INTEGER;
    impl_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO total_count FROM marketplace_api_methods;
    SELECT COUNT(*) INTO impl_count FROM marketplace_api_methods WHERE is_implemented = true;
    RAISE NOTICE '✅ Всього методів: % | Реалізовано: % | Не реалізовано: %',
        total_count, impl_count, total_count - impl_count;
END $$;

-- Статистика по маркетплейсах
SELECT
    marketplace,
    COUNT(*) AS total,
    SUM(CASE WHEN is_implemented THEN 1 ELSE 0 END) AS implemented,
    SUM(CASE WHEN NOT is_implemented THEN 1 ELSE 0 END) AS not_implemented,
    array_agg(DISTINCT domain ORDER BY domain) AS domains
FROM marketplace_api_methods
GROUP BY marketplace
ORDER BY marketplace;
