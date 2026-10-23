# -*- coding: utf-8 -*-
"""Вердикт Apple «Запчасти и история обслуживания» — из системного журнала.

По USB вердикт не отдаётся никем (проверено: lockdown-домены, IORegistry,
MobileGestalt — пусто; вопрос в libimobiledevice #1301 без ответа с 2022).
Но его считает демон mobilerepaird и пишет в журнал при ПЕРЕХОДЕ в раздел
Настройки → Основные → Об этом устройстве → Запчасти и история обслуживания.
Уже открытый экран отдаёт кэш — нужен именно переход внутрь.
"""
import asyncio, re, time

from pymobiledevice3.services.syslog import SyslogService

RU = {"Battery": "Аккумулятор", "Display": "Экран", "Camera": "Камера",
      "FaceID": "Face ID", "MTUB": "Верхний модуль", "LogicBoard": "Материнская плата",
      "BackGlass": "Заднее стекло", "Enclosure": "Корпус", "RearSystem": "Задняя система",
      "FrontCamera": "Фронтальная камера", "RearCamera": "Основная камера"}

# Код 1029 встречался и как MTUB, и как LogicBoard — опираемся на ИМЯ.
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


async def capture(ld, seconds=120, keep_going=None, on_tick=None):
    """Слушает журнал до записей или до истечения времени.
    Возвращает (items, сырой_текст, секунд_ждали)."""
    q = asyncio.Queue()
    state = {"svc": None, "task": None}
    notes = []

    async def start_reader():
        svc = SyslogService(ld)
        await svc.connect()

        async def reader():
            try:
                async for line in svc.watch():
                    await q.put(line)
                await q.put(EOFError("поток syslog закончился"))
            except Exception as e:                      # noqa: BLE001
                await q.put(e)
        state["svc"], state["task"] = svc, asyncio.create_task(reader())

    async def stop_reader():
        if state["task"]:
            state["task"].cancel()
        try:
            if state["svc"]:
                await state["svc"].close()
        except Exception:                               # noqa: BLE001
            pass

    await start_reader()
    buf, found = [], {}
    start = time.monotonic()
    grace_until = None
    reconnects = 0
    try:
        while True:
            now = time.monotonic()
            if grace_until and now > grace_until:
                break
            if not grace_until and (now - start > seconds or (keep_going and not keep_going())):
                break
            try:
                line = await asyncio.wait_for(q.get(), timeout=0.5)
            except asyncio.TimeoutError:
                if on_tick:
                    on_tick(int(now - start))
                continue
            if isinstance(line, Exception):
                # Поток журнала оборвался раньше срока (так было на живом iPhone 12 через
                # 20 с) — переподключаемся и слушаем дальше, пока не вышло время.
                notes.append(f"# syslog оборвался через {round(now - start, 1)} с: {type(line).__name__}: {line}\n")
                if grace_until or reconnects >= 5 or now - start > seconds:
                    break
                reconnects += 1
                await stop_reader()
                await asyncio.sleep(1.0)
                try:
                    await start_reader()
                except Exception as e:                  # noqa: BLE001
                    notes.append(f"# переподключение не удалось: {type(e).__name__}: {e}\n")
                    break
                continue
            if isinstance(line, bytes):
                line = line.decode("utf-8", "replace")
            if "CRRepairHistoryItem" in line:
                buf.append(line)
                found = parse("".join(buf))
                if found and not grace_until:
                    grace_until = time.monotonic() + 2.0   # записи идут пачкой — добираем
    finally:
        await stop_reader()
    return found, "".join(buf) + "".join(notes), round(time.monotonic() - start, 1)
