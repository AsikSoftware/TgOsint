# -*- coding: utf-8 -*-
"""NANDInfo — 52 КБ телеметрии контроллера памяти из домена disk_usage.

Формат: подряд записи «ключ u32 LE, количество u32 LE, count × u64 LE».
Запись key=0,count=0 встречается В СЕРЕДИНЕ — это не конец. Идём до конца
буфера; правильность разбора проверяется тем, что остатка нет.

Ключи (см. заметки прошлой сессии):
  0x2a8 — текстовая версия прошивки контроллера (обязана совпасть с
          Firmware Revision узла NVMe — иначе парсер врёт),
  0x038 — дата появления NAND, 0x039 — время последнего СНИМКА статистики
          (не время чтения: первое чтение бывает на дни старее),
  0x03a — секунды с последнего сброса статистики, 0x031–0x034 — геометрия.
"""
import struct


def parse(blob):
    """→ (records {key: [values]}, остаток_байт). Остаток != 0 — разбор неверен."""
    if not blob:
        return {}, 0
    b = bytes(blob)
    recs, p, n = {}, 0, len(b)
    while p + 8 <= n:
        key, count = struct.unpack_from("<II", b, p)
        p += 8
        if count > (n - p) // 8:
            break                          # повреждённая запись — дальше мусор
        vals = list(struct.unpack_from("<%dQ" % count, b, p)) if count else []
        p += 8 * count
        recs.setdefault(key, []).extend(vals)
    return recs, n - p


def _text(vals):
    """u64-слова как ASCII-строка (0x2a8 — версия прошивки)."""
    out = b"".join(struct.pack("<Q", v) for v in vals)
    return out.rstrip(b"\x00").decode("ascii", "replace")


def summarize(blob, nvme_firmware=None):
    recs, rest = parse(blob)
    fw = _text(recs[0x2a8]) if recs.get(0x2a8) else ""
    ok = bool(recs) and rest == 0
    # Контроллер отдаёт прошивку обрезанной («532.140.»), NANDInfo — полной
    # («532.140.2»): сравниваем по префиксу, иначе ложная тревога.
    a, b = fw.strip().rstrip("."), str(nvme_firmware or "").strip().rstrip(".")
    consistent = None if not (a and b) else (a.startswith(b) or b.startswith(a))
    return {
        "записей": len(recs),
        "остаток_байт": rest,
        "разбор_верен": ok,
        "прошивка": fw,
        "прошивка_совпала_с_nvme": consistent,
        "nand_появился": recs.get(0x038, [None])[0],
        "снимок_статистики": recs.get(0x039, [None])[0],
        "сброс_статистики_сек": recs.get(0x03a, [None])[0],
    }
