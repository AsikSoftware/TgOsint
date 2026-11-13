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
ФРАЗЫ = {"JET BLACK": "BLACK", "COSMIC ORANGE": "ORANGE", "ROSE GOLD": "PINK", "LIGHT GOLD": "GOLD"}
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


# ---------------------------------------------------------------- выбор цвета сотрудником

# База IMEI цвет знает не всегда: на 13.11.2026 — у 32 телефонов из 34 (раз не ответила вовсе,
# раз у Apple в записи модель без цвета). Тогда цвет выбирает сотрудник — кнопкой, из этого
# же словаря, а не вводом с клавиатуры: ввод уже дал в базе Оценки «ПИРПУЛ», «БЛУ» и «Б».
#
# Здесь цвета, в которых Apple выпускала модель, словами словаря. Модели нет в списке —
# касса показывает весь словарь.
_11_PRO = ("GRAY", "SILVER", "GOLD", "MIDNIGHT GREEN")
_12 = ("BLACK", "WHITE", "BLUE", "GREEN", "PURPLE", "RED")
_12_PRO = ("GRAPHITE", "SILVER", "GOLD", "PACIFIC BLUE")
_13 = ("MIDNIGHT", "STARLIGHT", "BLUE", "PINK", "GREEN", "RED")
_13_PRO = ("GRAPHITE", "SILVER", "GOLD", "SIERRA BLUE", "ALPINE GREEN")
_14 = ("MIDNIGHT", "STARLIGHT", "BLUE", "PURPLE", "YELLOW", "RED")
_14_PRO = ("BLACK", "SILVER", "GOLD", "DEEP PURPLE")
_15 = ("BLACK", "BLUE", "GREEN", "YELLOW", "PINK")
_15_PRO = ("BLACK", "WHITE", "BLUE", "NATURAL")
_16 = ("BLACK", "WHITE", "PINK", "TEAL", "ULTRAMARINE")
_16_PRO = ("BLACK", "WHITE", "NATURAL", "DESERT")
_17_PRO = ("SILVER", "ORANGE", "DEEP BLUE")
ЦВЕТА_МОДЕЛЕЙ = {
    "iPhone XR": ("BLACK", "WHITE", "BLUE", "YELLOW", "CORAL", "RED"),
    "iPhone XS": ("GRAY", "SILVER", "GOLD"), "iPhone XS Max": ("GRAY", "SILVER", "GOLD"),
    "iPhone 11": ("BLACK", "WHITE", "GREEN", "YELLOW", "PURPLE", "RED"),
    "iPhone 11 Pro": _11_PRO, "iPhone 11 Pro Max": _11_PRO,
    "iPhone 12": _12, "iPhone 12 mini": _12, "iPhone 12 Pro": _12_PRO, "iPhone 12 Pro Max": _12_PRO,
    "iPhone 13": _13, "iPhone 13 mini": _13, "iPhone 13 Pro": _13_PRO, "iPhone 13 Pro Max": _13_PRO,
    "iPhone 14": _14, "iPhone 14 Plus": _14, "iPhone 14 Pro": _14_PRO, "iPhone 14 Pro Max": _14_PRO,
    "iPhone 15": _15, "iPhone 15 Plus": _15, "iPhone 15 Pro": _15_PRO, "iPhone 15 Pro Max": _15_PRO,
    "iPhone 16": _16, "iPhone 16 Plus": _16, "iPhone 16 Pro": _16_PRO, "iPhone 16 Pro Max": _16_PRO,
    "iPhone 16e": ("BLACK", "WHITE"),
    "iPhone 17": ("BLACK", "WHITE", "MIST BLUE", "SAGE", "LAVENDER"),
    "iPhone 17 Pro": _17_PRO, "iPhone 17 Pro Max": _17_PRO,
    "iPhone Air": ("BLACK", "CLOUD WHITE", "GOLD", "SKY BLUE"),
}

# Образец цвета для кружка на кнопке и порядок кнопок в полном списке: от тёмных к светлым,
# дальше по кругу. Слово на кнопке главное, кружок — подсказка глазу.
ОБРАЗЦЫ = {
    "BLACK": "#1F2125", "GRAPHITE": "#54524F", "GRAY": "#6E6F73", "MIDNIGHT": "#232A31",
    "SILVER": "#DCDDDE", "WHITE": "#F7F7F5", "CLOUD WHITE": "#F1F1EC", "STARLIGHT": "#F0E8DC",
    "NATURAL": "#BEB8AE", "DESERT": "#C9AE96", "GOLD": "#E7CFA8",
    "BLUE": "#3F6FA8", "DEEP BLUE": "#2B3A55", "PACIFIC BLUE": "#2D4E5C", "SIERRA BLUE": "#9BB5CE",
    "SKY BLUE": "#BFD9EE", "MIST BLUE": "#A9BCD6", "ULTRAMARINE": "#8E9EEB", "TEAL": "#7DB3B1",
    "GREEN": "#5F8A66", "ALPINE GREEN": "#50604A", "MIDNIGHT GREEN": "#4E5851", "SAGE": "#A9B49A",
    "PURPLE": "#B9A7D6", "DEEP PURPLE": "#594F63", "LAVENDER": "#D8CDEA", "PINK": "#F4C7CD",
    "RED": "#C8102E", "BURGUNDY": "#6B1F2E", "CORAL": "#FF6E5A", "ORANGE": "#F0803C",
    "YELLOW": "#F6E27A",
}
ВСЕ_ЦВЕТА = tuple(ОБРАЗЦЫ)


# Как цвет называет сама Apple — для подписи на кнопке. Сотрудник узнаёт телефон по
# «Natural Titanium» и «Space Black», а в сделку и в название товара уходит короткое слово
# словаря (NATURAL, BLACK). Здесь только то, что отличается от слова с заглавной буквы.
_ТИТАН_15 = {"BLACK": "Black Titanium", "WHITE": "White Titanium", "BLUE": "Blue Titanium",
             "NATURAL": "Natural Titanium"}
_ТИТАН_16 = {"BLACK": "Black Titanium", "WHITE": "White Titanium", "NATURAL": "Natural Titanium",
             "DESERT": "Desert Titanium"}
_КРАСНЫЙ = {"RED": "(PRODUCT)RED"}
_СЕРЫЙ = {"GRAY": "Space Gray"}
НАЗВАНИЯ_APPLE = {
    "iPhone XR": _КРАСНЫЙ, "iPhone XS": _СЕРЫЙ, "iPhone XS Max": _СЕРЫЙ,
    "iPhone 11": _КРАСНЫЙ, "iPhone 11 Pro": _СЕРЫЙ, "iPhone 11 Pro Max": _СЕРЫЙ,
    "iPhone 12": _КРАСНЫЙ, "iPhone 12 mini": _КРАСНЫЙ,
    "iPhone 13": _КРАСНЫЙ, "iPhone 13 mini": _КРАСНЫЙ,
    "iPhone 14": _КРАСНЫЙ, "iPhone 14 Plus": _КРАСНЫЙ,
    "iPhone 14 Pro": {"BLACK": "Space Black"}, "iPhone 14 Pro Max": {"BLACK": "Space Black"},
    "iPhone 15 Pro": _ТИТАН_15, "iPhone 15 Pro Max": _ТИТАН_15,
    "iPhone 16 Pro": _ТИТАН_16, "iPhone 16 Pro Max": _ТИТАН_16,
    "iPhone 17 Pro": {"ORANGE": "Cosmic Orange"}, "iPhone 17 Pro Max": {"ORANGE": "Cosmic Orange"},
    "iPhone Air": {"BLACK": "Space Black", "GOLD": "Light Gold"},
}

_ПО_ИМЕНИ = {re.sub(r"\s+", "", имя).lower(): цвета for имя, цвета in ЦВЕТА_МОДЕЛЕЙ.items()}
_НАЗВАНИЯ = {re.sub(r"\s+", "", имя).lower(): d for имя, d in НАЗВАНИЯ_APPLE.items()}


def название(слово, модель=None) -> str:
    """Подпись на кнопке: как цвет называет Apple у этой модели. Не знаем особого названия —
    слово словаря с заглавных букв («DEEP PURPLE» → «Deep Purple»)."""
    свои = _НАЗВАНИЯ.get(re.sub(r"\s+", "", str(модель or "")).lower(), {})
    return свои.get(слово) or str(слово or "").title()


def цвета_модели(модель) -> tuple:
    """Цвета, в которых выпускалась модель, — для кнопок выбора. Не знаем модель — пусто.
    Регистр и пробелы не важны: база IMEI пишет и «iPhone 16 Promax», и «IPHONE 16E»."""
    return _ПО_ИМЕНИ.get(re.sub(r"\s+", "", str(модель or "")).lower(), ())


def уточнить(имя, модель):
    """Слово базы IMEI → цвет именно этой модели.

    База сокращает: у iPhone 17 Pro она пишет «BLU», а цвет называется DEEP BLUE; у 13 Pro
    «GREEN» — это ALPINE GREEN. Сотрудник же кнопкой выбирает полное слово, и один и тот же
    цвет лёг бы в товары под двумя названиями. Поэтому, если слова нет среди цветов модели,
    а ровно один её цвет это слово содержит, берём его. Иначе не трогаем: список моделей
    составлен нами и может не знать нового цвета."""
    свои = цвета_модели(модель)
    if not имя or not свои or имя in свои:
        return имя
    похожие = [c for c in свои if имя in c.split()]
    return похожие[0] if len(похожие) == 1 else имя
