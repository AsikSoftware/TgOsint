# -*- coding: utf-8 -*-
"""pintel-doctor — консольный «врач»: читает телефон, пишет слепок и отчёт.

  pintel-doctor selfcheck                 окружение: драйвер, pymobiledevice3, конфиг
  pintel-doctor wait                      ждать телефон, показывать состояние кабеля
  pintel-doctor snapshot [--out DIR] [--apple SEC] [--sickw]
                                          полный слепок + отчёт (+ история Apple, + Sickw)
  pintel-doctor report FILE.snapshot.json пересчитать отчёт из слепка
  pintel-doctor apple [--seconds N]       только история обслуживания Apple
  pintel-doctor sickw IMEI|balance        проверка по внешней базе / баланс ключа
  pintel-doctor price                     забрать прайс из Google Таблицы, показать сводку
  pintel-doctor fixtures                  отчёты по архивным слепкам (регрессия)

Конфиг: config.toml рядом с программой или --config путь.
"""
import argparse, asyncio, json, os, sys, time, tomllib
from datetime import datetime

from . import __version__
from .analysis import report as report_mod
from .devicelink import connect, repair_history, snapshot
from .external import gsheet, pricing, sickw

if os.name == "nt":
    os.system("chcp 65001 >nul 2>&1")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def say(*a):
    print(*a, flush=True)


# ---------- конфиг ----------

def app_dir():
    return os.path.dirname(sys.executable) if getattr(sys, "frozen", False) \
        else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_config(path=None):
    p = path or os.path.join(app_dir(), "config.toml")
    cfg = {}
    if os.path.isfile(p):
        cfg = tomllib.load(open(p, "rb"))
        cfg["_path"] = p
    g = (cfg.get("price") or {}).get("gservice_json")
    if g:
        if not os.path.isabs(g):
            g = os.path.join(os.path.dirname(p), g)
        gsheet.set_service_account(g)
    return cfg


def out_dir(base, serial):
    d = os.path.join(base or os.path.join(app_dir(), "out"),
                     f"{datetime.now():%Y%m%d_%H%M%S}_{(serial or 'phone')[:12]}")
    os.makedirs(d, exist_ok=True)
    return d


# ---------- печать отчёта ----------

def fmt_report(rep):
    p, b, s, l = rep["паспорт"], rep["батарея"], rep["память"], rep["правовой"]
    L = ["═" * 64,
         f"  {p['модель']}  ·  {s['объём_гб'] or '?'} ГБ  ·  iOS {p['ios'] or '?'}  ·  "
         f"{p['номер_модели'] or '—'} ({p['регион'] or 'регион ?'})",
         f"  серийный {p['серийник'] or '—'}  IMEI {p['imei'] or '—'}  плата {p['серийник_платы'] or '—'}",
         f"  цвет {p.get('цвет') or 'по кабелю не читается'}  ·  выпуск {p.get('выпуск') or 'в серийнике не закодирован'}"
         f"  ·  {p.get('sim') or 'SIM ?'}{' + eSIM-профиль' if p.get('esim') else ''}",
         f"  Wi-Fi {p.get('wifi_mac') or '—'}  BT {p.get('bluetooth_mac') or '—'}  сотовый {p.get('cellular_mac') or '—'}",
         "═" * 64,
         f"  ИТОГ: {rep['итог']['вердикт']} — {rep['итог']['почему']}", ""]
    L.append(f"  Батарея: здоровье {b['здоровье_%']}% ({b['ёмкость_мАч']}/{b['заводская_мАч']} мА·ч), "
             f"{b['циклы']} циклов, серийник {b['серийник'] or '—'}, шлейф снимали {b['снятий_шлейфа']} раз")
    for f in b["подделка"]:
        L.append(f"    ⛔ {f}")
    nandv = " ".join(x for x in (s.get("nand_производитель"), s.get("nand_тип")) if x)
    L.append(f"  Память: {s['объём_гб']} ГБ {nandv} (контроллер {s['nvme_модель'] or '—'} / {s['nvme_объём_гб'] or '?'} ГБ), "
             f"занято {s['занято_гб']} ГБ ({s['занято_%']}%), свободно {s['свободно_гб']} ГБ"
             + ("" if s["объём_сошёлся"] is not False else "  ⛔ ОБЪЁМ НЕ СХОДИТСЯ"))
    nd = rep.get("nand") or {}
    if nd:
        L.append(f"  NANDInfo: записей {nd['записей']}, остаток {nd['остаток_байт']} байт, "
                 f"прошивка {nd['прошивка']} (совпала с NVMe: {nd['прошивка_совпала_с_nvme']})")
    L.append(f"  Статусы: Найти iPhone — {l['найти_iphone']}; активация — {l['активация'] or '?'}; "
             f"пароль — {'стоит' if l['пароль'] else 'нет'}; MDM — {'ЕСТЬ' if l['mdm'] else 'нет'}")
    L.append("  Сигналы сопряжения:")
    for name, sg in rep["сигналы"].items():
        mark = "✓" if sg["ок"] is True else ("✗" if sg["ок"] is False else "·")
        L.append(f"    {mark} {name}: {sg['почему']}")
    if rep.get("детали"):
        L.append("  Серийники деталей (дата выпуска из серийника):")
        for d in rep["детали"]:
            extra = " · ".join(x for x in (d.get("дата"), d.get("производитель"), d.get("фабрика")) if x)
            L.append(f"    {d['деталь']:<22} {d['серийник']:<26} {extra}")
    ah = rep.get("apple_история")
    if ah:
        L.append("  История обслуживания Apple:")
        for v in sorted(ah.values(), key=lambda x: x.get("код", 0)):
            L.append(f"    {'✗' if v['меняли'] else '✓'} {v['деталь']}: " + (
                ("МЕНЯЛИ — " + ("б/у" if v["бу"] else "новая") + (" · " + v["дата"] if v["дата"] else ""))
                if v["меняли"] else "не меняли"))
    sk = rep.get("sickw")
    if sk:
        na = "услуга не отдаёт"
        srv = ",".join(str(x) for x in (sk.get("службы") or [sk.get("служба")]) if x)
        L.append(f"  Sickw (службы {srv or '?'}{', из кэша' if sk.get('из_кэша') else ''}): "
                 f"{sk.get('описание') or sk.get('модель_строка') or '?'}; цвет {sk.get('цвет') or '?'}; "
                 f"оператор {sk.get('оператор') or na}; sim-lock {sk.get('sim_lock') or na}")
        L.append(f"         гарантия: {sk.get('гарантия') or na}; покупка {sk.get('дата_покупки') or '?'} "
                 f"({sk.get('страна_покупки') or '?'}); чёрный список: {sk.get('чёрный_список') or na}; "
                 f"«Найти iPhone»: {sk.get('icloud') or na}")
        for s, e in (sk.get("ошибки_служб") or {}).items():
            L.append(f"         служба {s} не ответила: {e}")
    L.append(f"  Джейлбрейк: {rep.get('джейлбрейк')}; MobileGestalt: {rep.get('mobilegestalt')}"
             + (f"; цвет корпуса по коду {rep['паспорт'].get('код_цвета_корпуса')}: {rep['паспорт'].get('цвет_по_коду')}"
                if rep["паспорт"].get("код_цвета_корпуса") is not None else ""))
    pr = rep.get("цена")
    if pr:
        L.append(f"  ЦЕНА: {pr['цена'] if pr['цена'] else '—'} {pr['валюта']}  {pr['основание']}  "
                 + " ".join(pr["нехватка"]))
    for k, items in (("СТОП", rep["стоп"]), ("СДЕЛАТЬ", rep["сделать"]),
                     ("ВНИМАНИЕ", rep["внимание"]), ("НЕ ПРОЧИТАЛОСЬ", rep["не_прочиталось"])):
        for x in items:
            L.append(f"  [{k}] {x}")
    q = rep.get("качество_чтения") or {}
    if q and "время_с" in q:
        L.append(f"  Качество чтения: повторов {len(q.get('повторы', {}))}, устарело {q.get('устарело')}, "
                 f"не прочиталось {list(q.get('не_прочиталось', {}))[:6]}, время {q.get('время_с')}")
    L.append("═" * 64)
    return "\n".join(L)


# ---------- команды ----------

def cmd_selfcheck(args, cfg):
    import pymobiledevice3
    try:
        from importlib.metadata import version as _v
        pmd = _v("pymobiledevice3")
    except Exception:
        pmd = "в сборке"
    say(f"pintel-doctor {__version__}, pymobiledevice3 {pmd}, "
        f"Python {sys.version.split()[0]}")
    say(f"конфиг: {cfg.get('_path') or 'НЕ НАЙДЕН (config.toml рядом с программой)'}")
    say(f"ключ Sickw: {'есть' if (cfg.get('sickw') or {}).get('key') else 'нет'}; "
        f"gservice.json: {'есть' if os.path.isfile(gsheet.sa_path()) else 'нет'}")
    st, detail, devs = asyncio.run(connect.list_usb())
    say(f"кабель/драйвер: {st} — {connect.HUMAN[st]} {detail}")
    if devs:
        say("устройства на USB:", [d.serial for d in devs])
    return 0


def cmd_wait(args, cfg):
    st = asyncio.run(connect.wait_ready(
        on_status=lambda s: say(f"[{time.strftime('%H:%M:%S')}] {s.state}: {s.human}")))
    say("готово:", st.serial, st.timings)
    return 0


async def _snapshot(args, cfg):
    st = await connect.wait_ready(
        on_status=lambda s: say(f"[{time.strftime('%H:%M:%S')}] {s.state}: {s.human}"))
    ld = st.lockdown
    t0 = time.monotonic()
    say("открываю диагностику…")
    diag, tries = await connect.open_diagnostics(ld)
    say(f"  диагностика готова с {tries}-й попытки, {time.monotonic() - t0:.1f} с")
    snap = await snapshot.collect(ld, diag, log=lambda m: say("  " + m))
    snap["quality"]["диагностика_попыток"] = tries
    snap["quality"]["подключение"] = st.timings
    try:
        await diag.close()
    except Exception:
        pass

    rep = report_mod.build(snap)
    d = out_dir(args.out, rep["паспорт"]["серийник"] or st.serial)
    open(os.path.join(d, "snapshot.json"), "w", encoding="utf-8").write(snapshot.dumps(snap))

    if args.apple:
        say(f"\n  На телефоне: Настройки → Основные → Об этом устройстве → ЗАЙДИТЕ в "
            f"«Запчасти и история обслуживания». Слушаю {args.apple} с…")
        items, raw, waited = await repair_history.capture(ld, seconds=args.apple)
        say(f"  история Apple: {'получена' if items else 'не появилась'} за {waited} с")
        snap["repair_history"] = items
        snap["repair_history_raw"] = raw
        open(os.path.join(d, "snapshot.json"), "w", encoding="utf-8").write(snapshot.dumps(snap))
        rep = report_mod.build(snap)

    if args.sickw and (cfg.get("sickw") or {}).get("key"):
        imei = rep["паспорт"]["imei"]
        if sickw.luhn_ok(imei):
            say("  Sickw…")
            try:
                snap["sickw"] = sickw.lookup_many(imei, cfg["sickw"]["key"], sickw_services(cfg, args),
                                                  cache_dir=os.path.join(app_dir(), "out", "sickw_cache"))
                for s, e in (snap["sickw"].get("ошибки_служб") or {}).items():
                    say(f"  Sickw: служба {s} не ответила: {e}")
                open(os.path.join(d, "snapshot.json"), "w", encoding="utf-8").write(snapshot.dumps(snap))
                rep = report_mod.build(snap)
            except Exception as e:
                rep["sickw_ошибка"] = str(e)
                say("  Sickw не ответил:", e)
        else:
            say("  Sickw пропущен: IMEI не прочитался")

    grid_path = os.path.join(app_dir(), "out", "price_grid.json")
    if os.path.isfile(grid_path):
        g = json.load(open(grid_path, encoding="utf-8"))
        b = rep["батарея"]
        rep["цена"] = pricing.estimate(g, rep["паспорт"]["код_модели"], rep["память"]["объём_гб"],
                                       b["здоровье_%"], b["циклы"])

    open(os.path.join(d, "report.json"), "w", encoding="utf-8").write(
        json.dumps(rep, ensure_ascii=False, indent=1, default=str))
    text = fmt_report(rep)
    open(os.path.join(d, "report.txt"), "w", encoding="utf-8").write(text)
    say("\n" + text)
    say(f"\nфайлы: {d}")
    try:
        await ld.close()
    except Exception:
        pass
    return 0


def cmd_snapshot(args, cfg):
    return asyncio.run(_snapshot(args, cfg))


def cmd_report(args, cfg):
    snap = snapshot.loads(open(args.file, encoding="utf-8").read())
    say(fmt_report(report_mod.build(snap)))
    return 0


async def _apple(args, cfg):
    st = await connect.wait_ready(on_status=lambda s: say(s.human))
    say(f"Слушаю {args.seconds} с. На телефоне: Настройки → Основные → Об этом устройстве → "
        f"зайдите в «Запчасти и история обслуживания» (если открыто — выйдите и зайдите снова).")
    items, raw, waited = await repair_history.capture(st.lockdown, seconds=args.seconds)
    say(json.dumps(items, ensure_ascii=False, indent=1) if items else f"ничего не пришло за {waited} с")
    return 0 if items else 1


def cmd_apple(args, cfg):
    return asyncio.run(_apple(args, cfg))


def sickw_services(cfg, args=None):
    """Какие услуги Sickw дёргать: --service N (можно несколько) > config.toml > 61."""
    s = getattr(args, "service", None)
    if not s:
        sc = cfg.get("sickw") or {}
        s = sc.get("services") or ([sc["service"]] if sc.get("service") else None)
    try:
        return [int(x) for x in (s or sickw.DEFAULT_SERVICES)]
    except (TypeError, ValueError):
        say(f"  [sickw] services в config.toml непонятны ({s!r}) — беру {list(sickw.DEFAULT_SERVICES)}")
        return list(sickw.DEFAULT_SERVICES)


def cmd_sickw(args, cfg):
    key = (cfg.get("sickw") or {}).get("key")
    if not key:
        say("нет ключа Sickw в config.toml"); return 2
    if args.imei == "balance":
        say(json.dumps(sickw.balance(key), ensure_ascii=False)); return 0
    services = sickw_services(cfg, args)
    say(f"  службы Sickw: {services}{' (без кэша)' if args.fresh else ''}")
    r = sickw.lookup_many(args.imei, key, services,
                          cache_dir=os.path.join(app_dir(), "out", "sickw_cache"), use_cache=not args.fresh)
    for s, raw in (r.get("сырые_ответы") or {}).items():
        say(f"\n  ── сырой ответ службы {s} ──")
        for line in sickw.raw_lines(raw):
            say("   ", line)
    for s, e in (r.get("ошибки_служб") or {}).items():
        say(f"\n  служба {s} не ответила: {e}")
    say("\n  ── разбор ──")
    say(json.dumps({k: v for k, v in r.items() if k not in ("все_поля", "сырые_ответы")},
                   ensure_ascii=False, indent=1))
    return 0


def cmd_price(args, cfg):
    g = gsheet.fetch_grid((cfg.get("price") or {}).get("sheet_url"))
    os.makedirs(os.path.join(app_dir(), "out"), exist_ok=True)
    json.dump(g, open(os.path.join(app_dir(), "out", "price_grid.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    say(f"прайс: {g['моделей']} моделей, {g['позиций']} позиций, источник {g['источник']}, "
        f"сетка по износу: {g['по_износу']}")
    for u in g["не_распознано"]:
        say("  •", u)
    return 0


def cmd_fixtures(args, cfg):
    sys.path.insert(0, os.path.join(app_dir(), "tests"))
    try:
        from fixtures import INVENTORIES, load_snapshot
    except ImportError:
        say("архивные слепки не найдены (папка data/inventories)"); return 1
    for p in INVENTORIES:
        say(fmt_report(report_mod.build(load_snapshot(p))))
    return 0


# ---------- меню для запуска двойным щелчком ----------

class _A:
    """Аргументы для команд, когда их задаёт меню, а не командная строка."""
    def __init__(self, **kw):
        self.out = None; self.apple = 0; self.sickw = False; self.fresh = False; self.service = None
        self.file = None; self.seconds = 120; self.imei = None
        self.__dict__.update(kw)


def first_run_config(cfg):
    """Нет config.toml — создаём его диалогом, чтобы не править файлы руками."""
    if cfg.get("_path"):
        return cfg
    path = os.path.join(app_dir(), "config.toml")
    say("Первый запуск: создаю config.toml рядом с программой.")
    key = input("  Ключ Sickw (Enter — пропустить): ").strip()
    gs = os.path.join(app_dir(), "gservice.json")
    say(f"  gservice.json: {'найден' if os.path.isfile(gs) else 'положите рядом с программой, когда будет'}")
    with open(path, "w", encoding="utf-8") as f:
        f.write('[sickw]\nkey = "%s"\n# номера услуг Sickw через запятую; 61 = iPhone CARRIER & FMI & BLACKLIST\n'
                'services = [61]\n\n[price]\nsheet_url = "%s"\ngservice_json = "gservice.json"\n'
                % (key, gsheet.DEFAULT_URL))
    say(f"  записан: {path}\n")
    return load_config(path)


def interactive(cfg):
    cfg = first_run_config(cfg)
    menu = """
  ┌──────────────────────────────────────────────────────┐
  │  PINTEL DOCTOR — чтение iPhone по кабелю             │
  ├──────────────────────────────────────────────────────┤
  │  1  Полная проверка телефона (слепок + Apple + Sickw)│
  │  2  Проверка окружения (драйвер, ключи, кабель)      │
  │  3  Обновить прайс из Google Таблицы                 │
  │  4  Баланс ключа Sickw                               │
  │  5  Только история обслуживания Apple                │
  │  6  Слепок без Apple и Sickw (быстро)                │
  │  0  Выход                                            │
  └──────────────────────────────────────────────────────┘"""
    while True:
        say(menu)
        try:
            choice = input("  Выбор: ").strip()
        except EOFError:
            return 0
        try:
            if choice == "1":
                asyncio.run(_snapshot(_A(apple=120, sickw=True), cfg))
                _open_out()
            elif choice == "2":
                cmd_selfcheck(_A(), cfg)
            elif choice == "3":
                cmd_price(_A(), cfg)
            elif choice == "4":
                cmd_sickw(_A(imei="balance"), cfg)
            elif choice == "5":
                asyncio.run(_apple(_A(seconds=120), cfg))
            elif choice == "6":
                asyncio.run(_snapshot(_A(), cfg))
                _open_out()
            elif choice in ("0", "q", ""):
                return 0
            else:
                say("  нет такого пункта")
        except KeyboardInterrupt:
            say("\n  прервано")
        except Exception as e:
            say(f"\n  ОШИБКА: {type(e).__name__}: {e}")
            import traceback
            with open(os.path.join(app_dir(), "doctor_errors.log"), "a", encoding="utf-8") as f:
                f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {choice}\n{traceback.format_exc()}\n")
            say("  подробности — в doctor_errors.log рядом с программой")
        say("")


def _open_out():
    d = os.path.join(app_dir(), "out")
    if os.name == "nt" and os.path.isdir(d):
        try:
            os.startfile(d)
        except Exception:
            pass


COMMANDS = {"selfcheck": cmd_selfcheck, "wait": cmd_wait, "snapshot": cmd_snapshot,
            "report": cmd_report, "apple": cmd_apple, "sickw": cmd_sickw,
            "price": cmd_price, "fixtures": cmd_fixtures}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="pintel-doctor", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", help="путь к config.toml")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("selfcheck")
    sub.add_parser("wait")
    s = sub.add_parser("snapshot")
    s.add_argument("--out")
    s.add_argument("--apple", type=int, default=0, help="секунд слушать историю Apple (0 — не слушать)")
    s.add_argument("--sickw", action="store_true")
    s = sub.add_parser("report"); s.add_argument("file")
    s = sub.add_parser("apple"); s.add_argument("--seconds", type=int, default=120)
    s = sub.add_parser("sickw"); s.add_argument("imei"); s.add_argument("--fresh", action="store_true")
    s.add_argument("--service", type=int, action="append", help="номер услуги Sickw (можно несколько раз)")
    sub.add_parser("price")
    sub.add_parser("fixtures")
    if argv is None:
        argv = sys.argv[1:]
    if not argv:                                   # двойной щелчок по exe
        code = interactive(load_config())
        _pause()
        return code
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    try:
        return COMMANDS[args.cmd](args, cfg)
    except KeyboardInterrupt:
        say("\nпрервано"); return 130


def _pause():
    if os.name == "nt" and getattr(sys, "frozen", False):
        try:
            input("\nНажмите Enter, чтобы закрыть…")
        except EOFError:
            pass


if __name__ == "__main__":
    sys.exit(main())
