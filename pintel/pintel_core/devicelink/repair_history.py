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
# Запись разбираем как набор полей «ключ:значение:», а не жёстким шаблоном: Apple может
# добавить поле (например, о неизвестной детали), и его нельзя молча потерять.
ITEM = re.compile(r"componentName:(\w+):((?:\s*\w+:[^:\n\]\"]*:)*)")
FIELD = re.compile(r"(\w+):([^:\n\]\"]*):")
KNOWN_FIELDS = ("componentType", "isRepaired", "isUsed", "repairDate")
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


def _flag(v):
    return str(v).strip().lower() in ("1", "true", "yes")


def parse(text):
    """Записи CRRepairHistoryItem → {компонент: {...}}. Одна и та же запись печатается
    несколько раз (кэш, затем после загрузки списка ремонтов), поэтому признаки
    накапливаются: раз помеченное «меняли»/«б/у»/«неизвестная» поздней строкой не снимается,
    дата берётся первая непустая. Неизвестные поля сохраняются в «поля»."""
    items = {}
    for m in ITEM.finditer(text):
        comp, body = m.groups()
        f = dict(FIELD.findall(body))
        date = re.sub(r"\\U([0-9a-fA-F]{4})", lambda g: chr(int(g.group(1), 16)), f.get("repairDate", "").strip())
        if date in ("(null)", ""):
            date = ""
        extra = {k: v.strip() for k, v in f.items() if k not in KNOWN_FIELDS}
        low = {k.lower(): v for k, v in extra.items()}
        unknown = any(_flag(v) for k, v in low.items() if "unknown" in k or "unseal" in k or "nongenuine" in k)
        unknown = unknown or any(not _flag(v) for k, v in low.items() if k in ("isgenuine", "genuine"))
        serviced = any(_flag(v) for k, v in low.items() if "service" in k or "replaced" in k)
        cur = items.get(comp) or {"деталь": RU.get(comp, comp), "код": 0, "меняли": False, "бу": False, "дата": ""}
        try:
            cur["код"] = int(f.get("componentType") or cur["код"])
        except ValueError:
            pass
        cur["меняли"] = cur["меняли"] or _flag(f.get("isRepaired")) or serviced or unknown
        cur["бу"] = cur["бу"] or _flag(f.get("isUsed"))
        cur["дата"] = cur["дата"] or date
        if unknown:
            cur["неизвестная"] = True
        if extra:
            cur["поля"] = {**cur.get("поля", {}), **extra}
        items[comp] = cur
    return items


def signature(items):
    """Отпечаток записей — чтобы заметить, что вердикт изменился после повторной печати."""
    import json
    return json.dumps(items or {}, sort_keys=True, ensure_ascii=False)


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
                self._apply_seal()
                self.meta["формат"] = "записи обслуживания (iOS 26)"
                self.meta["раздел_открыт"] = True
                self.last_related_at = time.monotonic()
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
        elif self.items and (delta is not None or unsealed is not None):
            self._apply_seal()                     # записи уже есть — сверка их дополняет, а не теряется

    def _apply_seal(self):
        """Детали, которых нет в заводской печати (delta/Unsealed), — «неизвестного происхождения»,
        даже если записи обслуживания про них молчат: записи — это ремонты Apple, а подмену
        детали видит только сверка."""
        unknown = list(dict.fromkeys(list(self.meta.get("дельта") or []) + list(self.meta.get("unsealed") or [])))
        for comp in unknown:
            cur = self.items.get(comp) or {"деталь": RU.get(comp, comp), "код": 0, "бу": False, "дата": ""}
            if not cur.get("неизвестная"):
                self.items[comp] = {**cur, "меняли": True, "неизвестная": True,
                                    "источник": "сверка с заводской печатью"}

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

    async def wait(self, seconds, keep_going=None, on_tick=None, grace=2.0, unknown_quiet=8.0, settle=5.0):
        """Ждать вердикт не дольше seconds (или пока keep_going() истинно).
        После первой записи — добрать grace секунд (записи идут пачкой; если у Apple
        есть записи о ремонте, а деталей ещё нет — ждём их дольше), а пока журнал по теме
        не затих — ещё до settle секунд: телефон допечатывает записи после подгрузки
        списка ремонтов, и ранний выход отдал бы «всё родное» из кэша.
        Если раздел открыт, но ни один известный формат не встретился, а журнал по
        теме затих на unknown_quiet секунд — выходим: формат этой iOS не распознан,
        сырьё сохранено, клиента дальше не держим.
        → (items, raw, секунд_ждали)."""
        start = time.monotonic()
        while True:
            now = time.monotonic()
            if self.found_at:
                g = grace * 3 if "RepairRecords" in self.items else grace
                quiet = now - (self.last_related_at or self.found_at) >= 1.0
                if now - self.found_at >= g and (quiet or now - self.found_at >= g + settle):
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

    async def wait_change(self, seen, keep_going=None, grace=2.0):
        """Ждать, пока записи станут отличаться от отпечатка seen (signature) — телефон
        допечатал вердикт позже, — затем добрать grace секунд. Выход и по keep_going().
        → (items, raw, секунд_ждали); если изменений нет — items с тем же отпечатком."""
        start = time.monotonic()
        changed_at = None
        while True:
            now = time.monotonic()
            if changed_at is None and signature(self.items) != seen:
                changed_at = now
            if changed_at is not None and now - changed_at >= grace:
                break
            if keep_going and not keep_going():
                break
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
