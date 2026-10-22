#!/usr/bin/env python3
"""Pintel Проверка — приёмка iPhone. Точка входа.

Запуск из исходников:  python3 app.py
Сборка в exe (Windows): см. README.md
"""
import os, sys, threading, webbrowser

# Русский текст в консоли Windows. Без этого собранный exe ПАДАЕТ на первом
# же print: консоль живёт в cp1252/cp866, а PyInstaller игнорирует PYTHONUTF8.
# errors="replace" — чтобы вывод не мог уронить программу ни при какой кодировке.
if os.name == "nt":
    os.system("chcp 65001 >nul 2>&1")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.server import serve

PORT = int(os.environ.get("PINTEL_PORT", "8765"))

def main():
    # flush обязателен: в собранном виде вывод буферизуется, и продавец
    # не видит ни адреса, ни ошибок — окно просто молчит.
    say = lambda *a: print(*a, flush=True)
    say("Pintel Проверка — запускаюсь…")
    try:
        srv = serve(PORT)
    except OSError as e:
        say(f"\nНе удалось занять порт {PORT}: {e}")
        say("Скорее всего программа уже запущена. Закрой лишнее окно и запусти снова.")
        input("\nНажми Enter, чтобы закрыть…")
        return
    url = f"http://127.0.0.1:{PORT}/"
    say("")
    say("  Готово. Открой в браузере:  " + url)
    say("  Это окно не закрывай — программа работает в нём.")
    say("")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановлено.")

if __name__ == "__main__":
    main()
