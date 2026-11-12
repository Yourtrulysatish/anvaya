"""Runtime configuration. All secrets come from environment variables (never from code)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_dotenv() -> None:
    """Tiny .env loader (no dependency). Real environment variables win."""
    for candidate in (Path.cwd() / ".env", Path(__file__).resolve().parents[2] / ".env"):
        if candidate.is_file():
            for line in candidate.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            return


_load_dotenv()

TASKS = ("reasoning", "agent", "extraction", "summarisation", "report")


@dataclass
class Settings:
    freemodel_api_key: str = field(default_factory=lambda: os.environ.get("FREEMODEL_API_KEY", ""))
    freemodel_base_url: str = field(default_factory=lambda: os.environ.get("FREEMODEL_BASE_URL", "https://freemodel.in/v1"))
    # Optional explicit model per task. When empty the provider picks from the live catalogue.
    model_overrides: dict = field(default_factory=lambda: {
        t: os.environ.get(f"ANVAYA_MODEL_{t.upper()}", "") for t in TASKS})
    requests_per_minute: int = field(default_factory=lambda: int(os.environ.get("ANVAYA_RPM", "50")))
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("ANVAYA_DATA_DIR", "./data")).resolve())
    cors_origins: list = field(default_factory=lambda: [
        o.strip() for o in os.environ.get("ANVAYA_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()])
    allow_registration: bool = field(default_factory=lambda: os.environ.get("ANVAYA_ALLOW_REGISTRATION", "true").lower() == "true")
    max_upload_mb: int = field(default_factory=lambda: int(os.environ.get("ANVAYA_MAX_UPLOAD_MB", "15")))
    max_agents: int = field(default_factory=lambda: int(os.environ.get("ANVAYA_MAX_AGENTS", "600")))
    max_rounds: int = field(default_factory=lambda: int(os.environ.get("ANVAYA_MAX_ROUNDS", "60")))
    # Optional research provider (web search). FreeModel's catalogue flags some models "web_search"
    # but that capability is NOT assumed; a dedicated provider is configured here if wanted.
    research_provider: str = field(default_factory=lambda: os.environ.get("ANVAYA_RESEARCH_PROVIDER", "none"))
    tavily_api_key: str = field(default_factory=lambda: os.environ.get("TAVILY_API_KEY", ""))
    mirofish_url: str = field(default_factory=lambda: os.environ.get("MIROFISH_URL", ""))

    @property
    def db_path(self) -> Path:
        return self.data_dir / "anvaya.sqlite3"

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def llm_configured(self) -> bool:
        return bool(self.freemodel_api_key)

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
