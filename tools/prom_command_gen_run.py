"""Живий прогін: 21 метод Prom API → Gemini → команди каталогу. Нічого не пише
в бота — лише генерує й перевіряє. ЯКЩО впаде на кількох методах — не критично,
частину можна дозаповнити вручну."""
import json, sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv; load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))
from shared.utils.llm_router import call_gemini
import content.prom_api_registry as reg
import content.prom_command_gen as gen

results, failed = {}, []
for mid, method in reg.METHODS.items():
    prompt = gen.build_prompt(mid, method)
    try:
        text, model, tokens = call_gemini(prompt, max_tokens=600)
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
