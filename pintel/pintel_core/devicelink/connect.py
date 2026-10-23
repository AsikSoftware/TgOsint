# -*- coding: utf-8 -*-
"""Подключение к iPhone с человеческими состояниями и готовностью служб.

Состояния (для интерфейса и журнала):
  NO_DRIVER      — usbmuxd недоступен: не стоит iTunes / служба Apple не запущена
  NO_DEVICE      — на USB нет телефона
  LOCKED         — телефон заблокирован паролем, сопряжение невозможно
  TRUST_PENDING  — ждём «Доверять» на экране телефона
  TRUST_DENIED   — нажали «Не доверять»
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
    FatalPairingError, MuxException, NoDeviceConnectedError, NotPairedError,
    NotTrustedError, PairingDialogResponsePendingError, PairingError,
    PasscodeRequiredError, PasswordRequiredError, UserDeniedPairingError,
)
from pymobiledevice3.lockdown import create_using_usbmux
from pymobiledevice3.services.diagnostics import DiagnosticsService

NO_DRIVER, NO_DEVICE, LOCKED, TRUST_PENDING, TRUST_DENIED, READY, ERROR = (
    "NO_DRIVER", "NO_DEVICE", "LOCKED", "TRUST_PENDING", "TRUST_DENIED", "READY", "ERROR")

HUMAN = {
    NO_DRIVER: "Драйвер Apple не найден: установите iTunes с сайта Apple (служба Apple Mobile Device).",
    NO_DEVICE: "Телефон не подключён. Нужен кабель для передачи данных, не только зарядки.",
    LOCKED: "Телефон заблокирован — разблокируйте экран.",
    TRUST_PENDING: "На телефоне нажмите «Доверять» и введите код-пароль.",
    TRUST_DENIED: "На телефоне нажали «Не доверять». Переподключите кабель и нажмите «Доверять».",
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

    @property
    def human(self):
        return HUMAN.get(self.state, self.state) + (f" ({self.detail})" if self.detail and self.state == ERROR else "")


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
        return LinkStatus(TRUST_PENDING, serial=serial or "")
    except (UserDeniedPairingError,):
        return LinkStatus(TRUST_DENIED, serial=serial or "")
    except (PasswordRequiredError, PasscodeRequiredError):
        return LinkStatus(LOCKED, serial=serial or "")
    except (NotTrustedError, NotPairedError):
        return LinkStatus(TRUST_PENDING, serial=serial or "")
    except (NoDeviceConnectedError, DeviceNotFoundError):
        return LinkStatus(NO_DEVICE)
    except (ConnectionFailedToUsbmuxdError, MuxException):
        return LinkStatus(NO_DRIVER)
    except (FatalPairingError, PairingError, ConnectionFailedError) as e:
        return LinkStatus(ERROR, detail=f"{type(e).__name__}: {e}")
    except Exception as e:
        return LinkStatus(ERROR, detail=f"{type(e).__name__}: {e}")
    st = LinkStatus(READY, lockdown=ld, serial=getattr(ld, "udid", "") or serial or "")
    st.timings["подключение_с"] = round(time.monotonic() - t0, 2)
    return st


async def wait_ready(poll=1.5, on_status=None, deadline=None):
    """Цикл ожидания до READY. on_status(LinkStatus) зовётся при смене состояния."""
    last = None
    while True:
        st_name, detail, devs = await list_usb()
        if st_name != READY:
            st = LinkStatus(st_name, detail)
        else:
            st = await connect(serial=devs[0].serial, trust_timeout=0.0)
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
            await svc.connect()
            probe = await svc.ioregistry(name="AppleSmartBattery")
            if probe:
                return svc, i + 1
            last = RuntimeError("диагностика ответила пустым")
        except Exception as e:
            last = e
        try:
            await svc.close()
        except Exception:
            pass
        await asyncio.sleep(delays[min(i, len(delays) - 1)])
    raise RuntimeError(f"служба диагностики не ответила после {attempts} попыток: {last}")
