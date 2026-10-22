"""Предварительная оценка. Переводит вердикты в поправки к цене.

Цифры берутся из prices.json и ЗАГЛУШЕЧНЫЕ: прайс магазина я не выдумываю,
ошибка в базовой цене дороже ошибки в диагностике. Движок считает честно
по тому, что заполнено, и прямо говорит, чего не хватает.
"""
import json, os
from .paths import writable

# Прайс магазин редактирует, значит он должен лежать РЯДОМ с программой,
# а не внутри неё. При первом запуске образец выкладывается наружу.
def cfg_path():
    return writable("prices.json", "prices.json")


def load():
    return json.load(open(cfg_path(), encoding="utf-8"))


def _pick_gb(tbl, gb):
    """Ключ объёма с округлением к ближайшей известной ступени: телефон
    рапортует 128, а в прайсе может стоять 127 или 256*10^9//10^9=256."""
    if not tbl:
        return None
    if gb in tbl:
        return gb
    try:
        want = int(gb)
        best = min(tbl, key=lambda k: abs(int(k) - want))
        if abs(int(best) - want) <= max(8, want * 0.1):
            return best
    except Exception:
        pass
    return None


import re as _re


def _wear_price(grid, wear, cycles):
    """Цена из сетки износа: (цена|None, ключ|None). Ключ без цены означает
    «диапазон в прайсе есть, но магазин не задал цену» — это стоп-сигнал."""
    if not grid:
        return None, None
    if wear is None:
        k = "неизвестно"
        return (grid.get(k), k) if k in grid else (None, None)
    if wear >= 100:
        if cycles is not None and cycles <= 30 and "100новый" in grid:
            return grid["100новый"], "100новый"
        if "100" in grid:
            return grid["100"], "100"
        return None, None
    for k, v in grid.items():
        m = _re.match(r"^(\d+)-(\d+)$", k)
        if m and int(m.group(1)) <= wear <= int(m.group(2)):
            return v, k
    return None, None


def estimate(res, sick=None, apple=None):
    cfg = load()
    cur = cfg.get("валюта", "₸")
    d = cfg["вычеты"]
    pt = res["паспорт"]["код_модели"]
    gb = str(res["паспорт"]["память_гб"] or "")
    base_tbl = cfg["база"].get(pt, {})
    gb_key = _pick_gb(base_tbl, gb)
    base = base_tbl.get(gb_key) if gb_key else None

    lines, refuse, lack = [], [], []

    # --- сетка износа: магазин сам задал цену за каждый диапазон батареи ---
    # Если она есть и даёт цену — берём её КАК БАЗУ и не применяем вычеты
    # за износ (иначе батарея была бы посчитана дважды).
    wear_used = False
    wg = cfg.get("сетка_износа", {}).get(pt, {})
    wg_key = _pick_gb(wg, gb)
    grid = wg.get(wg_key) if wg_key else None
    if grid:
        w = res["батарея"]["износ"]
        p, k = _wear_price(grid, w, res["батарея"]["циклы"])
        if p:
            base = p
            wear_used = True
            if k and k != "100новый":
                lines.append((f"батарея {w if w is not None else '?'}% — "
                              f"цена прайса за «{k}»", 0))
        elif k:          # диапазон есть, но магазин не задал для него цену
            base = None
            what = (f"износа {w}%" if w is not None
                    else "аппарата, у которого износ не определился")
            lack.append(f"прайс не задаёт цену для {what} "
                        f"(столбец «{k}» пуст) — согласуй с руководителем")

    # --- отказы: цену не считаем вообще ---
    if sick and str(sick.get("чёрный_список", "")).strip().upper() not in ("", "CLEAN", "CLEAR"):
        refuse.append(cfg["отказ"]["чёрный_список"] + f" ({sick['чёрный_список']})")
    if res["юридический"]["mdm"]:
        refuse.append(cfg["отказ"]["mdm"])
    if res["юридический"]["каналы_сошлись"] is False:
        refuse.append(cfg["отказ"]["данные_подменены"])

    # --- вычеты по состоянию ---
    bat = res["батарея"]
    if not wear_used:
        if bat["износ"] is not None:
            if bat["износ"] < 80:
                lines.append(("износ батареи %d%%" % bat["износ"], d["износ_батареи_ниже_80"]))
            elif bat["износ"] < 85:
                lines.append(("износ батареи %d%%" % bat["износ"], d["износ_батареи_ниже_85"]))
    if bat["циклы"] and bat["циклы"] > 800:
        lines.append(("%d циклов" % bat["циклы"], d["циклов_больше_800"]))

    MAP = {
        "Батарея": ("батарея_неоригинал", "батарея неоригинальная"),
        "Экран": ("экран_заменён", "экран заменён"),
        "Основная камера": ("камера_заменена", "основная камера заменена"),
        "Сверхширокая": ("камера_заменена", "сверхширокая заменена"),
        "Телефото": ("камера_заменена", "телефото заменена"),
        "Face ID": ("face_id_заменён", "Face ID заменён"),
        "Taptic Engine": ("taptic_заменён", "Taptic заменён"),
    }
    for lbl, pv in res["детали"].items():
        v = pv["вердикт"]
        if lbl not in MAP:
            continue
        kk, text = MAP[lbl]
        if v.startswith(("ЗАМЕН", "НЕОРИГ")):
            lines.append((text, d.get(kk, 0)))
        elif v == "ПОД ВОПРОСОМ" and lbl == "Экран":
            lines.append(("экран под вопросом", d["экран_под_вопросом"]))

    # --- вердикт Apple: он авторитетнее моих правил ---
    if apple:
        AP = {"BackGlass": ("заднее_стекло_заменено", "заднее стекло заменено"),
              "Enclosure": ("корпус_заменён", "корпус заменён"),
              "LogicBoard": ("плата_заменена", "материнская плата заменена")}
        seen = {t for t, _ in lines}
        for comp, v in apple.items():
            if not v["меняли"]:
                continue
            if comp in AP:
                kk, text = AP[comp]
                lines.append((text + " (по Apple)", d.get(kk, 0)))
            if v["бу"]:
                lines.append((f"{v['деталь'].lower()}: поставлена б/у деталь (по Apple)",
                              d["деталь_бу_по_apple"]))

    # --- сверка объёма с внешней базой: ловит перепайку памяти ---
    if sick and sick.get("объём_гб") and res["паспорт"]["память_гб"]:
        want, have = sick["объём_гб"], res["паспорт"]["память_гб"]
        if abs(want - have) > max(8, want * 0.1):
            lines.append((f"память перепаяна: завод {want} ГБ, аппарат {have} ГБ",
                          d["память_перепаяна"]))

    total = (base or 0) + sum(v for _, v in lines)
    if base is None and not lack:
        lack.append(f"нет базовой цены для {pt} / {gb} ГБ — обнови прайс из таблицы")
    return {
        "валюта": cur,
        "база": base,
        "база_известна": base is not None,
        "вычеты": [{"за_что": t, "сумма": v} for t, v in lines if v or "цена прайса" in t],
        "итого": max(0, total) if base is not None else None,
        "отказ": refuse,
        "чего_не_хватает": [] if base is not None else lack,
    }
