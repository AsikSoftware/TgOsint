# -*- coding: utf-8 -*-
"""Цена из сетки магазина по износу батареи (проверено на живом прайсе).

grid = {"база": {код: {гб: цена_идеала}}, "сетка_износа": {код: {гб: {диапазон: цена|None}}}}
Пустая ячейка диапазона — стоп-сигнал магазина, а не повод считать по-своему.
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
            out["основание"] = (f"прайс: батарея {health}% → столбец «{rk}»" if rk != "100новый"
                                else "прайс: 100%, до 30 циклов — как новый")
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
