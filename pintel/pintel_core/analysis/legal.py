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

    # Надзор (MDM): флаг TRM_TransportSupervised. На Lightning-аппаратах он в AIDBus,
    # на USB-C узла AIDBus нет — ищем в узлах аксессуарного порта; не нашли — None,
    # и это честное «не определился», а не «нет».
    trm = None
    for key in ("AIDBus", "accessory", "accessory_mgr", "accessory_port"):
        v = deep(nodes.get(key) or {}, "TRM_TransportSupervised")
        if v is not None:
            trm = v
            break
    from ..devicelink import mdm as mdm_mod
    mdm_svc, mdm_why = mdm_mod.verdict(snap.get("mdm"))
    mdm_node = boolish(trm) if trm is not None else None
    if mdm_svc is not None:
        mdm = True if (mdm_svc or mdm_node) else False
        mdm_source = "служба профилей" + (" + узел порта" if mdm_node is not None else "")
    else:
        mdm = mdm_node
        mdm_source = "узел порта" if mdm_node is not None else None
        mdm_why = "по флагу TRM_TransportSupervised" if mdm_node is not None else mdm_why
    restr = doms.get("com.apple.mobile.restriction") or {}
    purple = doms.get("com.apple.purplebuddy") or {}
    return {
        "найти_iphone": find_my or "не определился",
        "каналы_сошлись": channels_agree,
        "активация": txt(root.get("ActivationState")),
        "пароль": boolish(root.get("PasswordProtected")) is True,
        "mdm": mdm,
        "mdm_почему": mdm_why,
        "mdm_источник": mdm_source,
        "первичная_настройка_пройдена": boolish(purple.get("SetupDone")) if purple else None,
        "ограничения": {k: v for k, v in restr.items() if boolish(v) is True} if restr else {},
    }
