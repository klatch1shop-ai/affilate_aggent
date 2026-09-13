#!/usr/bin/env python3
"""
tools/watchdog_report_selftest.py — перевірка шестигодинного звіту watchdog.

Навіщо окремий інструмент. Звіт `send_report()` надсилається раз на 6 годин і
лише тоді, коли всі перевірки вже відпрацювали. Побачити його поведінку
«за фактом» означає чекати пів дня і ще й підгадати момент, коли фід зламаний,
— тобто ніколи. Тому звіт збирається тут із підставлених результатів, а
Telegram і файл-позначка часу підмінюються заглушками: жодного повідомлення
власникові й жодного зсуву розкладу справжнього watchdog.

Що саме перевіряється (а не «чи не падає»):
  1. у звіті є рядок по КОЖНОМУ з чотирьох фідів — і в доброму звіті теж;
  2. зламаний фід при цілій решті **знімає** заголовок «Watchdog OK»;
  3. текст причини доїжджає в звіт, а не лише позначка ❌;
  4. наявні перевірки (сервіси, git, cron, sync) не загубились.

**Позитивний контроль вбудований** (`--control`, і він же частина `--all`):
ті самі випадки проганяються проти версії ДО правки (`git show`), і перевірка
ЗОБОВ'ЯЗАНА на ній впасти. Без цього кроку «7/7 пройдено» означало б лише те,
що тест уміє говорити «так»; правило черги 6 і SKILL-21 вимагають доказу, що
він уміє сказати «ні».

Запуск:
    python3 tools/watchdog_report_selftest.py            # усе разом
    python3 tools/watchdog_report_selftest.py --against tools/watchdog.py
Код виходу: 0 — звіт показує фіди й контроль спрацював, 1 — ні.
"""

import argparse
import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_TARGET = REPO / "tools" / "watchdog.py"

FEED_LABELS = ["Єпіцентр NOIRE", "Rozetka NOIRE", "Prom NOIRE", "Carvol → Rozetka"]


# ── завантаження модуля з довільного файлу ───────────────────────────────────

def load_watchdog(path: Path):
    """Імпорт watchdog.py як модуля з підміненими побічними ефектами.

    Модуль на імпорті читає лише `.env` і змінні оточення — мережі й БД не
    чіпає, тож його безпечно піднімати на ноутбуці, де `/home/tek` немає.
    """
    spec = importlib.util.spec_from_file_location(f"wd_{abs(hash(str(path)))}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    sent = []
    mod.tg = lambda msg: sent.append(msg)
    mod.save_report_ts = lambda: None          # не зсуваємо розклад справжнього звіту
    mod.log = lambda msg: None
    mod._sent = sent
    return mod


def build_report(mod, git_r, svc_r, cron_r, sync_r, feeds):
    """Викликає send_report і повертає текст повідомлення.

    Стара сигнатура (до 01.09) приймає лише чотири аргументи — це не збій
    інструмента, а саме та відсутність, яку ми й ловимо. Тому TypeError
    перетворюється на зрозумілий текст, а не на traceback.
    """
    mod._sent.clear()
    try:
        mod.send_report(git_r, svc_r, cron_r, sync_r, *feeds)
    except TypeError as e:
        return f"<<TypeError: {e}>>"
    return mod._sent[0] if mod._sent else "<<повідомлення не надіслано>>"


# ── підставні результати перевірок ───────────────────────────────────────────

def ok(msg="feed ok"):
    return {"ok": True, "msg": msg}


def bad(msg):
    return {"ok": False, "msg": msg}


GREEN_SVC = {"ok": True,
             "services": {"rozetka-order-agent": True, "tg-dispatcher": True,
                          "noire-notifier": True},
             "restarted": [], "failed": []}
RED_SVC = {"ok": False,
           "services": {"rozetka-order-agent": True, "tg-dispatcher": False,
                        "noire-notifier": True},
           "restarted": [], "failed": ["tg-dispatcher"]}
GREEN_FEEDS = (ok(), ok(), ok(), ok())


def cases():
    """Перелік випадків: (назва, аргументи, перевірка тексту → список помилок).

    Випадки 5-7 навмисно очікують ВІДСУТНІСТЬ ознаки: перевірка, яка вміє лише
    знаходити, на порожньому місці теж скаже «знайшов».
    """
    return [
        ("1. усе зелене — фіди все одно перелічені",
         (ok("clean"), GREEN_SVC, ok("ok"), ok("07:15 ok"), GREEN_FEEDS),
         lambda m: (
             ["немає заголовка «Watchdog OK»"] * ("Watchdog OK" not in m)
             + ["немає блоку «Фіди:»"] * ("Фіди:" not in m)
             + [f"немає рядка «{l}»" for l in FEED_LABELS if l not in m]
             + ["фід позначено ❌ у зеленому випадку"] * (m.count("❌") > 0)
         )),

        ("2. зламаний фід Rozetka при цілій решті знімає «OK»",
         (ok("clean"), GREEN_SVC, ok("ok"), ok("07:15 ok"),
          (ok(), bad("фід Rozetka не оновлювався 9 год"), ok(), ok())),
         lambda m: (
             ["заголовок лишився «Watchdog OK» над зламаним фідом"]
             * ("Watchdog OK" in m)
             + ["немає позначки тривоги 🚨"] * ("🚨" not in m)
             + ["немає рядка «Rozetka NOIRE»"] * ("Rozetka NOIRE" not in m)
             + ["причину не видно у звіті"] * ("не оновлювався 9 год" not in m)
             + [f"зник рядок «{l}»" for l in FEED_LABELS if l not in m]
         )),

        ("3. недоставлена публікація Carvol видно у звіті",
         (ok("clean"), GREEN_SVC, ok("ok"), ok("07:15 ok"),
          (ok(), ok(), ok(), bad("опублікована версія Carvol старша за 26 год (33)"))),
         lambda m: (
             ["заголовок лишився «Watchdog OK»"] * ("Watchdog OK" in m)
             + ["причину не видно у звіті"] * ("старша за 26 год" not in m)
             + ["немає рядка «Carvol → Rozetka»"] * ("Carvol → Rozetka" not in m)
         )),

        ("4. сервіс упав І фід зламаний — обидві причини у звіті",
         (ok("clean"), RED_SVC, ok("ok"), ok("07:15 ok"),
          (ok(), ok(), bad("локального фіду Prom немає"), ok())),
         lambda m: (
             ["немає впалого сервісу"] * ("tg-dispatcher" not in m)
             + ["немає причини по фіду Prom"] * ("локального фіду Prom немає" not in m)
             + ["немає блоку «Фіди:»"] * ("Фіди:" not in m)
         )),

        ("5. зламаний git при зелених фідах — фіди лишаються ✅",
         (bad("commit failed"), GREEN_SVC, ok("ok"), ok("07:15 ok"), GREEN_FEEDS),
         lambda m: (
             ["немає причини по git"] * ("git sync" not in m)
             + ["фіди зникли з поганого звіту"] * ("Фіди:" not in m)
             + ["фід позначено ❌, хоч усі чотири зелені"] * (m.count("❌ Єпіцентр") > 0)
             + [f"зник рядок «{l}»" for l in FEED_LABELS if l not in m]
         )),

        ("6. зелений звіт не вигадує тривоги (контроль порожнечі)",
         (ok("clean"), GREEN_SVC, ok("ok"), ok("07:15 ok"), GREEN_FEEDS),
         lambda m: (
             ["у зеленому звіті з'явилась позначка тривоги 🚨"] * ("🚨" in m)
             + ["у зеленому звіті з'явилось слово «git sync»"] * ("git sync" in m)
         )),

        ("7. наявні перевірки не загубились (сервіси й sync)",
         (ok("clean"), GREEN_SVC, ok("ok"), ok("07:15 ok"), GREEN_FEEDS),
         lambda m: (
             [f"немає сервісу {s}" for s in GREEN_SVC["services"] if s not in m]
             + ["немає позначки sync"] * ("sync" not in m)
         )),
    ]


def run_suite(mod, verbose=True) -> list:
    """Проганяє всі випадки. Повертає перелік провалів (назва, причини)."""
    failures = []
    for name, args, check in cases():
        msg = build_report(mod, *args)
        problems = check(msg)
        if problems:
            failures.append((name, problems, msg))
            if verbose:
                print(f"  ❌ {name}")
                for p in problems:
                    print(f"       {p}")
        elif verbose:
            print(f"  ✅ {name}")
    return failures


def live_report(mod) -> str:
    """Текст звіту з РЕАЛЬНОГО стану машини — без надсилання й без наслідків.

    Підставні випадки доводять, що звіт уміє показати фід. Вони не доводять,
    що він показує СЬОГОДНІШНІЙ фід: між ними стоять справжні перевірки, які
    у випадках підмінені. Тому тут викликаються самі перевірки — і звіт
    збирається з того, що вони повернули.

    Що знешкоджено, щоб прогін лишався читанням:
      * `check_git()` не викликається взагалі — він робить авто-коміт;
      * `check_services()` замінено на `is-active` без перезапуску;
      * файли-прапорці дедуплікації переставлено у тимчасову теку, інакше цей
        прогін «погасив» би тривогу, яку справжній watchdog ще не надіслав;
      * `tg()` і `save_report_ts()` уже заглушені — ні повідомлення, ні зсуву
        шестигодинного розкладу.
    """
    tmp = Path(tempfile.mkdtemp())
    for name in ("NOIRE_FLAG", "NOIRE_RZ_FLAG", "NOIRE_PROM_FLAG",
                 "CARVOL_RZ_FLAG", "SYNC_ERROR_FLAG", "CRON_FLAG",
                 "RZ_FEEDBACK_SEEN"):
        if hasattr(mod, name):
            setattr(mod, name, str(tmp / name))

    rc, out, _ = mod.run("git status --porcelain")
    git_r = {"ok": rc == 0, "msg": "clean" if not out else f"{len(out.splitlines())} файлів"}

    services = {}
    for svc in mod.SERVICES:
        _, act, _ = mod.run(f"systemctl --user is-active {svc}")
        services[svc] = act.strip() == "active"
    svc_r = {"ok": all(services.values()), "services": services,
             "restarted": [], "failed": [s for s, a in services.items() if not a]}

    cron_r = mod.check_cron()
    sync_r = mod.check_sync_log()
    feeds = (mod.check_noire_feed(), mod.check_noire_rozetka_feed(),
             mod.check_noire_prom_feed(), mod.check_carvol_rozetka_feed())

    return build_report(mod, git_r, svc_r, cron_r, sync_r, feeds)


def control_old_text(mod) -> list:
    """Що САМЕ друкувала стара версія — її ж власною сигнатурою.

    Проганяти старий модуль вісьмома аргументами замало: він падає на
    TypeError, і «перевірка провалилась» тоді доводить лише те, що змінився
    підпис функції. Тому тут стара `send_report` викликається чотирма
    аргументами, як її й викликав старий `main()`, і читається текст: у ньому
    має стояти «Watchdog OK» і не має бути ЖОДНОГО згадування фідів — саме та
    відповідь, яку звіт давав над зламаним фідом.

    Повертає перелік розбіжностей із цим очікуванням; порожній перелік = стара
    поведінка відтворена й підтверджена.
    """
    mod._sent.clear()
    try:
        mod.send_report(ok("clean"), GREEN_SVC, ok("ok"), ok("07:15 ok"))
    except TypeError as e:
        return [f"стара send_report не приймає й чотирьох аргументів: {e}"]
    msg = mod._sent[0] if mod._sent else ""
    return (
        ["стара версія не дала заголовка «Watchdog OK»"] * ("Watchdog OK" not in msg)
        + ["у старій версії вже є блок «Фіди:» — правка не там"] * ("Фіди:" in msg)
        + [f"у старій версії вже є рядок «{l}»" for l in FEED_LABELS if l in msg]
    )


def head_version() -> Path:
    """Версія watchdog.py до правки — з git, а не з памʼяті."""
    out = subprocess.run(["git", "show", "HEAD:tools/watchdog.py"],
                         cwd=REPO, capture_output=True, text=True)
    if out.returncode != 0 or not out.stdout:
        return None
    tmp = Path(tempfile.mkdtemp()) / "watchdog_head.py"
    tmp.write_text(out.stdout, encoding="utf-8")
    return tmp


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--against", default=str(DEFAULT_TARGET),
                    help="який watchdog.py перевіряти")
    ap.add_argument("--no-control", action="store_true",
                    help="без позитивного контролю (не рекомендовано)")
    ap.add_argument("--control-against", default=None,
                    help="файл із версією ДО правки (типово — git show HEAD)")
    ap.add_argument("--live", action="store_true",
                    help="показати звіт із реального стану машини (нічого не надсилає)")
    a = ap.parse_args()

    target = Path(a.against).resolve()

    if a.live:
        print(f"Звіт із реального стану ({target}), НЕ надіслано:\n")
        print(live_report(load_watchdog(target)))
        return 0

    print(f"Перевіряю звіт: {target}")
    failures = run_suite(load_watchdog(target))
    total = len(cases())
    print(f"\nПройдено {total - len(failures)}/{total}")

    control_ok = True
    if not a.no_control:
        print("\n── позитивний контроль: та сама перевірка проти версії ДО правки ──")
        head = Path(a.control_against) if a.control_against else head_version()
        if head is None:
            print("  ⚠️  git show не дав версії HEAD — контроль не виконано")
            control_ok = False
        else:
            head_mod = load_watchdog(head)
            head_failures = run_suite(head_mod, verbose=False)
            if head_failures:
                print(f"  ✅ на старій версії провалено {len(head_failures)}/{total} "
                      f"випадків — перевірка вміє сказати «ні»")
                for name, problems, _ in head_failures[:3]:
                    print(f"       {name} → {problems[0]}")
            else:
                print("  ❌ стара версія пройшла ВСІ випадки — перевірка нічого "
                      "не міряє, результату «пройдено» вірити не можна")
                control_ok = False

            # Другий шар контролю: відтворити стару поведінку її ж підписом,
            # інакше «провалено 6/7» доводить лише зміну сигнатури.
            drift = control_old_text(head_mod)
            if drift:
                print("  ❌ стару поведінку відтворити не вдалось:")
                for d in drift:
                    print(f"       {d}")
                control_ok = False
            else:
                print("  ✅ стара версія над тими самими даними друкує "
                      "«Watchdog OK» і жодного рядка про фіди — дефект із "
                      "черги відтворено дослівно")

    if failures:
        print("\nЗВІТ НЕ ПОКАЗУЄ ФІДИ ЯК ТРЕБА")
        return 1
    if not control_ok:
        print("\nРЕЗУЛЬТАТ НЕ ЗАРАХОВАНО: позитивний контроль не спрацював")
        return 1
    print("\nOK: звіт перелічує всі чотири фіди й враховує їх у присуді.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
