#!/usr/bin/env python3
"""Настройка рабочего места на точке. Логика здесь, а не в .bat —
по той же причине: cmd читает .bat в OEM-866 и ломает кириллицу.
"""
import os, sys, webbrowser

if os.name == "nt":
    os.system("chcp 65001 >nul 2>&1")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
AMDS = "https://support.apple.com/ru-ru/106372"


def main():
    print("=" * 52)
    print("  PINTEL ПРОВЕРКА — настройка рабочего места")
    print("=" * 52)
    try:
        from core.setup import check
    except Exception as e:
        print(f"\n  Не удалось загрузить проверку: {e}")
        print("  Похоже, файлы программы повреждены — скачай дистрибутив заново.")
        return 1

    r = check()
    print(f"  Система: {r['система']}, Python {r['python']}\n")

    надо = []
    for i in r["пункты"]:
        знак = "[ok]" if i["готово"] else ("[--]" if i.get("необязательно") else "[!!]")
        print(f"  {знак} {i['что']}")
        if i["где"]:
            print(f"        {i['где']}")
        if not i["готово"] and i.get("как_починить"):
            for строка in i["как_починить"].split(". "):
                if строка.strip():
                    print(f"        {строка.strip()}")
            if not i.get("необязательно"):
                надо.append(i)

    print()
    if r["всё_готово"]:
        print("  ВСЁ ГОТОВО. Подключи телефон кабелем, разблокируй экран")
        print("  и нажми на нём «Доверять». Затем запусти PintelCheck.")
    else:
        print(f"  ОСТАЛОСЬ СДЕЛАТЬ: {r['осталось']} — смотри выше.")
        # Страницу Apple открываем только если дело в драйвере
        if any("Драйвер" in i["что"] for i in надо):
            print("  Открываю страницу Apple с iTunes — там же драйвер USB.")
            print("  После установки ПЕРЕЗАГРУЗИ компьютер и запусти это снова.")
            try:
                webbrowser.open(AMDS)
            except Exception:
                print(f"  Открой вручную: {AMDS}")
    return 0


if __name__ == "__main__":
    code = main()
    try:
        input("\nНажми Enter, чтобы закрыть…")
    except EOFError:
        pass
    sys.exit(code)
