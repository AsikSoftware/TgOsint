# -*- coding: utf-8 -*-
"""Вердикт Apple «Запчасти и история обслуживания» — из системного журнала.

По USB вердикт не отдаётся никем (проверено: lockdown-домены, IORegistry,
MobileGestalt — пусто; вопрос в libimobiledevice #1301 без ответа с 2022).
Но его пишет в журнал сам телефон при ПЕРЕХОДЕ в раздел Настройки → Основные →
Об этом устройстве → Запчасти и история обслуживания (на iOS 26 — процесс
Preferences(CoreRepairCore), строка repairHistoryForUI:{…CRRepairHistoryItem…}).
Уже открытый экран отдаёт кэш — нужен именно переход внутрь.

Слушатель (Listener) живёт всё время, пока телефон на кабеле: стартует сразу
после «Доверять», переподключается при обрыве потока (на живом iPhone 12 поток
обрывался через ~20 с) и собирает записи, когда бы клиент ни открыл раздел.
"""
import asyncio
import re
import time

from pymobiledevice3.services.syslog import SyslogService

RU = {"Battery": "Аккумулятор", "Display": "Экран", "Camera": "Камера",
      "FaceID": "Face ID", "MTUB": "Верхний модуль", "LogicBoard": "Материнская плата",
      "BackGlass": "Заднее стекло", "Enclosure": "Корпус", "RearSystem": "Задняя система",
      "FrontCamera": "Фронтальная камера", "RearCamera": "Основная камера"}

# Код 1029 встречался и как MTUB, и как LogicBoard — опираемся на ИМЯ.
ITEM = re.compile(r"componentName:(\w+): componentType:(\d+): isRepaired:(\d): "
                  r"isUsed:(\d): repairDate:(.*?):\"?")
MARKER = "CRRepairHistoryItem"
RELATED = ("repair", "CoreRepair", "mobilerepaird")


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


class Listener:
    """Непрерывное чтение журнала с переподключением.

    items — разобранные записи (пусто, пока раздел не открыли)
    raw   — сырые строки с записями + заметки об обрывах + (если записей нет)
            строки, похожие на тему, чтобы разбираться по файлу, а не по догадке
    """

    def __init__(self, ld, log=None, max_reconnects=30, reconnect_delay=1.0):
        self.ld, self.log = ld, (log or (lambda *_: None))
        self.max_reconnects, self.reconnect_delay = max_reconnects, reconnect_delay
        self.items, self.buf, self.notes, self.related = {}, [], [], []
        self.found_at = None
        self.connects = 0
        self.reconnects = 0
        self.lines = 0
        self._task = None
        self._stop = False

    async def start(self):
        self._task = asyncio.create_task(self._run())
        return self

    async def _run(self):
        while not self._stop and self.reconnects <= self.max_reconnects:
            svc = SyslogService(self.ld)
            try:
                await svc.connect()
                self.connects += 1
                async for line in svc.watch():
                    if self._stop:
                        break
                    self._feed(line)
                else:
                    raise EOFError("поток журнала закончился")
            except asyncio.CancelledError:
                raise
            except Exception as e:                      # noqa: BLE001
                if self._stop:
                    break
                self.reconnects += 1
                note = f"# syslog оборвался ({type(e).__name__}: {e}), переподключение {self.reconnects}\n"
                self.notes.append(note)
                self.log(note.strip())
                await asyncio.sleep(self.reconnect_delay)
            finally:
                try:
                    await svc.close()
                except Exception:                       # noqa: BLE001
                    pass
            if self._stop:
                break

    def _feed(self, line):
        if isinstance(line, bytes):
            line = line.decode("utf-8", "replace")
        self.lines += 1
        if MARKER in line:
            self.buf.append(line if line.endswith("\n") else line + "\n")
            self.items = parse("".join(self.buf))
            if self.items and not self.found_at:
                self.found_at = time.monotonic()
                self.log(f"история Apple: {len(self.items)} записей")
        elif any(k.lower() in line.lower() for k in RELATED) and len(self.related) < 200:
            self.related.append(line[:300])

    @property
    def raw(self):
        out = "".join(self.buf) + "".join(self.notes)
        if not self.buf and self.related:
            out += "".join(f"# похожее: {l}\n" for l in self.related[:60])
        return out

    async def wait(self, seconds, keep_going=None, on_tick=None, grace=2.0):
        """Ждать записи не дольше seconds (или пока keep_going() истинно);
        после первой записи добрать ещё grace секунд — они идут пачкой.
        → (items, raw, секунд_ждали)."""
        start = time.monotonic()
        while True:
            now = time.monotonic()
            if self.found_at and now - self.found_at >= grace:
                break
            if not self.found_at and (now - start >= seconds or (keep_going and not keep_going())):
                break
            if on_tick:
                on_tick(int(now - start))
            await asyncio.sleep(0.25)
        return self.items, self.raw, round(time.monotonic() - start, 1)

    async def stop(self):
        self._stop = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):    # noqa: BLE001
                pass


async def capture(ld, seconds=120, keep_going=None, on_tick=None, log=None):
    """Разовый захват (доктор): слушать до записей или до истечения времени.
    Возвращает (items, сырой_текст, секунд_ждали)."""
    lst = Listener(ld, log=log)
    await lst.start()
    try:
        return await lst.wait(seconds, keep_going=keep_going, on_tick=on_tick)
    finally:
        await lst.stop()
