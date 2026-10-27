# -*- coding: utf-8 -*-
"""Словарь ремонтного журнала Apple из прошивки — без сохранения образов на диск.

Как пользоваться:
    python tools/каталог.py iPhone16,1 26.6        # → версия, сборка, размер, ссылка
    python tools/прошивка.py "<ссылка>"            # → какие строки журнала есть в этой iOS

Зачем это в репозитории: Apple меняет формулировки в журнале с каждым крупным обновлением
(iOS 16 — systemhealth, 18 — delta components, 26 — isComponentRepairedUsing). Раньше мы
узнавали об этом только по живому аппарату на точке. Теперь новую iOS можно прочитать до
того, как такой телефон приедет: сравнить словарь с docs/RESEARCH_apple_parts.md.

Ограничение: с iOS 18 образы в прошивке зашифрованы (.dmg.aea, ключ выдаёт сервер Apple
wkms.sd.apple.com), и этот способ их не берёт. До 17.x включительно работает.

Зачем: живого телефона на нужной iOS может не быть годами, а формат журнала знать надо
сейчас. Прошивка его показывает: строки, которыми телефон пишет вердикт по деталям,
лежат в бинарниках как есть.

Что делает: читает центральный каталог IPSW, берёт образы и прогоняет каждый через поиск
строк потоком. Сжатый в zip образ (криптекс ОС, где с iOS 16 лежит общий кэш dyld)
разжимается на лету; образ без сжатия разбирается как UDIF с распаковкой кусков LZFSE.

Запуск: python прошивка.py <url ipsw> [--мин-мб 300]
"""
import plistlib
import re
import struct
import subprocess
import sys
import time
import zlib


try:
    import liblzfse                                    # нужен только для образов без сжатия
except ImportError:                                    # pragma: no cover
    liblzfse = None

URL = sys.argv[1]
МИН = int(sys.argv[sys.argv.index("--мин-мб") + 1]) if "--мин-мб" in sys.argv else 300

ИГЛЫ = (rb"systemhealth", rb"Unsealed:", rb"delta components", rb"failed preflight",
        rb"isComponentRepairedUsing", rb"CRRepairHistoryItem", rb"repairHistoryForUI",
        rb"AuthCP Components", rb"Battery Health State", rb"fetched RCHL", rb"IsServicePart",
        rb"FDRSealingStatus", rb"RCHLBasedRepairDate", rb"isTrustedForUI", rb"CRRepairHistory",
        rb"componentName", rb"isRepaired", rb"isUsed", rb"repairDate", rb"CRRepairStatus",
        rb"BatteryHealthServiceState", rb"preflightControl", rb"updateSpecifiersWith")
PATTERN = re.compile(rb"[\x20-\x7e]{0,60}(" + rb"|".join(ИГЛЫ) + rb")[\x20-\x7e]{0,60}")


def диапазон(a, b):
    return subprocess.run(["curl", "-sS", "-r", f"{a}-{b}", URL], capture_output=True, timeout=300).stdout


def длина():
    h = subprocess.run(["curl", "-sSI", URL], capture_output=True, text=True, timeout=60).stdout
    return next(int(l.split(":")[1]) for l in h.splitlines() if l.lower().startswith("content-length"))


def каталог():
    total = длина()
    tail = диапазон(total - 65536, total - 1)
    i = tail.rfind(b"PK\x05\x06")
    cd_size, cd_off = struct.unpack("<II", tail[i + 12:i + 20])
    if cd_off == 0xFFFFFFFF:
        j = tail.rfind(b"PK\x06\x06")
        cd_size, cd_off = struct.unpack("<QQ", tail[j + 40:j + 56])
    cd, p, out = диапазон(cd_off, cd_off + cd_size - 1), 0, []
    while p < len(cd) and cd[p:p + 4] == b"PK\x01\x02":
        meth, = struct.unpack("<H", cd[p + 10:p + 12])
        csize, usize = struct.unpack("<II", cd[p + 20:p + 28])
        nlen, elen, clen = struct.unpack("<HHH", cd[p + 28:p + 34])
        name = cd[p + 46:p + 46 + nlen].decode("utf-8", "replace")
        lho, = struct.unpack("<I", cd[p + 42:p + 46])
        extra = cd[p + 46 + nlen:p + 46 + nlen + elen]
        if 0xFFFFFFFF in (csize, usize, lho):
            q = 0
            while q + 4 <= len(extra):
                tag, ln = struct.unpack("<HH", extra[q:q + 4])
                if tag == 1:
                    v = struct.unpack_from("<" + "Q" * (ln // 8), extra, q + 4)
                    usize = v[0] if usize == 0xFFFFFFFF and v else usize
                    csize = v[1] if csize == 0xFFFFFFFF and len(v) > 1 else csize
                    lho = v[-1] if lho == 0xFFFFFFFF else lho
                q += 4 + ln
        out.append({"имя": name, "метод": meth, "сжат": csize, "размер": usize, "заголовок": lho})
        p += 46 + nlen + elen + clen
    return out


def данные(entry):
    """Где лежат байты записи: локальный заголовок переменной длины."""
    lh = диапазон(entry["заголовок"], entry["заголовок"] + 29)
    n2, e2 = struct.unpack("<HH", lh[26:30])
    start = entry["заголовок"] + 30 + n2 + e2
    return start, start + entry["сжат"] - 1


class Поток:
    """Образ как файл с произвольным доступом: окна по 64 МБ с повтором.

    Куски UDIF по 1–2 МБ, и запрашивать каждый отдельно — тысячи запросов на образ:
    на корневом образе (где лежит кэш до iOS 16) это десятки минут только на задержках."""
    ОКНО = 64 << 20

    def __init__(self, a, b):
        self.a, self.b, self.pos, self.buf, self.buf_at = a, b, a, b"", a

    def читать(self, off, n):
        """off — смещение внутри образа, не в архиве."""
        self.pos = self.a + off
        out = bytearray()
        while len(out) < n and self.pos <= self.b:
            if not (self.buf_at <= self.pos < self.buf_at + len(self.buf)):
                self._окно(self.pos)
            i = self.pos - self.buf_at
            take = min(n - len(out), len(self.buf) - i)
            out += self.buf[i:i + take]
            self.pos += take
        return bytes(out)

    def _окно(self, off):
        end = min(off + self.ОКНО - 1, self.b)
        for попытка in range(5):
            d = диапазон(off, end)
            if len(d) == end - off + 1:
                self.buf, self.buf_at = d, off
                return
            time.sleep(2 ** попытка)
        raise RuntimeError(f"окно {off}–{end} так и не пришло целиком")


найдено = {}


def искать(кусок, хвост):
    область = хвост + кусок
    # Сначала дешёвый поиск подстрок: на образе в 6 ГБ почти все куски пустые, и гонять по
    # каждому большой регексп с контекстом — часы. Отбираем кусок, и только его разбираем.
    if not any(г in область for г in ИГЛЫ):
        return кусок[-4096:]
    for m in PATTERN.finditer(область):
        s = m.group(0).decode("ascii", "replace").strip()
        найдено[s] = найдено.get(s, 0) + 1
    return кусок[-4096:]


def сжатый(entry):
    """Образ сжат в архиве: разжимаем поток и ищем строки прямо в нём.

    Долгое соединение рвётся (видели на половине образа), а поток zlib с середины не
    продолжить — значит при обрыве начинаем образ заново. Иначе словарь выходит неполным,
    и «строки нет в этой iOS» означало бы всего лишь «мы до неё не дочитали»."""
    a, b = данные(entry)
    нужно = entry["сжат"]
    for попытка in range(1, 4):
        proc = subprocess.Popen(["curl", "-sS", "-r", f"{a}-{b}", URL], stdout=subprocess.PIPE, bufsize=1 << 22)
        d, хвост, прочитано = zlib.decompressobj(-15), b"", 0
        while True:
            part = proc.stdout.read(1 << 22)
            if not part:
                break
            прочитано += len(part)
            хвост = искать(d.decompress(part), хвост)
        proc.kill()
        print(f"    попытка {попытка}: прочитано {прочитано / 1e9:.2f} из {нужно / 1e9:.2f} ГБ сжатых, "
              f"строк найдено {len(найдено)}", flush=True)
        if прочитано >= нужно * 0.995:
            return
        time.sleep(3 * попытка)
    print("    образ так и не дочитан целиком — словарь может быть неполным", flush=True)


def udif(entry):
    """Образ без сжатия: UDIF, распаковываем куски и ищем в них."""
    a, b = данные(entry)
    koly = диапазон(b - 511, b)
    if koly[:4] != b"koly":
        print("    не UDIF — пропускаем", flush=True)
        return
    xml_off, xml_len = struct.unpack(">QQ", koly[0xD8:0xE8])
    plist = plistlib.loads(диапазон(a + xml_off, a + xml_off + xml_len - 1))
    chunks = []
    for item in plist["resource-fork"]["blkx"]:
        mish = item["Data"]
        data_off, = struct.unpack(">Q", mish[0x18:0x20])
        n, = struct.unpack(">I", mish[0xC8:0xCC])
        for i in range(n):
            typ, _c, _s, _sc, coff, clen = struct.unpack(">IIQQQQ", mish[0xCC + i * 40:0xCC + i * 40 + 40])
            if typ in (0x80000005, 0x80000007, 0x00000001) and clen:
                chunks.append((data_off + coff, clen, typ))
    chunks.sort()
    хвост, прочитано, поток = b"", 0, Поток(a, b)
    for off, ln, typ in chunks:
        raw = поток.читать(off, ln)
        прочитано += len(raw)
        try:
            if typ == 0x80000007 and liblzfse is None:
                raise SystemExit("для образа без сжатия нужен pyliblzfse: pip install pyliblzfse")
            out = liblzfse.decompress(raw) if typ == 0x80000007 else (
                zlib.decompress(raw) if typ == 0x80000005 else raw)
        except Exception:                                        # noqa: BLE001
            continue
        хвост = искать(out, хвост)
    print(f"    прочитано {прочитано / 1e9:.2f} ГБ, найдено разных строк: {len(найдено)}", flush=True)


образы = [e for e in каталог() if e["имя"].endswith(".dmg") and e["размер"] > МИН * 1e6
          and not e["имя"].startswith("Firmware/")]
# Сначала сжатые: с iOS 16 это криптекс ОС, где и лежит общий кэш dyld со строками
# фреймворков. Корневой образ читается кусками по отдельным запросам — он последний.
образы.sort(key=lambda e: (e["метод"] == 0, -e["размер"]))
print(f"образов крупнее {МИН} МБ: {len(образы)}", flush=True)
for e in образы:
    print(f"  {e['имя']}: {e['размер'] / 1e9:.2f} ГБ, "
          f"{'без сжатия' if e['метод'] == 0 else f'метод {e['метод']}'}", flush=True)
    (udif if e["метод"] == 0 else сжатый)(e)
    if найдено:
        break                                                    # нашли — дальше смотреть незачем

print("\n=== найденные строки ===", flush=True)
for s, n in sorted(найдено.items()):
    print(f"  {n:>4}×  {s}", flush=True)
