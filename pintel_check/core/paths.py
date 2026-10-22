"""Пути к файлам. Внутри собранной программы они другие, и это не мелочь.

PyInstaller распаковывает содержимое во ВРЕМЕННУЮ папку, которая стирается
при выходе. Если положить туда базу приёмок, она пропадёт после закрытия
программы — каждый рабочий день начинался бы с пустой базы.
А прайс, лежащий внутри exe, магазин не сможет отредактировать.

Поэтому: читаемое-только (интерфейс, справочник моделей) берём изнутри,
а то, что меняется (база, прайс, настройки), держим РЯДОМ С ПРОГРАММОЙ.
"""
import os, sys

def _frozen():
    return getattr(sys, "frozen", False)

def bundled(*parts):
    """Файл из комплекта: только для чтения."""
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)

def beside(*parts):
    """Файл рядом с программой: переживает перезапуск, доступен для правки."""
    if _frozen():
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)

def writable(name, default_from_bundle=None):
    """Файл, который может меняться. Если рядом с программой его нет,
    а в комплекте есть образец — копируем образец наружу, чтобы его
    можно было открыть и отредактировать."""
    p = beside(name)
    if not os.path.exists(p) and default_from_bundle:
        src = bundled(default_from_bundle)
        if os.path.exists(src):
            os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
            with open(src, "rb") as a, open(p, "wb") as b:
                b.write(a.read())
    return p
