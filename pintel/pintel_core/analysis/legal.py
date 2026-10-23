# -*- coding: utf-8 -*-
"""Правовой статус: Найти iPhone, активация, пароль, MDM-надзор.

Find My читается ДВУМЯ каналами (корневой домен и узел options) и оба
обязаны декодироваться одинаково — расхождение значит подмену данных.
Третий канал — домен com.apple.fmip/IsAssociated, если телефон его отдаёт.
"""
from ..devicelink.nodes import deep, txt, boolish


def build(snap):
    root = snap.get("root") or {}
    nodes = snap.get("nodes") or {}
    doms = snap.get("domains") or {}
    fm_root = txt(deep(root, "fm-activation-locked")).strip().upper()
    fm_opt = txt(deep(nodes.get("options") or {}, "fm-activation-locked")).strip().upper()
    fmip = doms.get("com.apple.fmip") or {}
    fmip_assoc = boolish(fmip.get("IsAssociated")) if fmip else None

    find_my = {"NO": "выключен", "YES": "включён"}.get(fm_root)
    if find_my is None and fmip_assoc is not None:
        find_my = "включён" if fmip_assoc else "выключен"
    channels_agree = None if not (fm_root and fm_opt) else (fm_root == fm_opt)

    mdm = boolish(deep(nodes.get("AIDBus") or {}, "TRM_TransportSupervised")) is True
    restr = doms.get("com.apple.mobile.restriction") or {}
    purple = doms.get("com.apple.purplebuddy") or {}
    return {
        "найти_iphone": find_my or "не определился",
        "каналы_сошлись": channels_agree,
        "активация": txt(root.get("ActivationState")),
        "пароль": boolish(root.get("PasswordProtected")) is True,
        "mdm": mdm,
        "первичная_настройка_пройдена": boolish(purple.get("SetupDone")) if purple else None,
        "ограничения": {k: v for k, v in restr.items() if boolish(v) is True} if restr else {},
    }
