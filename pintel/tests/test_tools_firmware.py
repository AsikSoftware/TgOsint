# -*- coding: utf-8 -*-
"""Сканер прошивок — рабочий инструмент, а не черновик: он обязан хотя бы разбираться
и держать список строк, которые мы ищем. Иначе он тихо сгниёт между версиями iOS."""
import ast
import os

КОРЕНЬ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _разобрать(имя):
    путь = os.path.join(КОРЕНЬ, "tools", имя)
    assert os.path.isfile(путь), путь
    return ast.parse(open(путь, encoding="utf-8").read()), open(путь, encoding="utf-8").read()


def test_firmware_scanner_parses():
    дерево, текст = _разобрать("прошивка.py")
    assert "ИГЛЫ" in текст                             # список строк, которые ищем
    assert "зашифрован" in текст and ".aea" in текст    # и честно названное ограничение
    assert isinstance(дерево, ast.Module)


def test_catalog_helper_parses():
    дерево, текст = _разобрать("каталог.py")
    assert "ipsw.me" in текст and isinstance(дерево, ast.Module)


def test_needles_cover_every_known_format():
    """Каждый формат, который мы умеем читать, должен быть в списке поиска — иначе новая
    iOS «потеряет» его молча, и мы этого не увидим."""
    _, текст = _разобрать("прошивка.py")
    for строка in ("systemhealth", "isComponentRepairedUsing", "CRRepairHistoryItem",
                   "CRRepairHistory", "Unsealed", "delta components", "fetched RCHL",
                   "isTrustedForUI", "failed preflight", "AuthCP Components", "Battery Health State"):
        assert строка in текст, строка
