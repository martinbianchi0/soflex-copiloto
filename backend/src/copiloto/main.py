"""La aplicación web: la API vive bajo `/api` y, si está compilado, el panel se sirve en `/`."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.types import Scope

from copiloto import callejero, catalogo, dataset, ejemplos, mapa
from copiloto.catalogo import Catalogo, SubtipoInvalido
from copiloto.config import Configuracion
from copiloto.ejemplos import Ejemplo
from copiloto.esquemas import (
    Derivacion,
    Duplicados,
    Historial,
    Llamada,
    NuevaLlamada,
    NuevoTurno,
    PedidoDePlano,
    Plano,
    Proveedor,
)
from copiloto.flujo import DictadoInvalido, FaltanDatos, MarcaInvalida
from copiloto.llamadas import (
    LlamadaIlegible,
    LlamadaInexistente,
    LlamadaNoEsperaOperador,
    Llamadas,
    ProveedorNoDisponible,
    TurnoNoEntra,
)
from copiloto.modelo import de_ollama
from copiloto.trazas import callbacks_de_trazas


class Panel(StaticFiles):
    """Los archivos del panel compilado."""

    def file_response(
        self,
        full_path: str | os.PathLike[str],
        stat_result: os.stat_result,
        scope: Scope,
        status_code: int = 200,
    ) -> Response:
        respuesta = super().file_response(full_path, stat_result, scope, status_code)
        if os.fspath(full_path).endswith(".html"):
            # La página se vuelve a pedir siempre: sin esto, el navegador puede seguir mostrando
            # el panel anterior después de reconstruir la imagen. Los demás archivos llevan su
            # huella en el nombre.
            respuesta.headers["Cache-Control"] = "no-cache"
        return respuesta


def crear_app(configuracion: Configuracion | None = None) -> FastAPI:
    configuracion = configuracion or Configuracion()

    @asynccontextmanager
    async def ciclo_de_vida(app: FastAPI) -> AsyncIterator[None]:
        # Los datos se leen al arrancar: si alguno no sirve, el servicio no levanta, en vez de
        # fallar en la primera llamada.
        catalogo.cargar()
        callejero.cargar()
        dataset.cargar()
        ejemplos.cargar()
        modelo = de_ollama(configuracion) if configuracion.llm_provider == "ollama" else None
        with callbacks_de_trazas(configuracion) as callbacks:
            servicio = Llamadas(
                configuracion.sqlite_path, modelo, configuracion.llm_timeout_s, callbacks=callbacks
            )
            app.state.llamadas = servicio
            try:
                yield
            finally:
                servicio.cerrar()

    # La aplicación de afuera sólo reparte: lo que empieza con `/api` va a la API y el resto, al
    # panel. Así los errores de la API (404, 405) los contesta siempre la API, en JSON.
    app = FastAPI(lifespan=ciclo_de_vida, docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/api", crear_api(app, configuracion))
    if configuracion.static_dir is not None:
        app.mount("/", Panel(directory=configuracion.static_dir, html=True), name="panel")
    return app


def crear_api(app: FastAPI, configuracion: Configuracion) -> FastAPI:
    api = FastAPI(title="Copiloto para Operadores de Sala")

    def llamadas() -> Llamadas:
        servicio: Llamadas = app.state.llamadas
        return servicio

    @api.exception_handler(LlamadaInexistente)
    def llamada_inexistente(request: Request, error: LlamadaInexistente) -> JSONResponse:
        return JSONResponse({"detail": "No existe una llamada con ese identificador."}, 404)

    @api.exception_handler(LlamadaNoEsperaOperador)
    def llamada_no_espera(request: Request, error: LlamadaNoEsperaOperador) -> JSONResponse:
        return JSONResponse({"detail": error.detalle}, 409)

    @api.exception_handler(LlamadaIlegible)
    def llamada_ilegible(request: Request, error: LlamadaIlegible) -> JSONResponse:
        detalle = "La llamada está guardada en un formato que esta versión no puede leer."
        return JSONResponse({"detail": detalle}, 500)

    @api.exception_handler(RequestValidationError)
    def pedido_invalido(request: Request, error: RequestValidationError) -> JSONResponse:
        # Dónde está el error y por qué, sin devolver lo que mandó el cliente.
        detalle = [
            {"type": e["type"], "loc": list(e["loc"]), "msg": e["msg"]} for e in error.errors()
        ]
        return JSONResponse({"detail": detalle}, 422)

    @api.exception_handler(FaltanDatos)
    def faltan_datos(request: Request, error: FaltanDatos) -> JSONResponse:
        # Con la misma forma que los errores de validación, para que el panel los muestre igual.
        detalle = [
            {"type": "missing", "loc": ["ajustes", campo], "msg": "Hace falta para derivar."}
            for campo in error.campos
        ]
        return JSONResponse({"detail": detalle}, 422)

    @api.exception_handler(SubtipoInvalido)
    def subtipo_invalido(request: Request, error: SubtipoInvalido) -> JSONResponse:
        donde = ["ajustes", "tipo_hecho", "subtipo"]
        return JSONResponse(
            {"detail": [{"type": "value_error", "loc": donde, "msg": str(error)}]}, 422
        )

    @api.exception_handler(MarcaInvalida)
    def marca_invalida(request: Request, error: MarcaInvalida) -> JSONResponse:
        donde = ["ajustes", "checklist"]
        return JSONResponse(
            {"detail": [{"type": "value_error", "loc": donde, "msg": str(error)}]}, 422
        )

    @api.exception_handler(DictadoInvalido)
    def dictado_invalido(request: Request, error: DictadoInvalido) -> JSONResponse:
        donde = ["ajustes", "dictados_quitados"]
        return JSONResponse(
            {"detail": [{"type": "value_error", "loc": donde, "msg": str(error)}]}, 422
        )

    @api.get("/health")
    def health() -> dict[str, str | list[Proveedor] | None]:
        hay_modelo = configuracion.llm_provider == "ollama"
        proveedores: list[Proveedor] = ["mock", "ollama"] if hay_modelo else ["mock"]
        return {
            "status": "ok",
            "llm_provider": configuracion.llm_provider,
            "modelo": configuracion.ollama_model if hay_modelo else None,
            "proveedores": proveedores,
        }

    @api.get("/ejemplos")
    def listar_ejemplos() -> list[Ejemplo]:
        return ejemplos.cargar()

    @api.get("/catalogo")
    def consultar_catalogo() -> Catalogo:
        return catalogo.cargar()

    @api.post("/mapa")
    def consultar_mapa(pedido: PedidoDePlano) -> Plano:
        plano = mapa.plano(pedido.calle, pedido.altura, pedido.esquinas)
        if plano is None:
            raise HTTPException(404, "No se pudo ubicar la dirección en el callejero.")
        return plano

    @api.post("/llamadas", status_code=201)
    def iniciar_llamada(nueva: NuevaLlamada) -> Llamada:
        try:
            return llamadas().iniciar(nueva.turnos, nueva.proveedor)
        except ProveedorNoDisponible as error:
            detalle = {"type": "value_error", "loc": ["body", "proveedor"], "msg": str(error)}
            raise RequestValidationError([detalle]) from error

    @api.get("/llamadas/{llamada_id}")
    def consultar_llamada(llamada_id: str) -> Llamada:
        return llamadas().consultar(llamada_id)

    @api.get("/llamadas/{llamada_id}/duplicados")
    def consultar_duplicados(llamada_id: str) -> Duplicados:
        recibida_en, posibles = llamadas().consultar_duplicados(llamada_id)
        return Duplicados(llamada_id=llamada_id, recibida_en=recibida_en, posibles=posibles)

    @api.get("/llamadas/{llamada_id}/historial")
    def consultar_historial(llamada_id: str) -> Historial:
        return llamadas().consultar_historial(llamada_id)

    @api.post("/llamadas/{llamada_id}/analisis")
    def completar_analisis(llamada_id: str) -> Llamada:
        return llamadas().completar_analisis(llamada_id)

    @api.post("/llamadas/{llamada_id}/turnos")
    def sumar_turno(llamada_id: str, nuevo: NuevoTurno) -> Llamada:
        try:
            return llamadas().sumar_turno(llamada_id, nuevo.turno)
        except TurnoNoEntra as error:
            detalle = {"type": "value_error", "loc": ["body", "turno"], "msg": str(error)}
            raise RequestValidationError([detalle]) from error

    @api.post("/llamadas/{llamada_id}/derivar")
    def derivar_llamada(llamada_id: str, derivacion: Derivacion) -> Llamada:
        return llamadas().derivar(llamada_id, derivacion.ajustes)

    @api.post("/llamadas/{llamada_id}/actualizaciones")
    def actualizar_carta(llamada_id: str, actualizacion: Derivacion) -> Llamada:
        return llamadas().actualizar(llamada_id, actualizacion.ajustes)

    @api.post("/llamadas/{llamada_id}/terminar")
    def terminar_llamada(llamada_id: str) -> Llamada:
        return llamadas().terminar(llamada_id)

    return api


app = crear_app()
