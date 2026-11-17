# -*- coding: utf-8 -*-
"""Подключение к iPhone с человеческими состояниями и готовностью служб.

Состояния (для интерфейса и журнала):
  NO_DRIVER      — usbmuxd недоступен: службы Apple нет или она не запущена
                   (ставит и чинит её `apple_service`)
  NO_DEVICE      — на USB нет телефона
  LOCKED         — телефон заблокирован паролем, сопряжение невозможно
  TRUST_PENDING  — ждём «Доверять» на экране телефона
  TRUST_DENIED   — нажали «Не доверять»
  RESTORE_MODE   — телефон в режиме восстановления: по кабелю он не читается
  READY          — сопряжены, lockdown отвечает
  ERROR          — иное, с текстом

Главная выстраданная вещь: сразу после «Доверять» служба диагностики
отказывает первому запросу. open_diagnostics() пробует до шести раз
с паузами и считает ответ готовым только когда узел батареи реально
прочитался.
"""
import asyncio, os, time
from dataclasses import dataclass, field
from pathlib import Path

from pymobiledevice3 import usbmux
from pymobiledevice3.exceptions import (
    ConnectionFailedError, ConnectionFailedToUsbmuxdError, DeviceNotFoundError,
    FatalPairingError, IncorrectModeError, MuxException, NoDeviceConnectedError, NotPairedError,
    NotTrustedError, PairingDialogResponsePendingError, PairingError,
    PasscodeRequiredError, PasswordRequiredError, UserDeniedPairingError,
)
from pymobiledevice3.lockdown import create_using_usbmux
from pymobiledevice3.services.diagnostics import DiagnosticsService

NO_DRIVER, NO_DEVICE, LOCKED, TRUST_PENDING, TRUST_DENIED, READY, ERROR = (
    "NO_DRIVER", "NO_DEVICE", "LOCKED", "TRUST_PENDING", "TRUST_DENIED", "READY", "ERROR")
RESTORE_MODE = "RESTORE_MODE"

HUMAN = {
    NO_DRIVER: ("Служба Apple не отвечает. Программа чинит её сама: на экране ожидания — "
                "кнопка «Починить связь с iPhone», в докторе — `pintel-doctor link --install`. "
                "Затем воткните кабель заново."),
    NO_DEVICE: "Телефон не подключён. Нужен кабель для передачи данных, не только зарядки.",
    LOCKED: "Телефон заблокирован — разблокируйте экран.",
    TRUST_PENDING: "На телефоне нажмите «Доверять» и введите код-пароль.",
    TRUST_DENIED: "На телефоне нажали «Не доверять». Переподключите кабель и нажмите «Доверять».",
    RESTORE_MODE: ("Телефон в режиме восстановления — в нём он по кабелю не читается. "
                   "Выведите его оттуда: нажмите и отпустите «громкость +», нажмите и "
                   "отпустите «громкость −», затем держите боковую кнопку, пока не появится "
                   "яблоко."),
    READY: "Телефон на связи.",
    ERROR: "Ошибка связи с телефоном.",
}


def pair_records_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/.local/share")
    p = Path(base) / "Pintel" / "pair_records"
    p.mkdir(parents=True, exist_ok=True)
    return p


@dataclass
class LinkStatus:
    state: str
    detail: str = ""
    serial: str = ""
    lockdown: object = None
    attempts: int = 0
    timings: dict = field(default_factory=dict)
    # что телефон говорит о себе ДО «Доверять»: модель, iOS, серийник. Так 3uTools показывает
    # карточку аппарата, пока клиент ещё не нажал «Доверять»
    сведения: dict = field(default_factory=dict)

    @property
    def human(self):
        строка = HUMAN.get(self.state, self.state) + (f" ({self.detail})" if self.detail and self.state == ERROR else "")
        подпись = self.подпись_телефона
        return f"{подпись} — {строка}" if подпись else строка

    @property
    def подпись_телефона(self) -> str:
        """«iPhone 14 Pro · iOS 18.7.8» — то, что известно и без сопряжения."""
        с = self.сведения or {}
        модель = с.get("модель") or с.get("ProductType") or ""
        ios = с.get("ios") or с.get("ProductVersion") or ""
        return " · ".join(x for x in (модель, f"iOS {ios}" if ios else "") if x)


async def сведения_без_доверия(serial=None, ждать=8.0) -> dict:
    """Что телефон отдаёт БЕЗ сопряжения: модель, iOS, сборка, серийник.

    lockdown отвечает на эти ключи до «Доверять» — pymobiledevice3 читает их в
    `_initialize()`, ещё до проверки пары. Ради них и открываем соединение с `autopair=False`:
    пусть сотрудник видит, какой аппарат на кабеле, даже если клиент ещё не нажал «Доверять»
    или телефон вообще не даёт себя прочитать. Ничего не вышло — пустой словарь."""
    ld = None
    try:
        ld = await asyncio.wait_for(create_using_usbmux(
            serial=serial, autopair=False, label="PintelKiosk",
            pairing_records_cache_folder=pair_records_dir()), ждать)
        все = dict(getattr(ld, "all_values", None) or {})
        from ..analysis.passport import MODELS
        pt = str(все.get("ProductType") or "")
        return {k: v for k, v in {
            "модель": MODELS.get(pt) or (pt or None),
            "код_модели": pt or None,
            "ios": все.get("ProductVersion") or None,
            "сборка": все.get("BuildVersion") or None,
            "серийник": все.get("SerialNumber") or None,
            "класс": все.get("DeviceClass") or None,
        }.items() if v}
    except Exception:                                            # noqa: BLE001 — это подсказка, не чтение
        return {}
    finally:
        if ld is not None:
            try:
                итог = ld.close()
                if asyncio.iscoroutine(итог):
                    await asyncio.wait_for(итог, 3)
            except Exception:                                    # noqa: BLE001
                pass


async def list_usb():
    """Телефоны на USB. (NO_DRIVER, NO_DEVICE, или список MuxDevice.)"""
    try:
        devs = await usbmux.list_devices()
    except (ConnectionFailedToUsbmuxdError, MuxException, OSError, ConnectionRefusedError) as e:
        return NO_DRIVER, str(e), []
    usb = [d for d in devs if d.is_usb]
    if not usb:
        return NO_DEVICE, "", []
    return READY, "", usb


async def connect(serial=None, trust_timeout=0.0):
    """Одна попытка подключения. trust_timeout=0 — не ждать диалог,
    вернуть TRUST_PENDING сразу (для опроса в цикле)."""
    t0 = time.monotonic()
    try:
        ld = await create_using_usbmux(
            serial=serial, autopair=True, pair_timeout=trust_timeout,
            label="PintelKiosk", pairing_records_cache_folder=pair_records_dir())
    except PairingDialogResponsePendingError:
        return LinkStatus(TRUST_PENDING, serial=serial or "",
                          сведения=await сведения_без_доверия(serial))
    except (UserDeniedPairingError,):
        return LinkStatus(TRUST_DENIED, serial=serial or "",
                          сведения=await сведения_без_доверия(serial))
    except (PasswordRequiredError, PasscodeRequiredError):
        return LinkStatus(LOCKED, serial=serial or "",
                          сведения=await сведения_без_доверия(serial))
    except (NotTrustedError, NotPairedError):
        return LinkStatus(TRUST_PENDING, serial=serial or "",
                          сведения=await сведения_без_доверия(serial))
    except (NoDeviceConnectedError, DeviceNotFoundError):
        return LinkStatus(NO_DEVICE)
    except (ConnectionFailedToUsbmuxdError, MuxException):
        return LinkStatus(NO_DRIVER)
    except IncorrectModeError as e:
        # Телефон отвечает не lockdown, а restored — это режим восстановления. Сотрудник
        # видел «Ошибка связи с телефоном (IncorrectModeError: …)» и переподключал кабель по
        # кругу: за один вечер такого набралось полторы сотни строк в журнале точки.
        return LinkStatus(RESTORE_MODE, detail=str(e)[:160], serial=serial or "")
    except (FatalPairingError, PairingError, ConnectionFailedError) as e:
        return LinkStatus(ERROR, detail=f"{type(e).__name__}: {e}")
    except Exception as e:
        return LinkStatus(ERROR, detail=f"{type(e).__name__}: {e}")
    st = LinkStatus(READY, lockdown=ld, serial=getattr(ld, "udid", "") or serial or "")
    st.timings["подключение_с"] = round(time.monotonic() - t0, 2)
    return st


async def второе_соединение(ld):
    """Ещё одно соединение lockdown с тем же телефоном — под вопрос, ответ на который телефон
    может считать долго (память). Сопряжение уже есть, диалога «Доверять» не будет."""
    return await create_using_usbmux(
        serial=getattr(ld, "udid", None) or None, autopair=False, label="PintelKiosk",
        pairing_records_cache_folder=pair_records_dir())


ЖДАТЬ_ПОДКЛЮЧЕНИЕ = 12.0        # сколько ждём ответа lockdown при подключении
ЖДАТЬ_ДИАГНОСТИКУ = 6.0         # ...и на одну попытку открыть службу диагностики


async def wait_ready(poll=1.5, on_status=None, deadline=None):
    """Цикл ожидания до READY. on_status(LinkStatus) зовётся при смене состояния.

    Предел на само подключение обязателен: без него цикл зависает ВНУТРИ connect(), а не
    между опросами, и свой `deadline` соблюсти не может — окно кассы остаётся «подключаем»
    навсегда."""
    last = None
    while True:
        st_name, detail, devs = await list_usb()
        if st_name != READY:
            st = LinkStatus(st_name, detail)
        else:
            try:
                st = await asyncio.wait_for(connect(serial=devs[0].serial, trust_timeout=0.0),
                                            ЖДАТЬ_ПОДКЛЮЧЕНИЕ)
            except asyncio.TimeoutError:
                st = LinkStatus(ERROR, detail=f"lockdown не ответил за {ЖДАТЬ_ПОДКЛЮЧЕНИЕ:g} с")
        if on_status and (last is None or st.state != last.state):
            on_status(st)
        last = st
        if st.state == READY:
            return st
        if deadline and time.monotonic() > deadline:
            return st
        await asyncio.sleep(poll)


async def open_diagnostics(ld, attempts=6, delays=(0.5, 1.0, 1.5, 2.0, 3.0, 3.0)):
    """Служба диагностики с проверкой готовности. Возвращает (svc, попыток)."""
    last = None
    for i in range(attempts):
        svc = DiagnosticsService(ld)
        try:
            await asyncio.wait_for(svc.connect(), ЖДАТЬ_ДИАГНОСТИКУ)
            probe = await asyncio.wait_for(svc.ioregistry(name="AppleSmartBattery"),
                                           ЖДАТЬ_ДИАГНОСТИКУ)
            if probe:
                return svc, i + 1
            last = RuntimeError("диагностика ответила пустым")
        except asyncio.TimeoutError:
            last = RuntimeError(f"диагностика не ответила за {ЖДАТЬ_ДИАГНОСТИКУ:g} с")
        except Exception as e:
            last = e
        try:
            await svc.close()
        except Exception:
            pass
        await asyncio.sleep(delays[min(i, len(delays) - 1)])
    raise RuntimeError(f"служба диагностики не ответила после {attempts} попыток: {last}")
