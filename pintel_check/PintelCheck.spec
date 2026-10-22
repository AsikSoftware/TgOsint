# -*- mode: python ; coding: utf-8 -*-
# Общий файл сборки для Windows и macOS. Зависимостей у программы нет,
# поэтому собирается всё, что нужно, одним файлом.
#
# Написан под PyInstaller 6: старые параметры (block_cipher, a.zipped_data,
# win_no_prefer_redirects) из него убраны — шестая версия на них падает.
import os

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
                   'core.price', 'core.store', 'core.server', 'core.setup', 'ui'],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    # Лишние куски Qt не тащим: нужен только виджетный стек.
    excludes=['tkinter', 'unittest', 'pydoc', 'doctest',
              'PySide6.QtNetwork', 'PySide6.QtQml', 'PySide6.QtQuick',
              'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
              'PySide6.QtMultimedia', 'PySide6.QtSql', 'PySide6.QtTest',
              'PySide6.QtPdf', 'PySide6.QtOpenGL', 'PySide6.Qt3DCore'],
    noarchive=False,
)
pyz = PYZ(a.pure)

# Собираем В ПАПКУ, а не одним файлом. Один файл распаковывает ~10 МБ при
# КАЖДОМ запуске: замерено 15 секунд молчания до старта. На точке продавец
# за это время решит, что программа сломалась. Папка стартует мгновенно.
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='PintelCheck',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=True,
    upx_exclude=[], runtime_tmpdir=None,
    console=False,           # полноценный клиент: чёрное окно консоли не нужно,
                             # ошибки пишутся в app_log.txt рядом с программой
    disable_windowed_traceback=False, argv_emulation=False,
    target_arch=None, codesign_identity=None, entitlements_file=None,
    # Иконка ТОЛЬКО .ico: PyInstaller под Windows на .png падает с ошибкой,
    # а на macOS молча проглатывает — поэтому здесь собиралось, а на Windows нет.
    # Нет .ico — собираем без иконки, это не повод ронять сборку.
    icon=('web/icon.ico' if os.path.exists('web/icon.ico') else None),
)

coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=True, upx_exclude=[],
    name='PintelCheck',
)
