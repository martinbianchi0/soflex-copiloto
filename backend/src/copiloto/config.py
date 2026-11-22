"""Configuración del servicio. Sale sólo de variables de entorno (ver `.env.example`)."""

from typing import Literal

from pydantic_settings import BaseSettings


class Configuracion(BaseSettings):
    # `mock` responde de forma determinística y sin red. Un valor desconocido corta el arranque.
    llm_provider: Literal["mock"] = "mock"
