"""Підготовка й зведення спору на спільному наборі доказів без зовнішніх дій."""

import json
import re


SIDES = ('за', 'проти')


def build_prompts(claim: str, evidence: list[dict]) -> dict:
    """Підготувати протилежні завдання з однаковими доказами."""
    if not claim.strip() or not evidence:
        raise ValueError('Потрібні непорожня теза й докази')
    ids = [item['id'] for item in evidence]
    if len(set(ids)) != len(ids):
        raise ValueError('Ідентифікатори доказів мають бути унікальними')
    facts = '\n'.join(f"[{item['id']}] {item['text']}" for item in evidence)
    common = (
        f'Теза: {claim}\nДокази:\n{facts}\n'
        'Відповідай лише JSON-списком об’єктів з ключами "point" (текст аргументу) '
        'і "refs" (список id доказів). '
        'Посилайся лише на наведені id доказів. Не вигадуй нових фактів.\n'
    )
    return {
        'за': common + 'Обґрунтуй тезу: наведи аргументи за неї.',
        'проти': common + 'Спростуй тезу: наведи аргументи проти неї.',
    }


def parse_side(text: str) -> list[dict]:
    """Розібрати JSON-відповідь і нормалізувати аргументи та посилання."""
    raw = text.strip()
    fence = re.fullmatch(r'```(?:json)?\s*\n?(.*?)\s*```', raw, re.DOTALL | re.IGNORECASE)
    if fence:
        raw = fence.group(1)
    items = json.loads(raw)
    if not isinstance(items, list):
        raise ValueError('Відповідь має бути JSON-списком')
    result = []
    for item in items:
        if not isinstance(item, dict):
            continue
        point = item.get('point')
        if point is None:
            continue
        point = str(point).strip()
        if not point:
            continue
        refs = item.get('refs', [])
        if isinstance(refs, str):
            refs = [refs]
        if not isinstance(refs, list):
            raise ValueError('Посилання мають бути рядком або списком')
        result.append({'point': point, 'refs': [str(ref).strip() for ref in refs]})
    return result


def merge(pro: list[dict], con: list[dict], evidence: list[dict]) -> dict:
    """Зарахувати лише аргументи, усі посилання яких є серед доказів."""
    known = {item['id'] for item in evidence}
    used = set()
    result = {'for': [], 'against': [], 'dropped': []}
    for side, key, points in (('за', 'for', pro), ('проти', 'against', con)):
        for item in points:
            refs = item['refs']
            reason = ''
            if not refs:
                reason = 'без доказу'
            else:
                for ref in refs:
                    if ref not in known:
                        reason = f'невідомий доказ: {ref}'
                        break
            if reason:
                result['dropped'].append({
                    'side': side, 'point': item['point'], 'reason': reason,
                })
            else:
                result[key].append({'point': item['point'], 'refs': list(refs)})
                used.update(refs)
    result['unused'] = [item['id'] for item in evidence if item['id'] not in used]
    for_count, against_count = len(result['for']), len(result['against'])
    if not for_count or not against_count:
        balance = 'однобоко'
    elif for_count == against_count:
        balance = 'рівно'
    else:
        balance = 'за' if for_count > against_count else 'проти'
    result['balance'] = balance
    return result


def report(claim: str, merged: dict) -> str:
    """Сформувати стислий текст спору з посиланнями й підсумком."""
    lines = [f'⚖️ {claim}']
    for title, key in (('За', 'for'), ('Проти', 'against')):
        points = merged[key]
        lines.append(f'{title} ({len(points)}):')
        if not points:
            lines.append('• —')
        for item in points:
            lines.append(f"• {item['point']} [{', '.join(item['refs'])}]")
    without_evidence = sum(item['reason'] == 'без доказу' for item in merged['dropped'])
    if without_evidence:
        lines.append(f'Відкинуто без доказу: {without_evidence}')
    if merged['unused']:
        lines.append(f"Не використані докази: {', '.join(merged['unused'])}")
    lines.append(f"Підсумок: {merged['balance']}")
    return '\n'.join(lines)
