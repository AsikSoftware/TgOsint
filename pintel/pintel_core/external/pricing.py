# -*- coding: utf-8 -*-
"""Цена из сетки магазина по износу батареи (проверено на живом прайсе).

grid = {"база": {код: {гб: цена_идеала}}, "сетка_износа": {код: {гб: {колонка: цена|None}}}}
Колонки — либо диапазоны («0-74», «75-79», … «100», «100новый», «неизвестно»), либо точные
проценты («72%» … «100%»): как размечена таблица, так и считаем.
Пустая ячейка — стоп-сигнал магазина, а не повод считать по-своему.
"""
import re


def _pick_gb(tbl, gb):
    if not tbl:
        return None
    gb = str(gb)
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


def wear_price(cells, health, cycles):
    """(цена|None, ключ|None): ключ без цены = «магазин не задал цену»."""
    if not cells:
        return None, None
    if any(str(k).endswith("%") for k in cells):
        return _exact_price(cells, health)
    if health is None:
        k = "неизвестно"
        return (cells.get(k), k) if k in cells else (None, None)
    if health >= 100:
        if cycles is not None and cycles <= 30 and "100новый" in cells:
            return cells["100новый"], "100новый"
        if "100" in cells:
            return cells["100"], "100"
        return None, None
    for k, v in cells.items():
        m = re.match(r"^(\d+)-(\d+)$", k)
        if m and int(m.group(1)) <= health <= int(m.group(2)):
            return v, k
    return None, None


def _exact_price(cells, health):
    """Сетка по точным процентам. Ключ есть всегда: «нет цены» здесь — это ответ, а не
    повод взять базовую цену идеала (так аппарат с 60% получил бы цену нового)."""
    по_проценту = {int(str(k)[:-1]): v for k, v in cells.items() if str(k).endswith("%")}
    if health is None:
        # процента нет: цена только там, где она от батареи не зависит
        цены = set(по_проценту.values())
        if len(цены) == 1 and None not in цены:
            return цены.pop(), "любой %"
        return None, "нет информации"
    p = min(int(health), 100)
    return по_проценту.get(p), f"{p}%"       # ниже таблицы колонки нет — цены нет


def estimate(grid, code, gb, health, cycles, currency="₸"):
    base_tbl = (grid.get("база") or {}).get(code, {})
    wg = (grid.get("сетка_износа") or {}).get(code, {})
    k = _pick_gb(wg, gb)
    cells = wg.get(k) if k else None
    out = {"валюта": currency, "цена": None, "основание": "", "нехватка": []}
    if cells:
        p, rk = wear_price(cells, health, cycles)
        if p:
            out["цена"] = p
            out["основание"] = ("прайс: 100%, до 30 циклов — как новый" if rk == "100новый"
                                else "прайс: цена от батареи не зависит" if rk == "любой %"
                                else f"прайс: батарея {health}% → столбец «{rk}»")
            return out
        if rk:
            what = f"износа {health}%" if health is not None else "аппарата с нечитаемым износом"
            out["нехватка"].append(f"прайс не задаёт цену для {what} (столбец «{rk}» пуст) — согласовать с руководителем")
            return out
    kb = _pick_gb(base_tbl, gb)
    if kb:
        out["цена"] = base_tbl[kb]
        out["основание"] = "прайс: базовая цена (сетки по износу нет)"
        return out
    out["нехватка"].append(f"в прайсе нет {code} / {gb} ГБ")
    return out
