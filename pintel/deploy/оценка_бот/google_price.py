# utils/google_price.py
import asyncio
import logging
import re
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials

from config import settings

from database.models import Device

_PRICE_TABLE: list[list[str]] | None = None


def reset_price_cache() -> None:
    global _PRICE_TABLE
    _PRICE_TABLE = None
    try:                                   # прайсы точек: handlers/kiosk_price.py
        from handlers.kiosk_price import сбросить_кэш
        сбросить_кэш()
    except Exception:                      # модуля нет — значит прайс один на всю сеть
        pass


# ---------------------------------------------------------
# 1. Индексы колонок под диапазоны АКБ
# (в таблице индекс 0 = Марка, 1 = Модель, 2 = Память)
# ---------------------------------------------------------
AKB_COL_INDEX_BY_STATE: dict[str, int] = {
    "нет информации": 3,
    "0-74": 4,
    "75-79": 5,
    "80-85": 6,
    "86-90": 7,
    "91-95": 8,
    "96-99": 9,
    "100": 10,
    "100 (0-30)": 11,
}

# ---------------------------------------------------------
# 1а. Вкладка по точному проценту АКБ: шапка «72% | 73% | … | 100%»
# ---------------------------------------------------------
# Колонку ищем ПО ШАПКЕ, а не по номеру: вкладку можно расширять и сужать, код не трогая.
# Вкладка по диапазонам («0-74 | 75-79 | …») читается как раньше, по номерам выше, —
# формат определяется сам: есть в шапке клетки вида «95%» — значит вкладка по процентам.
#
# Какой процент берём:
#   • точный (`akb_exact`), если он есть и не спорит с выбранным диапазоном;
#   • иначе верх диапазона: цена диапазона — это цена его верхнего процента
#     («91-95» → 95%), поэтому сделки без точного процента стоят столько же, сколько раньше;
#   • процента нет («нет информации») или он может быть ниже таблицы («0-74» без точного
#     числа) — цена только там, где она от батареи не зависит: все клетки строки равны.
# Нет колонки под процент или клетка пуста — цены нет, сделку оценит человек.
_PERCENT_HEADER = re.compile(r"^\s*(\d{1,3})\s*%\s*$")

AKB_BOUNDS_BY_STATE: dict[str, tuple[int, int]] = {
    "0-74": (0, 74),
    "75-79": (75, 79),
    "80-85": (80, 85),
    "86-90": (86, 90),
    "91-95": (91, 95),
    "96-99": (96, 99),
    "100": (100, 100),
    "100 (0-30)": (100, 100),
}


def akb_state_from_percent(percent: int) -> str:
    """Точный процент → прежняя метка диапазона («88» → «86-90»).

    Продавец диапазон больше не выбирает — вводит процент. Метка осталась только как
    служебное поле `devices.akb`: по ней МойСклад заполняет характеристику «АКБ», и её же
    получает Pay. Считается из процента, руками её никто не задаёт."""
    percent = int(percent)
    if percent >= 100:
        return "100"
    for state, (low, high) in AKB_BOUNDS_BY_STATE.items():
        if low <= percent <= high:
            return state
    return "0-74"


def percent_columns(header) -> dict[int, int]:
    """Шапка вкладки → {процент: номер колонки}. Пусто — вкладка по диапазонам."""
    cols: dict[int, int] = {}
    for idx, cell in enumerate(header or []):
        m = _PERCENT_HEADER.match(str(cell))
        if m:
            cols[int(m.group(1))] = idx
    return cols


def _cell_price(row, idx) -> Optional[int]:
    """Клетка строки → цена. Нет колонки, пусто или не число — None, а не ноль."""
    if idx is None or len(row) <= idx:
        return None
    raw_value = str(row[idx]).strip()
    if not raw_value:
        return None
    try:
        return int(raw_value.replace(" ", "").replace("\xa0", "").replace(",", ""))
    except ValueError:
        return None


def price_in_row(header, row, akb_state, akb_exact=None) -> Optional[int]:
    """Цена из найденной строки прайса по состоянию АКБ. Понимает обе шапки."""
    percents = percent_columns(header)
    if not percents:                       # вкладка по диапазонам — ровно как было
        return _cell_price(row, AKB_COL_INDEX_BY_STATE.get(akb_state))

    if akb_state not in AKB_COL_INDEX_BY_STATE:
        return None                        # незнакомое состояние — соседнюю колонку не берём

    percent = None
    bounds = AKB_BOUNDS_BY_STATE.get(akb_state)
    if bounds:
        low, high = bounds
        try:
            exact = int(akb_exact) if akb_exact is not None else None
        except (TypeError, ValueError):
            exact = None
        if exact is not None and low <= exact <= high:
            percent = exact
        elif low > 0:
            percent = high
    if percent is not None:
        return _cell_price(row, percents.get(min(percent, 100)))

    # процент неизвестен: цена есть только там, где от батареи она не зависит
    prices = {_cell_price(row, idx) for idx in percents.values()}
    return prices.pop() if len(prices) == 1 else None


# ---------------------------------------------------------
# 2. Создаём клиента Google Sheets
# ---------------------------------------------------------
def _get_client() -> gspread.Client:
    creds = Credentials.from_service_account_info(
        settings.GOOGLE_SHEETS_CREDS_JSON,
        scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
    )
    return gspread.authorize(creds)


def _get_price_table() -> list[list[str]]:
    global _PRICE_TABLE

    if _PRICE_TABLE is not None:
        return _PRICE_TABLE

    client = _get_client()
    sh = client.open_by_key(settings.GOOGLE_SHEETS_SPREADSHEET_ID)
    ws = sh.get_worksheet_by_id(settings.GOOGLE_SHEETS_SHEET_GID)

    _PRICE_TABLE = ws.get_all_values() or []
    return _PRICE_TABLE


# ---------------------------------------------------------
# 3. Синхронная функция получения цены
# ---------------------------------------------------------
def get_price_sync(
        marka: str,
        model: str,
        memory: str | int,
        akb_state: str,
        akb_exact: Optional[int] = None,
) -> Optional[int]:
    """
    Ищем строку в Google-таблице по трём параметрам:

      - Марка  (колонка 0)
      - Модель (колонка 1)
      - Память (колонка 2)

    А затем возвращаем цену из колонки,
    соответствующей akb_state (например '100', '91-95').
    """

    # незнакомое состояние АКБ — цены нет (за таблицей даже не ходим)
    if akb_state not in AKB_COL_INDEX_BY_STATE:
        return None

    values = _get_price_table()

    if not values or len(values) < 2:
        return None

    # нормализация входящих значений
    marka_norm = marka.strip().lower()
    model_norm = model.strip().lower()
    memory_norm = str(memory).strip().lower()

    # пропускаем шапку → начинаем с values[1:]
    for row in values[1:]:
        if len(row) < 3:
            continue

        # ВАЖНО: порядок колонок в таблице:
        # 0 = Марка
        # 1 = Модель
        # 2 = Память
        row_marka = row[0].strip().lower()
        row_model = row[1].strip().lower()
        row_memory = row[2].strip().lower()

        # проверяем совпадение трёх параметров
        if (
                row_marka == marka_norm
                and row_model == model_norm
                and row_memory == memory_norm
        ):
            # колонку АКБ выбирает шапка: диапазоны или точные проценты
            return price_in_row(values[0], row, akb_state, akb_exact)

    return None


# ---------------------------------------------------------
# 4. Асинхронная обёртка над get_price_sync
# ---------------------------------------------------------
async def get_price(
        marka: str,
        model: str,
        memory: str | int,
        akb_state: str,
        akb_exact: Optional[int] = None,
) -> Optional[int]:
    return await asyncio.to_thread(
        get_price_sync,
        marka,
        model,
        memory,
        akb_state,
        akb_exact,
    )


# ---------------------------------------------------------
# 5. Получить цену по объекту Device
# ---------------------------------------------------------
async def get_price_for_device(device: Device) -> Optional[int]:
    marka = device.producer
    model = device.model
    memory = device.ddr
    akb_state = device.akb

    # минимальная валидация
    if not marka or not model or memory is None:
        return None

    # Прайс точки (shops.price_url). Своя вкладка есть, а строки в ней нет — автоцены у
    # сделки нет вовсе: цена из чужого списка хуже, чем ручная оценка.
    try:
        from handlers.kiosk_price import по_точке
    except ImportError:                    # модуль не поставлен — считаем по общему прайсу
        по_точке = None
    if по_точке is not None:
        try:
            свой, цена = await по_точке(device)
            if свой:
                return цена
        except Exception as e:             # noqa: BLE001
            logging.exception("Прайс точки недоступен (%s %s): %s", marka, model, e)
            return None

    # прайс недоступен (нет доступа к таблице/сеть) — сделка не должна срываться
    try:
        return await get_price(
            marka=marka,
            model=model,
            memory=memory,
            akb_state=akb_state,
            akb_exact=getattr(device, "akb_exact", None),
        )
    except Exception as e:
        logging.exception("Автооценка недоступна (%s %s): %s", marka, model, e)
        return None
