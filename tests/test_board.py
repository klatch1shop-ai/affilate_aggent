"""Дошка, 26.09.2026. Головне, що перевіряємо: дошка показує «перевірено
двома різними вендорами», а не лише лічильник зроблених, і чесно розрізняє
«живий» і «придатний» провайдер.
"""
from shared.utils import board


def test_verified_number_is_shown_next_to_counter():
    text = board.render_track({'name': 'Епіцентр', 'done': 1385, 'total': 1790,
                               'verified': 131, 'moving': True})
    assert '1385/1790' in text
    assert 'перевірено двома різними вендорами: 131' in text


def test_blocked_track_is_red_and_says_why():
    text = board.render_track({'name': 'Епіцентр', 'done': 10, 'total': 100,
                               'blocker': 'квота Codex до 11:40'})
    assert text.startswith('## 🔴')
    assert 'квота Codex до 11:40' in text


def test_moving_track_is_green_stalled_is_yellow():
    assert board.health({'moving': True}) == board.GREEN
    assert board.health({'moving': False}) == board.YELLOW
    assert board.health({'moving': True, 'blocker': 'щось'}) == board.RED


def test_percent_and_bar_handle_zero_total():
    assert board.percent(0, 0) == 0
    assert board.bar(5, 0) == '░' * 16          # не падає й не бреше


def test_bar_is_proportional():
    assert board.bar(0, 100, width=10) == '░' * 10
    assert board.bar(100, 100, width=10) == '█' * 10
    assert board.bar(50, 100, width=10) == '█' * 5 + '░' * 5


def test_vendor_alive_but_not_useful_is_visible():
    """26.09: Gemini відповідав за 0.8 с і на всіх картках казав «НЕ ВИДНО».
    Живий — ще не значить придатний."""
    text = board.render_vendors([{'name': 'gemini', 'alive': True, 'useful': False,
                                  'note': 'усі відповіді НЕ ВИДНО'}])
    assert '| gemini | ✅ | ✖️ |' in text
    assert 'НЕ ВИДНО' in text


def test_unknown_usefulness_is_dash_not_false():
    text = board.render_vendors([{'name': 'groq', 'alive': True}])
    assert '| groq | ✅ | — |' in text


def test_owner_actions_go_first():
    text = board.render([{'name': 'Розетка', 'done': 0, 'total': 1103}],
                        needs_owner=['перевірити фід у кабінеті'])
    assert text.index('Потребує вашої дії') < text.index('Розетка')


def test_telegram_summary_has_no_markdown_tables():
    text = board.render_telegram(
        [{'name': 'Епіцентр', 'done': 1385, 'total': 1790, 'verified': 131}],
        vendors=[{'name': 'openrouter', 'alive': True},
                 {'name': 'codex', 'alive': False}],
        needs_owner=['перевірити кабінет'])
    assert '|' not in text
    assert 'перевірено двома: 131' in text
    assert 'провайдери живі: openrouter' in text
    assert 'перевірити кабінет' in text


def test_telegram_says_when_no_vendor_alive():
    text = board.render_telegram([], vendors=[{'name': 'codex', 'alive': False}])
    assert 'жодного' in text
