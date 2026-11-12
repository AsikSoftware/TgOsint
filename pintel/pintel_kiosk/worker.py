# -*- coding: utf-8 -*-
"""Поток проверки: ждёт телефон → смотрит, не проверяли ли его только что → слушатель
журнала стартует СРАЗУ → слепок →
отчёт → ждём историю Apple (подсказка на экране) → Sickw через сервер →
отправка → `done`. Дальше поток не умирает: слушатель живёт, пока телефон на
кабеле, и если клиент открыл раздел позже — приходит `history`, карточка и
сервер обновляются. Всё на pintel_core, ничего не дублируем."""
import asyncio
import collections
import glob
import json
import os
import shutil
import threading
import time
import traceback
import uuid
from datetime import datetime

from PySide6.QtCore import QThread, Signal

from pintel_core import previous, reference
from pintel_core.analysis import legal as legal_mod
from pintel_core.analysis import report as report_mod
from pintel_core.analysis import sealed as sealed_mod
from pintel_core.devicelink import connect, repair_history, snapshot
from pintel_core.devicelink.connect import READY
from pintel_core.external import rfs, sickw

from .client import ServerError
from .config import data_dir


ЛОГ_МАКС = 5 * 1024 * 1024               # дальше заводим kiosk.log.1, старый перезаписываем

# Очередь строк на сервер: их забирает фоновый поток связи. Файл на точке остаётся полным
# журналом, а это копия последних строк — чтобы журнал можно было читать, не приезжая.
_НА_СЕРВЕР = collections.deque(maxlen=2000)


def log_line(text):
    строка = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {text}"
    _НА_СЕРВЕР.append(строка)
    try:
        путь = os.path.join(data_dir(), "logs", "kiosk.log")
        with open(путь, "a", encoding="utf-8") as f:
            f.write(строка + "\n")
            велик = f.tell() > ЛОГ_МАКС
        if велик:                        # лог на точке никто не чистит — делаем это сами
            os.replace(путь, путь + ".1")
    except Exception:                                            # noqa: BLE001
        pass


def забрать_логи(предел=300) -> list:
    """Забрать накопленные строки для отправки. Не ушли — не беда: файл на точке полный."""
    строки = []
    while _НА_СЕРВЕР and len(строки) < предел:
        строки.append(_НА_СЕРВЕР.popleft())
    return строки


def убрать_старое(дней=90):
    """Чистка на точке. → сколько удалено.

    Оценка весит около мегабайта — это слепок телефона целиком, со всем сырьём. Без
    уборки диск на точке кончается за несколько месяцев, а кончившийся диск останавливает
    приём: записать очередную оценку будет некуда.

    Эталоны не трогаем: они обезличены, по 85 КБ и ограничены числом (reference_keep).
    Чеки клиентам и остатки очереди на сервер чистим вместе с оценками."""
    if not дней or int(дней) <= 0:
        return 0
    порог = time.time() - int(дней) * 86400
    убрано = 0
    цели = (glob.glob(os.path.join(data_dir(), "out", "*"))
            + glob.glob(os.path.join(data_dir(), "queue", "*.json")))
    for путь in цели:
        try:
            if os.path.getmtime(путь) >= порог:
                continue
            if os.path.isdir(путь):
                shutil.rmtree(путь, ignore_errors=True)
            else:
                os.remove(путь)
            убрано += 1
        except OSError:                  # занят, нет прав — не повод валить запуск
            pass
    return убрано


def _прочитать_слепок(папка):
    """Слепок прошлой проверки — чтобы оценка этого визита уехала на сервер целой.

    Не читается (папку унесли, файл побился) — отправим одну отчётную часть: оценка без
    слепка полезнее, чем отсутствие оценки."""
    try:
        with open(os.path.join(папка, "snapshot.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        log_line(f"прошлый слепок не прочитался: {e}")
        return None


def проверить_рфс(cfg, имеи, step):
    """Реестр РФС РК по всем IMEI аппарата → (результаты, почему проверки не было).

    Один и тот же шаг для аппарата на кабеле и для запечатанного по коробке: гос-реестр
    отвечает по секунде на запрос, отказывает точечно, из-за рубежа может молчать —
    всё это шаг показывает словами, а отчёт решает, что с этим делать.

    Вторым значением возвращается причина, по которой проверки НЕ было: шаг на экране
    горел оранжевым, а в отчёт не попадало ничего, и аппарат с непроверенным реестром
    выглядел ровно как проверенный и чистый."""
    имеи = [str(x or "").strip() for x in (имеи or []) if str(x or "").strip()]
    if not имеи:
        step("rfs", "warn", "у телефона нет IMEI")
        return None, "реестр РФС не проверялся — у телефона не прочитался IMEI"
    if not cfg.get("rfs", True):
        step("rfs", "warn", "выключена в кассе")
        return None, "реестр РФС не проверялся — проверка выключена в настройках"
    step("rfs", "run", f"{len(имеи)} IMEI")
    try:
        итог = rfs.проверить(имеи, os.path.join(data_dir(), "cache", "rfs"), cfg.get("rfs_proxy") or None)
    except Exception as e:                                       # noqa: BLE001 — реестр не роняет приём
        step("rfs", "warn", "реестр недоступен")
        log_line(f"rfs: {e}")
        return None, f"реестр РФС не проверялся — {type(e).__name__}"
    св = rfs.сводка(итог)
    step("rfs",
         {rfs.BLOCKED: "fail", rfs.NOT_VERIFIED: "warn", rfs.UNKNOWN: "warn"}.get(св["вердикт"], "done"),
         {rfs.BLOCKED: "ЗАБЛОКИРОВАН",
          rfs.NOT_VERIFIED: "не верифицирован" + (f" · до {св['срок']}" if св.get("срок") else ""),
          rfs.UNKNOWN: "реестр не ответил"}.get(св["вердикт"], "верифицирован"))
    return итог, ""


# Сколько секунд после чтения слепка ждать, пока телефон сам назовёт процент батареи. На
# кабеле powerd печатает его раз в 20 секунд (iOS 14 и новее), так что за 25 первая строка
# приходит наверняка; быстрая проверка без этого заканчивалась раньше неё.
# Отсчёт — от КОНЦА слепка, а не от подключения: пока читается занятое место, служба
# `deleted` на телефоне заваливает журнал (iPhone 12, 12.11.2026 — до 12 тысяч строк в
# секунду), и касса на точке получает из этого потока малую часть — строка powerd в нём
# терялась (проверка 57: 47 секунд слепка, 49 тысяч строк, ни одной от powerd).
ЖДАТЬ_БАТАРЕЮ = 25


class Pipeline(QThread):
    status = Signal(str, str)                 # состояние связи: state, текст
    step = Signal(str, str, str)              # шаг: ключ, состояние (wait|run|done|warn|fail), подпись
    apple_prompt = Signal(bool)               # показать/скрыть панель «один шаг на телефоне»
    done = Signal(dict)                       # результат (отчёт, ответ сервера, …)
    прошлая = Signal(dict)                    # взяли проверку, сделанную недавно (не читали заново)
    history = Signal(dict)                    # история Apple пришла позже: обновлённый результат
    failed = Signal(str)                      # человеческий текст ошибки

    def __init__(self, cfg, client, parent=None, заново=False):
        super().__init__(parent)
        self.cfg, self.client = cfg, client
        self.skip_apple = threading.Event()
        self.cancel = threading.Event()
        # `заново` ставит кнопка «Проверить телефон заново»: тогда прошлую проверку не берём
        # даже если она свежая — сотрудник сказал, что хочет перечитать аппарат.
        self.заново = bool(заново)
        self.serial = None
        self.started = datetime.now()                 # имя эталона за этот прогон — одно на все перезаписи
        self._listener = None                         # чтобы закрыть канал к телефону снаружи
        self._loop = None
        self._слепок_готов_в = None                   # от этого момента ждём процент батареи

    def run(self):
        try:
            asyncio.run(self._main())
        except Exception as e:                                   # noqa: BLE001
            log_line(traceback.format_exc())
            self.failed.emit(f"{type(e).__name__}: {e}")

    def остановить_слушателя(self):
        """Закрыть канал к телефону немедленно, из чужого потока.

        `cancel` поток замечает не сразу: он может сидеть в запросе к серверу (до 90 с).
        Пока он там сидит, его слушатель журнала держит и переоткрывает канал к тому же
        телефону — а новая проверка уже открыла свой. Два слушателя на одном аппарате
        дерутся за usbmux, и в журнале точки это видно как обрывы раз в секунду."""
        слушатель, loop = self._listener, self._loop
        if слушатель is None or loop is None or loop.is_closed():
            return
        слушатель._stop = True
        задача = getattr(слушатель, "_task", None)
        if задача is not None:
            try:
                loop.call_soon_threadsafe(задача.cancel)
            except RuntimeError:                      # цикл уже остановлен — канал и так закрыт
                pass

    def _step(self, key, state, text=""):
        log_line(f"шаг {key}: {state} {text}".rstrip())
        self.step.emit(key, state, text)

    async def _main(self):
        self._loop = asyncio.get_running_loop()
        self._step("connect", "run", "ждём «Доверять»")
        st = None
        сказано = None

        def связь(s):
            # В журнал — только смена состояния. Цикл спрашивает телефон каждые две секунды,
            # и аппарат в режиме восстановления писал одну и ту же строку сотнями.
            nonlocal сказано
            if s.state != сказано:
                log_line(f"связь: {s.state} {s.human}")
                сказано = s.state
            self.status.emit(s.state, s.human)

        while not self.cancel.is_set():
            st = await connect.wait_ready(on_status=связь, deadline=time.monotonic() + 2.0)
            if st.state == READY:
                break
            if st.state == "NO_DEVICE":
                self.failed.emit("телефон отключили")
                return
            await asyncio.sleep(0.5)
        if self.cancel.is_set():
            return
        ld = st.lockdown
        self.serial = st.serial
        self._step("connect", "done", "телефон на связи")

        # Этот телефон проверяли только что? Тогда берём готовый отчёт и ведём сотрудника
        # дальше — к тесту и медиа. Смотрим ДО слушателя журнала и слепка: ради того же
        # ответа держать клиента минуты незачем.
        if await self._взять_прошлую(ld):
            return

        # Слушатель журнала — с первой секунды: если клиент откроет раздел, пока идёт
        # слепок, записи не пропадут.
        listener = repair_history.Listener(ld, log=log_line)
        self._listener = listener
        await listener.start()
        self.apple_prompt.emit(True)
        try:
            await self._flow(ld, st, listener)
        finally:
            await listener.stop()

    async def _дождаться_батареи(self, listener):
        """Дать телефону назвать процент батареи — не дольше ЖДАТЬ_БАТАРЕЮ секунд после
        чтения слепка. Обычно ждать почти нечего: за это время сотрудник делает шаг с
        историей Apple, идут Sickw и реестр."""
        if self._слепок_готов_в is None:
            return
        сказали = False
        while not self.cancel.is_set():
            meta = getattr(listener, "meta", None) or {}
            if meta.get("батарея_телефона") or meta.get("канал_потерян"):
                return
            if time.monotonic() - self._слепок_готов_в >= ЖДАТЬ_БАТАРЕЮ:
                log_line(f"батарея: за {ЖДАТЬ_БАТАРЕЮ} с телефон свой процент не назвал — считаем сами")
                return
            if not сказали:
                self._step("battery", "run", "ждём число от телефона")
                сказали = True
            await asyncio.sleep(0.25)

    @staticmethod
    def _донести_батарею(snap, listener):
        """Последнее, что телефон сказал о батарее, — в слепок, из которого строится отчёт."""
        сказал = (getattr(listener, "meta", None) or {}).get("батарея_телефона")
        if сказал:
            snap.setdefault("repair_history_meta", {})["батарея_телефона"] = dict(сказал)

    async def _взять_прошлую(self, ld) -> bool:
        """Взять проверку этого телефона, сделанную недавно. → взяли (и `done` уже ушёл)?

        Что здесь происходит и почему именно так:

        * ищем самый свежий отчёт того же аппарата за окно (`reuse_days`, по умолчанию
          один день) — дольше хранить «свежесть» нельзя, отчёт перестаёт быть про этот
          телефон;
        * **сверяем с живым телефоном то, что читается мгновенно**: серийник, IMEI и
          правовой статус (Найти iPhone, активация, пароль). Один вызов `get_value` — это не
          минуты, а доли секунды, и без этой сверки прошлый отчёт мог бы прикрыть включённый
          за это время «Найти iPhone», то есть заблокированный аппарат в выкупе;
        * расхождение — читаем заново, молча ничего не подменяем. Не прочиталось вовсе —
          так и пишем в отметке: «не сверили», и это видно и на экране, и в карточке.

        Отчёт уезжает на сервер как оценка этого визита: к ней потом прицепляются тест с
        телефона клиента и чек, и без своей оценки их было бы некуда дописать.
        """
        if self.заново or self.cancel.is_set():
            return False
        дней = self.cfg.get("reuse_days", previous.ДНЕЙ)
        находка = previous.найти(os.path.join(data_dir(), "out"), self.serial, дней)
        if not находка:
            return False
        отчёт = находка["отчёт"]
        сверка, почему = await self._сверить_живьём(ld, отчёт)
        if сверка is False:
            log_line(f"прошлая проверка ({находка['словами']}) не подошла: {почему} — читаем заново")
            self._step("passport", "run", "телефон изменился — читаем заново")
            return False
        rep = previous.отметить(отчёт, находка)
        rep["повторная_проверка"]["сверка"] = "сошлась" if сверка else почему
        for ключ, подпись in (("passport", "взята прошлая проверка"),
                              ("battery", находка["словами"]),
                              ("locks", "сверено с телефоном" if сверка else почему),
                              ("apple", "из прошлой проверки"),
                              ("sickw", "из прошлой проверки"),
                              ("rfs", "из прошлой проверки")):
            self._step(ключ, "done", подпись)
        self._step("upload", "run")
        cid = f"{self.serial or 'phone'}-{uuid.uuid4().hex[:12]}"
        payload = {"client_id": cid, "report": json.loads(snapshot.dumps(rep)),
                   "snapshot": _прочитать_слепок(находка["путь"])}
        server = await asyncio.to_thread(self.client.upload, payload)
        if not server:
            server = {"номер": self.client.local_number(), "локально": True}
            self._step("upload", "done" if not self.client.enabled else "warn",
                       "сохранено на киоске" if not self.client.enabled else "отправим позже")
        else:
            self._step("upload", "done", "отправлено")
        log_line(f"взята прошлая проверка: {находка['словами']}, папка {находка['путь']}, "
                 f"сверка с телефоном: {rep['повторная_проверка']['сверка']}")
        self.прошлая.emit(dict(rep["повторная_проверка"]))
        self.done.emit({"report": rep, "server": server, "client_id": cid,
                        "serial": self.serial, "out": находка["путь"], "повторная": True})
        return True

    async def _сверить_живьём(self, ld, отчёт: dict):
        """Прошлый отчёт против живого телефона по тому, что читается мгновенно.

        → (True, "") сошлось · (False, почему) расходится · (None, почему) не прочитали.

        Сравниваем только однозначное: серийник и IMEI (это тот же аппарат?) и правовой
        статус (его могли изменить в промежутке). «Не определился» расхождением не считаем —
        это незнание, и врать про сверку из-за него нельзя, поэтому оно едет в отметку
        словами.
        """
        try:
            root = await ld.get_value() or {}
        except Exception as exc:                                 # noqa: BLE001
            return None, f"не сверили: телефон не ответил ({type(exc).__name__})"
        try:
            fmip = await ld.get_value(domain="com.apple.fmip") or {}
        except Exception:                                        # noqa: BLE001 — домен отдают не все
            fmip = {}
        пас = (отчёт.get("паспорт") or {})
        for поле, было in (("SerialNumber", пас.get("серийник")),
                           ("InternationalMobileEquipmentIdentity", пас.get("imei"))):
            сейчас = str(root.get(поле) or "").strip()
            if сейчас and было and сейчас.casefold() != str(было).strip().casefold():
                return False, f"{поле}: было {было}, стало {сейчас}"
        живой = legal_mod.build({"root": root, "domains": {"com.apple.fmip": fmip}, "nodes": {}})
        прошлый = отчёт.get("правовой") or {}
        for поле in ("найти_iphone", "активация"):
            стало, было = живой.get(поле), прошлый.get(поле)
            if not стало or стало == "не определился":
                return None, f"не сверили: {поле} сейчас не прочитался"
            if было and стало != было:
                return False, f"{поле}: было «{было}», стало «{стало}»"
        if живой.get("пароль") is not прошлый.get("пароль"):
            return False, "пароль на телефоне изменился"
        return True, ""

    async def _flow(self, ld, st, listener):
        diag, tries = await connect.open_diagnostics(ld)
        self._step("passport", "run")
        snap = await snapshot.collect(ld, diag)
        self._слепок_готов_в = time.monotonic()
        snap["quality"]["диагностика_попыток"] = tries
        snap["quality"]["подключение"] = st.timings
        try:
            await diag.close()
        except Exception:                                        # noqa: BLE001
            pass
        rep = report_mod.build(snap)
        pas, bat = rep["паспорт"], rep["батарея"]
        self._step("passport", "done", f"{pas['модель']} · {rep['память'].get('объём_гб') or '?'} ГБ")
        h = bat.get("здоровье_%")
        self._step("battery", "done" if h is not None else "warn", f"{h} %" if h is not None else "не прочиталась")
        leg = rep["правовой"]
        locks = [x for x, ok in (("Найти iPhone", leg["найти_iphone"] != "включён"),
                                 ("надзор MDM", leg["mdm"] is not True), ("пароль", not leg["пароль"])) if not ok]
        self._step("locks", "done" if not locks else "warn", "чисто" if not locks else ", ".join(locks))

        # история Apple: у модели вообще есть? (iPhone X и старше, iOS < 15.2 — нет, не держим клиента)
        hist_ok, hist_why = repair_history.supported(pas["код_модели"], pas["ios"])
        if not hist_ok:
            self.apple_prompt.emit(False)
            items, raw, waited = {}, "", 0
            self._step("apple", "done", hist_why)
        else:
            # Вердикт по деталям уже собран с кабеля (привязка + печать Apple). Журнал Apple —
            # только обогащение датами, поэтому ждём коротко и не держим клиента.
            secs = int(self.cfg.get("apple_history_seconds") or 45)
            self._step("apple", "run", f"ждём один шаг на телефоне · {secs} с")
            items, raw, waited = await listener.wait(
                secs, keep_going=lambda: not (self.skip_apple.is_set() or self.cancel.is_set()),
                on_tick=lambda s: self.step.emit(
                    "apple", "run", ("экран открыт, читаем…" if listener.meta.get("раздел_открыт")
                                     else f"«Об этом устройстве» на телефоне · {max(0, secs - s)} с")))
            self.apple_prompt.emit(False)
            if items:
                self._step("apple", "done", "получена")
            elif listener.state == "opened_unknown":
                self._step("apple", "warn", "раздел открыт — проверит сотрудник")
            else:
                # подтвердить подлинность может только Apple, и только с экрана телефона:
                # шаг остаётся открытым, слушатель работает, пока телефон на кабеле
                self._step("apple", "warn", "откройте раздел на телефоне")
        snap["repair_history"], snap["repair_history_raw"] = items, raw
        meta = dict(getattr(listener, "meta", None) or {})
        meta.update({"статус": listener.state if hist_ok else "не поддерживается", "почему": hist_why})
        snap["repair_history_meta"] = meta
        rep = report_mod.build(snap)
        log_line(f"история Apple: {listener.state if hist_ok else hist_why} за {waited} с; формат "
                 f"{meta.get('формат')}; строк журнала {listener.lines}, по теме {meta.get('строк_по_теме')}, "
                 f"подключений {listener.connects}, обрывов {listener.reconnects}")
        if self.cancel.is_set():
            return

        # Sickw через сервер (ключ только там). Непроверенный чёрный список — это НЕ чистый
        # чёрный список: шаг горел оранжевым, а в отчёте о нём не было ни слова.
        # Запрос блокирующий, поэтому в отдельный поток: иначе на всё время ожидания
        # встаёт цикл событий и слушатель журнала не читает syslog — а именно там приходит
        # ПОВТОРНАЯ печать записей Apple, в которой и появляются замены.
        не_проверено = snap.setdefault("quality", {}).setdefault("не_проверено", {})
        imei = pas.get("imei") or ""
        if self.cfg.get("sickw", True) and self.client.enabled and sickw.luhn_ok(imei):
            self._step("sickw", "run")
            try:
                snap["sickw"] = await asyncio.to_thread(self.client.sickw, imei)
                rep = report_mod.build(snap)
                sk = rep.get("sickw") or {}
                if sk.get("в_чёрном_списке") is None:
                    # ответ пришёл, а поля чёрного списка в нём нет — «проверено» тут неправда
                    не_проверено["чёрный список (Sickw)"] = "в ответе базы IMEI нет статуса чёрного списка"
                self._step("sickw", "done" if sk.get("в_чёрном_списке") is not True else "fail",
                           "чисто" if sk.get("в_чёрном_списке") is False else (sk.get("чёрный_список") or "проверено"))
            except ServerError as e:
                self._step("sickw", "warn", "база недоступна")
                не_проверено["чёрный список (Sickw)"] = "база IMEI недоступна"
                log_line(f"sickw: {e}")
        elif not sickw.luhn_ok(imei):
            self._step("sickw", "warn", "у телефона нет IMEI")
            не_проверено["чёрный список (Sickw)"] = "у телефона не прочитался IMEI"
        else:
            self._step("sickw", "warn", "выключена в кассе")
            не_проверено["чёрный список (Sickw)"] = "проверка по базе IMEI выключена в настройках"

        # Реестр РФС РК — оба IMEI, при любой оценке
        рфс, рфс_нет = await asyncio.to_thread(
            проверить_рфс, self.cfg, [pas.get("imei"), pas.get("imei2")], self._step)
        if рфс_нет:
            не_проверено["реестр РФС"] = рфс_нет
        if рфс is not None:
            snap["rfs"] = рфс
        # Процент батареи телефон называет сам, но раз в 20 секунд: строка могла прийти уже
        # после того, как метаданные слушателя сняты выше, или не успеть вовсе, если проверка
        # прошла быстро. Добираем её и кладём в слепок самое свежее, что слышали.
        await self._дождаться_батареи(listener)
        self._донести_батарею(snap, listener)
        rep = report_mod.build(snap)
        h = rep["батарея"].get("здоровье_%")
        self._step("battery", "done" if h is not None else "warn", f"{h} %" if h is not None else "не прочиталась")
        if self.cancel.is_set():
            return

        # сохраняем локально и отправляем
        cid = f"{self.serial or 'phone'}-{uuid.uuid4().hex[:12]}"
        out = os.path.join(data_dir(), "out", f"{datetime.now():%Y%m%d_%H%M%S}_{(self.serial or 'phone')[:12]}")
        os.makedirs(out, exist_ok=True)
        self._save(out, snap, rep)
        payload = {"client_id": cid, "report": json.loads(snapshot.dumps(rep)),
                   "snapshot": json.loads(snapshot.dumps(snap))}
        self._step("upload", "run")
        # в отдельный поток по той же причине: пока ждём сервер, журнал Apple должен читаться
        server = await asyncio.to_thread(self.client.upload, payload)   # без связи кладёт в очередь сама
        if not server:
            server = {"номер": self.client.local_number(), "локально": True}
            self._step("upload", "done" if not self.client.enabled else "warn",
                       "сохранено на киоске" if not self.client.enabled else "отправим позже")
        else:
            self._step("upload", "done", "отправлено")
        result = {"report": rep, "server": server, "client_id": cid, "serial": self.serial, "out": out}
        self.done.emit(result)
        self._reference(snap, rep)                    # эталон с каждого телефона, уже после результата
        if self.cancel.is_set() or not hist_ok:
            return

        # Слушаем дальше, пока телефон на кабеле: вердикт мог прийти позже (клиент открыл
        # раздел после результата) или ИЗМЕНИТЬСЯ — iOS печатает записи повторно, когда
        # подгрузит список ремонтов Apple, и только тогда в них появляются замены.
        if not items:
            self._step("apple", "run", "ждём историю Apple")
        seen = repair_history.signature(items)
        while not self.cancel.is_set():
            items, raw, waited = await listener.wait_change(seen, keep_going=lambda: not self.cancel.is_set())
            if self.cancel.is_set() or repair_history.signature(items) == seen:
                return
            seen = repair_history.signature(items)
            snap["repair_history"], snap["repair_history_raw"] = items, raw
            snap["repair_history_meta"] = {**(getattr(listener, "meta", None) or {}), "статус": "found", "почему": ""}
            rep = report_mod.build(snap)
            self._save(out, snap, rep)
            self._reference(snap, rep)                # вердикт пришёл позже — перезаписываем эталон
            log_line(f"история Apple обновилась через {waited} с: {len(items)} записей")
            if server and server.get("id") and not server.get("локально") and self.client.enabled:
                try:
                    self.client.update_evaluation(server["id"], json.loads(snapshot.dumps(rep)),
                                                  {"repair_history": items, "repair_history_raw": raw,
                                                   "repair_history_meta": getattr(listener, "meta", None)})
                except ServerError as e:
                    log_line(f"обновление оценки не ушло: {e}")
            self._step("apple", "done", "получена")
            self.history.emit({**result, "report": rep})


    def _reference(self, snap, rep):
        """Эталон с КАЖДОГО телефона: обезличенный слепок, сырой журнал Apple и наш вердикт.
        На этом учится разбор: новая iOS пишет вердикт по-своему, и угадывать нечего — нужен
        живой аппарат. Пишем после результата, чтобы не задержать экран; если вердикт пришёл
        позже, файл за тот же прогон перезаписывается.

        Обезличиваем здесь же: наружу (и даже в папку на точке) серийники и IMEI не уходят.
        Замена не удалась или изменила выводы — эталон не пишем вовсе."""
        try:
            clean, ok, why = reference.pseudonymize(snap, report_mod.build)
            if not ok:
                log_line(f"эталон не сохранён (обезличивание): {why}")
                return
            clean_rep = report_mod.build(clean)
            path = os.path.join(data_dir(), "эталоны", reference.bundle_name(clean_rep, self.started))
            reference.save_bundle(
                path, clean, clean_rep,
                reference.auto_truth(раздел_открывали=bool((snap.get("repair_history_meta") or {}).get("раздел_открыт"))),
                raw=clean.get("repair_history_raw") or "", dumps=snapshot.dumps)
            keep = int(self.cfg.get("reference_keep") or 500)
            старые = sorted(glob.glob(os.path.join(data_dir(), "эталоны", "эталон_*.zip")),
                            key=os.path.getmtime, reverse=True)[keep:]
            for p in старые:                           # диск на точке не резиновый
                try:
                    os.remove(p)
                except OSError:
                    pass
        except Exception as exc:                       # noqa: BLE001 — эталон не имеет права сорвать приём
            log_line(f"эталон не сохранён: {type(exc).__name__}: {exc}")

    @staticmethod
    def _save(out, snap, rep):
        open(os.path.join(out, "snapshot.json"), "w", encoding="utf-8").write(snapshot.dumps(snap))
        open(os.path.join(out, "report.json"), "w", encoding="utf-8").write(snapshot.dumps(rep))


class SealedPipeline(QThread):
    """Запечатанный аппарат: кабеля нет. По IMEI с коробки — база IMEI (Sickw, служба для
    запечатанных: модель, объём, цвет, активация) и реестр РФС; из них отчёт в тех же
    ключах, что и с кабеля, чтобы экран, чек и посылка в Оценку читали его одинаково.

    На кассу такая оценка не уходит: там ждут слепок телефона, а его нет. Отчёт лежит в
    out/ рядом с остальными."""
    step = Signal(str, str, str)
    done = Signal(dict)
    failed = Signal(str)

    def __init__(self, cfg, client, imeis, parent=None):
        super().__init__(parent)
        self.cfg, self.client = cfg, client
        self.imeis = [str(x or "").strip() for x in (imeis or []) if str(x or "").strip()]

    def run(self):
        try:
            self._main()
        except Exception as e:                                   # noqa: BLE001
            log_line(traceback.format_exc())
            self.failed.emit(f"{type(e).__name__}: {e}")

    def _step(self, key, state, text=""):
        log_line(f"запечатанный · шаг {key}: {state} {text}".rstrip())
        self.step.emit(key, state, text)

    def _main(self):
        имеи = self.imeis
        if not имеи or not sickw.luhn_ok(имеи[0]):
            self.failed.emit("IMEI с коробки не проходит контрольную цифру — проверьте цифры")
            return
        self._step("passport", "run", "по базе IMEI")
        sk, не_проверено = None, {}
        службы = [int(x) for x in (self.cfg.get("sickw_services_sealed") or [sickw.SERVICE_SEALED])]
        if self.cfg.get("sickw", True) and self.client.enabled:
            self._step("sickw", "run", "служба " + ", ".join(map(str, службы)))
            try:
                sk = self.client.sickw(имеи[0], services=службы)
                if sk.get("в_чёрном_списке") is None:
                    не_проверено["чёрный список (Sickw)"] = "в ответе базы IMEI нет статуса чёрного списка"
                self._step("sickw", "done" if sk.get("в_чёрном_списке") is not True else "fail",
                           "чисто" if sk.get("в_чёрном_списке") is False
                           else (sk.get("чёрный_список") or "проверено"))
            except ServerError as e:
                self._step("sickw", "warn", "база недоступна")
                не_проверено["чёрный список (Sickw)"] = "база IMEI недоступна"
                log_line(f"sickw: {e}")
        else:
            self._step("sickw", "warn", "выключена в кассе")
            не_проверено["чёрный список (Sickw)"] = "проверка по базе IMEI выключена в настройках"
        if sk and sk.get("модель"):
            self._step("passport", "done", f"{sk['модель']} · {sk.get('объём_гб') or '?'} ГБ")
        else:
            self._step("passport", "warn", "модель по базе не определилась")

        рфс, рфс_нет = проверить_рфс(self.cfg, имеи, self._step)
        if рфс_нет:
            не_проверено["реестр РФС"] = рфс_нет
        rep = sealed_mod.build(sk, имеи, рфс, не_проверено=не_проверено)
        out = os.path.join(data_dir(), "out", f"{datetime.now():%Y%m%d_%H%M%S}_box_{имеи[0][-6:]}")
        os.makedirs(out, exist_ok=True)
        open(os.path.join(out, "report.json"), "w", encoding="utf-8").write(snapshot.dumps(rep))
        self.done.emit({"report": rep, "server": {"номер": self.client.local_number(), "локально": True},
                        "client_id": f"box-{uuid.uuid4().hex[:12]}", "serial": None, "out": out,
                        "запечатанный": True})
