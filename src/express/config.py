from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

# XDG-ish user data under ~/.express (migrates from legacy ~/.el)
CONFIG_DIR = Path.home() / ".express"
LEGACY_DIR = Path.home() / ".el"
CONFIG_PATH = CONFIG_DIR / "config.toml"
DB_PATH = CONFIG_DIR / "shipments.db"

# Order used by default_provider = "auto": stable free API first.
DEFAULT_PROVIDER_CHAIN = ["apizero", "alapi"]


@dataclass
class AppConfig:
    default_provider: str = "auto"
    apizero_key: str = ""
    alapi_key: str = ""
    huawei_jm_appkey: str = ""
    huawei_jm_appsecret: str = ""
    kd100_appkey: str = ""
    kd100_appsecret: str = ""
    provider_chain: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def has_apizero_credentials(self) -> bool:
        return bool(self.apizero_key)

    def has_alapi_credentials(self) -> bool:
        return bool(self.alapi_key)

    def has_huawei_jm_credentials(self) -> bool:
        return bool(self.huawei_jm_appkey and self.huawei_jm_appsecret)

    def has_kd100_credentials(self) -> bool:
        return bool(self.kd100_appkey and self.kd100_appsecret)


def ensure_config_dir() -> Path:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _migrate_legacy_if_needed()
    return CONFIG_DIR


def _migrate_legacy_if_needed() -> None:
    """Copy credentials/DB from ~/.el once if ~/.express is empty."""
    if not LEGACY_DIR.is_dir():
        return
    legacy_cfg = LEGACY_DIR / "config.toml"
    legacy_db = LEGACY_DIR / "shipments.db"
    if legacy_cfg.is_file() and not CONFIG_PATH.is_file():
        shutil.copy2(legacy_cfg, CONFIG_PATH)
    if legacy_db.is_file() and not DB_PATH.is_file():
        shutil.copy2(legacy_db, DB_PATH)


def _load_toml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open("rb") as f:
        return tomllib.load(f)


def load_config() -> AppConfig:
    ensure_config_dir()
    data = _load_toml(CONFIG_PATH)
    provider = str(data.get("default_provider", "auto"))

    az = data.get("apizero") or {}
    if not isinstance(az, dict):
        az = {}
    al = data.get("alapi") or {}
    if not isinstance(al, dict):
        al = {}

    apizero_key = (
        os.environ.get("EXPRESS_APIZERO_KEY")
        or str(az.get("key", "") or "")
    ).strip()
    alapi_key = (
        os.environ.get("EXPRESS_ALAPI_TOKEN")
        or os.environ.get("EL_ALAPI_TOKEN")
        or str(al.get("key", "") or "")
    ).strip()

    hw = data.get("huawei_jm") or {}
    if not isinstance(hw, dict):
        hw = {}
    huawei_jm_appkey = (
        os.environ.get("EXPRESS_HUAWEI_JM_APPKEY")
        or os.environ.get("EL_HUAWEI_JM_APPKEY")
        or str(hw.get("app_key", "") or "")
    ).strip()
    huawei_jm_appsecret = (
        os.environ.get("EXPRESS_HUAWEI_JM_APPSECRET")
        or os.environ.get("EL_HUAWEI_JM_APPSECRET")
        or str(hw.get("app_secret", "") or "")
    ).strip()

    kd100 = data.get("huawei_kd100") or {}
    if not isinstance(kd100, dict):
        kd100 = {}
    kd100_appkey = (
        os.environ.get("EXPRESS_KD100_APPKEY")
        or os.environ.get("EL_KD100_APPKEY")
        or str(kd100.get("app_key", "") or "")
    ).strip()
    kd100_appsecret = (
        os.environ.get("EXPRESS_KD100_APPSECRET")
        or os.environ.get("EL_KD100_APPSECRET")
        or str(kd100.get("app_secret", "") or "")
    ).strip()

    chain: list[str] = []
    raw_chain = data.get("provider_chain") or []
    if isinstance(raw_chain, str):
        chain = [c.strip() for c in raw_chain.split(",") if c.strip()]
    elif isinstance(raw_chain, list):
        chain = [str(c).strip() for c in raw_chain if str(c).strip()]
    env_chain = os.environ.get("EXPRESS_PROVIDER_CHAIN")
    if env_chain:
        chain = [c.strip() for c in env_chain.split(",") if c.strip()]

    env_provider = os.environ.get("EXPRESS_PROVIDER") or os.environ.get("EL_PROVIDER")
    if env_provider:
        provider = env_provider.strip()

    return AppConfig(
        default_provider=provider,
        apizero_key=apizero_key,
        alapi_key=alapi_key,
        huawei_jm_appkey=huawei_jm_appkey,
        huawei_jm_appsecret=huawei_jm_appsecret,
        kd100_appkey=kd100_appkey,
        kd100_appsecret=kd100_appsecret,
        provider_chain=chain,
        extra={
            k: v
            for k, v in data.items()
            if k
            not in (
                "default_provider",
                "provider_chain",
                "apizero",
                "alapi",
                "huawei_jm",
                "huawei_kd100",
            )
        },
    )


def write_example_config(path: Path | None = None) -> Path:
    ensure_config_dir()
    target = path or CONFIG_PATH
    if target.is_file():
        return target
    target.write_text(
        """# express tracker config
# default_provider: auto | apizero | alapi | mock
# auto = try providers in order until one succeeds (see provider_chain)
# apizero = free real data (30/day no key, 100/day with key from apizero.cn)
# alapi = free tier (token from alapi.cn; kd interface may need membership)
default_provider = "auto"

# Order for auto fallback; providers without credentials are skipped.
# Stable free API first.
provider_chain = ["apizero", "alapi"]

[apizero]
key = ""

[alapi]
key = ""

[huawei_jm]
# Huawei Cloud marketplace 快递查询【最新版】 (聚美智数/杭州安那其; APP signature)
# from the purchased-service Resource Detail -> APIG gateway
app_key = ""
app_secret = ""

[huawei_kd100]
# 快递100/百递云 via Huawei Cloud APIG (same APP signature as [huawei_jm],
# different product gateway). Purchase:
#   marketplace.huaweicloud.com/contents/af4f963a-0894-4aa3-860d-acab425267e7
app_key = ""
app_secret = ""
""",
        encoding="utf-8",
    )
    return target


def save_default_provider(name: str) -> Path:
    """Set default_provider in the config file, preserving comments/other keys."""
    ensure_config_dir()
    if not CONFIG_PATH.is_file():
        write_example_config()
    text = CONFIG_PATH.read_text(encoding="utf-8")
    marker = "default_provider ="
    lines = text.splitlines(keepends=True)
    replaced = False
    for i, line in enumerate(lines):
        # Match the assignment, ignore commented lines like "# default_provider: ..."
        if marker in line and not line.lstrip().startswith("#"):
            lines[i] = f'default_provider = "{name}"\n'
            replaced = True
            break
    if not replaced:
        # Insert after the leading comment/blank header block
        insert_at = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                insert_at = i + 1
            else:
                break
        lines.insert(insert_at, f'default_provider = "{name}"\n')
    CONFIG_PATH.write_text("".join(lines), encoding="utf-8")
    return CONFIG_PATH
