"""Проверка готовности рабочего места. Для продавца на точке — одна кнопка.

Сознательно НЕ скачивает и не запускает ничего из сети: тихая загрузка
исполняемых файлов — это дыра, через которую на кассовый компьютер заедет
что угодно. libimobiledevice едет вместе с программой (он открытый и
распространяется свободно), а драйвер Apple ставится с сайта Apple руками.
Скрипт говорит, чего не хватает, и даёт точную ссылку.
"""
import os, platform, subprocess, sys
from .device import _tool

NEEDED = ["idevice_id", "ideviceinfo", "idevicediagnostics", "idevicesyslog"]
AMDS_URL = "https://support.apple.com/ru-ru/106372"   # страница Apple про iTunes/AMDS


def _amds_windows():
    """Служба Apple Mobile Device Service — без неё Windows не видит iPhone."""
    try:
        r = subprocess.run(["sc", "query", "Apple Mobile Device Service"],
                           capture_output=True, text=True, timeout=10)
        if "RUNNING" in r.stdout:
            return "работает"
        if "STOPPED" in r.stdout:
            return "установлена, но остановлена"
        return "не установлена"
    except Exception:
        return "не удалось проверить"


def check():
    win = platform.system() == "Windows"
    items = []

    for t in NEEDED:
        p = _tool(t)
        items.append({
            "что": t,
            "готово": bool(p),
            "где": p or "",
            "почему": "" if p else "нет бинарника libimobiledevice",
            "как_починить": "" if p else
                "Положи бинарники libimobiledevice в папку bin/ рядом с программой. "
                "Они должны идти в комплекте — если папки нет, скачай дистрибутив заново.",
        })

    if win:
        st = _amds_windows()
        ok = st == "работает"
        items.append({
            "что": "Драйвер Apple (Apple Mobile Device Service)",
            "готово": ok, "где": st,
            "почему": "" if ok else f"служба: {st}",
            "как_починить": "" if ok else
                "Установи iTunes с сайта Apple — вместе с ним ставится драйвер USB. "
                f"Страница Apple: {AMDS_URL}. После установки перезагрузи компьютер.",
            "ссылка": None if ok else AMDS_URL,
        })
    else:
        items.append({
            "что": "Драйвер Apple",
            "готово": True, "где": platform.system(),
            "почему": "", "как_починить": "",
            "примечание": "На macOS драйвер встроен, ставить нечего.",
        })

    # Ключ Sickw не обязателен: без него работает всё, кроме внешней проверки
    from . import sickw
    items.append({
        "что": "Ключ Sickw (необязательно)",
        "готово": sickw.key_available(),
        "где": "~/.sickw_key" if sickw.key_available() else "",
        "почему": "" if sickw.key_available() else "ключа нет",
        "как_починить": "" if sickw.key_available() else
            "Без него работает всё, кроме проверки по чёрному списку и цвета. "
            "Чтобы включить: положи ключ одной строкой в файл ~/.sickw_key",
        "необязательно": True,
    })

    # Живая проверка: видим ли телефон прямо сейчас
    phone = {"что": "Телефон на проводе", "готово": False, "где": "",
             "почему": "", "как_починить": "", "необязательно": True}
    try:
        from .device import udid
        phone["где"] = udid()
        phone["готово"] = True
    except Exception as e:
        phone["почему"] = str(e)
        phone["как_починить"] = ("Подключи кабелем, разблокируй экран и нажми «Доверять». "
                                 "Кабель должен быть для передачи данных, а не только для зарядки.")
    items.append(phone)

    need = [i for i in items if not i["готово"] and not i.get("необязательно")]
    return {"система": platform.system(), "python": sys.version.split()[0],
            "пункты": items, "всё_готово": not need,
            "осталось": len(need)}
