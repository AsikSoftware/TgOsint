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


def test_aea_decryptor_parses():
    """Расшифровщик .dmg.aea — тоже рабочий инструмент: обязан разбираться и держать метки
    HKDF из эталона blacktop/ipsw (на них посегментно держится расшифровка) и свой API."""
    дерево, текст = _разобрать("aea.py")
    assert isinstance(дерево, ast.Module)
    for метка in ("AEA_AMK", "AEA_RHEK", "AEA_CK", "AEA_CHEK", "AEA_SK"):
        assert метка in текст, метка
    for имя in ("разобрать_auth", "ключ_из_полей", "корневой_заголовок", "идти_по_сегментам"):
        assert имя in текст, имя
    # HPKE-развёртка ключа и проверка по HMAC — обе должны остаться в коде
    assert "HPKE-v1" in текст and "compare_digest" in текст


def test_scanner_wired_to_aea_decryptor():
    """Сканер прошивок должен уметь звать расшифровщик на .dmg.aea, а не молча их пропускать."""
    _, текст = _разобрать("прошивка.py")
    assert "import aea" in текст
    assert ".dmg.aea" in текст and "зашифрованный(" in текст
