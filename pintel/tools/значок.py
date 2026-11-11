# -*- coding: utf-8 -*-
"""Значок программы: знак на белой плитке → `pintel_kiosk/assets/icon.ico`.

    python tools/значок.py            # нужен Pillow; в сборку он не входит

Почему файл собирается руками, а не `Image.save("icon.ico")`: Pillow сжимает PNG-ом все
размеры, а Windows надёжно понимает PNG внутри значка только у кадра 256×256. С мелкими
кадрами в PNG значок у exe в Проводнике и на панели задач пропадал — вместо него стояла
пустая заглушка. Поэтому мелкие кадры пишем несжатыми (32 бита BGRA + маска), как их
ждёт Windows со времён XP, и только 256 — PNG.
"""
import io
import os
import struct

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "..", "pintel_kiosk", "assets")
РАЗМЕРЫ = (16, 20, 24, 32, 40, 48, 64, 128, 256)
БЕЛЫЙ, КАЙМА = (255, 255, 255, 255), (198, 214, 236, 255)


def плитка(сторона, знак):
    """Белая скруглённая плитка со знаком. Рисуем вчетверо крупнее и ужимаем — края ровнее.
    На мелких размерах кайму не рисуем и поля сужаем: иначе от знака остаётся точка."""
    к = 4
    s = сторона * к
    холст = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    рисуем = ImageDraw.Draw(холст)
    радиус = round(s * 0.22)
    if сторона >= 48:
        рисуем.rounded_rectangle((0, 0, s - 1, s - 1), radius=радиус, fill=БЕЛЫЙ,
                                 outline=КАЙМА, width=max(к, round(s * 0.012)))
        поле = round(s * 0.12)
    else:
        рисуем.rounded_rectangle((0, 0, s - 1, s - 1), radius=радиус, fill=БЕЛЫЙ)
        поле = round(s * 0.07)
    # именно resize, не thumbnail: тот только уменьшает, и на крупных кадрах знак
    # оставался бы в половину плитки
    доля = min((s - 2 * поле) / знак.size[0], (s - 2 * поле) / знак.size[1])
    м = знак.resize((round(знак.size[0] * доля), round(знак.size[1] * доля)), Image.LANCZOS)
    холст.alpha_composite(м, ((s - м.size[0]) // 2, (s - м.size[1]) // 2))
    return холст.resize((сторона, сторона), Image.LANCZOS)


def кадр_bmp(im):
    """Кадр значка без сжатия: заголовок с удвоенной высотой, BGRA снизу вверх, маска."""
    w, h = im.size
    точки = im.tobytes("raw", "BGRA")
    строки = [точки[y * w * 4:(y + 1) * w * 4] for y in range(h)]
    маска_строка = b"\x00" * (((w + 31) // 32) * 4)          # прозрачность — в альфа-канале
    заголовок = struct.pack("<IiiHHIIiiII", 40, w, h * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    return заголовок + b"".join(reversed(строки)) + маска_строка * h


def кадр_png(im):
    b = io.BytesIO()
    im.save(b, format="PNG", optimize=True)
    return b.getvalue()


def собрать(путь=None):
    знак = Image.open(os.path.join(ASSETS, "logo_mark.png")).convert("RGBA")
    знак = знак.crop(знак.getbbox())                          # без прозрачных полей вокруг
    кадры = []
    for сторона in РАЗМЕРЫ:
        im = плитка(сторона, знак)
        кадры.append((сторона, кадр_png(im) if сторона >= 256 else кадр_bmp(im)))
    шапка = struct.pack("<HHH", 0, 1, len(кадры))
    смещение = 6 + 16 * len(кадры)
    оглавление, тело = b"", b""
    for сторона, данные in кадры:
        оглавление += struct.pack("<BBBBHHII", сторона % 256, сторона % 256, 0, 0, 1, 32,
                                  len(данные), смещение + len(тело))
        тело += данные
    путь = путь or os.path.join(ASSETS, "icon.ico")
    with open(путь, "wb") as f:
        f.write(шапка + оглавление + тело)
    return путь


if __name__ == "__main__":
    print("значок:", собрать())
