"""Вердикт Apple по запчастям — тот самый экран «Запчасти и история обслуживания».

По USB сам вердикт не отдаётся: ни lockdown-домены (перебрано ~77), ни
IORegistry (перечислено 868-959 узлов на семи аппаратах) его не содержат.
Но считает его демон mobilerepaird, и он пишет результат в системный журнал,
а журнал по кабелю читается. Демон просыпается на ПЕРЕХОД в раздел — просто
открытый экран не годится, Настройки кэшируют ответ.
"""
import html, os, re, subprocess, time
from .device import _tool, NOWIN

RU = {"Battery": "Аккумулятор", "Display": "Экран", "Camera": "Камера",
      "FaceID": "Face ID", "MTUB": "Верхний модуль", "LogicBoard": "Материнская плата",
      "BackGlass": "Заднее стекло", "Enclosure": "Корпус", "RearSystem": "Задняя система"}

# Код 1029 встречался и как MTUB, и как LogicBoard — опираемся на ИМЯ, не на код.
ITEM = re.compile(r"componentName:(\w+): componentType:(\d+): isRepaired:(\d): "
                  r"isUsed:(\d): repairDate:(.*?):\"?")

def parse(text):
    items = {}
    for m in ITEM.finditer(text):
        comp, code, rep, used, date = m.groups()
        date = re.sub(r"\\U([0-9a-fA-F]{4})", lambda g: chr(int(g.group(1), 16)), date.strip())
        if date in ("(null)", ""):
            date = ""
        if items.get(comp, {}).get("дата") and not date:
            continue
        items[comp] = {"деталь": RU.get(comp, comp), "код": int(code),
                       "меняли": rep == "1", "бу": used == "1", "дата": date}
    return items

def capture(udid, seconds=60, on_tick=None, keep_going=None):
    """Слушает журнал и ждёт записей. Возвращает (items, сырой_текст).

    keep_going — функция «продолжать?»: киоск слушает непрерывно, пока
    телефон на проводе, а не разовые 60 секунд. Проверяется каждую строку.
    """
    t = _tool("idevicesyslog")
    if not t:
        return {}, ""
    p = subprocess.Popen([t, "-u", udid], stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, text=True, errors="replace",
                         bufsize=1, **NOWIN)
    buf, found = [], {}
    start = time.time()
    try:
        while time.time() - start < seconds:
            if keep_going and not keep_going():
                break
            line = p.stdout.readline()
            if not line:
                break
            if "CRRepairHistoryItem" in line:
                buf.append(line)
                found = parse("".join(buf))
                if found:
                    # добираем ещё немного: записи идут пачкой
                    deadline = time.time() + 2
                    while time.time() < deadline:
                        l2 = p.stdout.readline()
                        if not l2:
                            break
                        if "CRRepairHistoryItem" in l2:
                            buf.append(l2)
                    return parse("".join(buf)), "".join(buf)
            if on_tick:
                on_tick(int(time.time() - start))
    finally:
        # p.kill(), не SIGKILL: на Windows нет signal.SIGKILL, и слушатель
        # оставался жить — повторный захват после этого молчал. Тот самый баг.
        try:
            p.kill()
        except Exception:
            pass
    return found, "".join(buf)
