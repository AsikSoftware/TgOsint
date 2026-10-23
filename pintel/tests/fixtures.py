# -*- coding: utf-8 -*-
"""Адаптер слепков из архива (data/inventories/*.json) к формату snapshot.

Архивные файлы плоские: «узел/IORegistry/ключ» → строка; «DOMAIN:домен/ключ».
Бинарные значения в них заменены заглушкой «<N байт>» — становятся None.
"""
import glob, json, os, re

HERE = os.path.dirname(os.path.abspath(__file__))
INVENTORIES = sorted(glob.glob(os.path.join(HERE, "..", "..", "data", "inventories", "*.json")))


def _coerce(v):
    if not isinstance(v, str):
        return v
    s = v.strip()
    if s in ("True", "False"):
        return s == "True"
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    if re.fullmatch(r"<\d+ байт>", s):
        return None
    return v


def unflatten(flat):
    root = {}
    for path, v in flat.items():
        parts = path.split("/")
        d = root
        for p in parts[:-1]:
            d = d.setdefault(p, {})
            if not isinstance(d, dict):
                break
        else:
            d[parts[-1]] = _coerce(v)
    return root


def load_snapshot(path):
    flat = json.load(open(path, encoding="utf-8"))
    tree = unflatten(flat)
    root = tree.get("DOMAIN:_root", {})
    domains = {k[len("DOMAIN:"):]: v for k, v in tree.items()
               if k.startswith("DOMAIN:") and k != "DOMAIN:_root"}
    nodes = {}
    for name, v in tree.items():
        if isinstance(v, dict) and "IORegistry" in v:
            nodes[name] = v["IORegistry"]
    cam = next((nodes[n] for n in nodes if re.match(r"^Apple(H\d+CamIn|Camera)$", n)), None)
    nvme = next((nodes[n] for n in nodes if re.match(r"^Apple(ANS\d\w*Controller|EmbeddedNVMeController)$", n)), None)
    picked = {n: nodes.get(n) for n in (
        "AppleSmartBattery", "AppleARMBacklight", "AppleCLCD2", "AppleMultitouchDevice",
        "AppleHapticsSupportArcEEPROM", "haptics-support-interface", "AppleProxHIDEventDriver",
        "product", "device-tree", "options", "AIDBus")}
    picked["camera"], picked["nvme"] = cam, nvme
    return {"snapshot_version": 2, "когда": "архив", "root": root, "domains": domains,
            "node_names": sorted(nodes), "nodes": picked, "nand_summary": {}, "quality": {"источник": "архив"}}
