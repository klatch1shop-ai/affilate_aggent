# SMTM (sexopt, NOIRE) — вивантаження постачальника

Надіслано власником 20.09.2026 (текст постачальника). Усі файли публічні.

## Для додавання товарів (оновлення раз на добу до 08:00)
| формат | файл | що |
|---|---|---|
| XLS | `https://smtm.com.ua/_prices/import-retail.xls` | усе: артикул, назва, опис, фото, роздрібна ціна, характеристики |
| XLS | `…/import-retail-lingerie.xls` | лише білизна |
| XLS | `…/import-retail-cosmetic.xls` | **лише косметика** |
| XLS | `…/import-retail-horoshop.xls` / `…-horoshop-ua.xls` | під Хорошоп, рос. / укр. |
| XLS | `…/import-retail-geske.xls` | лише бренд Geske |
| XML | `…/import-retail-2.xml` / `…/import-retail-ua-2.xml` | рос. / укр., + наявність true/false |
| XML | `…/import-retail-geske.xml` | Geske, укр. |

## Для цін і наявності (оновлення кожні 2 години)
| файл | наявність |
|---|---|
| `…/price-retail-horoshop.xls`, `…-lingerie.xls`, `…-cosmetic.xls`, `…/price-retail.xls` | 0–5 (5 = «5 і більше») |
| `…/price-retail-prom.xls` | `+` / `-` |
| `…/price-retail.csv` | 0, 1, 3, `>3` |

«Роздрібна ціна» — це поріг ціни власника (не нижче, `price-floor-no-dumping`).

## Косметика — зріз 20.09.2026 (`import-retail-cosmetic.xls`)
- 446 товарів, у наявності 325 (прайс 2 год), ціна 29–5 899 грн, медіана 949 грн; фото — у всіх, опис — у 411.
- Розділи: масажні олії 123, масажні свічки 74, масажна косметика без олії 57, інтимна гігієна 36,
  феромони 19, масажні пінки 18, подарункові набори 17+8, фарба/карамель для тіла 14, парфуми 11,
  гелі для душу 11, гоління 9, сіль/піна для ванни 9, NURU 8…
- Бренди: Shunga 82, Sensuva 58, Plaisirs Secrets 47, Exsens 37, Orgie 30, Bijoux Indiscrets 26, Love To Love 23.
- Звірка з нами: у БД `sexopt_products` 426/446; у фіді **Rozetka 198**, **Prom 184**, Епіцентр 426.
  Тобто ~230 товарів косметики не виставлено на Rozetka і ~260 — на Prom.
