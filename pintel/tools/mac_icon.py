# -*- coding: utf-8 -*-
"""Значок для маковской сборки: icon.ico → icon.icns.

Зачем отдельный файл. Мак не умеет windows-овский .ico и без .icns ставит программе
серую заглушку — на точке это выглядит как чужая, непонятная программа. Держать в репозитории
второй файл со значком не хотим: он разъедется с первым. Поэтому .icns собирается из того же
.ico перед сборкой — и на машине сборки, и на маке разработчика.

Запуск: python tools/mac_icon.py pintel_kiosk/assets/icon.ico pintel_kiosk/assets/icon.icns
"""
import os
import shutil
import subprocess
import sys
import tempfile

# Что мак просит у .icns: размер и имя внутри набора (обычный и «для retina»).
РАЗМЕРЫ = ((16, "16x16"), (32, "16x16@2x"), (32, "32x32"), (64, "32x32@2x"),
           (128, "128x128"), (256, "128x128@2x"), (256, "256x256"), (512, "256x256@2x"),
           (512, "512x512"), (1024, "512x512@2x"))


def собрать(ico: str, icns: str) -> str:
    from PIL import Image

    картинка = Image.open(ico)
    # Самый большой кадр .ico — 256×256; меньшие мак дорисует сам, большие тянем из него.
    кадры = sorted(картинка.ico.sizes()) if hasattr(картинка, "ico") else [картинка.size]
    картинка = картинка.resize(кадры[-1]) if картинка.size != кадры[-1] else картинка
    if hasattr(картинка, "ico"):
        картинка = картинка.ico.getimage(кадры[-1])
    картинка = картинка.convert("RGBA")

    папка = tempfile.mkdtemp()
    набор = os.path.join(папка, "icon.iconset")
    os.makedirs(набор, exist_ok=True)
    try:
        for сторона, имя in РАЗМЕРЫ:
            картинка.resize((сторона, сторона), Image.LANCZOS).save(
                os.path.join(набор, f"icon_{имя}.png"))
        os.makedirs(os.path.dirname(os.path.abspath(icns)) or ".", exist_ok=True)
        subprocess.check_call(["iconutil", "-c", "icns", набор, "-o", icns])
    finally:
        shutil.rmtree(папка, ignore_errors=True)
    return icns


if __name__ == "__main__":
    если = sys.argv[1:]
    ico = если[0] if если else "pintel_kiosk/assets/icon.ico"
    icns = если[1] if len(если) > 1 else "pintel_kiosk/assets/icon.icns"
    print("значок для мака:", собрать(ico, icns))
