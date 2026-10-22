"""Кабельный слой: всё, что читается с iPhone через libimobiledevice.

Логика перенесена из diag.sh, включая выстраданные поправки:
  * имена записей реестра различаются между поколениями — перебираем варианты;
  * служба диагностики отказывает с первого раза — повторяем;
  * отсутствие данных НИКОГДА не превращается в вердикт.
"""
import os, plistlib, re, shutil, subprocess, tempfile, time

# Под Windows бинарники кладутся рядом с exe в папку bin/
BIN_DIRS = ["/opt/homebrew/bin", "/usr/local/bin",
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin")]

def _tool(name):
    for d in BIN_DIRS:
        for ext in ("", ".exe"):
            p = os.path.join(d, name + ext)
            if os.path.isfile(p):
                return p
    return shutil.which(name) or shutil.which(name + ".exe")

class NoDevice(Exception):
    pass

def udid():
    t = _tool("idevice_id")
    if not t:
        raise NoDevice("libimobiledevice не найден. Под Windows положи бинарники в папку bin/.")
    out = subprocess.run([t, "-l"], capture_output=True, text=True, timeout=15).stdout
    ids = [x.strip() for x in out.split("\n") if x.strip()]
    if not ids:
        raise NoDevice("Телефон не подключён или не нажато «Доверять».")
    return ids[0]

def _info(u, domain=None):
    t = _tool("ideviceinfo")
    cmd = [t, "-u", u, "--xml"] + (["-q", domain] if domain else [])
    r = subprocess.run(cmd, capture_output=True, timeout=40)
    try:
        return plistlib.loads(r.stdout)
    except Exception:
        return {}

def _entry(u, name, tries=3):
    """Запись IORegistry. Служба отказывает с первого раза заметно часто,
    поэтому повторяем: один отказ раньше стоил пропавшего вердикта."""
    t = _tool("idevicediagnostics")
    for _ in range(tries):
        r = subprocess.run([t, "-u", u, "ioregentry", name],
                           capture_output=True, timeout=30)
        try:
            d = plistlib.loads(r.stdout)
            if d.get("IORegistry"):
                return d["IORegistry"]
        except Exception:
            pass
        time.sleep(1)
    return {}

def _first_entry(u, names):
    """Имя записи зависит от поколения: у камеры это AppleH13CamIn или
    AppleCamera или AppleH16CamIn, у контроллера памяти ANS2/ANS3/CGv2."""
    for n in names:
        d = _entry(u, n, tries=2)
        if d:
            return n, d
    return None, {}

def deep(o, key):
    """Ищем ключ на любой глубине: Apple прячет нужное во вложенных разделах."""
    if isinstance(o, dict):
        if key in o and not isinstance(o[key], (dict, list)):
            return o[key]
        for v in o.values():
            r = deep(v, key)
            if r is not None:
                return r
    elif isinstance(o, list):
        for v in o:
            r = deep(v, key)
            if r is not None:
                return r
    return None

def txt(v):
    """Серийники лежат байтами с нулём на конце."""
    if isinstance(v, (bytes, bytearray)):
        s = bytes(v).rstrip(b"\x00")
        try:
            return s.decode("ascii")
        except Exception:
            return ""
    return str(v or "")

def num(v):
    try:
        return int(v)
    except Exception:
        return 0

CAM_NAMES = ("AppleH13CamIn", "AppleCamera", "AppleH14CamIn", "AppleH16CamIn", "AppleH10CamIn")
NVME_NAMES = ("AppleANS3NVMeController", "AppleANS2NVMeController",
              "AppleANS3CGv2Controller", "AppleANS2CGv2Controller",
              "AppleANS2CGNVMeController", "AppleEmbeddedNVMeController")

def collect():
    """Снимает с телефона всё нужное. Возвращает сырые данные без суждений."""
    u = udid()
    root = _info(u)
    disk = _info(u, "com.apple.disk_usage")
    _, cam = _first_entry(u, CAM_NAMES)
    _, nvme = _first_entry(u, NVME_NAMES)
    out = {
        "udid": u,
        "root": root,
        "disk_total_gb": num(disk.get("TotalDiskCapacity")) // 10**9,
        "disk_free_gb": num(disk.get("TotalDataAvailable")) // 10**9,
        "nand_blob": disk.get("NANDInfo"),
        "battery": _entry(u, "AppleSmartBattery"),
        "display": _entry(u, "AppleCLCD2"),
        "backlight": _entry(u, "AppleARMBacklight"),
        "touch": _entry(u, "AppleMultitouchDevice"),
        "camera": cam,
        "nvme": nvme,
        "product": _entry(u, "product"),
        "devtree": _entry(u, "device-tree"),
        "prox": _entry(u, "AppleProxHIDEventDriver"),
        "haptic_eeprom": _entry(u, "AppleHapticsSupportArcEEPROM"),
        "haptic_iface": _entry(u, "haptics-support-interface"),
        "options": _entry(u, "options"),
        "aidbus": _entry(u, "AIDBus"),
    }
    return out
