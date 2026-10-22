#!/usr/bin/env python3
"""Сборка программы. Вся логика здесь, а не в .bat — намеренно.

Файлы .bat читаются командной строкой Windows в кодировке OEM-866, а не UTF-8.
Русский текст в .bat рассыпается, и обрывки слов cmd принимает за команды —
именно так первая версия и развалилась. Python с UTF-8 не спорит, поэтому
.bat оставлен английским и пустым, а говорит с человеком этот файл.
"""
import os, subprocess, sys

if os.name == "nt":                      # консоль Windows: включаем UTF-8
    os.system("chcp 65001 >nul 2>&1")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)

# Пишем журнал С САМОГО НАЧАЛА. Если программа упадёт на первой строке,
# окно закроется, и без файла причину будет не найти — так уже было.
ЖУРНАЛ = os.path.join(HERE, "build_log.txt")


def запиши(текст):
    try:
        with open(ЖУРНАЛ, "a", encoding="utf-8", errors="replace") as f:
            f.write(текст + "\n")
    except Exception:
        pass


def скажи(*части):
    текст = " ".join(str(c) for c in части)
    print(текст, flush=True)
    запиши(текст)


def шаг(n, всего, текст):
    скажи(f"\n[{n}/{всего}] {текст}")


def main():
    скажи("=" * 52)
    скажи("  PINTEL ПРОВЕРКА — сборка программы")
    скажи("=" * 52)
    скажи(f"  Python {sys.version.split()[0]}")
    скажи(f"  Папка  {HERE}")

    шаг(1, 3, "Ставлю PyInstaller…")
    r = subprocess.run([sys.executable, "-m", "pip", "install", "--quiet",
                        "--upgrade", "pyinstaller"])
    if r.returncode:
        скажи("  Не удалось поставить PyInstaller.")
        скажи("  Проверь интернет и права. Если компьютер за прокси —")
        скажи("  попроси администратора настроить pip.")
        return 1
    скажи("  готово")

    шаг(2, 3, "Проверяю программы для чтения телефона…")
    exe = "idevice_id.exe" if os.name == "nt" else "idevice_id"
    if os.path.isfile(os.path.join("bin", exe)):
        скажи("  папка bin на месте")
    else:
        скажи("  ВНИМАНИЕ: папки bin с libimobiledevice нет.")
        скажи("  Программа соберётся, но телефон видеть НЕ БУДЕТ.")
        скажи("  Положи в bin: idevice_id.exe, ideviceinfo.exe,")
        скажи("  idevicediagnostics.exe, idevicesyslog.exe и их DLL,")
        скажи("  затем собери заново.")

    шаг(3, 3, "Собираю. Это пара минут…")
    # Пишем весь вывод в файл: окно может закрыться или прокрутиться, и тогда
    # причина сбоя теряется — а без неё починить нечего.
    лог = os.path.join(HERE, "build_log.txt")
    with open(лог, "w", encoding="utf-8", errors="replace") as f:
        f.write(f"Python {sys.version}\nПапка {HERE}\n\n")
        f.flush()
        r = subprocess.run([sys.executable, "-m", "PyInstaller",
                            "--clean", "--noconfirm", "PintelCheck.spec"],
                           stdout=f, stderr=subprocess.STDOUT, text=True)
    if r.returncode:
        скажи("\n  СБОРКА НЕ УДАЛАСЬ.")
        скажи(f"  Весь вывод записан в файл: {лог}")
        скажи("  Последние строки:")
        try:
            хвост = open(лог, encoding="utf-8", errors="replace").read().strip().split("\n")[-12:]
            for строка in хвост:
                скажи("    " + строка[:150])
        except Exception:
            pass
        скажи("\n  Пришли этот файл — по нему видно, что именно не вышло.")
        return 1
    скажи("  собралось")

    out = os.path.join(HERE, "dist", "PintelCheck")
    # Проверяем, что файл ДЕЙСТВИТЕЛЬНО появился: PyInstaller умеет завершиться
    # без ошибки, не создав результат, и тогда «готово» вводило бы в заблуждение.
    имя = "PintelCheck.exe" if os.name == "nt" else "PintelCheck"
    путь = os.path.join(out, имя)
    if not os.path.isfile(путь):
        скажи("\n  Сборка прошла, но файла нет по адресу:")
        скажи("  " + путь)
        скажи("  Что лежит в dist:")
        try:
            for корень, папки, файлы in os.walk(os.path.join(HERE, "dist")):
                for f in файлы[:10]:
                    скажи("    " + os.path.join(корень, f))
        except Exception:
            скажи("    папки dist нет вовсе")
        скажи("\n  Пришли build_log.txt — по нему видно причину.")
        return 1
    скажи("\n" + "=" * 52)
    скажи("  ГОТОВО. Программа здесь:")
    скажи("  " + путь)
    скажи(f"  размер: {os.path.getsize(путь)//1024} КБ")
    скажи()
    скажи("  На точку копируй ВСЮ папку PintelCheck целиком,")
    скажи("  а не один файл: рядом с программой лежат интерфейс,")
    скажи("  прайс и база приёмок.")
    скажи("=" * 52)
    return 0


if __name__ == "__main__":
    try:
        open(ЖУРНАЛ, "w", encoding="utf-8").write("")   # начинаем журнал заново
    except Exception:
        pass
    запиши(f"Python {sys.version}")
    запиши(f"Папка  {HERE}")
    запиши(f"Система {os.name}")
    try:
        code = main()
    except Exception:
        import traceback
        текст = traceback.format_exc()
        запиши(текст)
        print("\n  ПРОГРАММА УПАЛА:", flush=True)
        print(текст, flush=True)
        print(f"  Подробности записаны в {ЖУРНАЛ}", flush=True)
        print("  Пришли этот файл — по нему видно причину.", flush=True)
        code = 1
    try:
        input("\nНажми Enter, чтобы закрыть…")
    except EOFError:
        pass
    sys.exit(code)
