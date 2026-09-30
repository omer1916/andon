"""Uygulama ayarları. Önce ortam değişkenlerine, yoksa proje kökündeki .env dosyasına bakılır."""

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_DOSYASI = Path(__file__).resolve().parent.parent / ".env"


class Ayarlar(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_DOSYASI, env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = "postgresql://andon:andon@localhost:5432/andon"

    llm_saglayici: Literal["gemini", "ollama"] = "gemini"
    llm_model: str | None = None  # boşsa sağlayıcının varsayılan modeli
    gemini_api_key: str | None = None
    ollama_url: str = "http://localhost:11434/v1"


def ayarlar() -> Ayarlar:
    """Her çağrıda yeniden okunur; testlerde ortam değişkeni değiştirmek yeterli olsun."""
    return Ayarlar()
