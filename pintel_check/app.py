#!/usr/bin/env python3
"""Pintel Проверка — приёмка iPhone. Точка входа.

Настольное приложение (Qt), никакого веба: интерфейс зовёт функции core/*
напрямую. Запуск из исходников:  python3 app.py
Сборка в exe (Windows): см. README.md

Флаги:
  --selftest   построить окно без экрана и проверить инструменты
               (для автосборки), код выхода 0/1
"""
import os, sys

# Русский текст в консоли Windows, если exe запустили из cmd. Окна консоли
# у клиента нет, но защита нужна: вывод не должен уметь уронить программу.
if os.name == "nt":
    os.system("chcp 65001 >nul 2>&1")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _crash_log(text):
    """Падение — в файл рядом с программой: окна консоли нет, и без файла
    причину потом не найти."""
    try:
        from core.paths import beside
        with open(beside("app_log.txt"), "a", encoding="utf-8", errors="replace") as f:
            f.write(text + "\n")
    except Exception:
        pass


def main():
    import ui
    if "--selftest" in sys.argv:
        sys.exit(ui.selftest())
    sys.exit(ui.run())


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        import traceback
        tb = traceback.format_exc()
        _crash_log(tb)
        try:
            print(tb, flush=True)
        except Exception:
            pass
        if os.name == "nt":
            try:
                import ctypes
                ctypes.windll.user32.MessageBoxW(
                    None, "Программа упала. Подробности в app_log.txt рядом с ней.\n\n" + tb[-600:],
                    "Pintel Проверка", 0x10)
            except Exception:
                pass
        sys.exit(1)
