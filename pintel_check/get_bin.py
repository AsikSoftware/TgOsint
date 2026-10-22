#!/usr/bin/env python3
"""Собирает папку bin из установленного MSYS2.

Почему так, а не «скачать готовое»: официальных сборок libimobiledevice под
Windows нет, есть только сторонние. Класть на кассовый компьютер исполняемые
файлы неизвестного происхождения — плохая идея, поэтому источник выбираете вы:
ставите MSYS2 с их сайта, а этот скрипт только раскладывает уже установленное.

Зависимости (DLL) определяются чтением таблицы импорта самих exe, а не
угадыванием списка: угаданный список рано или поздно окажется неполным,
и программа упадёт на точке с невнятной ошибкой.
"""
import os, shutil, struct, subprocess, sys

if os.name == "nt":
    os.system("chcp 65001 >nul 2>&1")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
НУЖНЫ = ["idevice_id", "ideviceinfo", "idevicediagnostics", "idevicesyslog"]
ПАПКИ_MSYS = [r"C:\msys64\ucrt64\bin", r"C:\msys64\mingw64\bin",
              r"C:\msys64\clang64\bin", r"C:\msys2\ucrt64\bin"]
ПАКЕТ = "mingw-w64-ucrt-x86_64-libimobiledevice"


def импорты_pe(путь):
    """Имена DLL, которые нужны этому exe/dll. Читаем таблицу импорта PE."""
    try:
        d = open(путь, "rb").read()
        if d[:2] != b"MZ":
            return []
        pe = struct.unpack_from("<I", d, 0x3C)[0]
        if d[pe:pe+4] != b"PE\0\0":
            return []
        маш = struct.unpack_from("<H", d, pe+4)[0]
        секций = struct.unpack_from("<H", d, pe+6)[0]
        разм_опц = struct.unpack_from("<H", d, pe+20)[0]
        опц = pe + 24
        magic = struct.unpack_from("<H", d, опц)[0]
        сдвиг_дир = 96 if magic == 0x10b else 112      # PE32 или PE32+
        import_rva = struct.unpack_from("<I", d, опц + сдвиг_дир + 8)[0]
        if not import_rva:
            return []
        секции = []
        s0 = опц + разм_опц
        for i in range(секций):
            о = s0 + i*40
            va = struct.unpack_from("<I", d, о+12)[0]
            sz = struct.unpack_from("<I", d, о+16)[0]
            raw = struct.unpack_from("<I", d, о+20)[0]
            секции.append((va, sz, raw))

        def в_файл(rva):
            for va, sz, raw in секции:
                if va <= rva < va + max(sz, 1):
                    return raw + (rva - va)
            return None

        имена, п = [], в_файл(import_rva)
        if п is None:
            return []
        while True:
            блок = d[п:п+20]
            if len(блок) < 20 or блок == b"\0"*20:
                break
            имя_rva = struct.unpack_from("<I", блок, 12)[0]
            if not имя_rva:
                break
            о = в_файл(имя_rva)
            if о is not None:
                конец = d.index(b"\0", о)
                имена.append(d[о:конец].decode("ascii", "replace"))
            п += 20
        return имена
    except Exception:
        return []


def main():
    print("=" * 52)
    print("  Сбор папки bin для Pintel Проверки")
    print("=" * 52)

    if os.name != "nt":
        print("\n  Этот скрипт для Windows — там нужны .exe и .dll.")
        print("  На macOS libimobiledevice ставится так:  brew install libimobiledevice")
        return 1

    источник = next((p for p in ПАПКИ_MSYS if os.path.isdir(p)), None)
    if not источник:
        print("\n  MSYS2 не найден.")
        print("  Поставь его с официального сайта:  https://www.msys2.org/")
        print("  Потом открой «MSYS2 UCRT64» и выполни:")
        print(f"      pacman -S {ПАКЕТ}")
        print("  После этого запусти этот скрипт снова.")
        return 1
    print(f"\n  MSYS2: {источник}")

    нет = [n for n in НУЖНЫ if not os.path.isfile(os.path.join(источник, n + ".exe"))]
    if нет:
        print(f"  Не хватает программ: {', '.join(нет)}")
        print("  Открой «MSYS2 UCRT64» и выполни:")
        print(f"      pacman -S {ПАКЕТ}")
        return 1

    # Собираем всё дерево зависимостей, а не только первый уровень.
    bin_dir = os.path.join(HERE, "bin")
    os.makedirs(bin_dir, exist_ok=True)
    очередь = [os.path.join(источник, n + ".exe") for n in НУЖНЫ]
    взято, системные = set(), 0
    while очередь:
        файл = очередь.pop()
        имя = os.path.basename(файл)
        if имя.lower() in взято:
            continue
        взято.add(имя.lower())
        shutil.copy2(файл, os.path.join(bin_dir, имя))
        for dll in импорты_pe(файл):
            путь = os.path.join(источник, dll)
            if os.path.isfile(путь):
                очередь.append(путь)
            else:
                системные += 1      # api-ms-*, kernel32 и прочее — есть в Windows

    exe = [f for f in os.listdir(bin_dir) if f.lower().endswith(".exe")]
    dll = [f for f in os.listdir(bin_dir) if f.lower().endswith(".dll")]
    print(f"  Скопировано: {len(exe)} программ, {len(dll)} библиотек")
    print(f"  Системных библиотек пропущено: {системные} (они есть в Windows)")

    # Проверяем на деле, а не на глаз
    проба = os.path.join(bin_dir, "idevice_id.exe")
    try:
        r = subprocess.run([проба, "-l"], capture_output=True, text=True, timeout=20)
        if r.returncode in (0, 255) or r.stdout or "no device" in (r.stderr or "").lower():
            print("  Проверка: программы запускаются ✔")
        else:
            print(f"  Проверка: запустилось, но ответило странно: {(r.stderr or '')[:80]}")
    except OSError as e:
        print(f"\n  ОШИБКА: программы не запускаются — {e}")
        print("  Значит каких-то библиотек всё же не хватает.")
        return 1
    except Exception as e:
        print(f"  Проверку выполнить не удалось: {e}")

    print(f"\n  Папка готова: {bin_dir}")
    print("  Теперь запусти BUILD.bat — программа соберётся вместе с ней.")
    return 0


if __name__ == "__main__":
    code = main()
    try:
        input("\nНажми Enter, чтобы закрыть…")
    except EOFError:
        pass
    sys.exit(code)
