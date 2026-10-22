#!/usr/bin/env python3
"""Pintel Проверка — киоск приёмки iPhone. Точка входа.

Полноэкранное приложение (Qt Quick): логотип на весь экран, телефон
подключили — проверка запускается сама. Запуск из исходников:
    pip install pyside6 google-auth requests
    python3 app.py

Флаги:
  --selftest   построить сцену без экрана и проверить инструменты
               (для автосборки), код выхода 0/1
"""
import json, os, sys

if os.name == "nt":
    os.system("chcp 65001 >nul 2>&1")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SELFTEST = "--selftest" in sys.argv
if SELFTEST:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("QT_QUICK_BACKEND", "software")


def _crash_log(text):
    try:
        from core.paths import beside
        with open(beside("app_log.txt"), "a", encoding="utf-8", errors="replace") as f:
            f.write(text + "\n")
    except Exception:
        pass


def _hard_exit(code):
    """Выход, минуя уборку Qt: без экрана она падает (segfault / 0xC0000409)
    уже ПОСЛЕ теста, и код выхода врал бы."""
    sys.stdout.flush()
    if os.name == "nt":
        import ctypes
        ctypes.windll.kernel32.TerminateProcess(
            ctypes.windll.kernel32.GetCurrentProcess(), code)
    os._exit(code)


def main():
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QGuiApplication, QIcon
    from PySide6.QtQml import QQmlApplicationEngine

    from backend import Backend
    from core import setup
    from core.paths import bundled

    app = QGuiApplication(sys.argv)
    ico = bundled("web", "icon.ico")
    if os.path.exists(ico):
        app.setWindowIcon(QIcon(ico))

    engine = QQmlApplicationEngine()
    backend = Backend(watch=not SELFTEST)
    engine.rootContext().setContextProperty("backend", backend)
    engine.rootContext().setContextProperty(
        "logoUrl", QUrl.fromLocalFile(bundled("web", "logo.png")))
    engine.load(QUrl.fromLocalFile(bundled("qml", "Main.qml")))
    ui_ok = bool(engine.rootObjects())

    if SELFTEST:
        r = setup.check()
        tools = [i for i in r["пункты"] if str(i["что"]).startswith("idevice")]
        ok = ui_ok and len(tools) == 4 and all(i["готово"] for i in tools)
        line = ("SELFTEST OK " if ok else "SELFTEST FAIL ") + json.dumps(
            {"ui": "ok" if ui_ok else "НЕ ЗАГРУЗИЛСЯ",
             "готовы": [i["что"] for i in tools if i["готово"]],
             "не_готовы": [i["что"] for i in tools if not i["готово"]]},
            ensure_ascii=False)
        print(line, flush=True)
        try:
            from core.paths import beside
            open(beside("selftest.txt"), "w", encoding="utf-8").write(line + "\n")
        except Exception:
            pass
        _hard_exit(0 if ok else 1)

    if not ui_ok:
        raise RuntimeError("Интерфейс (qml/Main.qml) не загрузился — смотри app_log.txt")
    sys.exit(app.exec())


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
                    None, "Программа упала. Подробности в app_log.txt рядом с ней.\n\n"
                    + tb[-600:], "Pintel Проверка", 0x10)
            except Exception:
                pass
        sys.exit(1)
