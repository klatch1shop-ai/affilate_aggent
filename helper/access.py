"""Перевірка доступу до бота, закритого за замовчуванням."""


def parse_ids(value: str | None) -> frozenset[int]:
    if value is None or not value.strip():
        return frozenset()
    return frozenset(int(item.strip()) for item in value.split(','))


def is_allowed(user_id, allowed: frozenset[int]) -> bool:
    if not allowed or isinstance(user_id, bool):
        return False
    if isinstance(user_id, str):
        if not user_id.isdecimal():
            return False
        user_id = int(user_id)
    return isinstance(user_id, int) and user_id in allowed
