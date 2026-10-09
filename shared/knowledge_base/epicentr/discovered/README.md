# core-api Єпіцентру — звідки взявся перелік

`core_api_paths.txt` — 261 унікальний шлях, витягнутий з JS-бандла кабінету
`admin.epicentrm.com.ua/main.*.js` (09.10.2026). Публічної специфікації в
core-api немає, тому це найповніше джерело: фронтенд кабінету знає кожен
метод, який сам викликає.

**Чому не перехоплення XHR.** `epicentr_cabinet.py --action intercept_api`
існує, але жодного разу не завершився: браузер падає (core dump), файл
`epicentr_api_discovered.json` так і не з'явився.

**Розрізнення «є / немає» перевірено:**
* метод є, але даних немає → `{"code":404,"message":"entity.not_found"}`
* методу немає в сервісі → `No route found for "GET https://em--oms--…"`
* шляху немає взагалі → `{"message":"No route configured"}` (негативний контроль)

**Перевірено живою сесією 09.10:** `/v2/pim/attribute-sets` (total **5521**),
`/v2/pim/categories` (4721), `/v4/oms/orders`, `/v4/oms/orders/total`.
`/v2/pim/categories/public` відповідає навіть БЕЗ авторизації.

**Не плутати з merchant-api.** Це інший хост і окремий токен, якого в нас
немає. Але довідник атрибутів і категорій доступний саме через core-api,
тобто для нього токен merchant-api НЕ потрібен.
