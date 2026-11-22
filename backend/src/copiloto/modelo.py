"""La consulta al modelo devuelve texto crudo y deja su interpretación afuera."""

from time import monotonic
from typing import Protocol

from httpx import ConnectError, TimeoutException
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama
from ollama import ResponseError

from copiloto.config import Configuracion

_TOKENS_DE_RESPUESTA = 400
_CONTEXTOS = (4096, 8192)
_TIEMPO_AGOTADO = "se agotó el tiempo de espera"
_LLAMADA_LARGA = "la llamada es demasiado larga para el modelo"


class ModeloNoDisponible(RuntimeError):
    """El modelo no respondió a la consulta."""

    def __init__(self, motivo: str) -> None:
        self.motivo = motivo
        super().__init__(motivo)


class Modelo(Protocol):
    def __call__(self, sistema: str, usuario: str, vence: float) -> str: ...


def tiempo_restante(vence: float) -> float:
    restante = vence - monotonic()
    if restante <= 0:
        raise ModeloNoDisponible(_TIEMPO_AGOTADO)
    return restante


def de_ollama(configuracion: Configuracion) -> Modelo:
    def consultar(sistema: str, usuario: str, vence: float) -> str:
        restante = tiempo_restante(vence)
        estimados = (len(sistema) + len(usuario)) / 3 + _TOKENS_DE_RESPUESTA
        contexto = next((largo for largo in _CONTEXTOS if estimados <= largo), None)
        if contexto is None:
            raise ModeloNoDisponible(_LLAMADA_LARGA)
        try:
            cliente = ChatOllama(
                model=configuracion.ollama_model,
                base_url=configuracion.ollama_base_url,
                reasoning=False,
                keep_alive="30m",
                validate_model_on_init=False,
                client_kwargs={"timeout": restante},
            )
            respuesta = cliente.invoke(
                [SystemMessage(content=sistema), HumanMessage(content=usuario)],
                options={
                    "temperature": 0,
                    "seed": 7,
                    "num_ctx": contexto,
                    "num_predict": _TOKENS_DE_RESPUESTA,
                    # La penalización del modelo puede dejar campos vacíos.
                    "presence_penalty": 0,
                },
            )
        except TimeoutException as error:
            raise ModeloNoDisponible(_TIEMPO_AGOTADO) from error
        except ConnectError as error:
            raise ModeloNoDisponible("no hay conexión con Ollama") from error
        except Exception as error:
            motivo = "Ollama devolvió un error"
            if isinstance(error, ResponseError) and error.status_code == 404:
                motivo = "el modelo no está descargado en Ollama"
            raise ModeloNoDisponible(motivo) from error

        tiempo_restante(vence)
        if (
            respuesta.usage_metadata is not None
            and respuesta.usage_metadata.get("input_tokens", 0) >= contexto - _TOKENS_DE_RESPUESTA
        ):
            raise ModeloNoDisponible(_LLAMADA_LARGA)
        return respuesta.text

    return consultar
