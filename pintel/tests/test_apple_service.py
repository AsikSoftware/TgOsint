# -*- coding: utf-8 -*-
"""Служба Apple на Windows: программа ставит и чинит её сама (`apple_service`).

Windows и сети здесь нет: всё внешнее — порт, `sc`, `msiexec`, скачивание, окно «Разрешить?»
— подменено окружением. Проверяется решение: что делаем без прав, когда просим права и
чего не ставим ни при каких условиях.
"""
import pytest

from pintel_core.devicelink import apple_service as служба

ЗАПРОС_RU = ("Имя_службы: Apple Mobile Device Service\n"
             "        Тип                : 10  WIN32_OWN_PROCESS\n"
             "        Состояние          : {код}  {слово}\n")
ЗАПРОС_EN = ("SERVICE_NAME: Apple Mobile Device Service\n"
             "        TYPE               : 10  WIN32_OWN_PROCESS\n"
             "        STATE              : {код}  {слово}\n")
КОДЫ = {"STOPPED": 1, "START_PENDING": 2, "RUNNING": 4}


class Окружение:
    """Компьютер точки в миниатюре."""

    def __init__(self, порт=False, состояние=None, запуск="AUTO_START", права=False,
                 пакет_сумма=служба.ПАКЕТ["sha256"], код_msi=0, согласие=True,
                 зависла=False, шаблон=ЗАПРОС_RU):
        self.порт, self.состояние, self.запуск, self.права = порт, состояние, запуск, права
        self.пакет_сумма, self.код_msi, self.согласие = пакет_сумма, код_msi, согласие
        self.зависла, self.шаблон = зависла, шаблон
        self.команды, self.скачано, self.повышений = [], [], []

    def это_windows(self):
        return True

    def порт_жив(self, ждать=0.4):
        return self.порт

    def папка(self):
        return "C:/Users/точка/AppData/Local/Pintel/apple"

    def сумма(self, путь):
        return self.пакет_сумма

    def скачать(self, url, путь, шаг=None):
        self.скачано.append((url, путь))

    def запустить(self, команда, ждать=300):
        self.команды.append(команда)
        что = команда[1] if команда[0] == "sc" else команда[0]
        if что == "msiexec":
            if self.код_msi in (0, 3010):
                self.состояние = "STOPPED"
            return self.код_msi, ""
        if self.состояние is None:
            return служба.НЕТ_ТАКОЙ_СЛУЖБЫ, "[SC] OpenService: ошибка 1060"
        if что == "query":
            return 0, self.шаблон.format(код=КОДЫ[self.состояние], слово=self.состояние)
        if что == "qc":
            return 0, f"        Тип_запуска        : 2   {self.запуск}\n"
        if not self.права:
            return служба.ОТКАЗАНО, "[SC] Отказано в доступе."
        if что == "config":
            self.запуск = "AUTO_START"
        elif что == "stop":
            self.состояние, self.порт, self.зависла = "STOPPED", False, False
        elif что == "start" and self.запуск != "DISABLED":
            self.состояние, self.порт = "RUNNING", not self.зависла
        return 0, ""

    def от_администратора(self, аргументы, ждать_мс=0):
        self.повышений.append(list(аргументы))
        if not self.согласие:
            raise служба.ОтказПрав()
        было, self.права = self.права, True
        try:
            assert аргументы[0] == "--apple-setup"
            пакеты = [x for x in аргументы[1:] if not x.startswith("--")]
            return служба.под_админом(пакеты[0] if пакеты else None, окр=self, пауза=lambda с: None,
                                      перезапуск="--restart" in аргументы)
        finally:
            self.права = было

    def делали(self, слово):
        return [к for к in self.команды if слово in к]


def чинить(окр):
    return служба.починить(окр, пауза=lambda с: None)


def обеспечить(окр, принудительно=False):
    сказано = []
    итог, текст = служба.обеспечить(окр, сказать=сказано.append, пауза=lambda с: None,
                                    принудительно=принудительно)
    return итог, текст, сказано


# ───────────── без прав администратора ─────────────

def test_a_working_link_is_left_alone():
    окр = Окружение(порт=True, состояние="RUNNING")
    assert чинить(окр) == служба.ГОТОВО and окр.команды == [], "порт отвечает — ничего не трогаем"


@pytest.mark.parametrize("шаблон", [ЗАПРОС_RU, ЗАПРОС_EN])
def test_the_service_state_is_read_in_any_windows_language(шаблон):
    """Подписи в выводе `sc` переведены, значения — нет; читаем по значениям."""
    assert служба.служба(Окружение(состояние="RUNNING", шаблон=шаблон)) == служба.РАБОТАЕТ
    assert служба.служба(Окружение(состояние="STOPPED", шаблон=шаблон)) == служба.ОСТАНОВЛЕНА
    assert служба.служба(Окружение(состояние="START_PENDING", шаблон=шаблон)) == служба.МЕНЯЕТСЯ
    assert служба.служба(Окружение(состояние="STOPPED", запуск="DISABLED", шаблон=шаблон)) == служба.ОТКЛЮЧЕНА
    assert служба.служба(Окружение(состояние=None, шаблон=шаблон)) == служба.НЕТ


def test_a_stopped_service_is_started_without_asking_anyone():
    окр = Окружение(состояние="STOPPED", права=True)
    assert чинить(окр) == служба.ГОТОВО and окр.делали("start") and not окр.повышений


def test_what_needs_admin_rights_is_named_not_attempted():
    """Нет службы, не дали запустить, отключена или зависла — без прав это не чинится."""
    assert чинить(Окружение(состояние=None)) == служба.НЕТ_СЛУЖБЫ
    assert чинить(Окружение(состояние="STOPPED", права=False)) == служба.НУЖНЫ_ПРАВА
    отключена = Окружение(состояние="STOPPED", запуск="DISABLED", права=True)
    assert чинить(отключена) == служба.НУЖНЫ_ПРАВА and not отключена.делали("start")
    зависла = Окружение(состояние="RUNNING", порт=False, права=True)
    assert чинить(зависла) == служба.НУЖНЫ_ПРАВА and not зависла.делали("stop")


def test_outside_windows_there_is_nothing_to_fix():
    class Мак(Окружение):
        def это_windows(self):
            return False
    assert чинить(Мак()) == служба.НЕ_WINDOWS
    assert служба.обеспечить(Мак())[0] == служба.НЕ_WINDOWS


# ───────────── по кнопке: установка и перезапуск ─────────────

def test_a_clean_laptop_gets_the_apple_package_installed():
    """Чистый ноутбук: скачали с сервера Apple, сверили, поставили одним окном прав."""
    окр = Окружение(состояние=None)
    итог, текст, сказано = обеспечить(окр)
    assert итог == служба.ГОТОВО, текст
    assert [u for u, _ in окр.скачано] == [служба.ПАКЕТ["url"]]
    assert len(окр.повышений) == 1 and окр.повышений[0][1].endswith("AppleMobileDeviceSupport64.msi")
    установка = окр.делали("msiexec")[0]
    assert "/qn" in установка and "/norestart" in установка, "тихо и без перезагрузки посреди дня"
    assert ["sc", "config", служба.СЛУЖБА, "start=", "auto"] in окр.команды
    assert окр.делали("failure"), "при падении служба поднимается сама"
    assert any("Скачиваем" in с for с in сказано) and any("«Да»" in с for с in сказано)


def test_a_package_that_is_not_apples_is_never_installed():
    """Сумма не та — не ставим, и права даже не спрашиваем.

    Сумма однозначно называет файл; что файл с этой суммой подписан Apple, проверяет
    сборка на Windows (шаг «Пакет подписан Apple»)."""
    окр = Окружение(состояние=None, пакет_сумма="0" * 64)
    итог, текст, _ = обеспечить(окр)
    assert итог == служба.НЕ_ВЫШЛО and "нельзя" in текст
    assert not окр.повышений and not окр.делали("msiexec")
    # и под администратором сумма сверяется ещё раз: файл лежал в папке пользователя
    подменили = Окружение(состояние=None, права=True, пакет_сумма="1" * 64)
    assert служба.под_админом("C:/x.msi", окр=подменили, пауза=lambda с: None) == 13
    assert not подменили.делали("msiexec")


def test_a_failed_download_points_to_the_old_way():
    class БезСети(Окружение):
        def сумма(self, путь):
            return "нет файла"

        def скачать(self, url, путь, шаг=None):
            raise OSError("нет сети")
    итог, текст, _ = обеспечить(БезСети(состояние=None))
    assert итог == служба.НЕ_ВЫШЛО and "интернет" in текст and "apple.com" in текст


def test_declining_the_windows_prompt_is_told_plainly():
    окр = Окружение(состояние=None, согласие=False)
    итог, текст, _ = обеспечить(окр)
    assert итог == служба.НУЖНЫ_ПРАВА and "«Да»" in текст


def test_installer_results_are_not_dressed_up():
    итог, текст, _ = обеспечить(Окружение(состояние=None, код_msi=3010))
    assert итог == служба.ГОТОВО and "Перезагрузите" in текст
    итог, текст, _ = обеспечить(Окружение(состояние=None, код_msi=1603))
    assert итог == служба.НЕ_ВЫШЛО and "1603" in текст

    class ПортМолчит(Окружение):
        def порт_жив(self, ждать=0.4):
            return False
    итог, текст, _ = обеспечить(ПортМолчит(состояние=None))
    assert итог == служба.НЕ_ВЫШЛО and "не отвечает" in текст, "поставили, а порт молчит — так и говорим"


def test_a_hung_or_disabled_service_is_restarted_with_one_prompt():
    """Служба есть, но не отвечает: без скачивания, одно окно прав — автозапуск и перезапуск."""
    for окр in (Окружение(состояние="RUNNING", порт=False),
                Окружение(состояние="STOPPED", запуск="DISABLED"),
                Окружение(состояние="STOPPED", права=False)):
        итог, текст, _ = обеспечить(окр)
        assert итог == служба.ГОТОВО, текст
        assert окр.повышений == [["--apple-setup"]] and not окр.скачано and not окр.делали("msiexec")
        assert окр.делали("start") and окр.запуск == "AUTO_START"


# ───────────── повышенный запуск ─────────────

def test_the_elevated_entry_point(monkeypatch):
    вызовы = []
    monkeypatch.setattr(служба, "под_админом",
                        lambda пакет=None, перезапуск=False: вызовы.append((пакет, перезапуск)) or 0)
    assert служба.точка_входа(["pintel-kiosk.exe"]) is None, "обычный запуск — не наш"
    assert служба.точка_входа(["pintel-kiosk.exe", "--apple-setup"]) == 0
    assert служба.точка_входа(["pintel-kiosk.exe", "--apple-setup", "C:/a b/x.msi"]) == 0
    assert служба.точка_входа(["pintel-kiosk.exe", "--apple-setup", "--restart"]) == 0
    assert вызовы == [(None, False), ("C:/a b/x.msi", False), (None, True)]


def test_the_button_restarts_a_service_that_answers_but_does_not_see_the_phone():
    """Кнопку «Починить связь» жмут и тогда, когда служба жива, а телефон не виден. Ответ
    «связь работает» в этот момент — отказ в помощи: по кнопке служба перезапускается всегда,
    одним окном прав, без скачивания. Сама, без кнопки, живую службу программа не трогает."""
    окр = Окружение(состояние="RUNNING", порт=True)
    итог, текст, _ = обеспечить(окр)
    assert итог == служба.ГОТОВО and not окр.повышений and not окр.делали("stop")

    итог, текст, сказано = обеспечить(окр, принудительно=True)
    assert итог == служба.ГОТОВО and "перезапущена" in текст and "кабель" in текст
    assert окр.повышений == [["--apple-setup", "--restart"]] and not окр.скачано
    assert окр.делали("stop") and окр.делали("start") and окр.запуск == "AUTO_START"
    assert any("нажмите «Да»" in с for с in сказано)

    отказ = Окружение(состояние="RUNNING", порт=True, согласие=False)
    итог, текст, _ = обеспечить(отказ, принудительно=True)
    assert итог == служба.НУЖНЫ_ПРАВА and "«Да»" in текст


def test_the_program_relaunches_itself(monkeypatch):
    """Собранный exe зовёт сам себя; из исходников — python с этим же модулем."""
    monkeypatch.setattr(служба.sys, "frozen", True, raising=False)
    monkeypatch.setattr(служба.sys, "executable", "C:/Pintel/pintel-kiosk.exe")
    assert служба.своя_команда(["--apple-setup"]) == ("C:/Pintel/pintel-kiosk.exe", ["--apple-setup"])
    monkeypatch.setattr(служба.sys, "frozen", False, raising=False)
    файл, параметры = служба.своя_команда(["--apple-setup", "x.msi"])
    assert параметры[:2] == ["-m", "pintel_core.devicelink.apple_service"] and параметры[-1] == "x.msi"


def test_the_package_comes_from_apple_itself():
    """Пакет не лежит в нашей сборке (лицензия Apple) — только адрес сервера Apple и сумма."""
    assert служба.ПАКЕТ["url"].startswith("https://swcdn.apple.com/")
    assert служба.ПАКЕТ["url"].endswith("AppleMobileDeviceSupport64.msi")
    assert len(служба.ПАКЕТ["sha256"]) == 64 and служба.ПАКЕТ["sha256"] == служба.ПАКЕТ["sha256"].lower()
