"""Configuration, read from environment variables (see .env.example).
No secrets are needed by this app."""
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int, lo: int, hi: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(lo, min(hi, value))


@dataclass(frozen=True)
class Settings:
    model_id: str = "k2-fsa/OmniVoice"
    device: str = "auto"            # auto | cuda:0 | mps | xpu | cpu
    dtype: str = "auto"             # auto | float16 | float32 | bfloat16
    allow_cpu: bool = False         # "auto" never falls back to CPU unless true
    load_on_startup: bool = True
    max_text_chars: int = 1000
    max_queue: int = 4              # requests allowed to wait for the single model
    rate_limit_per_min: int = 10    # per client IP, generation endpoints
    max_json_bytes: int = 64 * 1024
    max_upload_mb: int = 10
    output_dir: Path = Path("./tmp_audio")
    output_ttl_seconds: int = 300
    cors_origins: tuple = ("http://localhost:5173",)
    trust_proxy: bool = False       # honour X-Forwarded-For (only behind your own proxy)
    enable_voice_cloning: bool = False
    serve_frontend: bool = True

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


def load_settings() -> Settings:
    origins: List[str] = [o.strip() for o in os.getenv(
        "CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()]
    return Settings(
        model_id=os.getenv("OMNIVOICE_MODEL", "k2-fsa/OmniVoice"),
        device=os.getenv("OMNIVOICE_DEVICE", "auto").strip() or "auto",
        dtype=os.getenv("OMNIVOICE_DTYPE", "auto").strip() or "auto",
        allow_cpu=_bool("ALLOW_CPU", False),
        load_on_startup=_bool("LOAD_MODEL_ON_STARTUP", True),
        max_text_chars=_int("MAX_TEXT_CHARS", 1000, 50, 5000),
        max_queue=_int("MAX_QUEUE", 4, 1, 50),
        rate_limit_per_min=_int("RATE_LIMIT_PER_MIN", 10, 1, 1000),
        max_upload_mb=_int("MAX_UPLOAD_MB", 10, 1, 50),
        output_dir=Path(os.getenv("OUTPUT_DIR", "./tmp_audio")),
        output_ttl_seconds=_int("OUTPUT_TTL_SECONDS", 300, 30, 86400),
        cors_origins=tuple(origins),
        trust_proxy=_bool("TRUST_PROXY", False),
        enable_voice_cloning=_bool("ENABLE_VOICE_CLONING", False),
        serve_frontend=_bool("SERVE_FRONTEND", True),
    )
