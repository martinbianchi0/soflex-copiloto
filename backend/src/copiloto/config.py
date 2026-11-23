"""Configuración del servicio. Sale sólo de variables de entorno (ver `.env.example`)."""

from pathlib import Path
from typing import Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from copiloto.esquemas import Proveedor

ESPERA_DEL_MODELO_S = 60.0
_BASE_DE_LANGFUSE = "http://localhost:3000"


class Configuracion(BaseSettings):
    model_config = SettingsConfigDict(hide_input_in_errors=True)

    # `mock` responde de forma determinística y sin red. Un valor desconocido corta el arranque.
    llm_provider: Proveedor = "mock"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3.5:4b-q4_K_M"
    llm_timeout_s: float = Field(default=ESPERA_DEL_MODELO_S, gt=0)
    langfuse_public_key: str = ""
    langfuse_secret_key: SecretStr = Field(default=SecretStr(""), repr=False)
    langfuse_base_url: str = _BASE_DE_LANGFUSE
    # Dónde se guarda el estado de las llamadas.
    sqlite_path: Path = Path("data/llamadas.sqlite")
    # Carpeta con el panel ya compilado. Sin ella, el servicio expone sólo la API.
    static_dir: Path | None = None

    @field_validator("langfuse_base_url", mode="before")
    @classmethod
    def base_de_langfuse_por_defecto(cls, valor: object) -> object:
        return _BASE_DE_LANGFUSE if valor == "" else valor

    @model_validator(mode="after")
    def validar_claves_de_langfuse(self) -> Self:
        if bool(self.langfuse_public_key) != bool(self.langfuse_secret_key):
            raise ValueError(
                "Para activar Langfuse, configurá LANGFUSE_PUBLIC_KEY y LANGFUSE_SECRET_KEY juntas."
            )
        return self
