"""Приймальні тести: генератор YML-фіду для EVA Маркетплейс.

Формат і обмеження — з `docs/research/EVA_MARKETPLACE.md` §3 (реальний приклад
XML у довідці продавця). Написані ДО реалізації.
"""
import importlib
import re

import pytest

feed = importlib.import_module('content.eva_feed')


def item(**over):
    d = {'sku': 'SO3142', 'name_ru': 'Массажное масло Shunga', 'name_ua': 'Масажна олія Shunga',
         'price': 639.0, 'price_old': None, 'qty': 5, 'vendor': 'Shunga',
         'category_id': '100212', 'pictures': ['https://sexopt.com.ua/a.jpg', 'https://sexopt.com.ua/b.jpg'],
         'description_ru': '<p>Опис рос.</p>', 'description_ua': '<p>Опис укр.</p>',
         'params': {'Обʼєм': '100 мл', 'Країна': 'Франція'}}
    d.update(over)
    return d


# ── екранування ──────────────────────────────────────────────────────

@pytest.mark.parametrize('raw,out', [
    ('a & b', 'a &amp; b'), ('<tag>', '&lt;tag&gt;'), ("it's", 'it&apos;s'),
    ('"quoted"', '&quot;quoted&quot;'), (None, ''),
])
def test_esc_text(raw, out):
    assert feed.esc_text(raw) == out


def test_esc_text_strips_control_chars():
    # ASCII 0–31 заборонені стандартом YML, крім 9/10/13
    raw = 'до\x07бре\x00\tтак\n'
    out = feed.esc_text(raw)
    assert '\x07' not in out and '\x00' not in out
    assert '\t' in out and '\n' in out


def test_cdata_escapes_closing_sequence():
    assert feed.cdata('a ]]> b') == '<![CDATA[a ]]]]><![CDATA[> b]]>'
    assert feed.cdata('') == '<![CDATA[]]>'
    assert feed.cdata(None) == '<![CDATA[]]>'


# ── одна пропозиція ──────────────────────────────────────────────────

def test_build_offer_has_required_tags_in_order():
    # опис навмисно без вкладених HTML-тегів — інакше regex зловить теги з CDATA
    xml = feed.build_offer(item(description_ru='Опис рос.', description_ua='Опис укр.'))
    tags = re.findall(r'<(\w+)[ >]', xml)
    required_order = ['offer', 'price', 'stock_quantity', 'currencyId', 'categoryId',
                      'picture', 'picture', 'vendor', 'article', 'name', 'name_ua',
                      'description', 'description_ua', 'param', 'param']
    assert tags == required_order  # </offer> регулярка не ловить — "/" не \w


def test_build_offer_available_flag():
    assert 'available="true"' in feed.build_offer(item(qty=3))
    assert 'available="false"' in feed.build_offer(item(qty=0))
    assert 'available="false"' in feed.build_offer(item(qty=None))


def test_build_offer_price_old_optional():
    assert '<price_old>' not in feed.build_offer(item(price_old=None))
    xml = feed.build_offer(item(price_old=799.0))
    assert '<price_old>799</price_old>' in xml


def test_build_offer_price_is_integer_no_kopecks():
    assert '<price>639</price>' in feed.build_offer(item(price=639.4))
    assert '<price>640</price>' in feed.build_offer(item(price=639.6))


def test_build_offer_escapes_and_cdata():
    xml = feed.build_offer(item(name_ru='M&M "brand"', description_ru='<p>a ]]> b</p>'))
    assert '&amp;' in xml and '&quot;' in xml
    assert '<![CDATA[<p>a ]]]]><![CDATA[> b</p>]]>' in xml


def test_build_offer_params_rendered():
    xml = feed.build_offer(item(params={'Колір': 'Рожевий', 'Обʼєм': '50 мл'}))
    assert '<param name="Колір">Рожевий</param>' in xml
    assert '<param name="Обʼєм">50 мл</param>' in xml


def test_build_offer_no_params_omits_tag():
    assert '<param' not in feed.build_offer(item(params={}))


def test_build_offer_multiple_pictures_capped():
    many = [f'https://x/{i}.jpg' for i in range(20)]
    xml = feed.build_offer(item(pictures=many))
    assert xml.count('<picture>') == feed.MAX_PICTURES


def test_build_offer_requires_sku_and_price():
    with pytest.raises(ValueError):
        feed.build_offer(item(sku=''))
    with pytest.raises(ValueError):
        feed.build_offer(item(price=None))
    with pytest.raises(ValueError):
        feed.build_offer(item(price=0))


def test_build_offer_requires_at_least_one_picture():
    with pytest.raises(ValueError):
        feed.build_offer(item(pictures=[]))


# ── категорії ─────────────────────────────────────────────────────────

def test_build_categories_block():
    xml = feed.build_categories({'100212': 'Крем для тіла', '100222': 'Гель для душу'})
    assert '<category id="100212">Крем для тіла</category>' in xml
    assert '<category id="100222">Гель для душу</category>' in xml
    assert xml.startswith('<categories>') and xml.endswith('</categories>')


def test_build_categories_empty_raises():
    with pytest.raises(ValueError):
        feed.build_categories({})


# ── повний документ ──────────────────────────────────────────────────

def test_build_feed_structure():
    items = [item(sku='A1'), item(sku='A2', category_id='100222')]
    cats = {'100212': 'Крем для тіла', '100222': 'Гель для душу'}
    xml = feed.build_feed(items, cats, shop_name='klatch1 shop', shop_company='3721108',
                          shop_url='https://cs4053918.prom.ua/', now='2026-09-25 12:00')
    assert xml.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    assert '<yml_catalog date="2026-09-25 12:00">' in xml
    assert '<name>klatch1 shop</name>' in xml
    assert '<company>3721108</company>' in xml
    assert '<url>https://cs4053918.prom.ua/</url>' in xml
    assert '<currency rate="1" id="UAH"/>' in xml
    assert xml.count('<offer ') == 2
    assert xml.rstrip().endswith('</yml_catalog>')


def test_build_feed_skips_items_missing_category_and_reports():
    items = [item(sku='A1', category_id='100212'), item(sku='A2', category_id='999999')]
    cats = {'100212': 'Крем для тіла'}
    xml, skipped = feed.build_feed(items, cats, shop_name='s', shop_company='c',
                                   shop_url='u', now='2026-09-25', return_skipped=True)
    assert xml.count('<offer ') == 1
    assert skipped == [('A2', 'категорія 999999 відсутня в довіднику')]


def test_build_feed_empty_items_raises():
    with pytest.raises(ValueError):
        feed.build_feed([], {'1': 'x'}, shop_name='s', shop_company='c', shop_url='u', now='2026-09-25')


def test_valid_xml_output():
    import xml.etree.ElementTree as ET
    items = [item(sku='A1')]
    cats = {'100212': 'Крем для тіла'}
    xml_text = feed.build_feed(items, cats, shop_name='s', shop_company='c',
                               shop_url='u', now='2026-09-25')
    ET.fromstring(xml_text)          # не кидає — документ структурно валідний
