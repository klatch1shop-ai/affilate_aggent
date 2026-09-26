"""Живий прогін: 21 метод Prom API → Groq (fallback Cerebras) → команди каталогу.
Нічого не пише в бота — лише генерує й перевіряє. ЯКЩО впаде на кількох методах —
не критично, частину можна дозаповнити вручну.

26.09.2026: Gemini free tier виявився занадто малим (~20 запитів/добу на модель) —
не вистачило навіть на 21 виклик поспіль. Groq/Cerebras мають на порядки більшу
безкоштовну квоту (OpenAI-сумісні, reasoning-моделі — тому max_tokens=600, не 300:
`reasoning`-токени зʼїдають частину ліміту раніше за саму відповідь)."""
import json, sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv; load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))
from shared.utils.llm_router import call_groq, call_cerebras
import content.prom_api_registry as reg
import content.prom_command_gen as gen


def call_with_fallback(prompt, max_tokens):
    try:
        text, model = call_groq(prompt, max_tokens=max_tokens)
        return text, model
    except Exception:
        text, model = call_cerebras(prompt, max_tokens=max_tokens)
        return text, model


results, failed = {}, []
for mid, method in reg.METHODS.items():
    prompt = gen.build_prompt(mid, method)
    try:
        text, model = call_with_fallback(prompt, max_tokens=600)
        cmd = gen.parse_command(text)
        allowed = set(method['params'])
        if not gen.needs_are_real(cmd['needs'], allowed):
            bad = [n for n in cmd['needs'] if n not in allowed]
            print(f'⚠️  {mid}: вигадані параметри {bad} — відкидаю їх')
            cmd['needs'] = [n for n in cmd['needs'] if n in allowed]
        entry = gen.to_catalog_entry(mid, cmd, method)
        results[mid] = entry
        print(f"{mid:<32} [{model}] «{entry['example']}» · needs={entry['needs']}")
    except Exception as e:
        failed.append((mid, type(e).__name__, str(e)[:100]))
        print(f'❌ {mid}: {type(e).__name__}: {str(e)[:100]}')

print(f'\nусього: {len(reg.METHODS)} · згенеровано: {len(results)} · провалів: {len(failed)}')
json.dump(results, open('/tmp/prom_generated_commands.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
if failed:
    print('провали:', failed)
