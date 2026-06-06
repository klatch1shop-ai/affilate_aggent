"""
Category Mapper — знаходить відповідну категорію Prom по назві
"""
import sys
from difflib import SequenceMatcher
sys.path.insert(0, '/home/tekken/agent-system')
from shared.utils.db import get_connection


def get_all_categories():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('SELECT category_id, name, full_path, level FROM prom_categories ORDER BY level DESC')
    result = cur.fetchall()
    cur.close(); conn.close()
    return result


def find_category(search_name: str, top_n: int = 5) -> list:
    """Знаходить найближчі категорії по назві."""
    categories = get_all_categories()
    search_lower = search_name.lower().strip()
    
    scores = []
    for cat in categories:
        cat_name = (cat['name'] or '').lower()
        full_path = (cat['full_path'] or '').lower()
        
        # Точний збіг
        if search_lower == cat_name:
            score = 1.0
        # Пошук в назві
        elif search_lower in cat_name or cat_name in search_lower:
            score = 0.9
        # Пошук в повному шляху
        elif search_lower in full_path:
            score = 0.7
        # Fuzzy match
        else:
            score = SequenceMatcher(None, search_lower, cat_name).ratio()
        
        if score > 0.3:
            scores.append({
                'category_id': cat['category_id'],
                'name': cat['name'],
                'full_path': cat['full_path'],
                'level': cat['level'],
                'score': round(score, 3)
            })
    
    scores.sort(key=lambda x: (-x['score'], -x['level']))
    return scores[:top_n]


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Використання: python3 category_mapper.py "назва категорії"')
        sys.exit(1)
    
    query = ' '.join(sys.argv[1:])
    print(f'\nПошук категорії: "{query}"\n')
    results = find_category(query)
    
    if not results:
        print('Нічого не знайдено')
    else:
        print(f'{"ID":<12} {"Score":<8} {"Рівень":<8} {"Назва"}')
        print('-' * 80)
        for r in results:
            print(f'{r["category_id"]:<12} {r["score"]:<8} {r["level"]:<8} {r["full_path"]}')
