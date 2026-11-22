"""Trazas opcionales del grafo y del modelo en Langfuse."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from threading import Thread
from typing import TYPE_CHECKING

from copiloto.config import Configuracion

if TYPE_CHECKING:
    from langchain_core.callbacks import BaseCallbackHandler
    from opentelemetry.sdk.trace.export import SpanExporter

_registro = logging.getLogger(__name__)
_ESPERA_DE_CIERRE_S = 2.0


@contextmanager
def callbacks_de_trazas(
    configuracion: Configuracion, *, exportador: SpanExporter | None = None
) -> Iterator[list[BaseCallbackHandler] | None]:
    publica = configuracion.langfuse_public_key
    secreta = configuracion.langfuse_secret_key.get_secret_value()
    if not (publica and secreta):
        yield None
        return

    recursos = ExitStack()
    callbacks: list[BaseCallbackHandler] | None = None
    try:
        from langfuse import Langfuse
        from langfuse.langchain import CallbackHandler
        from opentelemetry.sdk.trace import TracerProvider

        proveedor = TracerProvider(shutdown_on_exit=False)
        recursos.callback(proveedor.shutdown)
        cliente = Langfuse(
            public_key=publica,
            secret_key=secreta,
            base_url=configuracion.langfuse_base_url,
            timeout=1,
            tracer_provider=proveedor,
            span_exporter=exportador,
        )
        recursos.callback(cliente.shutdown)
        callbacks = [CallbackHandler(public_key=publica)]
    except Exception:  # noqa: BLE001  El SDK es opcional y sus errores pueden incluir claves.
        _registro.warning("No se pudieron iniciar las trazas de Langfuse.")

    try:
        yield callbacks
    finally:
        _cerrar_con_limite(recursos.close)


def _cerrar_con_limite(cerrar: Callable[[], None]) -> None:
    def vaciar() -> None:
        try:
            cerrar()
        except Exception:  # noqa: BLE001  El cierre de las trazas no afecta al servicio.
            _registro.warning("No se pudieron cerrar las trazas de Langfuse.")

    # El vaciado de OpenTelemetry puede esperar al exportador más allá de su tiempo límite.
    hilo = Thread(target=vaciar, name="cerrar-trazas", daemon=True)
    hilo.start()
    hilo.join(timeout=_ESPERA_DE_CIERRE_S)
    if hilo.is_alive():
        _registro.warning("Se agotó el tiempo para cerrar las trazas de Langfuse.")
