"""
agents/interfaces/instruction_parser.py
==========================================
Парсер /learn команд — оновлює .md файли скілів агентів.

При отриманні /learn <інструкція>:
1. Визначає який .md файл оновити (по ключових словах)
2. Форматує інструкцію як блок "Оновлені правила"
3. Дописує в кінець відповідного .md файлу
4. Зберігає лог в БД (таблиця skill_updates)
5. Повідомляє що правило застосовано

Приклади:
/learn Єпіцентр змінив кнопку Export → оновлює browser_automation.md
/learn Prom змінив формат API відповіді → оновлює prom_api.md
/learn Нова категорія Єпіцентру → оновлює epicentr_api.md
"""

import os, sys, re
from datetime import datetime
from loguru import logger

sys.path.append('/home/tek/agent-system')
from shared.utils.db import get_connection

SKILLS_DIR = '/home/tek/agent-system/shared/skills'

# Маппінг ключових слів → файли скілів
SKILL_ROUTING = {
    # Browser automation
    'єпіцентр':         'scraper/browser_automation.md',
    'epicentr':         'scraper/browser_automation.md',
    'розетка':          'scraper/browser_automation.md',
    'rozetka':          'scraper/browser_automation.md',
    'браузер':          'scraper/browser_automation.md',
    'кнопка':           'scraper/browser_automation.md',
    'селектор':         'scraper/browser_automation.md',
    'playwright':       'scraper/browser_automation.md',
    'selenium':         'scraper/browser_automation.md',

    # Prom API
    'prom api':         'scraper/prom_api.md',
    'prom відповідь':   'scraper/prom_api.md',
    'prom формат':      'scraper/prom_api.md',

    # Ціноутворення
    'ціна':             'pricing/cpa_rates.md',
    'cpa':              'pricing/cpa_rates.md',
    'комісія':          'pricing/cpa_rates.md',
    'маржа':            'pricing/cpa_rates.md',

    # Розетка XML
    'xml':              'scraper/rozetka_xml_requirements.md',
    'роzetka xml':      'scraper/rozetka_xml_requirements.md',

    # Загальне
    'агент':            'orchestrator/agent_communication.md',
    'оркестратор':      'orchestrator/agent_communication.md',
}


class InstructionParser:

    def detect_skill_file(self, instruction: str) -> str:
        """Визначає який файл скіла оновити по тексту інструкції."""
        instruction_lower = instruction.lower()

        for keyword, skill_file in SKILL_ROUTING.items():
            if keyword in instruction_lower:
                return skill_file

        # За замовчуванням — browser_automation.md
        return 'scraper/browser_automation.md'

    def format_instruction(self, instruction: str) -> str:
        """Форматує інструкцію як markdown блок."""
        now = datetime.now().strftime('%d.%m.%Y %H:%M')
        return f'\n\n## Оновлені правила ({now})\n\n> {instruction}\n'

    async def apply_instruction(self, instruction: str, user_id: int = None) -> dict:
        """
        Застосовує /learn інструкцію:
        1. Визначає файл
        2. Дописує правило
        3. Зберігає в БД
        """
        try:
            skill_file = self.detect_skill_file(instruction)
            full_path = os.path.join(SKILLS_DIR, skill_file)

            if not os.path.exists(full_path):
                return {'success': False, 'error': f'Файл не знайдено: {full_path}'}

            # Читаємо поточний вміст
            with open(full_path, 'r', encoding='utf-8') as f:
                current_content = f.read()

            # Перевіряємо чи не дублюємо
            if instruction[:50] in current_content:
                return {
                    'success': False,
                    'error': 'Це правило вже є в файлі скіла'
                }

            # Дописуємо нове правило
            new_content = current_content + self.format_instruction(instruction)

            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(new_content)

            added_text = self.format_instruction(instruction)

            # Зберігаємо в БД
            self._save_to_db(skill_file, instruction, user_id, added_text)

            logger.success(f'[InstructionParser] Правило додано в {skill_file}')
            return {
                'success': True,
                'skill_file': skill_file,
                'added_text': added_text,
            }

        except Exception as e:
            logger.error(f'[InstructionParser] Помилка: {e}')
            return {'success': False, 'error': str(e)}

    def _save_to_db(self, skill_file: str, instruction: str,
                    user_id: int = None, notes: str = None):
        """Зберігає лог в таблицю skill_updates."""
        try:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute('''
                INSERT INTO skill_updates (skill_file, instruction, applied_by, notes)
                VALUES (%s, %s, %s, %s)
            ''', (skill_file, instruction, str(user_id) if user_id else None, notes))
            conn.commit(); cur.close(); conn.close()
        except Exception as e:
            logger.error(f'[InstructionParser] DB error: {e}')

    def get_update_history(self, limit: int = 20) -> list:
        """Повертає історію /learn команд."""
        try:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute(
                'SELECT skill_file, instruction, applied_at FROM skill_updates '
                'ORDER BY applied_at DESC LIMIT %s',
                (limit,)
            )
            rows = [dict(r) for r in cur.fetchall()]
            cur.close(); conn.close()
            return rows
        except:
            return []
