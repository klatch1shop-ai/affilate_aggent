"""Миттєвий чат у панелі через Anthropic API.

ЧИМ ЦЕ НЕ Є. Це НЕ та сесія Claude Code, що працює в терміналі. З нею
веб говорити не може — різні процеси, механізму не існує. Тут окремий
співрозмовник, якому ми самі даємо контекст проєкту й право читати.

ЧОМУ ОКРЕМО ВІД ЧАТУ-ЛИСТУВАННЯ. Листування (`/api/chat`) безкоштовне й
доходить до мене, коли я працюю. Це — платне за токени й відповідає за
секунди. Дві різні речі, тому дві різні кнопки, а не одне поле «чат».

УВІМКНЕННЯ. Потрібен справжній ANTHROPIC_API_KEY у .env (зараз там
заглушка `your_api_key`). Без нього сервіс чесно каже, що вимкнений, а
не падає.

ПРАВО ЛИШЕ ЧИТАТИ. Співрозмовник має доступ до документів репозиторію та
до читальних команд майданчиків (R0). Нічого змінити він не може — усі
записувальні дії лишаються за підтвердженням у боті.
"""
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

MODEL = os.getenv('PANEL_ASK_MODEL', 'claude-opus-5-5')
EFFORT = os.getenv('PANEL_ASK_EFFORT', 'medium')
# Ціна станом на довідник SDK, $/млн токенів. Показуємо власнику вартість
# кожної відповіді — інакше платний канал непомітно з'їдає гроші.
PRICE = {'claude-opus-5-5': (4.0, 20.0), 'claude-opus-5': (5.0, 25.0),
         'claude-sonnet-5-5': (2.0, 10.0), 'claude-haiku-4-5': (1.0, 5.0)}


def ключ_є():
    k = (os.getenv('ANTHROPIC_API_KEY') or '').strip()
    return bool(k) and not k.startswith('your_') and len(k) > 20


def _контекст():
    """Що співрозмовник має знати про наш проєкт із самого початку."""
    шматки = []
    for шлях, межа in (('docs/SYSTEM_INVENTORY.md', 7000),
                       ('docs/напрями/README.md', 3000),
                       ('docs/АУДИТ_КОДУ.md', 5000)):
        p = os.path.join(BASE, шлях)
        if os.path.exists(p):
            with open(p, encoding='utf-8') as f:
                шматки.append(f'### {шлях}\n{f.read()[:межа]}')
    try:
        from helper import panel_db as DB
        дошка = DB.board_list(limit=30)
        if дошка:
            шматки.append('### дошка завдань\n' + '\n'.join(
                f'#{b["id"]} [{b["status"]}] {b["kind"]}: {b["title"]}'
                for b in дошка))
    except Exception:
        pass
    return '\n\n'.join(шматки)


SYSTEM = """Ти — помічник власника невеликого бізнесу, який продає товари на
українських маркетплейсах (Rozetka, Prom, Єпіцентр, EVA). Відповідай
українською, стисло й по суті, без вступів на кшталт «звичайно».

Важливі правила цього проєкту:
* Не називай числа, яких не бачив. Якщо не знаєш — скажи «не знаю».
* Не стверджуй, що щось працює, якщо це не перевірено.
* Ти маєш право лише ЧИТАТИ. Усе, що змінює дані чи витрачає гроші,
  робиться через підтвердження в Telegram-боті, і ти цього не обходиш.

Нижче — опис системи станом на зараз. Спирайся на нього."""


def спитати(питання, історія=None):
    """→ {'текст', 'вартість', 'токени'} або {'вимкнено': причина}."""
    if not ключ_є():
        return {'вимкнено': 'немає справжнього ANTHROPIC_API_KEY у .env — '
                            'миттєвий чат платний і без ключа не працює'}
    import anthropic
    client = anthropic.Anthropic()
    msgs = []
    for m in (історія or [])[-10:]:
        msgs.append({'role': 'assistant' if m['role'] == 'claude' else 'user',
                     'content': m['text']})
    msgs.append({'role': 'user', 'content': питання})

    with client.messages.stream(
        model=MODEL,
        max_tokens=16000,
        thinking={'type': 'adaptive'},
        output_config={'effort': EFFORT},
        system=[{'type': 'text', 'text': SYSTEM},
                {'type': 'text', 'text': _контекст(),
                 'cache_control': {'type': 'ephemeral'}}],
        messages=msgs,
    ) as s:
        msg = s.get_final_message()

    текст = ''.join(b.text for b in msg.content if b.type == 'text')
    u = msg.usage
    вх, вих = PRICE.get(MODEL, (0, 0))
    ціна = (getattr(u, 'input_tokens', 0) * вх
            + getattr(u, 'output_tokens', 0) * вих) / 1_000_000
    return {'текст': текст, 'вартість': round(ціна, 4),
            'токени': {'вхід': getattr(u, 'input_tokens', 0),
                       'вихід': getattr(u, 'output_tokens', 0),
                       'з_кешу': getattr(u, 'cache_read_input_tokens', 0)}}
