"""Configuración del servicio. Sale sólo de variables de entorno (ver `.env.example`)."""

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings

ESPERA_DEL_MODELO_S = 60.0


class Configuracion(BaseSettings):
    # `mock` responde de forma determinística y sin red. Un valor desconocido corta el arranque.
    llm_provider: Literal["mock", "ollama"] = "mock"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3.5:4b-q4_K_M"
    llm_timeout_s: float = Field(default=ESPERA_DEL_MODELO_S, gt=0)
    # Dónde se guarda el estado de las llamadas.
    sqlite_path: Path = Path("data/llamadas.sqlite")
    # Carpeta con el panel ya compilado. Sin ella, el servicio expone sólo la API.
    static_dir: Path | None = None
