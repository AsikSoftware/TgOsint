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

ДВА ФОРМАТА (сверено по живым аппаратам):
  iOS 26   — Preferences(CoreRepairCore): repairHistoryForUI:{ … CRRepairHistoryItem … }
             — список деталей с isRepaired/isUsed, даже если ничего не меняли.
  iOS 18.7 — таких строк НЕТ. corerepaird сверяет живые детали с заводской
             печатью (FDR seal) и пишет:
               fetched RCHL successfully: (null) length = 0   — список ремонтов Apple пуст
               No delta components found / delta components: { }  — отличий от печати нет
             Пустая дельта + пустой RCHL = Apple не нашёл ни замен, ни ремонтов.
             Непустая дельта = детали, которых нет в печати («неизвестная деталь»).
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
# Модели, у которых Apple ведёт «Запчасти и история обслуживания»: iPhone XR/XS и новее
# (ProductType iPhone11,x и выше), iOS 15.2+. У iPhone X и старше раздела нет вообще —
# ждать клиента бессмысленно.
def supported(product_type, ios_version):
    """→ (True/False, причина)."""
    import re as _re
    m = _re.match(r"iPhone(\d+),", str(product_type or ""))
    if not m:
        return False, "не iPhone"
    if int(m.group(1)) < 11:
        return False, "у этой модели Apple не ведёт историю обслуживания (iPhone X и старше)"
    parts = [int(x) for x in _re.findall(r"\d+", str(ios_version or ""))[:2]] + [0, 0]
    if (parts[0], parts[1]) < (15, 2):
        return False, "историю обслуживания Apple показывает с iOS 15.2"
    return True, ""


MARKER = "CRRepairHistoryItem"
RELATED = ("repair", "CoreRepair", "mobilerepaird")
# признаки, что раздел на телефоне открыт (iOS 18): UI Настроек и демон проснулись
OPENED = ("updateSpecifiersWithCompletionHandler", "corerepair.preflightControl", "Getting local sealing manifest",
          "fetched RCHL", "delta components", "No delta components found", "repairHistoryForUI",
          "Preferences(CoreRepair", "CoreRepairUI", "Unsealed:")
# детали, которые показывает раздел на iOS 18 у всех моделей с Face ID
BASE_COMPONENTS = ("Battery", "Display", "Camera", "FaceID")
DELTA_RE = re.compile(r"delta components:\s*\{(.*?)\}\s*$", re.S)
UNSEALED_RE = re.compile(r"Unsealed:\s*\{(.*?)\}\s*$", re.S)
RCHL_RE = re.compile(r"fetched RCHL successfully:.*?length = (\d+)")
SEAL_RE = re.compile(r"_copyIdentifierListForSealingMapEntry: Using value (.+?) for key (\w+) from query cache")


def _dict_keys(body):
    """Ключи верхнего уровня из печати словаря Apple: '    Display =     {…};' → Display."""
    keys, depth = [], 0
    for ln in body.split("\n"):
        if depth == 0:
            m = re.match(r"^\s*\"?([A-Za-z]\w*)\"?\s*=", ln)
            if m:
                keys.append(m.group(1))
        depth += ln.count("{") + ln.count("(") - ln.count("}") - ln.count(")")
        depth = max(depth, 0)
    return keys


def parse_delta(line):
    """'delta components: {\n    Display = …;\n}' → ['Display']; пустые скобки → []; не та строка → None."""
    m = DELTA_RE.search(line)
    return _dict_keys(m.group(1)) if m else None


def parse_unsealed(line):
    m = UNSEALED_RE.search(line)
    return _dict_keys(m.group(1)) if m else None


def synthesize(meta):
    """Итог по сверке с заводской печатью (iOS 18):
      дельта пуста и RCHL пуст      → базовые детали «не меняли»
      дельта пуста, RCHL не пуст    → у Apple есть записи о ремонте, но в журнал они не вышли:
                                      вердикт «есть записи» (не «всё родное»!)
      дельта/Unsealed не пусты       → эти детали «неизвестного происхождения»."""
    delta = meta.get("дельта")
    if delta is None:
        return {}
    unknown = list(dict.fromkeys(list(delta) + list(meta.get("unsealed") or [])))
    rchl = meta.get("rchl_байт")
    items = {}
    if rchl:
        items["RepairRecords"] = {"деталь": "Записи о ремонте Apple", "код": 0, "меняли": True, "бу": False,
                                  "дата": "", "записи_без_деталей": True, "источник": "сверка с заводской печатью"}
    elif rchl == 0 or rchl is None:
        for comp in BASE_COMPONENTS:
            items[comp] = {"деталь": RU.get(comp, comp), "код": 0, "меняли": False, "бу": False, "дата": "",
                           "источник": "сверка с заводской печатью"}
    for comp in unknown:
        items[comp] = {"деталь": RU.get(comp, comp), "код": 0, "меняли": True, "бу": False, "дата": "",
                       "неизвестная": True, "источник": "сверка с заводской печатью"}
    return items


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
        # метаданные формата iOS 18: раздел открыт?, дельта, размер RCHL, значения печати
        self.meta = {"раздел_открыт": False, "дельта": None, "unsealed": None, "rchl_байт": None, "печать": {},
                     "формат": None, "строк_по_теме": 0}
        self.last_related_at = None
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
            parsed = parse("".join(self.buf))
            if parsed:
                self.items = parsed
                self.meta["формат"] = "записи обслуживания (iOS 26)"
                self.meta["раздел_открыт"] = True
                if not self.found_at:
                    self.found_at = time.monotonic()
                    self.log(f"история Apple: {len(self.items)} записей")
            return
        low = line.lower()
        if not any(k.lower() in low for k in RELATED):
            return
        self.meta["строк_по_теме"] += 1
        self.last_related_at = time.monotonic()
        if len(self.related) < 400:
            self.related.append(line[:600])
        if any(k in line for k in OPENED) and not self.meta["раздел_открыт"]:
            self.meta["раздел_открыт"] = True
            self.log("на телефоне открыт раздел «Об этом устройстве» / история обслуживания")
        m = RCHL_RE.search(line)
        if m:
            self.meta["rchl_байт"] = int(m.group(1))
        m = SEAL_RE.search(line)
        if m and len(self.meta["печать"]) < 60:
            self.meta["печать"][m.group(2)] = m.group(1)[:120]
        if "No delta components found" in line and self.meta["дельта"] is None:
            self.meta["дельта"] = []
        delta = parse_delta(line)
        if delta is not None:
            self.meta["дельта"] = delta
            self.buf.append(line if line.endswith("\n") else line + "\n")
        unsealed = parse_unsealed(line)
        if unsealed is not None:
            self.meta["unsealed"] = unsealed
            if unsealed:
                self.buf.append(line if line.endswith("\n") else line + "\n")
        if self.meta["дельта"] is not None and not self.items:
            self.items = synthesize(self.meta)
            self.meta["формат"] = "сверка с заводской печатью (iOS 18)"
            if self.items and not self.found_at:
                self.found_at = time.monotonic()
                self.log(f"история Apple (сверка с печатью): замен {len(self.meta['дельта'])}, "
                         f"RCHL {self.meta['rchl_байт']}")

    @property
    def raw(self):
        out = "".join(self.buf) + "".join(self.notes)
        if self.meta["раздел_открыт"] or not self.buf:
            out += "".join(f"# похожее: {l}\n" for l in self.related[:80])
        return out

    @property
    def state(self):
        """found | opened_unknown | waiting — для экрана и отчёта."""
        if self.items:
            return "found"
        if self.meta["раздел_открыт"]:
            return "opened_unknown"
        return "waiting"

    async def wait(self, seconds, keep_going=None, on_tick=None, grace=2.0, unknown_quiet=8.0):
        """Ждать вердикт не дольше seconds (или пока keep_going() истинно).
        После первой записи — добрать grace секунд (записи идут пачкой; если у Apple
        есть записи о ремонте, а деталей ещё нет — ждём их дольше).
        Если раздел открыт, но ни один известный формат не встретился, а журнал по
        теме затих на unknown_quiet секунд — выходим: формат этой iOS не распознан,
        сырьё сохранено, клиента дальше не держим.
        → (items, raw, секунд_ждали)."""
        start = time.monotonic()
        while True:
            now = time.monotonic()
            if self.found_at:
                g = grace * 3 if "RepairRecords" in self.items else grace
                if now - self.found_at >= g:
                    break
            elif (unknown_quiet and self.meta["раздел_открыт"] and self.last_related_at
                  and now - self.last_related_at >= unknown_quiet):
                self.meta["формат"] = self.meta["формат"] or "не распознан"
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
