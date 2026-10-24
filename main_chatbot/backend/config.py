from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    groq_api_key: str
    llm_model: str = "groq/openai/gpt-oss-120b"
    llm_max_tokens: int = 3500
    llm_temperature: float = 0.0
    pandasai_max_retries: int = 1
    max_upload_size_mb: int = 25
    session_ttl_minutes: int = 60
    max_active_sessions: int = 20
    upload_directory: Path = PROJECT_ROOT / "main_chatbot" / "storage" / "uploads"
    chart_directory: Path = PROJECT_ROOT / "main_chatbot" / "storage" / "charts"
    cors_origins: tuple[str, ...] = (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    )

    @classmethod
    def from_environment(cls) -> "Settings":
        api_key = os.getenv("GROQ_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("GROQ_API_KEY is not configured in the environment.")

        cors = tuple(
            origin.strip()
            for origin in os.getenv(
                "CORS_ORIGINS",
                "http://localhost:5173,http://127.0.0.1:5173",
            ).split(",")
            if origin.strip()
        )
        return cls(
            groq_api_key=api_key,
            llm_model=os.getenv("LLM_MODEL", cls.llm_model),
            llm_max_tokens=int(os.getenv("LLM_MAX_TOKENS", cls.llm_max_tokens)),
            llm_temperature=float(os.getenv("LLM_TEMPERATURE", cls.llm_temperature)),
            pandasai_max_retries=int(
                os.getenv("PANDASAI_MAX_RETRIES", cls.pandasai_max_retries)
            ),
            max_upload_size_mb=int(
                os.getenv("MAX_UPLOAD_SIZE_MB", cls.max_upload_size_mb)
            ),
            session_ttl_minutes=int(
                os.getenv("SESSION_TTL_MINUTES", cls.session_ttl_minutes)
            ),
            max_active_sessions=int(
                os.getenv("MAX_ACTIVE_SESSIONS", cls.max_active_sessions)
            ),
            cors_origins=cors,
        )

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    def create_runtime_directories(self) -> None:
        self.upload_directory.mkdir(parents=True, exist_ok=True)
        self.chart_directory.mkdir(parents=True, exist_ok=True)

