# -*- coding: utf-8 -*-
"""Матрица совместимости на реальных телефонах: каждая правка обязана держать ВСЕ
известные форматы и модели сразу, а не «одно починили — другое отвалилось».

Журналы (обезличены): iOS 18.7.8 iPhone 13 и iPhone 12, iOS 26.6 iPhone 12 и iPhone 17 Pro.
Слепки: iPhone 12 (iOS 18 и 26), iPhone 13, iPhone 14 Pro, iPhone 17 Pro + 228 паспортов."""
import asyncio, glob, json, os
import pytest

from pintel_core.devicelink import mdm, repair_history as rh, snapshot
from pintel_core.analysis import capabilities, report as report_mod

HERE = os.path.dirname(os.path.abspath(__file__))
SYSLOG = os.path.join(HERE, "fixtures_real", "syslog")


class Replay:
    """Подменная служба журнала: отдаёт строки реального телефона, потом молчит."""
    lines = []

    def __init__(self, ld):
        pass

    async def connect(self):
        pass

    async def watch(self):
        for l in Replay.lines:
            await asyncio.sleep(0)
            yield l
        while True:
            await asyncio.sleep(0.05)

    async def close(self):
        pass


def replay(name, monkeypatch, seconds=3.0):
    data = json.load(open(os.path.join(SYSLOG, name + ".json"), encoding="utf-8"))
    Replay.lines = data["lines"]
    monkeypatch.setattr(rh, "SyslogService", Replay)

    async def run():
        lst = rh.Listener(None)
        await lst.start()
        items, raw, waited = await lst.wait(seconds, grace=0.2, unknown_quiet=0.5)
        await lst.stop()
        return items, lst.state, dict(lst.meta), data["meta"]
    return asyncio.run(run())


@pytest.mark.parametrize("name,state,fmt,changed", [
    ("ios18_iphone13_seal_clean", "found", "сверка", set()),
    ("ios26_iphone12_records", "found", "записи", set()),
    ("ios26_iphone17pro_records", "found", "записи", set()),
    ("ios18_iphone12_opened_truncated", "opened_unknown", "не распознан", None),
])
def test_history_every_known_format(name, state, fmt, changed, monkeypatch):
    items, st, meta, m = replay(name, monkeypatch)
    assert st == state, (name, st, meta)
    assert (meta.get("формат") or "").startswith(fmt), meta.get("формат")
    assert meta["раздел_открыт"] is True
    if changed is not None:
        assert {k for k, v in items.items() if v["меняли"]} == changed
        assert {"Battery", "Display", "Camera", "FaceID"} <= set(items)


def test_history_seal_with_repair_records_is_not_all_original():
    meta = {"дельта": [], "unsealed": [], "rchl_байт": 512}
    items = rh.synthesize(meta)
    assert "RepairRecords" in items and not any(k in items for k in ("Battery", "Display"))
    meta = {"дельта": ["Display"], "unsealed": ["Battery"], "rchl_байт": 0}
    items = rh.synthesize(meta)
    assert items["Display"]["неизвестная"] and items["Battery"]["неизвестная"] and not items["Camera"]["меняли"]


@pytest.mark.parametrize("pt,ios,ok", [
    ("iPhone10,3", "16.7", False), ("iPhone11,8", "15.1", False), ("iPhone11,8", "15.2", True),
    ("iPhone12,8", "17.5", True), ("iPhone13,2", "18.7.8", True), ("iPhone18,1", "26.6", True), ("iPad13,1", "18", False),
])
def test_history_supported_matrix(pt, ios, ok):
    assert rh.supported(pt, ios)[0] is ok


@pytest.mark.parametrize("pt,face", [("iPhone10,3", True), ("iPhone10,4", False), ("iPhone12,8", False),
                                    ("iPhone14,6", False), ("iPhone14,5", True), ("iPhone17,5", True), ("iPhone18,4", True)])
def test_face_id_capability(pt, face):
    assert capabilities.has_face_id(pt) is face


def _snap(name):
    return snapshot.loads(open(os.path.join(HERE, "fixtures_real", name), encoding="utf-8").read())


def test_touch_id_model_is_not_incomplete_because_of_face_id():
    snap = _snap("iphone12_ios26_anon.snapshot.json")
    snap["root"]["ProductType"] = "iPhone14,6"                  # SE 3: Touch ID
    snap["nodes"]["camera"].pop("SavageSNUM", None)
    snap["nodes"]["camera"].pop("FrontIRCameraSerialNumber", None)
    snap["repair_history"] = rh.synthesize({"дельта": [], "rchl_байт": 0})
    rep = report_mod.build(snap)
    assert "Face ID ↔ плата" not in rep["сигналы"] and "FaceID" not in rep["apple_история"]
    assert rep["итог"]["вердикт"] != "ПРОВЕРКА НЕПОЛНАЯ", rep["итог"]


def test_node_absent_from_map_is_not_a_read_failure():
    snap = _snap("iphone12_ios26_anon.snapshot.json")
    snap["nodes"]["AppleHapticsSupportArcEEPROM"] = None
    snap["quality"]["нет_в_карте"] = ["AppleHapticsSupportArcEEPROM"]
    snap["repair_history_meta"] = {"формат": "записи обслуживания (iOS 26)", "дельта": []}   # Apple подтвердила
    rep = report_mod.build(snap)
    assert "Taptic ↔ плата" not in rep["сигналы"] and rep["итог"]["вердикт"] != "ПРОВЕРКА НЕПОЛНАЯ"


def test_history_status_in_report():
    # полный кабель, но Apple не прочиталась: зелёного нет — «кабель», проверка неполная,
    # сотрудник сверяет раздел на телефоне (кабель не видит пересаженный оригинальный экран)
    snap = _snap("iphone12_ios26_anon.snapshot.json")
    snap.pop("repair_history", None)
    snap["repair_history_meta"] = {"раздел_открыт": True, "формат": "не распознан"}
    rep = report_mod.build(snap)
    assert rep["apple_история_статус"] == "формат не распознан"
    assert rep["детали_вердикт"]["итог"] == "кабель" and rep["итог"]["вердикт"] == "ПРОВЕРКА НЕПОЛНАЯ"
    assert any("не подтверждена Apple" in x for x in rep["не_прочиталось"])
    assert not any("этот формат iOS" in x for x in rep["сделать"])      # не дёргаем клиента зря
    # модель без истории — честный статус, вердикт деталей всё равно с кабеля
    snap["root"]["ProductType"], snap["root"]["ProductVersion"] = "iPhone10,6", "16.7.10"
    snap["repair_history_meta"] = {}
    rep = report_mod.build(snap)
    assert rep["apple_история_статус"] == "не поддерживается" and rep["детали_вердикт"]["итог"] == "родные"


@pytest.mark.parametrize("probe,expect", [
    ({"прочитано": True, "cloud": {"IsSupervised": True, "OrganizationName": "ACME"}, "профили": []}, True),
    ({"прочитано": True, "cloud": {"ConfigurationURL": "https://mdm.acme/enroll", "IsMandatory": True}, "профили": []}, True),
    ({"прочитано": True, "cloud": {}, "профили": [{"id": "com.acme.mdm", "имя": "Device Management", "активен": True}]}, True),
    ({"прочитано": True, "cloud": {}, "профили": [{"id": "com.vpn.profile", "имя": "VPN", "активен": True}]}, False),
    ({"прочитано": True, "cloud": {}, "профили": []}, False),
    ({"прочитано": False, "ошибка": "timeout"}, None),
])
def test_mdm_verdict_matrix(probe, expect):
    assert mdm.verdict(probe)[0] is expect


def test_mdm_from_profiles_service_overrides_missing_usb_c_node():
    snap = _snap("iphone17pro_anon.snapshot.json")                # USB‑C: узла AIDBus нет
    snap["mdm"] = {"прочитано": True, "cloud": {}, "профили": []}
    rep = report_mod.build(snap)
    assert rep["правовой"]["mdm"] is False and rep["правовой"]["mdm_источник"].startswith("служба профилей")
    assert not any("MDM по кабелю не определился" in x for x in rep["сделать"])
    snap["mdm"] = {"прочитано": True, "cloud": {"IsSupervised": True, "OrganizationName": "Корп"}, "профили": []}
    rep = report_mod.build(snap)
    assert rep["правовой"]["mdm"] is True and rep["итог"]["вердикт"] == "ПРОБЛЕМНЫЙ"


@pytest.mark.parametrize("fixture", ["iphone12_FFXH33T20F0N.snapshot.json", "iphone12_ios26_anon.snapshot.json",
                                     "iphone17pro_anon.snapshot.json"])
def test_every_real_snapshot_builds_full_report(fixture):
    rep = report_mod.build(_snap(fixture))
    assert rep["паспорт"]["модель"] and rep["батарея"]["здоровье_%"] and rep["память"]["объём_гб"]
    assert rep["итог"]["вердикт"] in ("ИДЕАЛ", "ХОРОШИЙ", "ПРОВЕРКА НЕПОЛНАЯ", "ПРОБЛЕМНЫЙ")
    assert rep["apple_история_статус"] in ("получена", "не открыт", "формат не распознан", "не поддерживается")


@pytest.mark.parametrize("pt,back", [("iPhone15,2", False),    # 14 Pro — заднее стекло Apple не ведёт
                                     ("iPhone15,3", False),    # 14 Pro Max
                                     ("iPhone15,4", True),     # iPhone 15
                                     ("iPhone16,1", True),     # 15 Pro — на эталоне BackGlass = 1
                                     ("iPhone17,1", True),     # 16 Pro
                                     ("iPhone12,1", False)])   # iPhone 11 — только батарея и экран
def test_back_glass_tracked_only_since_iphone_15(pt, back):
    """Заднее стекло Apple ведёт с 15-й серии. Нумерация моделей это не разделяет:
    iPhone 14 Pro — это iPhone15,2, а iPhone 15 — iPhone15,4."""
    assert ("BackGlass" in capabilities.apple_tracked_parts(pt)) is back


@pytest.mark.parametrize("ios,можно", [("15.2.1", False), ("15.5", False), ("15.6.1", True),
                                       ("16.0", True), ("16.6.1", True), ("17.7", True),
                                       ("18.6.2", True), ("26.6.1", True)])
def test_apple_confirmation_impossible_on_ios15(ios, можно):
    """Разобрано по прошивкам: в iOS 15 нет ни словаря systemhealth, ни сверки с печатью —
    только отказы. Значит зелёного от Apple там не будет никогда, и обещать его нельзя."""
    assert rh.подтверждение_возможно(ios) is можно


def test_report_says_plainly_that_ios15_cannot_confirm():
    """Сотрудник должен прочитать причину, а не ждать подтверждения, которого не будет."""
    snap = _snap("iphone12_ios26_anon.snapshot.json")
    snap["root"] = {**snap["root"], "ProductVersion": "15.2.1"}
    snap["repair_history"], snap["repair_history_meta"] = {}, {}
    rep = report_mod.build(snap)
    assert rep["паспорт"]["ios"].startswith("15.2")
    assert rep["apple_подтверждение_возможно"] is False
    assert any("не подтверждает в принципе" in x for x in rep["не_прочиталось"]), rep["не_прочиталось"]


# ---------------------------------------------------------------- молчание канала — не вердикт
# Общее правило отчёта: «отсутствие данных НЕ превращается в вердикт». Ниже — места, где оно
# нарушалось молча, то есть проверка выглядела целой, а часть её просто не состоялась.

def test_a_missing_touch_key_is_not_zero_errors():
    """num(None) = 0, и «ключа нет» выглядело как «критических ошибок нет»: тачскрин получал
    зелёный из ничего, да ещё и подтверждал деталь «Экран» по кабелю. Apple уже переносила
    ключи (ёмкости батареи в iOS 26) — молчание узла обязано читаться как «нет данных»."""
    from pintel_core.analysis import pairing
    assert pairing.touch({"Critical Errors": 0}) == (True, 0)
    assert pairing.touch({"Critical Errors": 3}) == (False, 3)
    assert pairing.touch({"ChipRevision": "B2"}) == (None, None)     # узел есть, ключа нет
    snap = _snap("iphone12_ios26_anon.snapshot.json")
    snap["nodes"]["AppleMultitouchDevice"].pop("Critical Errors", None)
    rep = report_mod.build(snap)
    assert rep["сигналы"]["Тачскрин"]["ок"] is None
    assert not any("критических ошибок нет" in str(d.get("почему")) 
                   for d in rep["детали_вердикт"]["детали"])


def test_a_battery_node_without_capacities_is_not_a_read_battery():
    """Узел батареи есть, ёмкостей в нём нет: ни здоровья, ни проверки на подделку. Раньше
    это давало «ёмкость в норме заводской» по детали «Аккумулятор» и ноль циклов — а ноль
    циклов выбирает самую дорогую колонку прайса Оценки («100 (0-30)»)."""
    from pintel_core.analysis import battery
    from pintel_core.external import ocenka
    пустой = battery.analyze({"Serial": "F8Y", "BatteryInstalled": 1})
    assert пустой["есть_данные"] is False and пустой["узел_есть"] is True
    assert пустой["циклы"] is None and пустой["здоровье_%"] is None
    assert пустой["подделка"] == []                                  # и ложного стопа тоже нет
    assert ocenka.акб_для_оценки(пустой["здоровье_%"], пустой["циклы"]) == ocenka.АКБ_НЕТ
    assert ocenka.акб_для_оценки(100, пустой["циклы"]) == "100"      # не «100 (0-30)»
    snap = _snap("iphone12_ios26_anon.snapshot.json")
    snap["nodes"]["AppleSmartBattery"] = {"Serial": "F8Y"}
    rep = report_mod.build(snap)
    assert any("батарея не прочиталась" in x for x in rep["не_прочиталось"])
    assert rep["итог"]["вердикт"] == "ПРОВЕРКА НЕПОЛНАЯ"


def test_one_size_source_is_not_an_agreement():
    """«Объём сошёлся» при одном источнике было утверждением о сверке, которой не было:
    узел NVMe не прочитался — и всё равно «сошёлся». Перепайку ловит расхождение."""
    from pintel_core.analysis import storage
    один = storage.analyze({"TotalDiskCapacity": 61000000000}, None)
    assert один["объём_гб"] == 64 and один["объём_сошёлся"] is None


def test_bases_that_were_never_asked_are_named_in_the_report():
    """Непроверенный чёрный список — это НЕ чистый чёрный список. Шаг на экране киоска горел
    оранжевым, а в отчёте о нём не было ни слова, и аппарат выглядел ровно как проверенный."""
    snap = _snap("iphone12_ios26_anon.snapshot.json")
    snap["quality"]["не_проверено"] = {"чёрный список (Sickw)": "база IMEI недоступна",
                                       "реестр РФС": "реестр РФС не проверялся — TimeoutError"}
    rep = report_mod.build(snap)
    assert any("чёрный список (Sickw)" in x for x in rep["не_прочиталось"])
    assert any("реестр РФС" in x for x in rep["не_прочиталось"])
    assert rep["итог"]["вердикт"] == "ПРОВЕРКА НЕПОЛНАЯ"


def test_a_failed_node_read_does_not_stay_silent():
    """На живом iPhone 14 Pro в сборке не оказалось wintun.dll: туннель не поднялся, и по
    кабелю молча пропали цвет корпуса и серийники части модулей. Отказ чтения — это наш
    канал, он идёт в «служебное»; но и вердикт после него полным называться не может.
    Пустой ответ узла («пусто») — другое дело: у модели такого узла может не быть."""
    snap = _snap("iphone12_ios26_anon.snapshot.json")
    snap["quality"]["не_прочиталось"] = {"product": "TimeoutError: нет ответа"}
    rep = report_mod.build(snap)
    assert any("product" in x for x in rep["служебное"])
    assert any("не прочиталась" in x for x in rep["не_прочиталось"])
    snap["quality"]["не_прочиталось"] = {"AIDBus": "пусто", "AppleProxHIDEventDriver": "пусто"}
    rep = report_mod.build(snap)
    assert not any("узлы телефона" in x for x in rep["служебное"])


def test_the_line_a_person_can_close_is_kept_apart():
    """Сверку деталей на телефоне закрывает сотрудник (пункт «Детали Apple» ручной
    диагностики), а «батарея не прочиталась» не закрывает никто. Бот снимает автоцену по
    второму списку, поэтому различать их по тексту нельзя — нужен отдельный ключ."""
    from pintel_core.external import ocenka
    snap = _snap("iphone12_ios26_anon.snapshot.json")
    rep = report_mod.build(snap)
    assert rep["сверка_деталей"] and rep["сверка_деталей"] in rep["не_прочиталось"]
    assert ocenka.сверка_нужна(rep) is True
    assert ocenka.незакрытое(rep) == []                      # закрыть нечем — ничего
    snap["nodes"]["AppleSmartBattery"] = {}
    rep = report_mod.build(snap)
    assert any("батарея" in x for x in ocenka.незакрытое(rep))


def test_an_unrecognised_model_is_not_a_model_without_an_apple_section():
    """`supported()` отвечает «нет» и про iPhone X (раздела правда нет), и про НЕ РАСПОЗНАННУЮ
    модель. Во втором случае аппарат получал «все детали родные» вообще без участия Apple, а
    клиенту писалось «у этой модели Apple историю деталей не ведёт» — утверждение, которого
    никто не проверял. Не знаем модель — спрашиваем Apple строго."""
    snap = _snap("iphone12_ios26_anon.snapshot.json")
    snap["root"]["ProductType"] = "iPhoneXX,9"              # паспорт не прочитался / новая модель
    rep = report_mod.build(snap)
    assert rep["детали_вердикт"]["итог"] != "родные", rep["детали_вердикт"]
    assert any("модель не распознана" in x for x in rep["не_прочиталось"])
    # а настоящий iPhone X так и остаётся моделью без раздела: там кабель — единственный канал
    snap["root"]["ProductType"], snap["root"]["ProductVersion"] = "iPhone10,6", "16.7.10"
    snap.pop("repair_history", None)
    snap["repair_history_meta"] = {}
    rep = report_mod.build(snap)
    assert rep["apple_история_статус"] == "не поддерживается"
    assert rep["детали_вердикт"]["итог"] == "родные"
    assert not any("модель не распознана" in x for x in rep["не_прочиталось"])


def test_a_broken_factory_seal_is_also_said_in_words():
    """Нарушенную печать FDR вердикт по деталям учитывал, а «стоп» о ней молчал: заголовок
    отчёта мог остаться ИДЕАЛ «проверенные детали на месте». Отчёт и вердикт обязаны
    говорить одно и то же."""
    snap = _snap("iphone12_ios26_anon.snapshot.json")
    assert not any("печать" in x for x in report_mod.build(snap)["стоп"])    # слепок чистый
    snap["mobilegestalt"] = {"FDRSealingStatus": 0, "IsServicePart": 1}
    rep = report_mod.build(snap)
    assert rep["печать_деталей"]["печать_цела"] is False
    assert any("печать деталей нарушена" in x for x in rep["стоп"])
    assert any("сервисная деталь" in x for x in rep["внимание"])
    assert rep["итог"]["вердикт"] == "ПРОБЛЕМНЫЙ"           # а был ИДЕАЛ «детали на месте»


def test_a_journal_channel_that_died_is_not_a_silent_phone():
    """После 30 обрывов подряд слушатель мёртв, а снаружи он выглядит ровно как ждущий
    вердикта. Для оценщика это разные вещи: во втором случае ждать есть смысл."""
    snap = _snap("iphone12_ios26_anon.snapshot.json")
    snap["repair_history_meta"] = {**(snap.get("repair_history_meta") or {}), "канал_потерян": True}
    rep = report_mod.build(snap)
    assert any("оборвался" in x for x in rep["служебное"])
