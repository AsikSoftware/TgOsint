# -*- coding: utf-8 -*-
"""Поток проверки: ждёт телефон → слушатель журнала стартует СРАЗУ → слепок →
отчёт → ждём историю Apple (подсказка на экране) → Sickw через сервер →
отправка → `done`. Дальше поток не умирает: слушатель живёт, пока телефон на
кабеле, и если клиент открыл раздел позже — приходит `history`, карточка и
сервер обновляются. Всё на pintel_core, ничего не дублируем."""
import asyncio
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

from pintel_core import reference
from pintel_core.analysis import report as report_mod
from pintel_core.analysis import sealed as sealed_mod
from pintel_core.devicelink import connect, repair_history, snapshot
from pintel_core.devicelink.connect import READY
from pintel_core.external import rfs, sickw

from .client import ServerError
from .config import data_dir


ЛОГ_МАКС = 5 * 1024 * 1024               # дальше заводим kiosk.log.1, старый перезаписываем


def log_line(text):
    try:
        путь = os.path.join(data_dir(), "logs", "kiosk.log")
        with open(путь, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {text}\n")
            велик = f.tell() > ЛОГ_МАКС
        if велик:                        # лог на точке никто не чистит — делаем это сами
            os.replace(путь, путь + ".1")
    except Exception:                                            # noqa: BLE001
        pass


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


def проверить_рфс(cfg, имеи, step):
    """Реестр РФС РК по всем IMEI аппарата → результаты, или None (выключено, нечего).

    Один и тот же шаг для аппарата на кабеле и для запечатанного по коробке: гос-реестр
    отвечает по секунде на запрос, отказывает точечно, из-за рубежа может молчать —
    всё это шаг показывает словами, а отчёт решает, что с этим делать."""
    имеи = [str(x or "").strip() for x in (имеи or []) if str(x or "").strip()]
    if not имеи:
        step("rfs", "warn", "у телефона нет IMEI")
        return None
    if not cfg.get("rfs", True):
        step("rfs", "warn", "выключена (kiosk.toml)")
        return None
    step("rfs", "run", f"{len(имеи)} IMEI")
    try:
        итог = rfs.проверить(имеи, os.path.join(data_dir(), "cache", "rfs"), cfg.get("rfs_proxy") or None)
    except Exception as e:                                       # noqa: BLE001 — реестр не роняет приём
        step("rfs", "warn", "реестр недоступен")
        log_line(f"rfs: {e}")
        return None
    св = rfs.сводка(итог)
    step("rfs",
         {rfs.BLOCKED: "fail", rfs.NOT_VERIFIED: "warn", rfs.UNKNOWN: "warn"}.get(св["вердикт"], "done"),
         {rfs.BLOCKED: "ЗАБЛОКИРОВАН",
          rfs.NOT_VERIFIED: "не верифицирован" + (f" · до {св['срок']}" if св.get("срок") else ""),
          rfs.UNKNOWN: "реестр не ответил"}.get(св["вердикт"], "верифицирован"))
    return итог


class Pipeline(QThread):
    status = Signal(str, str)                 # состояние связи: state, текст
    step = Signal(str, str, str)              # шаг: ключ, состояние (wait|run|done|warn|fail), подпись
    apple_prompt = Signal(bool)               # показать/скрыть панель «один шаг на телефоне»
    done = Signal(dict)                       # результат (отчёт, ответ сервера, …)
    history = Signal(dict)                    # история Apple пришла позже: обновлённый результат
    failed = Signal(str)                      # человеческий текст ошибки

    def __init__(self, cfg, client, parent=None):
        super().__init__(parent)
        self.cfg, self.client = cfg, client
        self.skip_apple = threading.Event()
        self.cancel = threading.Event()
        self.serial = None
        self.started = datetime.now()                 # имя эталона за этот прогон — одно на все перезаписи

    def run(self):
        try:
            asyncio.run(self._main())
        except Exception as e:                                   # noqa: BLE001
            log_line(traceback.format_exc())
            self.failed.emit(f"{type(e).__name__}: {e}")

    def _step(self, key, state, text=""):
        log_line(f"шаг {key}: {state} {text}".rstrip())
        self.step.emit(key, state, text)

    async def _main(self):
        self._step("connect", "run", "ждём «Доверять»")
        st = None
        while not self.cancel.is_set():
            st = await connect.wait_ready(on_status=lambda s: (log_line(f"связь: {s.state} {s.human}"),
                                                               self.status.emit(s.state, s.human)),
                                          deadline=time.monotonic() + 2.0)
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

        # Слушатель журнала — с первой секунды: если клиент откроет раздел, пока идёт
        # слепок, записи не пропадут.
        listener = repair_history.Listener(ld, log=log_line)
        await listener.start()
        self.apple_prompt.emit(True)
        try:
            await self._flow(ld, st, listener)
        finally:
            await listener.stop()

    async def _flow(self, ld, st, listener):
        diag, tries = await connect.open_diagnostics(ld)
        self._step("passport", "run")
        snap = await snapshot.collect(ld, diag)
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

        # Sickw через сервер (ключ только там)
        imei = pas.get("imei") or ""
        if self.cfg.get("sickw", True) and (self.client.enabled or self.client.local_sickw) and sickw.luhn_ok(imei):
            self._step("sickw", "run")
            try:
                snap["sickw"] = self.client.sickw(imei)
                rep = report_mod.build(snap)
                sk = rep.get("sickw") or {}
                self._step("sickw", "done" if sk.get("в_чёрном_списке") is not True else "fail",
                           "чисто" if sk.get("в_чёрном_списке") is False else (sk.get("чёрный_список") or "проверено"))
            except ServerError as e:
                self._step("sickw", "warn", "база недоступна")
                log_line(f"sickw: {e}")
        elif not sickw.luhn_ok(imei):
            self._step("sickw", "warn", "у телефона нет IMEI")
        else:
            self._step("sickw", "warn", "не настроена (kiosk.toml)")

        # Реестр РФС РК — оба IMEI, при любой оценке
        рфс = проверить_рфс(self.cfg, [pas.get("imei"), pas.get("imei2")], self._step)
        if рфс is not None:
            snap["rfs"] = рфс
            rep = report_mod.build(snap)
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
        server = self.client.upload(payload)          # без связи кладёт в очередь сама
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
        sk = None
        службы = [int(x) for x in (self.cfg.get("sickw_services_sealed") or [sickw.SERVICE_SEALED])]
        if self.cfg.get("sickw", True) and (self.client.enabled or self.client.local_sickw):
            self._step("sickw", "run", "служба " + ", ".join(map(str, службы)))
            try:
                sk = self.client.sickw(имеи[0], services=службы)
                self._step("sickw", "done" if sk.get("в_чёрном_списке") is not True else "fail",
                           "чисто" if sk.get("в_чёрном_списке") is False
                           else (sk.get("чёрный_список") or "проверено"))
            except ServerError as e:
                self._step("sickw", "warn", "база недоступна")
                log_line(f"sickw: {e}")
        else:
            self._step("sickw", "warn", "не настроена (kiosk.toml)")
        if sk and sk.get("модель"):
            self._step("passport", "done", f"{sk['модель']} · {sk.get('объём_гб') or '?'} ГБ")
        else:
            self._step("passport", "warn", "модель по базе не определилась")

        рфс = проверить_рфс(self.cfg, имеи, self._step)
        rep = sealed_mod.build(sk, имеи, рфс)
        out = os.path.join(data_dir(), "out", f"{datetime.now():%Y%m%d_%H%M%S}_box_{имеи[0][-6:]}")
        os.makedirs(out, exist_ok=True)
        open(os.path.join(out, "report.json"), "w", encoding="utf-8").write(snapshot.dumps(rep))
        self.done.emit({"report": rep, "server": {"номер": self.client.local_number(), "локально": True},
                        "client_id": f"box-{uuid.uuid4().hex[:12]}", "serial": None, "out": out,
                        "запечатанный": True})
