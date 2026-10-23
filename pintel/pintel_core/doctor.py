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
         "═" * 64,
         f"  ИТОГ: {rep['итог']['вердикт']} — {rep['итог']['почему']}", ""]
    L.append(f"  Батарея: здоровье {b['здоровье_%']}% ({b['ёмкость_мАч']}/{b['заводская_мАч']} мА·ч), "
             f"{b['циклы']} циклов, серийник {b['серийник'] or '—'}, шлейф снимали {b['снятий_шлейфа']} раз")
    for f in b["подделка"]:
        L.append(f"    ⛔ {f}")
    L.append(f"  Память: {s['объём_гб']} ГБ (контроллер {s['nvme_модель'] or '—'} / {s['nvme_объём_гб'] or '?'} ГБ), "
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
    ah = rep.get("apple_история")
    if ah:
        L.append("  История обслуживания Apple:")
        for v in sorted(ah.values(), key=lambda x: x.get("код", 0)):
            L.append(f"    {'✗' if v['меняли'] else '✓'} {v['деталь']}: " + (
                ("МЕНЯЛИ — " + ("б/у" if v["бу"] else "новая") + (" · " + v["дата"] if v["дата"] else ""))
                if v["меняли"] else "не меняли"))
    sk = rep.get("sickw")
    if sk:
        L.append(f"  Sickw: чёрный список {sk['чёрный_список'] or '?'}; модель {sk['модель_строка']}; "
                 f"iCloud {sk['icloud'] or '?'}; гарантия {sk['гарантия'] or '?'}")
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
                rep["sickw"] = sickw.lookup(imei, cfg["sickw"]["key"],
                                            cache_dir=os.path.join(app_dir(), "out", "sickw_cache"))
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


def cmd_sickw(args, cfg):
    key = (cfg.get("sickw") or {}).get("key")
    if not key:
        say("нет ключа Sickw в config.toml"); return 2
    if args.imei == "balance":
        say(json.dumps(sickw.balance(key), ensure_ascii=False)); return 0
    r = sickw.lookup(args.imei, key, cache_dir=os.path.join(app_dir(), "out", "sickw_cache"),
                     use_cache=not args.fresh)
    say(json.dumps({k: v for k, v in r.items() if k != "все_поля"}, ensure_ascii=False, indent=1))
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
    sub.add_parser("price")
    sub.add_parser("fixtures")
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    try:
        return COMMANDS[args.cmd](args, cfg)
    except KeyboardInterrupt:
        say("\nпрервано"); return 130


if __name__ == "__main__":
    sys.exit(main())
