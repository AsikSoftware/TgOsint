# -*- coding: utf-8 -*-
"""Правка бота Оценки `price_client_patch.py`: колонка суммы клиенту и строка в карточке.

Кода бота в репозитории нет — правка ложится заменой на то, что стоит на сервере. Здесь
подменный каталог бота с теми же строками-якорями, подменные `sqlalchemy` и
`database.engine`: «колонка есть» — это файл-флажок, который ставит сам шаг `--column`.
"""
import importlib.util
import os
import subprocess
import sys
import types

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ПРАВКА = os.path.join(HERE, "..", "deploy", "оценка_бот", "price_client_patch.py")

МОДЕЛЬ = '''from typing import Optional


class Device:
    phone_status: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    price_grade_auto: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )
    price_grade_admin: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )

    online: Mapped[bool] = mapped_column(Boolean, insert_default=False)
'''

# тот же кусок create_tex, что стоит в боте: «Оценен», оценщик, цена выкупа
КАРТОЧКА = '''def format_number_with_spaces(n):
    return f"{n:,}".replace(",", " ")


def _(s, lang):
    return s


def create_tex(device, lang="ru", redact=False):
    text = "<b>Магазин оценки:</b> Точка"
    admin = getattr(device, "admin", None)
    price_grade_auto = getattr(device, "price_grade_auto", None)
    price_grade_admin = getattr(device, "price_grade_admin", None)
    price_buy = getattr(device, "price_buy", None)
    price = price_grade_admin if price_grade_admin is not None else price_grade_auto

    if not redact:
        if price is not None:
            cost = _("Оценен", lang)
            text += f"\\n\\n<b>{cost}: {format_number_with_spaces(int(price))} тг</b>"

        if admin:
            text += f"\\n<b>Оценщик:</b> {admin}"

        if price_buy is not None:
            text += f"\\n\\n<b>Цена выкупа:</b> {format_number_with_spaces(int(price_buy))} тг"
    return text
'''

SQLALCHEMY = '''def text(s):
    return s
'''

# «база»: колонка есть, когда рядом лежит флажок; ALTER его и ставит
ДВИЖОК = '''import os

ФЛАЖОК = os.path.join(os.path.dirname(os.path.abspath(__file__)), "колонка_есть")


class _Ответ:
    def __init__(self, v):
        self.v = v

    def scalar(self):
        return self.v


class _Связь:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, sql):
        if "ALTER TABLE" in sql:
            assert sql == 'ALTER TABLE "devices" ADD COLUMN IF NOT EXISTS "price_client" INTEGER', sql
            open(ФЛАЖОК, "w").close()
            return _Ответ(None)
        return _Ответ(1 if os.path.exists(ФЛАЖОК) else None)


class _Движок:
    def connect(self):
        return _Связь()

    def begin(self):
        return _Связь()


async_engine = _Движок()
'''


@pytest.fixture()
def бот(tmp_path):
    for путь, тело in (("database/models.py", МОДЕЛЬ), ("database/__init__.py", ""),
                       ("database/engine.py", ДВИЖОК), ("utils/utils.py", КАРТОЧКА),
                       ("utils/__init__.py", ""), ("sqlalchemy.py", SQLALCHEMY)):
        файл = tmp_path / путь
        файл.parent.mkdir(parents=True, exist_ok=True)
        файл.write_text(тело, encoding="utf-8", newline="\n")
    return tmp_path


def _запуск(бот, *ключи):
    среда = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    return subprocess.run([sys.executable, ПРАВКА, str(бот), *ключи], capture_output=True,
                          text=True, encoding="utf-8", env=среда, timeout=120)


def _карточка(бот):
    spec = importlib.util.spec_from_file_location("карточка_бота", str(бот / "utils" / "utils.py"))
    модуль = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(модуль)
    return модуль.create_tex


def _сделка(**поля):
    return types.SimpleNamespace(**поля)


def test_the_sum_named_to_the_client_gets_a_column_and_a_line_in_the_card(бот):
    """Полный путь установки: проверка → колонка → код. После него карточка сделки
    показывает сумму клиенту сразу под «Оценен», а сама оценка остаётся прежней."""
    было = {п: (бот / п).read_text(encoding="utf-8") for п in ("database/models.py", "utils/utils.py")}

    итог = _запуск(бот, "--check")
    assert итог.returncode == 0 and "изменится файлов: 2" in итог.stdout, итог.stdout + итог.stderr
    assert {п: (бот / п).read_text(encoding="utf-8") for п in было} == было, "проверка ничего не пишет"

    # код без колонки не ставится: модель с полем, которого нет в базе, роняет чтение сделок
    итог = _запуск(бот)
    assert итог.returncode != 0 and "нет колонки devices.price_client" in (итог.stdout + итог.stderr)
    assert {п: (бот / п).read_text(encoding="utf-8") for п in было} == было

    итог = _запуск(бот, "--column")
    assert итог.returncode == 0 and "колонка devices.price_client добавлена" in итог.stdout, \
        итог.stdout + итог.stderr
    assert (бот / "database" / "apply_price_client_field.py").exists()
    итог = _запуск(бот, "--column")
    assert "уже есть" in итог.stdout, "повторный --column ничего не делает"

    итог = _запуск(бот)
    assert итог.returncode == 0 and "готово" in итог.stdout, итог.stdout + итог.stderr
    копии = sorted(f.name for f in (бот / "database").iterdir() if ".bak_" in f.name) \
        + sorted(f.name for f in (бот / "utils").iterdir() if ".bak_" in f.name)
    assert len(копии) == 2, копии
    for п in было:
        копия = next(f for f in (бот / п).parent.iterdir() if f.name.startswith(os.path.basename(п) + ".bak_"))
        assert копия.read_text(encoding="utf-8") == было[п], "копия — прежний файл как есть"
    модель = (бот / "database/models.py").read_text(encoding="utf-8")
    assert модель.count("price_client: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)") == 1
    assert модель.index("price_grade_admin") < модель.index("price_client") < модель.index("online:")

    карточка = _карточка(бот)
    текст = карточка(_сделка(price_grade_auto=185000, price_client=170000, admin="Оценщик"))
    assert "\n\n<b>Оценен: 185 000 тг</b>\n<b>Сумма клиенту:</b> 170 000 тг\n<b>Оценщик:</b>" in текст, текст
    # оценку администратора сумма клиенту не заменяет и не прячет
    текст = карточка(_сделка(price_grade_auto=185000, price_grade_admin=180000, price_client=170000))
    assert "<b>Оценен: 180 000 тг</b>\n<b>Сумма клиенту:</b> 170 000 тг" in текст
    # сделка из бота: суммы нет — карточка прежняя, буква в букву
    прежняя = {}
    exec(было["utils/utils.py"], прежняя)
    for сделка in (_сделка(price_grade_auto=185000, price_buy=160000), _сделка(price_grade_auto=None),
                   _сделка(price_grade_auto=185000, price_client=None, admin="А")):
        assert карточка(сделка) == прежняя["create_tex"](сделка)
    # там, где цены скрыты (redact), нет и суммы
    assert "Сумма клиенту" not in карточка(_сделка(price_grade_auto=185000, price_client=170000), redact=True)
    # автоцены нет, а сумма есть (быть не должно, но карточка не ломается и строка читается)
    текст = карточка(_сделка(price_grade_auto=None, price_client=170000))
    assert текст.endswith("Точка\n\n<b>Сумма клиенту:</b> 170 000 тг")

    итог = _запуск(бот)
    assert "уже стоит" in (итог.stdout + итог.stderr), "второй раз правка не ложится"
    assert (бот / "database/models.py").read_text(encoding="utf-8") == модель


def test_the_patch_stops_without_writing_when_the_bot_code_is_not_what_it_expects(бот):
    """Якорь не нашёлся (код бота поменяли) — стоп, ни один файл не тронут: половина правки
    хуже, чем никакой."""
    чужая = КАРТОЧКА.replace('_("Оценен", lang)', '_("Оценка", lang)')
    (бот / "utils" / "utils.py").write_text(чужая, encoding="utf-8", newline="\n")
    _запуск(бот, "--column")
    итог = _запуск(бот)
    assert итог.returncode != 0 and "СТОП, ничего не записано" in (итог.stdout + итог.stderr)
    assert (бот / "database/models.py").read_text(encoding="utf-8") == МОДЕЛЬ
    assert (бот / "utils/utils.py").read_text(encoding="utf-8") == чужая
