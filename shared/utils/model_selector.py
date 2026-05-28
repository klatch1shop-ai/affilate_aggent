"""
shared/utils/model_selector.py
================================
Вибір моделі Ollama залежно від типу задачі.

Типи задач:
- routing   → швидка модель для маршрутизації команд
- code      → краща для коду і технічних задач
- text      → для генерації тексту, описів
- analysis  → для аналізу даних, конкурентів
- default   → за замовчуванням
"""
import os
from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))

# Маппінг задач → моделі (береться з .env або дефолт)
MODEL_MAP = {
    'routing':  os.getenv('OLLAMA_MODEL_ROUTING',  'llama3.2:3b'),
    'code':     os.getenv('OLLAMA_MODEL_CODE',     'qwen2.5:7b'),
    'text':     os.getenv('OLLAMA_MODEL_TEXT',     'llama3.2:3b'),
    'analysis': os.getenv('OLLAMA_MODEL_ANALYSIS', 'qwen2.5:7b'),
    'default':  os.getenv('OLLAMA_MODEL_DEFAULT',  'qwen2.5:7b'),
}

def get_model(task_type: str = 'default') -> str:
    """
    Повертає назву моделі для задачі.

    Використання:
        from shared.utils.model_selector import get_model
        model = get_model('routing')   # llama3.2:3b — швидка
        model = get_model('code')      # qwen2.5:7b — для коду
        model = get_model('analysis')  # qwen2.5:7b — для аналізу
    """
    return MODEL_MAP.get(task_type, MODEL_MAP['default'])

def list_models() -> dict:
    """Виводить всі налаштовані моделі."""
    return MODEL_MAP.copy()
