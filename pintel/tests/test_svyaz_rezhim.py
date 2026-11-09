# -*- coding: utf-8 -*-
"""Состояния связи, которые сотрудник должен понимать без нас."""
import asyncio

from pymobiledevice3.exceptions import IncorrectModeError

from pintel_core.devicelink import connect as c


def test_режим_восстановления_назван_словами(monkeypatch):
    """Телефон в режиме восстановления отвечает не lockdown, а restored. Раньше это
    вылезало как «Ошибка связи с телефоном (IncorrectModeError: …)», сотрудник решал, что
    дело в кабеле, и переподключал его по кругу: за вечер полторы сотни строк в журнале."""
    async def restored(**kw):
        raise IncorrectModeError("Incorrect mode returned. Got: {'Type': 'com.apple.mobile.restored'}")

    monkeypatch.setattr(c, "create_using_usbmux", restored)
    st = asyncio.run(c.connect(serial="KFFVKPDP2G"))
    assert st.state == c.RESTORE_MODE
    assert "восстановлен" in st.human.lower() and "громкость" in st.human.lower()
    assert "IncorrectModeError" not in st.human


def test_обычная_ошибка_связи_осталась_ошибкой(monkeypatch):
    async def беда(**kw):
        raise OSError("device busy")

    monkeypatch.setattr(c, "create_using_usbmux", беда)
    st = asyncio.run(c.connect(serial="X"))
    assert st.state == c.ERROR and "device busy" in st.human
