# -*- coding: utf-8 -*-
"""Цвет телефона — одним словарём: английское слово заглавными (BLACK, NATURAL, DEEP PURPLE).

Зачем. Цвет касса берёт из базы IMEI (Sickw / Apple GSX) и — редко — из кода корпуса, который
отдаёт сам телефон. Раньше слово из базы переводилось на русский по таблице, а чего в таблице
не было, оставалось как пришло. На 13.11.2026 в боевых проверках так лежало вперемешку:
«чёрный космос», «тёмная ночь», «Blue Ttnm», «Naturl Ttnm», «Bur», «White Cellular», «Org».
Это же слово уходит в сделку Оценки и дальше в название товара МойСклада, где оказывались
«NATURL TTNM» и «SILVER CELLULAR».

Теперь слово одно на всех — в кассе, в чеке, в карточке сделки и в названии товара. Словарь
тот, которым сотрудники уже называют товар в МойСкладе («БУ IP 14 PRO 256 GB 86% BLACK (K)»):
короткое слово без уточнений Apple — SPACE BLACK и BLACK TITANIUM это BLACK, NATURAL TITANIUM
это NATURAL.

Правила разбора:

* сокращения базы IMEI раскрываются: BLK → BLACK, NATURL → NATURAL, BUR → BURGUNDY;
* уточнения и мусор выбрасываются: TITANIUM, TTNM, SPACE, CELLULAR;
* русское название (так цвет лежит в проверках, сохранённых до этой правки, и приходит от
  касс прежних сборок) переводится тем же словарём;
* незнакомое английское слово пропускаем как есть, заглавными: новые цвета Apple выходят
  каждый год, и «MAUVE» лучше пустого поля. Незнакомое не-английское — пусто;
* кусок описания модели («Pro A2891», «iPhone 14 Pro») цветом не считается — пусто.
"""
from __future__ import annotations

import re

# Закрытый список: что считаем цветом наверняка. По нему же цвет ищется в сплошном описании.
КАНОН = frozenset((
    "BLACK", "WHITE", "SILVER", "GOLD", "BLUE", "GREEN", "RED", "YELLOW", "PINK", "PURPLE",
    "ORANGE", "CORAL", "GRAY", "GRAPHITE", "MIDNIGHT", "STARLIGHT", "SIERRA BLUE", "PACIFIC BLUE",
    "ALPINE GREEN", "MIDNIGHT GREEN", "DEEP PURPLE", "DEEP BLUE", "NATURAL", "DESERT", "TEAL",
    "ULTRAMARINE", "LAVENDER", "SAGE", "MIST BLUE", "SKY BLUE", "CLOUD WHITE", "BURGUNDY",
))

# Уточнения Apple и мусор базы IMEI, которых в словаре нет: «Space Black» → BLACK,
# «Natural Titanium» → NATURAL, «BLUE TTNM» → BLUE, «White Cellular» → WHITE, (PRODUCT)RED → RED.
ЛИШНЕЕ = frozenset(("TITANIUM", "TITAN", "TTNM", "SPACE", "CELLULAR", "PRODUCT"))

# Сокращения и слитные написания из описания GSX («IPHONE 17 PRO,NAJP,256GB,ORN»).
СОКРАЩЕНИЯ = {
    "BLK": "BLACK", "WHT": "WHITE", "SLV": "SILVER", "GLD": "GOLD", "BLU": "BLUE", "GRN": "GREEN",
    "YLW": "YELLOW", "PNK": "PINK", "PRP": "PURPLE", "ORN": "ORANGE", "ORG": "ORANGE",
    "GREY": "GRAY", "GRY": "GRAY", "SPG": "GRAY", "MDN": "MIDNIGHT", "STR": "STARLIGHT",
    "GRA": "GRAPHITE", "GPH": "GRAPHITE", "NAT": "NATURAL", "NATURL": "NATURAL", "DST": "DESERT",
    "TEL": "TEAL", "ULT": "ULTRAMARINE", "LAV": "LAVENDER", "SGE": "SAGE", "MST": "MIST BLUE",
    "SKY": "SKY BLUE", "SKYBLUE": "SKY BLUE", "CLD": "CLOUD WHITE", "DBL": "DEEP BLUE",
    "DEEPBLUE": "DEEP BLUE", "DPR": "DEEP PURPLE", "DEEPPURPLE": "DEEP PURPLE", "SPB": "BLACK",
    "CRL": "CORAL", "RSG": "PINK", "BUR": "BURGUNDY",
}

# Названия Apple из нескольких слов, которые в словаре называются иначе.
ФРАЗЫ = {"JET BLACK": "BLACK", "COSMIC ORANGE": "ORANGE", "ROSE GOLD": "PINK"}
# Что база отдаёт вместо цвета, когда его не знает.
ПУСТЫШКИ = frozenset(("UNKNOWN", "NONE", "NULL", "N", "NA"))

# Русские названия: так цвет записан в проверках, сохранённых до 13.11.2026, и так его шлют
# кассы прежних сборок. Пары через «/» — прежний вид цвета по коду корпуса.
РУССКИЕ = {
    "чёрный": "BLACK", "черный": "BLACK", "графитовый": "GRAPHITE", "белый": "WHITE",
    "серебристый": "SILVER", "золотой": "GOLD", "розовый": "PINK", "розовое золото": "PINK",
    "натуральный титан": "NATURAL", "красный": "RED", "жёлтый": "YELLOW", "желтый": "YELLOW",
    "оранжевый": "ORANGE", "коралловый": "CORAL", "синий": "BLUE", "фиолетовый": "PURPLE",
    "зелёный": "GREEN", "зеленый": "GREEN", "серый космос": "GRAY", "серый": "GRAY",
    "тёмная ночь": "MIDNIGHT", "темная ночь": "MIDNIGHT", "сияющая звезда": "STARLIGHT",
    "сьерра-блю": "SIERRA BLUE", "тихоокеанский синий": "PACIFIC BLUE",
    "пустынный титан": "DESERT", "бирюзовый": "TEAL", "ультрамарин": "ULTRAMARINE",
    "лавандовый": "LAVENDER", "шалфейный": "SAGE", "туманно-голубой": "MIST BLUE",
    "небесно-голубой": "SKY BLUE", "облачно-белый": "CLOUD WHITE", "тёмно-синий": "DEEP BLUE",
    "темно-синий": "DEEP BLUE", "тёмно-фиолетовый": "DEEP PURPLE", "темно-фиолетовый": "DEEP PURPLE",
    "чёрный космос": "BLACK", "черный космос": "BLACK", "чёрный оникс": "BLACK",
    "черный оникс": "BLACK", "альпийский зелёный": "ALPINE GREEN",
    "альпийский зеленый": "ALPINE GREEN", "чёрный титан": "BLACK", "черный титан": "BLACK",
    "белый титан": "WHITE", "синий титан": "BLUE",
}

# Кусок описания модели, принятый за цвет: в карточке Оценки уже видели «Цвет: Pro A2891».
_НЕ_ЦВЕТ = re.compile(r"(?i)^(pro max|pro|plus|mini|air|se|max|a\d{4}|iphone)\b")
ПРЕДЕЛ_СЛОВ, ПРЕДЕЛ_ЗНАКОВ = 3, 40


def _слова(текст: str) -> list[str]:
    """Английское написание → слова словаря: лишнее выброшено, сокращения раскрыты."""
    сырые = [w for w in re.split(r"[\s_\-()]+", текст.upper()) if w and w not in ЛИШНЕЕ]
    if " ".join(сырые) in КАНОН or " ".join(сырые) in ФРАЗЫ:
        return сырые                                  # «SKY BLUE» целиком, а не SKY → SKY BLUE
    out = []
    for w in сырые:
        out.extend(СОКРАЩЕНИЯ.get(w, w).split())
    return out


def цвет(сырое) -> str | None:
    """Любое написание цвета → слово словаря, иначе None.

    >>> цвет("NATURL TTNM"), цвет("Space Black"), цвет("тёмная ночь"), цвет("Pro A2891")
    ('NATURAL', 'BLACK', 'MIDNIGHT', None)
    """
    c = str(сырое or "").strip()
    if not c or _НЕ_ЦВЕТ.match(c) or re.fullmatch(r"(?i)a?\d{3,5}", c):
        return None
    первая = c.split("/")[0].strip()                  # «BLACK / GRAPHITE» → первое из пары
    по_русски = первая.lower()
    if по_русски in РУССКИЕ:
        return РУССКИЕ[по_русски]
    if по_русски.split() and по_русски.split()[0] in РУССКИЕ:
        return РУССКИЕ[по_русски.split()[0]]          # «чёрный матовый» → BLACK
    слова = _слова(первая)
    if (not слова or len(слова) > ПРЕДЕЛ_СЛОВ or " ".join(слова) in ПУСТЫШКИ
            or not all(w.isascii() and w.isalpha() for w in слова)):
        return None                                   # не словарь — лучше пусто, чем мусор
    имя = " ".join(слова)
    return ФРАЗЫ.get(имя, имя)[:ПРЕДЕЛ_ЗНАКОВ]


def известный(сырое) -> str | None:
    """То же, но только цвет из закрытого списка: незнакомое слово сюда не проходит."""
    имя = цвет(сырое)
    return имя if имя in КАНОН else None


def цвет_в_тексте(описание) -> str | None:
    """Цвет внутри сплошного описания модели — когда он не стоит отдельным полем.

    «IPHONE 14 PRO GOLD 256GB-RUS» → GOLD, «IPHONE 13 PRO MAX GPH 128GB VER-USA» → GRAPHITE.
    Берём только цвет из закрытого списка: пропускать незнакомое здесь нельзя, в описании
    хватает слов, цветом не являющихся. Смотрим только до объёма памяти — за ним идёт регион
    партии («RUS», «VER-USA»). Сначала ищем название из двух слов, потом из одного — иначе
    «DEEP PURPLE» нашёлся бы как PURPLE."""
    слова = []
    for w in re.split(r"[^A-Za-z0-9]+", str(описание or "").upper()):
        if re.fullmatch(r"\d+(GB|TB)", w):
            break
        if w:
            слова.append(w)
    for длина in (2, 1):
        for i in range(len(слова) - длина + 1):
            имя = известный(" ".join(слова[i:i + длина]))
            if имя:
                return имя
    return None
