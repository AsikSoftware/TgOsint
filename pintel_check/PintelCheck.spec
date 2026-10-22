# -*- mode: python ; coding: utf-8 -*-
# Общий файл сборки для Windows и macOS. Зависимостей у программы нет,
# поэтому собирается всё, что нужно, одним файлом.
#
# Написан под PyInstaller 6: старые параметры (block_cipher, a.zipped_data,
# win_no_prefer_redirects) из него убраны — шестая версия на них падает.
import os

datas = [
    ('qml', 'qml'),                      # киоск-интерфейс (Qt Quick)
    ('web', 'web'),                      # логотип и иконка
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
                   'core.price', 'core.store', 'core.server', 'core.setup',
                   'core.gsheet', 'backend',
                   'PySide6.QtQuick', 'PySide6.QtQuickControls2'],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    # Лишние куски Qt не тащим; QtQml/QtQuick нужны киоску.
    # cryptography (14 МБ) не нужна: google-auth сам переключается на чистый
    # python-rsa, когда её нет.
    excludes=['tkinter', 'unittest', 'pydoc', 'doctest', 'cryptography',
              'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
              'PySide6.QtMultimedia', 'PySide6.QtSql', 'PySide6.QtTest',
              'PySide6.QtPdf', 'PySide6.Qt3DCore'],
    noarchive=False,
)
# Хук PySide6 тащит ВЕСЬ Qt (3D, WebEngine, мультимедиа, переводы) — больше
# 500 МБ. Киоску нужен только стек Quick: режем по спискам жёстко.
def _keep(entry):
    dest = str(entry[0]).replace('\\', '/').lower()
    if 'pyside6/qml/' in dest:
        tail = dest.split('pyside6/qml/', 1)[1]
        if tail.startswith('qtquick3d'):
            return False
        return tail.startswith(('qtquick', 'qtqml'))
    bad = ('webengine', 'quick3d', 'qt63d', 'charts', 'datavisualization',
           'multimedia', 'qt6pdf', 'qt6test', 'sensors', 'qt6location',
           'positioning', 'virtualkeyboard', 'remoteobjects', 'scxml',
           'opengl32sw', 'qt6designer', 'qt6help', 'lupdate', 'lrelease',
           'assistant', 'linguist', 'translations/', 'avcodec', 'avformat',
           'avutil', 'swscale', 'swresample', 'qt6graphs', 'qt6spatialaudio',
           'qt6texttospeech', 'qt6serialport', 'qt6serialbus', 'qt6nfc',
           'qt6bluetooth', 'qt6websockets', 'qt6webchannel', 'qt6webview',
           'qt6statemachine', 'qt6quicktimeline')
    return not any(b in dest for b in bad)

a.binaries = [e for e in a.binaries if _keep(e)]
a.datas = [e for e in a.datas if _keep(e)]

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
