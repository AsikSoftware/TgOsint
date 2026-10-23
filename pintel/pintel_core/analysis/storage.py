# -*- coding: utf-8 -*-
"""Память: объём как на коробке и реальная заполненность.

Телефон отдаёт байты в десятичных гигабайтах (64 000 000 000 = 64 ГБ), а
Настройки показывают те же десятичные ГБ. Маркетинговый объём — ближайшая
ступень; сверяется с NVMe-контроллером (capacity, Model Number APxxxx).
"""
import re
from ..devicelink.nodes import deep, num, txt

STEPS = (16, 32, 64, 128, 256, 512, 1024, 2048)


def marketed_gb(total_bytes):
    if not total_bytes:
        return None
    gb = total_bytes / 1e9
    return min(STEPS, key=lambda s: abs(s - gb))


def analyze(disk, nvme=None):
    d = disk or {}
    total = num(d.get("TotalDiskCapacity"))
    data_cap = num(d.get("TotalDataCapacity"))
    data_free = num(d.get("TotalDataAvailable"))
    sys_cap = num(d.get("TotalSystemCapacity"))
    sys_free = num(d.get("TotalSystemAvailable"))
    used = (data_cap - data_free) if (data_cap and data_free is not None) else None

    nv = nvme or {}
    nv_cap = num(deep(nv, "capacity")) if nv else 0
    model = txt(deep(nv, "Model Number")) if nv else ""
    m = re.search(r"AP(\d{4})", model)
    nv_model_gb = int(m.group(1)) if m else None
    fw = txt(deep(nv, "Firmware Revision")) if nv else ""
    cc = (nv.get("Controller Characteristics") or {}) if isinstance(nv, dict) else {}
    vendor = txt(cc.get("vendor-name")).strip() or None
    cell = {1: "SLC", 2: "MLC", 3: "TLC", 4: "QLC"}.get(num(cc.get("cell-type") or cc.get("default-bits-per-cell")))
    marketing = txt(cc.get("nand-marketing-name")).strip() or None

    mk = marketed_gb(total)
    sources = [x for x in (mk, marketed_gb(nv_cap) if nv_cap else None, nv_model_gb) if x]
    agree = (len(set(sources)) <= 1) if sources else None
    return {
        "есть_данные": bool(d),
        "объём_гб": mk,
        "всего_байт": total or None,
        "занято_гб": round(used / 1e9, 1) if used is not None else None,
        "свободно_гб": round(data_free / 1e9, 1) if data_free else None,
        "занято_%": round(used * 100 / data_cap) if (used is not None and data_cap) else None,
        "система_гб": round(sys_cap / 1e9, 1) if sys_cap else None,
        "nvme_объём_гб": marketed_gb(nv_cap) if nv_cap else None,
        "nvme_модель": model,
        "nvme_модель_гб": nv_model_gb,
        "nvme_прошивка": fw,
        "nand_производитель": vendor,
        "nand_тип": cell,
        "nand_маркировка": marketing,
        "объём_сошёлся": agree,
    }
