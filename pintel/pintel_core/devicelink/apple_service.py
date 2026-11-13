# -*- coding: utf-8 -*-
"""Служба Apple на Windows: программа ставит и чинит её сама.

Телефон по кабелю читается через usbmuxd. На Windows это «Apple Mobile Device Service» и
драйвер USB Apple; оба приезжают одним пакетом — Apple Mobile Device Support. Раньше его
ставили руками вместе с iTunes («с сайта Apple, не из Microsoft Store»), и на каждом новом
ноутбуке это было отдельным местом, где всё ломалось: не тот iTunes, служба остановлена,
автозапуск выключен.

Что выяснено, чтобы не выяснять заново (11.2026):
  • без компонентов Apple iPhone на Windows не читается ни у кого: драйвер Apple держит
    телефон в режиме «только фото», пока не увидит службу Apple. Своего драйвера,
    независимого от Apple, нет ни у одного живого проекта, а самописный Windows заменит
    драйвером Apple при первом же обновлении;
  • вкладывать пакет Apple в свою сборку нельзя — лицензия. Скачать его с сервера Apple
    при установке можно, так делают и другие программы.

Поэтому модуль делает три вещи и больше ничего:
  1. `починить` — без прав: порт отвечает? служба есть? остановлена — запустить;
  2. `скачать_пакет` — скачать пакет с сервера Apple и сверить его сумму;
  3. `под_админом` — то единственное, что требует прав администратора: установка пакета,
     автозапуск службы, перезапуск при сбое, старт. Зовётся отдельным запуском программы
     с повышением прав (одно окно Windows «Разрешить?»).

Наружу всё ходит через «окружение» (`Windows`): в тестах оно подменяется, и логика
проверяется без Windows и без сети.
"""
import hashlib
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request

СЛУЖБА = "Apple Mobile Device Service"
ПОРТ = ("127.0.0.1", 27015)

# Пакет с сервера Apple. Адрес и сумма — из манифеста winget `Apple.AppleMobileDeviceSupport`
# (он ведёт на тот же сервер Apple). Обновить: взять там новую версию, проверить, что
# сборка проходит шаг «Служба Apple ставится сама».
#
# На точке сверяется только сумма: она однозначно называет файл. А то, что файл с этой
# суммой подписан Apple, проверяет сборка — на каждом прогоне, средствами самой Windows.
# Проверять подпись на точке пробовали через PowerShell и убрали: его модуль подписей не
# грузится, когда программу запустили из другой оболочки, — исправный пакет объявлялся
# «без подписи», и установка не шла.
ПАКЕТ = {
    "версия": "19.4.0.10",
    "url": ("https://swcdn.apple.com/content/downloads/20/49/047-76422/"
            "qcw2a7028lr8yp4rdkrfyzkvlhi9q1gg2g/AppleMobileDeviceSupport64.msi"),
    "sha256": "b60533fb54e7bd81ffc52d99678a9cce04e58cb54a76281bd7b1309f20d360e9",
}

# состояния службы
НЕТ, ОТКЛЮЧЕНА, ОСТАНОВЛЕНА, МЕНЯЕТСЯ, РАБОТАЕТ = "нет", "отключена", "остановлена", "меняется", "работает"
# итоги
ГОТОВО, НЕТ_СЛУЖБЫ, НУЖНЫ_ПРАВА, НЕ_ВЫШЛО, НЕ_WINDOWS = "готово", "нет_службы", "нужны_права", "не_вышло", "не_windows"

ЧЕЛОВЕКУ = {
    ГОТОВО: "Связь с iPhone работает.",
    НЕТ_СЛУЖБЫ: "На этом компьютере нет службы Apple — её нужно установить.",
    НУЖНЫ_ПРАВА: "Служба Apple остановлена, а запустить её можно только с правами администратора.",
    НЕ_WINDOWS: "Служба Apple нужна только на Windows.",
}

_СОСТОЯНИЕ = re.compile(r":\s*(\d)\s+(STOPPED|START_PENDING|STOP_PENDING|RUNNING|CONTINUE_PENDING|PAUSE_PENDING|PAUSED)")
_ЗАПУСК = re.compile(r":\s*(\d)\s+(BOOT_START|SYSTEM_START|AUTO_START|DEMAND_START|DISABLED)")
НЕТ_ТАКОЙ_СЛУЖБЫ, ОТКАЗАНО = 1060, 5


class ОтказПрав(Exception):
    """В окне Windows «Разрешить этому приложению…» нажали «Нет»."""


class Windows:
    """Настоящее окружение. Тонкая обёртка: вся логика — в функциях ниже."""

    def это_windows(self):
        return sys.platform == "win32"

    def порт_жив(self, ждать=0.4):
        try:
            with socket.create_connection(ПОРТ, timeout=ждать):
                return True
        except OSError:
            return False

    def запустить(self, команда, ждать=300):
        """(код возврата, вывод). Окно консоли не мелькает."""
        флаги = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        r = subprocess.run(команда, capture_output=True, timeout=ждать, creationflags=флаги)
        return r.returncode, (r.stdout + r.stderr).decode("cp866", errors="replace")

    def от_администратора(self, аргументы, ждать_мс=900_000):
        """Запустить эту же программу с повышением прав и дождаться её. → код возврата."""
        import ctypes
        from ctypes import wintypes

        class Запрос(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND),
                        ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR),
                        ("lpParameters", wintypes.LPCWSTR), ("lpDirectory", wintypes.LPCWSTR),
                        ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
                        ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR),
                        ("hkeyClass", wintypes.HKEY), ("dwHotKey", wintypes.DWORD),
                        ("hIcon", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]

        файл, параметры = своя_команда(аргументы)
        з = Запрос()
        з.cbSize = ctypes.sizeof(з)
        з.fMask = 0x00000040                                   # SEE_MASK_NOCLOSEPROCESS
        з.lpVerb, з.lpFile, з.lpParameters, з.nShow = "runas", файл, subprocess.list2cmdline(параметры), 0
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        if not shell32.ShellExecuteExW(ctypes.byref(з)):
            if ctypes.get_last_error() == 1223:                # ERROR_CANCELLED: нажали «Нет»
                raise ОтказПрав()
            raise OSError("Windows не запустила программу с правами администратора")
        ctypes.windll.kernel32.WaitForSingleObject(з.hProcess, ждать_мс)
        код = wintypes.DWORD()
        ctypes.windll.kernel32.GetExitCodeProcess(з.hProcess, ctypes.byref(код))
        ctypes.windll.kernel32.CloseHandle(з.hProcess)
        return код.value

    def скачать(self, url, путь, шаг=None):
        os.makedirs(os.path.dirname(путь), exist_ok=True)
        запрос = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(запрос, timeout=60) as ответ, open(путь + ".part", "wb") as f:
            всего, есть = int(ответ.headers.get("Content-Length") or 0), 0
            while True:
                кусок = ответ.read(1 << 18)
                if not кусок:
                    break
                f.write(кусок)
                есть += len(кусок)
                if шаг:
                    шаг(есть, всего)
        os.replace(путь + ".part", путь)

    def сумма(self, путь):
        h = hashlib.sha256()
        with open(путь, "rb") as f:
            for кусок in iter(lambda: f.read(1 << 20), b""):
                h.update(кусок)
        return h.hexdigest()

    def папка(self):
        база = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/.local/share")
        return os.path.join(база, "Pintel", "apple")


def своя_команда(аргументы):
    """Как запустить эту же программу ещё раз: (файл, параметры)."""
    if getattr(sys, "frozen", False):                          # собранный exe
        return sys.executable, list(аргументы)
    return sys.executable, ["-m", "pintel_core.devicelink.apple_service", *аргументы]


def служба(окр):
    """Что с «Apple Mobile Device Service»: нет / отключена / остановлена / меняется / работает.

    Читаем вывод `sc`: подписи в нём переведены, а сами значения («4  RUNNING») — нет."""
    код, текст = окр.запустить(["sc", "query", СЛУЖБА])
    if код == НЕТ_ТАКОЙ_СЛУЖБЫ:
        return НЕТ
    m = _СОСТОЯНИЕ.search(текст)
    if not m:
        return НЕТ
    if m.group(2) == "RUNNING":
        return РАБОТАЕТ
    if m.group(2) != "STOPPED":
        return МЕНЯЕТСЯ
    _, настройки = окр.запустить(["sc", "qc", СЛУЖБА])
    запуск = _ЗАПУСК.search(настройки)
    return ОТКЛЮЧЕНА if запуск and запуск.group(2) == "DISABLED" else ОСТАНОВЛЕНА


def _дождаться_порта(окр, секунд, пауза=time.sleep):
    for _ in range(max(1, int(секунд * 2))):
        if окр.порт_жив():
            return True
        пауза(0.5)
    return окр.порт_жив()


def починить(окр=None, пауза=time.sleep):
    """Без прав администратора: что можем — делаем, остальное называем. → итог."""
    окр = окр or Windows()
    if not окр.это_windows():
        return НЕ_WINDOWS
    if окр.порт_жив():
        return ГОТОВО
    что = служба(окр)
    if что == НЕТ:
        return НЕТ_СЛУЖБЫ
    if что == ОСТАНОВЛЕНА:
        окр.запустить(["sc", "start", СЛУЖБА])            # откажут — узнаем по порту
    if что in (ОСТАНОВЛЕНА, МЕНЯЕТСЯ) and _дождаться_порта(окр, 12, пауза):
        return ГОТОВО
    # отключена, не дали запустить или работает, но молчит — дальше только с правами
    return НУЖНЫ_ПРАВА


def скачать_пакет(окр, шаг=None):
    """Пакет Apple на диске, сумма сошлась. → путь к файлу. Иначе RuntimeError."""
    путь = os.path.join(окр.папка(), "AppleMobileDeviceSupport64.msi")
    if not (os.path.isfile(путь) and окр.сумма(путь) == ПАКЕТ["sha256"]):
        try:
            окр.скачать(ПАКЕТ["url"], путь, шаг)
        except Exception as e:                                 # noqa: BLE001
            raise RuntimeError(f"пакет Apple не скачался ({e}). Проверьте интернет и повторите; "
                               "запасной путь — поставить iTunes с сайта apple.com") from None
        if окр.сумма(путь) != ПАКЕТ["sha256"]:
            raise RuntimeError("скачанный пакет Apple не совпал с ожидаемым — ставить его нельзя")
    return путь


def обеспечить(окр=None, сказать=None, шаг=None, пауза=time.sleep, принудительно=False):
    """Полный путь по кнопке «Починить связь»: запустить, а если нечего — поставить.

    `принудительно` — кнопку нажал человек. Тогда служба перезапускается, даже если она
    отвечает: кнопку жмут как раз тогда, когда служба жива, а телефон всё равно не виден,
    и ответ «связь работает» в этот момент — отказ в помощи.

    Одно окно Windows с вопросом о правах — на установку или на перезапуск, не больше.
    → (итог, текст для человека)."""
    окр = окр or Windows()
    сказать = сказать or (lambda текст: None)
    итог = починить(окр, пауза)
    жива = итог == ГОТОВО
    if итог == НЕ_WINDOWS or (жива and not принудительно):
        return итог, ЧЕЛОВЕКУ[итог]
    try:
        if итог == НЕТ_СЛУЖБЫ:
            сказать("Скачиваем службу Apple (40 МБ)…")
            пакет = скачать_пакет(окр, шаг)
            сказать("Устанавливаем — Windows спросит разрешение, нажмите «Да»")
            код = окр.от_администратора(["--apple-setup", пакет])
        else:
            сказать("Перезапускаем службу Apple — Windows спросит разрешение, нажмите «Да»")
            код = окр.от_администратора(["--apple-setup", "--restart"] if жива else ["--apple-setup"])
    except ОтказПрав:
        return НУЖНЫ_ПРАВА, "Windows не дала прав: в окне «Разрешить?» нужно нажать «Да»."
    except Exception as e:                                     # noqa: BLE001
        return НЕ_ВЫШЛО, str(e)
    if код == 3010:
        return ГОТОВО, "Служба Apple установлена. Перезагрузите компьютер — после этого связь заработает."
    if код != 0:
        return НЕ_ВЫШЛО, f"установка не прошла (код Windows {код}). Запасной путь — iTunes с сайта apple.com."
    if _дождаться_порта(окр, 40, пауза):
        return ГОТОВО, ("Служба Apple перезапущена. Отключите и снова подключите кабель телефона."
                        if жива else ЧЕЛОВЕКУ[ГОТОВО])
    return НЕ_ВЫШЛО, "служба Apple установлена, но не отвечает — перезагрузите компьютер."


def под_админом(пакет=None, окр=None, пауза=time.sleep, перезапуск=False):
    """Та часть, что идёт с правами администратора. → код возврата (0 — хорошо).

    `перезапуск` — службу остановить и запустить, даже если она отвечает (кнопку нажал
    человек: телефон не виден при живой службе).

    Пакет ставим, только если он наш: сумму сверяем ещё раз, уже под администратором, —
    между проверкой и установкой файл лежал в папке пользователя."""
    окр = окр or Windows()
    код = 0
    if пакет:
        if окр.сумма(пакет) != ПАКЕТ["sha256"]:
            return 13                                          # ERROR_INVALID_DATA
        код, _ = окр.запустить(["msiexec", "/i", пакет, "/qn", "/norestart"], ждать=900)
        if код not in (0, 3010):
            return код
    # автозапуск и перезапуск при падении: служба поднимается сама, без нас и без прав
    окр.запустить(["sc", "config", СЛУЖБА, "start=", "auto"])
    окр.запустить(["sc", "failure", СЛУЖБА, "reset=", "86400",
                   "actions=", "restart/5000/restart/5000/restart/60000"])
    if перезапуск or not окр.порт_жив():                       # молчит или просили — перезапускаем
        окр.запустить(["sc", "stop", СЛУЖБА])
        пауза(3)
        окр.запустить(["sc", "start", СЛУЖБА])
    return код


def точка_входа(argv):
    """`… --apple-setup [--restart] [пакет.msi]` — повышенный запуск. Не наш аргумент → None."""
    if "--apple-setup" not in argv:
        return None
    хвост = argv[argv.index("--apple-setup") + 1:]
    пакеты = [x for x in хвост if not str(x).startswith("--")]
    пакет = пакеты[0] if пакеты else None
    return под_админом(пакет, перезапуск=True) if "--restart" in хвост else под_админом(пакет)


if __name__ == "__main__":
    код = точка_входа(sys.argv)
    if код is None:
        итог, текст = обеспечить(сказать=print)
        print(итог, "—", текст)
        код = 0 if итог in (ГОТОВО, НЕ_WINDOWS) else 1
    sys.exit(код)
