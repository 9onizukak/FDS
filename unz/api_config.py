"""FDH API settings shared by the GUI and command-line clients."""
from dataclasses import dataclass
import os
from pathlib import Path
from urllib.parse import urlsplit

import get_token
from runtime_paths import ENV_PATH

UAT_URL = "https://uat-fdh.inet.co.th"
PRODUCTION_URL = "https://fdh.moph.go.th"


def validate_url(url):
    parts = urlsplit(url)
    if (any(character.isspace() for character in url)
            or parts.scheme != "https" or not parts.hostname or parts.username or parts.password
            or parts.fragment):
        raise ValueError("URL ต้องขึ้นต้นด้วย https:// และไม่มีชื่อผู้ใช้ รหัสผ่าน หรือ #")
    return url.rstrip("/")


def dataset_base_url(base_url):
    """Accept a host or an explicit dataset API base path."""
    base_url = base_url.rstrip("/")
    return base_url if urlsplit(base_url).path.strip("/") else base_url + "/fdh_api/v1/dataset"


@dataclass(frozen=True)
class APIConfig:
    environment: str = "UAT"
    uat_url: str = UAT_URL
    production_url: str = PRODUCTION_URL
    token_url: str = get_token.TOKEN_URL

    def __post_init__(self):
        if self.environment not in ("UAT", "PRODUCTION"):
            raise ValueError("FDH_ENV ต้องเป็น UAT หรือ PRODUCTION")
        for url in (self.uat_url, self.production_url, self.token_url):
            validate_url(url)
        if urlsplit(self.uat_url).query or urlsplit(self.production_url).query:
            raise ValueError("Base URL ต้องไม่มี query string")

    @property
    def base_url(self):
        return (self.production_url if self.environment == "PRODUCTION" else self.uat_url).rstrip("/")

    def dataset_url(self, operation):
        return f"{dataset_base_url(self.base_url)}/{operation}"


def load(env=None):
    env = get_token.load_env() if env is None else env
    return APIConfig(
        environment=(env.get("FDH_ENV") or "UAT").strip().upper(),
        uat_url=(env.get("FDH_UAT_BASE_URL") or UAT_URL).strip(),
        production_url=(env.get("FDH_PRODUCTION_BASE_URL") or PRODUCTION_URL).strip(),
        token_url=(env.get("FDH_TOKEN_URL") or get_token.TOKEN_URL).strip())


def save(config, path=None):
    """Update only API keys, preserving credentials and other settings."""
    path = Path(path) if path is not None else ENV_PATH
    values = {
        "FDH_ENV": config.environment,
        "FDH_UAT_BASE_URL": config.uat_url.rstrip("/"),
        "FDH_PRODUCTION_BASE_URL": config.production_url.rstrip("/"),
        "FDH_TOKEN_URL": config.token_url,
    }
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    lines, seen = [], set()
    for line in existing.splitlines():
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else None
        if key in values:
            lines.append(f"{key}={values[key]}")
            seen.add(key)
        else:
            lines.append(line)
    lines.extend(f"{key}={value}" for key, value in values.items() if key not in seen)
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
