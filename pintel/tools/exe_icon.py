# -*- coding: utf-8 -*-
"""Проверка сборки: в exe зашит НАШ значок, а не заглушка PyInstaller.

    python tools/exe_icon.py dist\\pintel-kiosk\\pintel-kiosk.exe [ещё.exe …]

Значок у exe пропадал дважды и оба раза молча: сборка зелёная, а в Проводнике серая
заглушка. Поэтому после сборки сверяем побайтно — каждый кадр `icon.ico` обязан лежать
среди ресурсов RT_ICON собранного файла. Нужен pefile (приходит вместе с PyInstaller).
"""
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ЗНАЧОК = os.path.join(HERE, "..", "pintel_kiosk", "assets", "icon.ico")


def кадры_ico(путь=ЗНАЧОК):
    """[(сторона, байты кадра)] — как они лежат в файле значка."""
    with open(путь, "rb") as f:
        тело = f.read()
    _, вид, число = struct.unpack("<HHH", тело[:6])
    if вид != 1 or not число:
        raise ValueError(f"{путь}: это не значок Windows")
    кадры = []
    for n in range(число):
        w, _h, _c, _r, _pl, _bpp, размер, смещение = struct.unpack(
            "<BBBBHHII", тело[6 + 16 * n:22 + 16 * n])
        кадры.append((w or 256, тело[смещение:смещение + размер]))
    return кадры


def значки_exe(путь):
    """Все ресурсы RT_ICON исполняемого файла, как есть."""
    import pefile
    pe = pefile.PE(путь, fast_load=True)
    pe.parse_data_directories(
        directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]])
    куски = []
    for вид in getattr(pe, "DIRECTORY_ENTRY_RESOURCE", None).entries if hasattr(
            pe, "DIRECTORY_ENTRY_RESOURCE") else []:
        if вид.id != pefile.RESOURCE_TYPE["RT_ICON"]:
            continue
        for имя in вид.directory.entries:
            for язык in имя.directory.entries:
                d = язык.data.struct
                куски.append(pe.get_data(d.OffsetToData, d.Size))
    return куски


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    наши = кадры_ico()
    беда = 0
    for exe in argv:
        есть = set(значки_exe(exe))
        нет = [сторона for сторона, данные in наши if данные not in есть]
        if нет:
            беда = 1
            print(f"::error::{exe}: наш значок не зашит (нет кадров {нет}; значков в файле: {len(есть)})")
        else:
            print(f"{exe}: значок на месте, кадров {len(наши)}")
    return беда


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
