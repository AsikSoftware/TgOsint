# -*- coding: utf-8 -*-
"""Полный сырой слепок телефона с качеством чтения.

Что внутри:
  root        — корневой домен lockdown (паспорт)
  domains     — все домены из DOMAINS (что ответило)
  node_names  — карта всех узлов IORegistry (имена) — чтобы не угадывать
  nodes       — нужные узлы целиком (батарея, камера, NVMe, …)
  nand_summary — разбор NANDInfo и сверка прошивки с NVMe
  quality     — повторы, тайминги, что не прочиталось

Два правила, за которые заплачено на точках (17.11.2026):

* **Про память телефон спрашивают один раз, последним и недолго.** Домен
  `com.apple.disk_usage` телефон считает на ходу и отвечает когда как: обычно за доли секунды,
  но бывало 20–45 секунд и больше трёх минут, а повторный вопрос на iOS 27 шёл по 20 секунд
  каждый раз. Пока он считает, служба `deleted` заваливает журнал телефона тысячами строк в
  секунду, и в этом потоке теряются строки, которых ждёт касса: процент батареи и записи
  Apple о деталях. Раньше домен читали в начале и дважды (первый ответ бывает устаревшим —
  про свободное место), и шаг «Модель и память» стоял всё это время. Сколько памяти занято,
  владельцу не нужно; из домена нужны только объём для сверки и NANDInfo. Поэтому касса
  читает его в самом конце проверки, по своему соединению и не дольше нескольких секунд
  (`ЧтениеДиска`), а объём с первой секунды берётся с контроллера NVMe.
* **Оборвалась связь — чтение останавливается сразу** (`СвязьПропала`). Раньше оно шло дальше
  и по три раза с паузами стучалось в мёртвое соединение за каждым из двадцати узлов: шаг
  крутился 1,5–3,5 минуты и кончался отчётом с «? ГБ». Теперь тот, кто читает, ждёт телефон
  и начинает заново.
"""
import asyncio, base64, json, time
from datetime import datetime

from . import jailbreak, mdm, mobilegestalt as mg_mod, nand, panic
from .nodes import (CAMERA_FALLBACK, CAMERA_RE, DOMAINS, FIXED_NODES, MG_KEYS, MG_KEYS_COLOUR,
                    NVME_FALLBACK, NVME_RE, OPTIONAL_CLASSES, OPTIONAL_NODES, PROX_FALLBACK, PROX_RE,
                    collect_entry_names, deep, num, pick_names, txt)

SNAPSHOT_VERSION = 4      # 4: + отчёты о панике ядра (panic full)
#                           3: планы IOService/IODeviceTree, доп. узлы, MobileGestalt, джейлбрейк


class _Enc(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, (bytes, bytearray)):
            return {"__b64__": base64.b64encode(bytes(o)).decode("ascii")}
        if isinstance(o, datetime):
            return o.isoformat()
        return str(o)


def dumps(obj):
    return json.dumps(obj, cls=_Enc, ensure_ascii=False, indent=1)


def _dec(o):
    if isinstance(o, dict) and set(o) == {"__b64__"}:
        return base64.b64decode(o["__b64__"])
    return o


def loads(text):
    return json.loads(text, object_hook=_dec)


# Ошибки, которые говорят «связь моргнула», а не «телефон так отвечает». Только их имеет
# смысл перечитывать: отказ самого телефона повтором не лечится.
СВЯЗЬ_МИГНУЛА = ("DeviceNotFound", "ConnectionTerminated", "ConnectionAborted", "ConnectionReset",
                 "ConnectionFailed", "BrokenPipe", "Timeout", "MuxException", "OSError", "EOF")


class СвязьПропала(RuntimeError):
    """Соединение с телефоном оборвалось посреди чтения: по нему больше ничего не прочитать.
    Тот, кто читает, должен дождаться телефона и начать слепок заново."""


class Остановлено(RuntimeError):
    """Чтение отменили снаружи: телефон отключили или сделку закрыли."""


def _обрыв(текст) -> bool:
    return any(k in str(текст) for k in СВЯЗЬ_МИГНУЛА)


class _Связь:
    """Следит за чтением и отличает моргнувшую связь от оборванной.

    Одна сорвавшаяся по связи попытка — бывает, её перечитывают. Две подряд, без единого
    удачного чтения между ними, — повод спросить прямо: живо ли соединение? Спрашиваем тем,
    что у исправного телефона отвечает всегда (`проба`). Не ответило — `СвязьПропала`.
    У исправных телефонов ошибок связи при чтении не бывает вовсе (боевые слепки за 60 дней
    и все эталоны: в «не прочиталось» только «пусто»), так что ложной тревоги тут нет."""

    ПОДРЯД = 2

    def __init__(self, проба=None, жив=None):
        self.проба, self.жив, self.подряд = проба, жив, 0

    def проверить(self):
        """Между чтениями: не отменили ли нас. Иначе отменённое чтение дочитывало телефон до
        конца и рисовало свои шаги поверх новой проверки."""
        if self.жив is not None and not self.жив():
            raise Остановлено("чтение отменено")

    def удалось(self):
        self.подряд = 0

    async def сорвалось(self, имя, текст):
        if not _обрыв(текст):
            return
        self.подряд += 1
        if self.подряд < self.ПОДРЯД:
            return
        if self.проба is not None:
            try:
                if await asyncio.wait_for(self.проба(), 5):
                    self.подряд = 0              # соединение живо — не дался только этот запрос
                    return
            except Exception:                    # noqa: BLE001 — проба не прошла: связи нет
                pass
        raise СвязьПропала(f"{имя}: {str(текст)[:160]}")


async def _retry(fn, name, quality, tries=3, delays=(0.7, 1.5, 2.5), связь=None):
    last = None
    for i in range(tries):
        if связь is not None:
            связь.проверить()
        try:
            r = await fn()
            if r:
                if i:
                    quality["повторы"][name] = i + 1
                if связь is not None:
                    связь.удалось()
                return r
            last = "пусто"
        except (СвязьПропала, Остановлено):
            raise
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
            if связь is not None:
                await связь.сорвалось(name, last)
        await asyncio.sleep(delays[min(i, len(delays) - 1)])
    quality["не_прочиталось"][name] = str(last)
    return None


ДОМЕН_ДИСКА = "com.apple.disk_usage"

# Домены, из которых отчёт что-то берёт: заряд, третий канал «Найти iPhone», пройдена ли
# настройка, ограничения. Остальные читаются «на всякий случай» — в слепок и эталон.
ВАЖНЫЕ_ДОМЕНЫ = ("com.apple.mobile.battery", "com.apple.fmip", "com.apple.purplebuddy",
                 "com.apple.mobile.restriction")
# Сколько ждём ответа на один вопрос. Исправный телефон отвечает на ВСЕ домены за 0,1–0,3 с
# (боевые слепки за месяц: 57 из 65 — быстрее секунды), так что это не «поторопить», а
# «не висеть»: один домен из двадцати трёх у части телефонов отвечает 45–195 секунд.
ЖДАТЬ_ВАЖНЫЙ_ДОМЕН, ЖДАТЬ_ДОМЕН = 4.0, 2.0
ЖДАТЬ_СОЕДИНЕНИЕ = 5.0
# столько вопросов без ответа за одно чтение — и дальше не спрашиваем: телефон занят собой.
# Считаем все, а не подряд: иначе «через один» двадцать вопросов снова сложились бы в минуту.
ЗАВИСШИХ_НЕ_БОЛЬШЕ = 3
# доктор читает память сам (касса — отдельно, в конце проверки): столько ждём ответ
ЖДАТЬ_ПАМЯТЬ_ЗДЕСЬ = 20.0
НЕ_ОТВЕТИЛ = "телефон не ответил за"


async def _закрыть_соединение(соединение) -> None:
    if соединение is None:
        return
    try:
        итог = соединение.close()
        if asyncio.iscoroutine(итог):
            await asyncio.wait_for(итог, 3)
    except Exception:                                             # noqa: BLE001
        pass


class ПоздниеДомены:
    """Вопросы, на которые телефон не ответил вовремя: ждут в стороне, каждый на своём
    соединении.

    Бросить ждать ответ на общем соединении нельзя — он придёт позже и будет прочитан как
    ответ на следующий вопрос. Поэтому домены читаются на боковом соединении: зависший вопрос
    остаётся на нём ждать, а чтение идёт дальше на новом. Пришёл ответ до конца проверки —
    `вложить` кладёт его в слепок; не пришёл — в слепке сказано, какой домен молчал и сколько."""

    def __init__(self):
        self._ждут = {}                                # домен → (задача, соединение, начато)

    def __len__(self):
        return len(self._ждут)

    def оставить(self, домен, задача, соединение, начато) -> None:
        self._ждут[домен] = (задача, соединение, начато)

    def ждут(self) -> list:
        """На какие домены ответа ещё нет."""
        return [д for д, (з, _с, _н) in self._ждут.items() if not з.done()]

    async def вложить(self, snap: dict, ждать: float = 0.0) -> list:
        """Положить в слепок ответы, которые успели прийти (или придут за `ждать` секунд).
        → какие домены пришли."""
        задачи = {з for з, _с, _н in self._ждут.values() if not з.done()}
        if задачи and ждать > 0:
            await asyncio.wait(задачи, timeout=ждать)
        кач = snap.setdefault("quality", {})
        пришли = []
        for домен, (задача, соединение, начато) in list(self._ждут.items()):
            if not задача.done():
                кач.setdefault("зависшие_домены", {})[домен] = round(time.monotonic() - начато, 1)
                continue
            del self._ждут[домен]
            await _закрыть_соединение(соединение)
            try:
                ответ = None if задача.cancelled() else задача.result()
            except Exception as e:                                # noqa: BLE001
                if домен in ВАЖНЫЕ_ДОМЕНЫ:
                    кач.setdefault("не_прочиталось", {})[домен] = f"{type(e).__name__}: {str(e)[:120]}"
                continue
            (кач.get("зависшие_домены") or {}).pop(домен, None)
            if ответ:
                snap.setdefault("domains", {})[домен] = ответ
                (кач.get("не_прочиталось") or {}).pop(домен, None)
                кач.setdefault("поздние_домены", {})[домен] = round(time.monotonic() - начато, 1)
                пришли.append(домен)
        if not кач.get("зависшие_домены"):
            кач.pop("зависшие_домены", None)
        return пришли

    async def закрыть(self) -> None:
        """Больше не ждём: бросаем вопросы и закрываем их соединения."""
        for домен, (задача, соединение, _начато) in list(self._ждут.items()):
            if not задача.done():
                задача.cancel()
                try:
                    await задача
                except BaseException:                             # noqa: BLE001
                    pass
            await _закрыть_соединение(соединение)
        self._ждут.clear()


async def спросить_в_стороне(соединить, домен=None, ключ=None, ждать=ЖДАТЬ_ВАЖНЫЙ_ДОМЕН):
    """Один вопрос телефону на своём соединении и не дольше `ждать` секунд.
    → (ответ, почему нет): ответ None и причина словами, если не дождались или не вышло."""
    соединение = None
    try:
        соединение = await asyncio.wait_for(соединить(), ЖДАТЬ_СОЕДИНЕНИЕ)
        что = {k: v for k, v in (("domain", домен), ("key", ключ)) if v}
        return await asyncio.wait_for(соединение.get_value(**что), ждать), ""
    except asyncio.TimeoutError:
        return None, f"{НЕ_ОТВЕТИЛ} {ждать:g} с"
    except Exception as e:                                        # noqa: BLE001
        return None, f"{type(e).__name__}: {str(e)[:120]}"
    finally:
        await _закрыть_соединение(соединение)


async def _читать_домены(ld, quality, связь, соединить=None, поздние=None):
    """Домены lockdown → {домен: значение}. Ни один вопрос не держит чтение дольше своего срока.

    `соединить` — корутина без аргументов, дающая ещё одно соединение с тем же телефоном.
    С ней домены читаются на боковом соединении с пределом ожидания: не ответил — вопрос
    остаётся ждать на своём соединении (`поздние`), дальше спрашиваем на новом. Без неё
    (подставной телефон в тестах) — по-старому, на общем соединении и без предела."""
    domains, медленные = {}, {}
    порядок = ([d for d in DOMAINS if d in ВАЖНЫЕ_ДОМЕНЫ]
               + [d for d in DOMAINS if d not in ВАЖНЫЕ_ДОМЕНЫ and d != ДОМЕН_ДИСКА])
    бок, зависло, бока_нет = None, 0, соединить is None

    def не_спросили(dom, почему):
        # В «не прочиталось» — только то, из чего отчёт что-то берёт: такая запись делает
        # проверку неполной и снимает автоцену. Домен «на всякий случай» отчёту не нужен —
        # о нём остаётся отметка в слепке, и только.
        if dom in ВАЖНЫЕ_ДОМЕНЫ:
            quality["не_прочиталось"][dom] = почему
        else:
            quality.setdefault("домены_не_спрашивали", []).append(dom)

    async def открыть_бок():
        try:
            return await asyncio.wait_for(соединить(), ЖДАТЬ_СОЕДИНЕНИЕ)
        except Exception as e:                                    # noqa: BLE001
            quality["боковое_соединение"] = f"{type(e).__name__}: {str(e)[:120]}"
            return None

    try:
        for dom in порядок:
            связь.проверить()
            if зависло >= ЗАВИСШИХ_НЕ_БОЛЬШЕ:
                не_спросили(dom, "не спрашивали: телефон перестал отвечать на вопросы о себе")
                continue
            if not бока_нет and бок is None:
                бок = await открыть_бок()
                if бок is None:
                    бока_нет = True
                    if зависло:
                        # вопрос уже завис, а новое соединение не открылось: на общем
                        # соединении не спрашиваем — зависнет вся проверка
                        зависло = ЗАВИСШИХ_НЕ_БОЛЬШЕ
                        не_спросили(dom, "не спрашивали: телефон перестал отвечать на вопросы о себе")
                        continue
            if бока_нет and соединить is not None and dom not in ВАЖНЫЕ_ДОМЕНЫ:
                # бокового соединения нет: на общем спрашиваем только то, что нужно отчёту
                не_спросили(dom, "не спрашивали: второе соединение не открылось")
                continue
            t_dom = time.monotonic()
            if бока_нет:                                          # общее соединение, без предела
                try:
                    v = await ld.get_value(domain=dom)
                    связь.удалось()
                    if v:
                        domains[dom] = v
                except Exception as e:                            # noqa: BLE001
                    quality["не_прочиталось"][dom] = f"{type(e).__name__}: {e}"
                    await связь.сорвалось(dom, quality["не_прочиталось"][dom])
            else:
                ждать = ЖДАТЬ_ВАЖНЫЙ_ДОМЕН if dom in ВАЖНЫЕ_ДОМЕНЫ else ЖДАТЬ_ДОМЕН
                задача = asyncio.ensure_future(бок.get_value(domain=dom))
                try:
                    готово, _ = await asyncio.wait({задача}, timeout=ждать)
                except BaseException:                             # чтение сняли снаружи
                    задача.cancel()
                    raise
                if not готово:
                    зависло += 1
                    if dom in ВАЖНЫЕ_ДОМЕНЫ:
                        quality["не_прочиталось"][dom] = f"{НЕ_ОТВЕТИЛ} {ждать:g} с"
                    quality.setdefault("зависшие_домены", {})[dom] = ждать
                    if поздние is not None:
                        поздние.оставить(dom, задача, бок, t_dom)
                    else:
                        задача.cancel()
                        await _закрыть_соединение(бок)
                    бок = None                                    # следующий вопрос — на новом
                    continue
                try:
                    v = задача.result()
                    связь.удалось()
                    if v:
                        domains[dom] = v
                except Exception as e:                            # noqa: BLE001
                    quality["не_прочиталось"][dom] = f"{type(e).__name__}: {e}"
                    await _закрыть_соединение(бок)                # соединение могло умереть
                    бок = None
                    await связь.сорвалось(dom, quality["не_прочиталось"][dom])
            if time.monotonic() - t_dom >= 1.0:
                медленные[dom] = round(time.monotonic() - t_dom, 1)
    finally:
        await _закрыть_соединение(бок)
    if медленные:
        # какой именно домен телефон отдавал долго — раньше знали только сумму по всем
        quality["медленные_домены"] = медленные
    return domains


class ЧтениеДиска:
    """Ответ телефона про память, который читается в стороне от основного слепка.

    `соединить` — корутина без аргументов, дающая СВОЁ соединение lockdown с тем же
    телефоном. Своё — потому что телефон может считать ответ минутами, а бросить ждать ответ
    на общем соединении нельзя: он придёт позже и будет прочитан как ответ на следующий
    вопрос. Своё соединение просто закрывают."""

    def __init__(self, соединить):
        """Чтение начинается сразу, в стороне; забирают его через `вложить`."""
        self._соединить, self._соединение = соединить, None
        self.начато, self.готово_за, self.ответ, self.беда = time.monotonic(), None, None, ""
        self._задача = asyncio.ensure_future(self._читать())

    async def _читать(self):
        try:
            self._соединение = await self._соединить()
            self.ответ = await self._соединение.get_value(domain=ДОМЕН_ДИСКА) or None
            self.готово_за = round(time.monotonic() - self.начато, 2)
        except asyncio.CancelledError:
            raise
        except Exception as e:                                    # noqa: BLE001
            self.беда = f"{type(e).__name__}: {str(e)[:120]}"
        return self.ответ

    async def вложить(self, snap: dict, ждать: float = 0.0) -> bool:
        """Положить ответ в слепок, если он пришёл или придёт за `ждать` секунд. → пришёл ли.

        Не пришёл — в `quality` остаётся, сколько ждали: отчёт скажет, что объём взят с
        контроллера и с диском не сверен."""
        if not self._задача.done() and ждать > 0:
            await asyncio.wait({self._задача}, timeout=ждать)
        кач = snap.setdefault("quality", {})
        if self._задача.done() and self.ответ:
            snap.setdefault("domains", {})[ДОМЕН_ДИСКА] = self.ответ
            кач.setdefault("время_с", {})["диск"] = self.готово_за
            кач.pop("память_не_дождались_с", None)
            if self.ответ.get("NANDInfo"):
                nv_fw = txt(deep((snap.get("nodes") or {}).get("nvme") or {}, "Firmware Revision"))
                snap["nand_summary"] = nand.summarize(self.ответ["NANDInfo"], nv_fw)
            return True
        кач["память_не_дождались_с"] = round(time.monotonic() - self.начато, 1)
        if self.беда:
            кач["память_беда"] = self.беда
        return False

    async def закрыть(self):
        """Больше не ждём: бросаем чтение и закрываем его соединение."""
        if not self._задача.done():
            self._задача.cancel()
            try:
                await self._задача
            except BaseException:                                 # noqa: BLE001
                pass
        if self._соединение is not None:
            try:
                итог = self._соединение.close()
                if asyncio.iscoroutine(итог):
                    await итог
            except Exception:                                     # noqa: BLE001
                pass
            self._соединение = None


async def collect(ld, diag, log=lambda *a: None, жив=None, память=True, соединить=None, поздние=None):
    """Слепок телефона. `жив()` — не отменили ли чтение. `память=False` — про память не
    спрашивать вовсе: касса делает это сама, в конце проверки (`ЧтениеДиска`). Иначе (доктор,
    тесты) память читается здесь же — один раз и последней.

    `соединить` — корутина, дающая ещё одно соединение с тем же телефоном: с ней ни один
    вопрос о доменах не держит чтение дольше своего срока (`_читать_домены`). `поздние` —
    куда сложить вопросы, оставшиеся без ответа: касса заберёт ответы в конце проверки.

    Бросает `СвязьПропала`, если соединение оборвалось, и `Остановлено`, если отменили."""
    t0 = time.monotonic()
    quality = {"повторы": {}, "не_прочиталось": {}, "устарело": [], "время_с": {}}

    async def проба():
        # то же, чем `open_diagnostics` проверяет готовность: узел батареи есть у любого iPhone
        return bool(await diag.ioregistry(name="AppleSmartBattery")) and bool(await ld.get_value(key="ProductType"))
    связь = _Связь(проба, жив)

    log("паспорт…")
    root = await _retry(lambda: ld.get_value(), "root", quality, связь=связь) or {}
    quality["время_с"]["паспорт"] = round(time.monotonic() - t0, 2)

    log("домены…")
    t = time.monotonic()
    domains = await _читать_домены(ld, quality, связь, соединить=соединить, поздние=поздние)
    quality["время_с"]["домены"] = round(time.monotonic() - t, 2)

    # Второй заход за тем, без чего отчёт неполон. Домены читались ровно один раз, и одного
    # моргнувшего USB хватало, чтобы «Найти iPhone» стал «не определился»: в отчёт это уезжало
    # как незнание, хотя телефон всё это время лежал на кабеле. Перечитываем только то, что
    # сорвалось по связи: если домена на этой iOS просто нет, повторять нечего.
    for dom in ("com.apple.mobile.battery", "com.apple.fmip"):
        почему = quality["не_прочиталось"].get(dom) or ""
        if domains.get(dom) or not _обрыв(почему):
            continue
        if соединить is not None:
            # и перечитываем так же: на своём соединении и с пределом ожидания
            связь.проверить()
            v, _почему = await спросить_в_стороне(соединить, домен=dom)
        else:
            v = await _retry(lambda d=dom: ld.get_value(domain=d), dom, quality, tries=2, delays=(0.8, 2.0),
                             связь=связь)
        if v:
            domains[dom] = v
            quality["не_прочиталось"].pop(dom, None)
            quality["повторы"][dom] = quality["повторы"].get(dom, 2)

    log("карта узлов…")
    t = time.monotonic()
    tree = await _retry(lambda: diag.ioregistry(plane="IOService"), "ioreg:IOService", quality, связь=связь)
    names = collect_entry_names(tree) if tree else set()
    quality["время_с"]["карта"] = round(time.monotonic() - t, 2)
    quality["узлов_в_карте"] = len(names)

    # Дерево устройств целиком: все *-serial-num, device-colors, wifi-module-sn
    # любой модели попадают в слепок, даже если мы о них ещё не знаем.
    log("дерево устройств…")
    t = time.monotonic()
    dtree = await _retry(lambda: diag.ioregistry(plane="IODeviceTree"), "ioreg:IODeviceTree", quality, tries=2,
                         связь=связь)
    quality["время_с"]["дерево"] = round(time.monotonic() - t, 2)
    names_all = set(names) | (collect_entry_names(dtree) if dtree else set())

    cam_names = pick_names(names, CAMERA_RE, CAMERA_FALLBACK)
    nvme_names = pick_names(names, NVME_RE, NVME_FALLBACK)

    log("узлы…")
    t = time.monotonic()
    nodes = {}
    quality["нет_в_карте"] = []
    for name in FIXED_NODES:
        # Драйверных узлов, которых нет в карте телефона, не ждём по 5 секунд:
        # у iPhone 17 Pro нет AIDBus (USB-C) — это не сбой чтения, а устройство другое.
        if names_all and name[0].isupper() and name not in names_all:
            nodes[name] = None
            quality["нет_в_карте"].append(name)
            continue
        nodes[name] = await _retry(lambda n=name: diag.ioregistry(name=n), name, quality, связь=связь)
    nodes["prox"] = None
    for n in pick_names(names_all, PROX_RE, PROX_FALLBACK):
        if names_all and n not in names_all:
            continue
        v = await _retry(lambda n=n: diag.ioregistry(name=n), n, quality, tries=2, связь=связь)
        if v:
            nodes["prox"] = v
            quality["prox_узел"] = n
            break
    for key, cands in (("camera", cam_names), ("nvme", nvme_names)):
        nodes[key] = None
        for n in cands:
            v = await _retry(lambda n=n: diag.ioregistry(name=n), n, quality, tries=2, связь=связь)
            if v:
                nodes[key] = v
                quality[f"{key}_узел"] = n
                break
    # узлы «по возможности» — одна попытка, отсутствие не считается ошибкой чтения
    for key, (rx, fallback) in OPTIONAL_NODES.items():
        nodes[key] = None
        for n in pick_names(names_all, rx, fallback):
            if names_all and n not in names_all:
                continue
            try:
                v = await diag.ioregistry(name=n)
            except Exception:
                v = None
            if v:
                nodes[key] = v
                quality[f"{key}_узел"] = n
                break
    for key, cls in OPTIONAL_CLASSES.items():
        try:
            nodes[key] = await diag.ioregistry(ioclass=cls) or None
        except Exception:
            nodes[key] = None
    quality["время_с"]["узлы"] = round(time.monotonic() - t, 2)

    # MobileGestalt — лучшим доступным каналом: diagnostics до iOS 17.4, а на 17.4+
    # через userspace-туннель CoreDevice (без прав администратора; тот же канал, что у
    # 3uTools). Печать деталей, серийники модулей, цвета корпуса — без действий клиента.
    связь.проверить()
    log("MobileGestalt…")
    t = time.monotonic()
    serial = txt((root or {}).get("UniqueDeviceID")) or None
    try:
        mg_res = await mg_mod.read(diag, serial=serial)
    except Exception as e:                                        # noqa: BLE001
        mg_res = {"значения": {}, "канал": "нет", "ошибка": f"{type(e).__name__}: {str(e)[:160]}"}
    mg = dict(mg_res.get("значения") or {})
    if not mg:
        mg = {"недоступен": mg_res.get("ошибка") or "пусто"}
    mg["_канал"] = mg_res.get("канал")
    if mg_res.get("device_info"):
        mg["_device_info"] = mg_res["device_info"]
    if mg_res.get("диагностика"):
        # туннель поднялся, а службы нет: кладём в слепок, что телефон предлагает вместо неё
        mg["_диагностика"] = mg_res["диагностика"]
    quality["mobilegestalt_канал"] = mg_res.get("канал")
    quality["время_с"]["mobilegestalt"] = round(time.monotonic() - t, 2)

    связь.проверить()
    log("джейлбрейк…")
    t = time.monotonic()
    jb = await jailbreak.probe(ld)
    quality["время_с"]["джейлбрейк"] = round(time.monotonic() - t, 2)

    log("panic full…")
    t = time.monotonic()
    pan = await panic.probe(ld)
    quality["время_с"]["паника"] = round(time.monotonic() - t, 2)

    log("профили и надзор…")
    t = time.monotonic()
    mdm_info = await mdm.probe(ld)
    quality["время_с"]["mdm"] = round(time.monotonic() - t, 2)

    связь.проверить()
    nand_summary = {}
    if память:
        log("память…")
        t = time.monotonic()
        if соединить is not None:
            # своё соединение и предел: память телефон считает когда как (до минут)
            диск = ЧтениеДиска(соединить)
            try:
                частично = {"domains": domains, "nodes": nodes, "quality": quality}
                if await диск.вложить(частично, ждать=ЖДАТЬ_ПАМЯТЬ_ЗДЕСЬ):
                    nand_summary = частично.get("nand_summary") or {}
            finally:
                await диск.закрыть()
        else:
            disk = await _retry(lambda: ld.get_value(domain=ДОМЕН_ДИСКА), ДОМЕН_ДИСКА, quality, tries=2,
                                delays=(0.8, 2.0), связь=связь) or {}
            if disk:
                domains[ДОМЕН_ДИСКА] = disk
            quality["время_с"]["диск"] = round(time.monotonic() - t, 2)
            # NANDInfo: разбор и сверка прошивки с NVMe-контроллером
            if disk.get("NANDInfo"):
                nand_summary = nand.summarize(disk["NANDInfo"], txt(deep(nodes.get("nvme") or {}, "Firmware Revision")))

    quality["время_с"]["всего"] = round(time.monotonic() - t0, 2)
    return {
        "snapshot_version": SNAPSHOT_VERSION,
        "когда": datetime.now().isoformat(timespec="seconds"),
        "root": root,
        "domains": domains,
        "node_names": sorted(names),
        "nodes": nodes,
        "ioreg_planes": {"IOService": tree, "IODeviceTree": dtree},
        "mobilegestalt": mg,
        "jailbreak": jb,
        "panic": pan,
        "mdm": mdm_info,
        "nand_summary": nand_summary,
        "quality": quality,
    }
