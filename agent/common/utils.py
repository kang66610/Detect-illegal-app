import hashlib
from pathlib import Path

from cryptography.fernet import Fernet

from backend.app.config import PROJECT_ROOT, config


def sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def get_or_create_fernet_key(cfg: dict | None = None) -> bytes:
    cfg = cfg or config
    key_file = PROJECT_ROOT / cfg["encryption"]["key_file"]
    if key_file.exists():
        return key_file.read_bytes()
    key = Fernet.generate_key()
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_bytes(key)
    return key


def encrypt_bytes(data: bytes, key: bytes) -> bytes:
    return Fernet(key).encrypt(data)


def decrypt_bytes(data: bytes, key: bytes) -> bytes:
    return Fernet(key).decrypt(data)


def decrypt_to_temp(enc_path: Path, key: bytes, tmp_dir: Path) -> Path:
    """解密加密 APK 到临时文件（供 Androguard 解析），用完由调用方删除。"""
    tmp_dir.mkdir(parents=True, exist_ok=True)
    out = tmp_dir / (enc_path.stem + ".tmp.apk")  # x.apk.enc → x.apk.tmp.apk
    out.write_bytes(decrypt_bytes(enc_path.read_bytes(), key))
    return out
