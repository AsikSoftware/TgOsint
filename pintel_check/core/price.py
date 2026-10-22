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


def estimate(res, sick=None, apple=None):
    cfg = load()
    cur = cfg.get("валюта", "₸")
    d = cfg["вычеты"]
    pt = res["паспорт"]["код_модели"]
    gb = str(res["паспорт"]["память_гб"] or "")
    base_tbl = cfg["база"].get(pt, {})
    # Объём округляем к ближайшей известной ступени: телефон рапортует 128,
    # а в прайсе может стоять 128 — но бывает 127 или 256000000000/10^9=256.
    base = base_tbl.get(gb)
    if base is None and base_tbl:
        try:
            want = int(gb)
            best = min(base_tbl, key=lambda k: abs(int(k) - want))
            if abs(int(best) - want) <= max(8, want * 0.1):
                base = base_tbl[best]
        except Exception:
            base = None

    lines, refuse = [], []

    # --- отказы: цену не считаем вообще ---
    if sick and str(sick.get("чёрный_список", "")).strip().upper() not in ("", "CLEAN", "CLEAR"):
        refuse.append(cfg["отказ"]["чёрный_список"] + f" ({sick['чёрный_список']})")
    if res["юридический"]["mdm"]:
        refuse.append(cfg["отказ"]["mdm"])
    if res["юридический"]["каналы_сошлись"] is False:
        refuse.append(cfg["отказ"]["данные_подменены"])

    # --- вычеты по состоянию ---
    bat = res["батарея"]
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
    return {
        "валюта": cur,
        "база": base,
        "база_известна": base is not None,
        "вычеты": [{"за_что": t, "сумма": v} for t, v in lines],
        "итого": max(0, total) if base is not None else None,
        "отказ": refuse,
        "чего_не_хватает": ([] if base is not None else
                            [f"нет базовой цены для {pt} / {gb} ГБ — заполни prices.json"]),
    }
