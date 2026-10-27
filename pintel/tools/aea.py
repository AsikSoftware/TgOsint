# -*- coding: utf-8 -*-
"""Расшифровка .dmg.aea из прошивок Apple (iOS 18+) — потоком, без сохранения образа.

С iOS 18 образы в IPSW завёрнуты в Apple Encrypted Archive (профиль 1:
HKDF-SHA256 + AES-CTR + HMAC-SHA256, сегменты сжаты LZFSE). Ключ Apple отдаёт сама,
бесплатно и без авторизации: в заголовке AEA лежит ссылка на открытый сервер ключей
и завёрнутый ключ, развернуть его — обычный HPKE.

Разобрано по двум эталонам, им и соответствует байт в байт:
  * получение ключа — get_key.py (dhinakg/aeota): HPKE base, DHKEM(P-256,HKDF-SHA256) /
    HKDF-SHA256 / AES-256-GCM, info и aad пустые;
  * расшифровка кластеров — pkg/aea/decrypt.go (blacktop/ipsw, тег v3.1.580).

Корректность доказуема без распаковки: каждый сегмент несёт HMAC-SHA256 от шифртекста,
и корневой заголовок, и каждый кластер — тоже. Если HMAC сошёлся, AES-CTR расшифровал
ровно те байты; остаётся только разжать LZFSE. Поэтому ниже всё проверяется HMAC-ом.

Единственная внешняя зависимость — декодер LZFSE (сегменты им сжаты). Берётся любой из:
  1. модуль `liblzfse` (pip install pyliblzfse) — им же пользуется tools/прошивка.py;
  2. общий объект liblzfse.so через ctypes, путь в переменной окружения AEA_LZFSE_LIB.
Без него расшифровка проходит и проверяется по HMAC, но строки прочитать нельзя.
"""
import base64
import ctypes
import hashlib
import hmac as _hmac
import json
import os
import struct
import subprocess
import zlib

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import serialization

MAGIC = b"AEA1"
MAIN_KEY_INFO = b"AEA_AMK"
ROOT_HDR_INFO = b"AEA_RHEK"
CLUSTER_INFO = b"AEA_CK"
CLUSTER_MAT_INFO = b"AEA_CHEK"
SEGMENT_INFO = b"AEA_SK"
CHECKSUM_SIZE = {0: 0, 1: 8, 2: 32}            # нет / Murmur / SHA-256
# байты поля «сжатие» в корневом заголовке (compressionType в эталоне)
СЖАТИЕ = {ord("-"): "none", ord("z"): "zlib", ord("e"): "lzfse", ord("b"): "lzbitmap"}


def _hkdf(ikm, salt, info, length):
    return HKDF(algorithm=SHA256(), length=length, salt=salt, info=info).derive(ikm)


def _ctr(ct, key, iv):
    d = Cipher(algorithms.AES(key), modes.CTR(iv)).decryptor()
    return d.update(ct) + d.finalize()


def _mac(key, data, salt):
    """Повтор getHMAC из эталона: HMAC(key, salt || data || le64(len(salt)))."""
    m = _hmac.new(key, digestmod=hashlib.sha256)
    m.update(salt + data + struct.pack("<Q", len(salt)))
    return m.digest()


# --------------------------------------------------------------------------- ключ

def _hpke_open(enc, skR, ct):
    """HPKE base-mode открытие (RFC 9180) для нашего набора шифров. Возвращает ключ AEA."""
    kem = b"KEM" + struct.pack(">H", 0x0010)
    hp = b"HPKE" + struct.pack(">H", 0x0010) + struct.pack(">H", 0x0001) + struct.pack(">H", 0x0002)

    def extract(salt, label, ikm, suite):
        return _hmac.new(salt or b"\x00" * 32, b"HPKE-v1" + suite + label + ikm, hashlib.sha256).digest()

    def expand(prk, label, info, length, suite):          # HKDF-Expand с меткой HPKE
        data = struct.pack(">H", length) + b"HPKE-v1" + suite + label + info
        out, block, i = b"", b"", 1
        while len(out) < length:
            block = _hmac.new(prk, block + data + bytes([i]), hashlib.sha256).digest()
            out += block
            i += 1
        return out[:length]

    pkE = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), enc)
    dh = skR.exchange(ec.ECDH(), pkE)
    pkRm = skR.public_key().public_bytes(serialization.Encoding.X962,
                                         serialization.PublicFormat.UncompressedPoint)
    eae_prk = extract(b"", b"eae_prk", dh, kem)
    shared = expand(eae_prk, b"shared_secret", enc + pkRm, 32, kem)
    ks_ctx = b"\x00" + extract(b"", b"psk_id_hash", b"", hp) + extract(b"", b"info_hash", b"", hp)
    secret = extract(shared, b"secret", b"", hp)
    key = expand(secret, b"key", ks_ctx, 32, hp)
    nonce = expand(secret, b"base_nonce", ks_ctx, 12, hp)
    return AESGCM(key).decrypt(nonce, ct, b"")


def _get(url):
    return subprocess.run(["curl", "-sSL", url], capture_output=True, timeout=60).stdout


def ключ_из_полей(fields, http_get=_get):
    """fields: {имя(bytes) -> значение(bytes)} из auth-data. Возвращает 32-байтовый ключ AEA."""
    resp = json.loads(fields[b"com.apple.wkms.fcs-response"])
    url = fields[b"com.apple.wkms.fcs-key-url"].decode()
    enc = base64.b64decode(resp["enc-request"])
    wrapped = base64.b64decode(resp["wrapped-key"])
    skR = serialization.load_pem_private_key(http_get(url), password=None)
    return _hpke_open(enc, skR, wrapped)


# ------------------------------------------------------------------------ заголовок

def разобрать_auth(blob):
    """blob начинается с заголовка AEA. -> (profile_scrypt, auth_len, authData, fields)."""
    if blob[:4] != MAGIC:
        raise ValueError("не AEA1")
    profile_scrypt, = struct.unpack("<I", blob[4:8])
    if (profile_scrypt & 0xFFFFFF) != 1:
        raise ValueError(f"профиль {profile_scrypt & 0xFFFFFF}, ждали 1 (симметричный)")
    auth_len, = struct.unpack("<I", blob[8:12])
    authData = blob[12:12 + auth_len]
    fields, p = {}, 0
    while p < len(authData):
        ln, = struct.unpack("<I", authData[p:p + 4])
        if ln < 4 or p + ln > len(authData):
            break
        body = authData[p + 4:p + ln]
        z = body.find(b"\x00")
        fields[body[:z]] = body[z + 1:]
        p += ln
    return profile_scrypt, auth_len, authData, fields


def корневой_заголовок(symkey, profile_scrypt, authData, main_salt, enc_root):
    """Проверяет HMAC корневого заголовка и расшифровывает его. -> (mainKey, clusterHmac, rh)."""
    main_key = _hkdf(symkey, main_salt, MAIN_KEY_INFO + struct.pack("<I", profile_scrypt), len(symkey))
    rhk = _hkdf(main_key, b"", ROOT_HDR_INFO, 80)
    rhk_mac, rhk_key, rhk_iv = rhk[:32], rhk[32:64], rhk[64:80]
    hmac_field, data48, cluster_hmac = enc_root[:32], enc_root[32:80], enc_root[80:112]
    if not _hmac.compare_digest(_mac(rhk_mac, data48, cluster_hmac + authData), hmac_field):
        raise ValueError("корневой HMAC не сошёлся — ключ неверен")
    rh = _ctr(data48, rhk_key, rhk_iv)
    file_size, enc_size = struct.unpack("<QQ", rh[:16])
    seg_size, seg_per_cluster = struct.unpack("<II", rh[16:24])
    return main_key, cluster_hmac, {
        "file_size": file_size, "enc_size": enc_size, "seg_size": seg_size,
        "seg_per_cluster": seg_per_cluster, "compression": rh[24], "checksum": rh[25]}


# -------------------------------------------------------------------- распаковка

class НетLZFSE(RuntimeError):
    """Расшифровка прошла, но сегменты сжаты LZFSE, а декодера в сборке нет."""


def _найти_lzfse():
    """Декодер LZFSE: сперва модуль liblzfse, затем liblzfse.so через ctypes."""
    try:
        import liblzfse
        return lambda data, out_size: liblzfse.decompress(data)
    except ImportError:
        pass
    путь = os.environ.get("AEA_LZFSE_LIB")
    if путь and os.path.isfile(путь):
        lib = ctypes.CDLL(путь)
        lib.lzfse_decode_buffer.restype = ctypes.c_size_t
        lib.lzfse_decode_buffer.argtypes = [ctypes.c_char_p, ctypes.c_size_t,
                                            ctypes.c_char_p, ctypes.c_size_t, ctypes.c_void_p]

        def _decode(data, out_size):
            dst = ctypes.create_string_buffer(out_size)
            n = lib.lzfse_decode_buffer(dst, out_size, data, len(data), None)
            return dst.raw[:n]
        return _decode
    return None


def сделать_распаковщик():
    """Возвращает функцию (compression_byte, data, out_size) -> bytes. LZFSE грузит лениво."""
    lzfse = [None]      # кэш декодера LZFSE

    def распаковать(comp, data, out_size):
        if comp == ord("-"):
            return data
        if comp == ord("z"):
            return zlib.decompress(data)
        if comp == ord("e"):
            if lzfse[0] is None:
                lzfse[0] = _найти_lzfse() or False
            if not lzfse[0]:
                raise НетLZFSE("нужен декодер LZFSE: pip install pyliblzfse, "
                               "или AEA_LZFSE_LIB=/путь/к/liblzfse.so")
            return lzfse[0](data, out_size)
        raise НетLZFSE(f"сжатие {СЖАТИЕ.get(comp, comp)!r} пока не поддержано")

    return распаковать


# ------------------------------------------------------------- поток расшифровки

def идти_по_сегментам(read_exact, main_key, cluster_hmac, rh, распаковать=None, проверять=True):
    """Идёт по кластерам и сегментам, отдаёт расшифрованные (и распакованные) куски по порядку.

    read_exact(n) -> ровно n байт потока AEA, начиная сразу после корневого заголовка.
    распаковать(comp, data, out_size) -> распакованные байты; None — только расшифровать
    (сырьё отдаётся лишь для несжатых сегментов, остальные — пустыми, HMAC всё равно проверен).
    """
    seg_per = rh["seg_per_cluster"]
    seg_hdr_size = CHECKSUM_SIZE[rh["checksum"]] + 8
    cindex, total = 0, 0
    while True:
        cluster_key = _hkdf(main_key, b"", CLUSTER_INFO + struct.pack("<I", cindex), len(main_key))
        chk = _hkdf(cluster_key, b"", CLUSTER_MAT_INFO, 80)
        chk_mac, chk_key, chk_iv = chk[:32], chk[32:64], chk[64:80]
        enc_seg_hdrs = read_exact(seg_hdr_size * seg_per)
        next_cluster_mac = read_exact(32)
        seg_mac_data = read_exact(32 * seg_per)
        if проверять and not _hmac.compare_digest(
                _mac(chk_mac, enc_seg_hdrs, next_cluster_mac + seg_mac_data), cluster_hmac):
            raise ValueError(f"HMAC кластера #{cindex} не сошёлся")
        seg_macs = [seg_mac_data[i * 32:i * 32 + 32] for i in range(seg_per)]
        seg_hdr_plain = _ctr(enc_seg_hdrs, chk_key, chk_iv)
        for i in range(seg_per):
            o = i * seg_hdr_size
            dec_size, comp_size = struct.unpack("<II", seg_hdr_plain[o:o + 8])
            if dec_size == 0:
                continue
            total += dec_size
            seg_ct = read_exact(comp_size)
            seg_key = _hkdf(cluster_key, b"", SEGMENT_INFO + struct.pack("<I", i), 80)
            sk_mac, sk_key, sk_iv = seg_key[:32], seg_key[32:64], seg_key[64:80]
            if проверять and not _hmac.compare_digest(_mac(sk_mac, seg_ct, b""), seg_macs[i]):
                raise ValueError(f"HMAC сегмента #{i} (кластер {cindex}) не сошёлся")
            plain = _ctr(seg_ct, sk_key, sk_iv)
            if dec_size == comp_size:                      # сегмент не сжат
                yield plain
            elif распаковать is not None:
                yield распаковать(rh["compression"], plain, dec_size)
            else:
                yield b""
        cluster_hmac = next_cluster_mac
        cindex += 1
        if total >= rh["file_size"]:
            break
