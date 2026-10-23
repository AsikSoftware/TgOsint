# -*- coding: utf-8 -*-
import os
import sys
import tomllib

DEFAULTS = {
    "server": "",                 # https://pintel.example.kz
    "token": "",                  # pk_… из Настройки → Киоски
    "point": "",                  # подпись в шапке, если сервер недоступен
    "apple_history_seconds": 90,
    "return_seconds": 60,
    "fullscreen": True,
    "currency": "₸",
    "sickw": True,
}


def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def data_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    d = os.path.join(base, "PintelKiosk")
    for sub in ("queue", "cache", "out", "logs"):
        os.makedirs(os.path.join(d, sub), exist_ok=True)
    return d


def load(path=None) -> dict:
    cfg = dict(DEFAULTS)
    p = path or os.path.join(app_dir(), "kiosk.toml")
    if os.path.isfile(p):
        with open(p, "rb") as f:
            cfg.update({k: v for k, v in tomllib.load(f).items() if k in DEFAULTS})
    cfg["_path"] = p
    cfg["server"] = str(cfg["server"]).rstrip("/")
    return cfg
