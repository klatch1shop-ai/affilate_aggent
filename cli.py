#!/usr/bin/env python3
"""
Agent System CLI — командний рядок для керування системою
Використання:
  ./cli.py status          — статус всіх агентів
  ./cli.py cmd "текст"     — відправити команду оркестратору
  ./cli.py logs [агент]    — переглянути логи
  ./cli.py skills [агент]  — список скілів
  ./cli.py queues          — стан черг
  ./cli.py alerts          — непрочитані сповіщення
  ./cli.py chat            — інтерактивний чат з оркестратором
  ./cli.py skill create    — створити новий скіл
  ./cli.py marketplace     — перевірити підключення до маркетплейсів
"""
import os, sys, json, time, asyncio
from datetime import datetime

sys.path.append(os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

# Кольори для терміналу
class C:
    RESET  = "\033[0m"
    BOLD   = "\033[1m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    RED    = "\033[91m"
    BLUE   = "\033[94m"
    PURPLE = "\033[95m"
    CYAN   = "\033[96m"
    GRAY   = "\033[90m"

def color(text, c): return f"{c}{text}{C.RESET}"
def bold(text): return color(text, C.BOLD)
def green(text): return color(text, C.GREEN)
def yellow(text): return color(text, C.YELLOW)
def red(text): return color(text, C.RED)
def blue(text): return color(text, C.BLUE)
def cyan(text): return color(text, C.CYAN)
def gray(text): return color(text, C.GRAY)

def print_header(title):
    print()
    print(bold(cyan(f"═══ {title} ═══")))
    print()

def print_status():
    from shared.utils.db import get_connection
    from shared.utils.redis_queue import get_queue_length
    import redis as r

    print_header("AGENT SYSTEM STATUS")

    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT name, status, updated_at FROM agents ORDER BY name")
        agents = cur.fetchall()
        cur.execute("SELECT COUNT(*) as cnt FROM alerts WHERE is_read=false")
        unread = cur.fetchone()
        cur.execute("SELECT COUNT(*) as cnt FROM event_logs WHERE created_at > NOW() - INTERVAL '1 hour'")
        recent = cur.fetchone()
        cur.close(); conn.close()

        emoji = {"idle": green("● idle"), "busy": yellow("◉ busy"), "error": red("✗ error"), "offline": gray("○ offline")}
        rd = r.Redis(host=os.getenv("REDIS_HOST", "localhost"), port=int(os.getenv("REDIS_PORT", 6379)), decode_responses=True)

        print(bold("Агенти:"))
        for a in agents:
            status = emoji.get(a["status"], a["status"])
            q = get_queue_length(f"queue:{a['name']}")
            q_str = yellow(f" [черга:{q}]") if q > 0 else gray(" [черга:0]")
            print(f"  {status:30} {a['name']:15}{q_str}")

        print()
        snap_raw = rd.get("system:snapshot")
        if snap_raw:
            snap = json.loads(snap_raw)
            print(bold("Snapshot:"))
            print(f"  Ціль: {cyan(snap.get('goal','не встановлено'))}")
            if snap.get("last_command"):
                print(f"  Остання команда: {gray(snap['last_command'][:60])}")

        print()
        print(bold("Статистика:"))
        print(f"  Непрочитаних сповіщень: {yellow(str(unread['cnt']))}")
        print(f"  Подій за годину: {green(str(recent['cnt']))}")

    except Exception as e:
        print(red(f"Помилка: {e}"))

def print_logs(agent_name=None, limit=20):
    from shared.utils.db import get_connection
    print_header(f"ЛОГИ{' — ' + agent_name if agent_name else ''}")
    try:
        conn = get_connection()
        cur = conn.cursor()
        if agent_name:
            cur.execute("""SELECT el.level, el.message, el.created_at, a.name as agent
                FROM event_logs el LEFT JOIN agents a ON el.agent_id=a.id
                WHERE a.name=%s ORDER BY el.created_at DESC LIMIT %s""", (agent_name, limit))
        else:
            cur.execute("""SELECT el.level, el.message, el.created_at, a.name as agent
                FROM event_logs el LEFT JOIN agents a ON el.agent_id=a.id
                ORDER BY el.created_at DESC LIMIT %s""", (limit,))
        rows = cur.fetchall()
        cur.close(); conn.close()
        lv_color = {"INFO": green, "WARNING": yellow, "ERROR": red, "SUCCESS": cyan}
        for r in rows:
            t = r["created_at"].strftime("%H:%M:%S") if r["created_at"] else ""
            lv = r["level"] or "INFO"
            col = lv_color.get(lv, gray)
            ag = blue(f"[{r['agent'] or '?'}]")
            print(f"  {gray(t)} {col(lv[:4]):15} {ag:20} {r['message'][:70]}")
    except Exception as e:
        print(red(f"Помилка: {e}"))

def print_queues():
    from shared.utils.redis_queue import get_queue_length
    print_header("ЧЕРГИ ЗАВДАНЬ")
    agents = ["orchestrator","scraper","marketing","developer","finance","efficiency"]
    for a in agents:
        count = get_queue_length(f"queue:{a}")
        bar = green("█") * min(count, 20) + gray("░") * (20 - min(count, 20))
        count_str = yellow(str(count)) if count > 0 else gray("0")
        print(f"  {a:15} {bar} {count_str}")

def print_alerts(limit=10):
    from shared.utils.db import get_connection
    print_header("СПОВІЩЕННЯ")
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""SELECT level, source, title, message, created_at, is_read
            FROM alerts ORDER BY created_at DESC LIMIT %s""", (limit,))
        rows = cur.fetchall()
        cur.execute("UPDATE alerts SET is_read=true WHERE is_read=false")
        conn.commit()
        cur.close(); conn.close()
        lv_color = {"INFO": green, "WARNING": yellow, "ERROR": red}
        for r in rows:
            t = r["created_at"].strftime("%d.%m %H:%M") if r["created_at"] else ""
            col = lv_color.get(r["level"], gray)
            read = "" if r["is_read"] else yellow(" ●NEW")
            print(f"  {gray(t)} {col(r['level'][:4]):15} {bold(r['title'])}{read}")
            if r["message"]:
                print(f"  {gray(' ' * 20)} {gray(r['message'][:80])}")
    except Exception as e:
        print(red(f"Помилка: {e}"))

def print_skills(agent_name=None):
    from shared.utils.skill_loader import list_skills
    print_header(f"СКІЛИ{' — ' + agent_name if agent_name else ''}")
    skills = list_skills(agent_name)
    current_agent = None
    for s in sorted(skills, key=lambda x: x["agent"]):
        if s["agent"] != current_agent:
            current_agent = s["agent"]
            print(f"  {bold(blue(current_agent))}")
        print(f"    {green(s['name']):30} {gray(s['description'][:50])}")
    print()
    print(f"  Всього скілів: {bold(str(len(skills)))}")

def send_command(cmd: str):
    from shared.utils.redis_queue import push_task
    from shared.utils.db import log_event
    print_header("КОМАНДА")
    print(f"  Відправляю: {cyan(cmd)}")
    task = {"type": "admin_command", "description": cmd,
            "priority": 9, "source": "cli", "timestamp": time.time()}
    push_task("queue:orchestrator", task)
    log_event("orchestrator", "INFO", f"CLI command: {cmd}", {"source": "cli"})
    print(f"  {green('✓ Команду відправлено в чергу оркестратора')}")
    print(f"  Переглянь результат: {gray('./cli.py logs orchestrator')}")

def interactive_chat():
    from shared.utils.redis_queue import push_task
    from shared.utils.db import log_event
    print_header("ІНТЕРАКТИВНИЙ ЧАТ З ОРКЕСТРАТОРОМ")
    print(f"  {gray('Введи команду або питання. Ctrl+C або exit для виходу.')}")
    print()
    while True:
        try:
            cmd = input(f"{cyan('Ти')} {bold('>')}" + " ").strip()
            if cmd.lower() in ["exit", "quit", "q", ""]:
                print(gray("Вихід з чату."))
                break
            task = {"type": "admin_command", "description": cmd,
                    "priority": 9, "source": "cli_chat", "timestamp": time.time()}
            push_task("queue:orchestrator", task)
            print(f"  {green('✓ Відправлено → оркестратор обробляє...')}")
            print(f"  {gray('Результат буде в логах.')}")
            print()
        except KeyboardInterrupt:
            print()
            print(gray("Вихід з чату."))
            break

def create_skill_interactive():
    from shared.utils.skill_loader import list_skills
    print_header("СТВОРЕННЯ НОВОГО СКІЛА")
    agents = ["orchestrator","scraper","marketing","finance","developer","efficiency","researcher"]
    print("Для якого агента?")
    for i, a in enumerate(agents, 1):
        print(f"  {i}. {a}")
    choice = input("Номер: ").strip()
    try:
        agent = agents[int(choice)-1]
    except:
        print(red("Невірний вибір")); return
    name = input(f"Назва скіла (напр. price_monitoring): ").strip()
    if not name:
        print(red("Назва обов'язкова")); return
    desc = input("Короткий опис (1 речення): ").strip()
    print(f"\nСтворюю скіл {cyan(name)} для агента {blue(agent)}...")
    content = f"""# {desc}

## Опис
{desc}

## Коли використовувати
- TODO: описати коли використовувати цей скіл

## Інструкції
### Крок 1
TODO

### Крок 2
TODO

## Формат результату
TODO

## Заборонено
- TODO
"""
    path = f"shared/skills/{agent}/{name}.md"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
    print(green(f"✓ Скіл створено: {path}"))
    print(gray(f"Відредагуй файл: nano {path}"))

async def check_marketplaces():
    import httpx
    print_header("ПІДКЛЮЧЕННЯ ДО МАРКЕТПЛЕЙСІВ")
    checks = [
        ("Prom.ua API", "PROM_API_TOKEN",
         "https://my.prom.ua/api/v1/products/list",
         {"Authorization": f"Bearer {os.getenv('PROM_API_TOKEN','')}"},
         {"limit": 1}),
    ]
    for name, env_key, url, headers, params in checks:
        token = os.getenv(env_key, "")
        if not token or token == "your_token_here":
            print(f"  {yellow('⚠')} {name:20} {yellow('Токен не встановлено')}")
            print(f"    {gray(f'Встанови в .env: {env_key}=your_token')}")
            continue
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url, headers=headers, params=params)
                if resp.status_code == 200:
                    print(f"  {green('✓')} {name:20} {green('Підключено')}")
                else:
                    print(f"  {red('✗')} {name:20} {red(f'Помилка {resp.status_code}')}")
        except Exception as e:
            print(f"  {red('✗')} {name:20} {red(str(e)[:50])}")

    # Перевірка Ollama
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get("http://localhost:11434/api/tags")
            models = [m["name"] for m in resp.json().get("models",[])]
            print(f"  {green('✓')} {'Ollama LLM':20} {green('Активний')} {gray(str(models))}")
    except:
        print(f"  {red('✗')} {'Ollama LLM':20} {red('Недоступний')}")

    # Перевірка Docker сервісів
    import subprocess
    try:
        result = subprocess.run(["docker","compose","ps","--format","json"],
            capture_output=True, text=True, cwd=os.path.dirname(__file__))
        services = json.loads(f"[{result.stdout.strip().replace(chr(10),',')}]") if result.stdout.strip() else []
        for s in services:
            name = s.get("Name","").replace("agent_","")
            state = s.get("State","")
            if state == "running":
                print(f"  {green('✓')} {name:20} {green('running')}")
            else:
                print(f"  {red('✗')} {name:20} {red(state)}")
    except:
        pass

def main():
    args = sys.argv[1:]
    if not args:
        print(bold(cyan("\n╔══════════════════════════════╗")))
        print(bold(cyan("║     AGENT SYSTEM CLI v1.0    ║")))
        print(bold(cyan("╚══════════════════════════════╝")))
        print()
        print("Команди:")
        cmds = [
            ("status",          "Статус всіх агентів і системи"),
            ("cmd \"текст\"",    "Відправити команду оркестратору"),
            ("chat",            "Інтерактивний чат з оркестратором"),
            ("logs [агент]",    "Переглянути логи"),
            ("queues",          "Стан черг завдань"),
            ("alerts",          "Сповіщення системи"),
            ("skills [агент]",  "Список скілів"),
            ("skill create",    "Створити новий скіл"),
            ("marketplace",     "Перевірити підключення"),
        ]
        for cmd, desc in cmds:
            print(f"  {green(cmd):30} {gray(desc)}")
        print()
        return

    cmd = args[0].lower()

    if cmd == "status":
        print_status()
    elif cmd == "cmd" and len(args) > 1:
        send_command(" ".join(args[1:]))
    elif cmd == "chat":
        interactive_chat()
    elif cmd == "logs":
        agent = args[1] if len(args) > 1 else None
        print_logs(agent)
    elif cmd == "queues":
        print_queues()
    elif cmd == "alerts":
        print_alerts()
    elif cmd == "skills":
        agent = args[1] if len(args) > 1 else None
        print_skills(agent)
    elif cmd == "skill" and len(args) > 1 and args[1] == "create":
        create_skill_interactive()
    elif cmd == "marketplace":
        asyncio.run(check_marketplaces())
    else:
        print(red(f"Невідома команда: {cmd}"))
        print(gray("Запусти без аргументів для списку команд"))

if __name__ == "__main__":
    main()
