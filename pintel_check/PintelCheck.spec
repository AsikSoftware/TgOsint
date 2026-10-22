# -*- mode: python ; coding: utf-8 -*-
# Общий файл сборки для Windows и macOS. Зависимостей у программы нет,
# поэтому собирается всё, что нужно, одним файлом.
import os, sys
block_cipher = None

datas = [
    ('web', 'web'),                      # интерфейс
    ('core/models.json', 'core'),        # справочник моделей
    ('prices.json', '.'),                # прайс
]
# Бинарники libimobiledevice кладём внутрь, если папка есть. Под Windows
# она обязательна: без неё программа не увидит телефон.
if os.path.isdir('bin'):
    datas.append(('bin', 'bin'))

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=['core.device', 'core.verdict', 'core.apple', 'core.sickw',
                   'core.price', 'core.store', 'core.server', 'core.setup'],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['tkinter', 'unittest', 'pydoc', 'doctest'],
    win_no_prefer_redirects=False, win_private_assemblies=False,
    cipher=block_cipher, noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# Собираем В ПАПКУ, а не одним файлом. Один файл распаковывает ~10 МБ при
# КАЖДОМ запуске: замерено 15 секунд молчания до старта. На точке продавец
# за это время решит, что программа сломалась. Папка стартует мгновенно.
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='PintelCheck',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=True,
    upx_exclude=[], runtime_tmpdir=None,
    console=True,            # окно консоли нужно: в нём видно адрес и ошибки
    disable_windowed_traceback=False, argv_emulation=False,
    target_arch=None, codesign_identity=None, entitlements_file=None,
    # Иконка ТОЛЬКО .ico: PyInstaller под Windows на .png падает с ошибкой,
    # а на macOS молча проглатывает — поэтому здесь собиралось, а на Windows нет.
    # Нет .ico — собираем без иконки, это не повод ронять сборку.
    icon=('web/icon.ico' if os.path.exists('web/icon.ico') else None),
)

coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=True, upx_exclude=[],
    name='PintelCheck',
)
