"""La aplicación web: la API vive bajo `/api` y, si está compilado, el panel se sirve en `/`."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from copiloto import catalogo
from copiloto.catalogo import Catalogo, SubtipoInvalido
from copiloto.config import Configuracion
from copiloto.esquemas import Derivacion, Llamada, NuevaLlamada
from copiloto.flujo import FaltanDatos
from copiloto.llamadas import (
    LlamadaIlegible,
    LlamadaInexistente,
    LlamadaNoEsperaOperador,
    Llamadas,
)


def crear_app(configuracion: Configuracion | None = None) -> FastAPI:
    configuracion = configuracion or Configuracion()

    @asynccontextmanager
    async def ciclo_de_vida(app: FastAPI):
        catalogo.cargar()  # Si el catálogo no sirve, el servicio no arranca.
        app.state.llamadas = Llamadas(configuracion.sqlite_path)
        yield
        app.state.llamadas.cerrar()

    # La aplicación de afuera sólo reparte: lo que empieza con `/api` va a la API y el resto, al
    # panel. Así los errores de la API (404, 405) los contesta siempre la API, en JSON.
    app = FastAPI(lifespan=ciclo_de_vida, docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/api", crear_api(app, configuracion))
    if configuracion.static_dir is not None:
        app.mount("/", StaticFiles(directory=configuracion.static_dir, html=True), name="panel")
    return app


def crear_api(app: FastAPI, configuracion: Configuracion) -> FastAPI:
    api = FastAPI(title="Copiloto para Operadores de Sala")

    @api.exception_handler(LlamadaInexistente)
    def llamada_inexistente(request: Request, error: LlamadaInexistente) -> JSONResponse:
        return JSONResponse({"detail": "No existe una llamada con ese identificador."}, 404)

    @api.exception_handler(LlamadaNoEsperaOperador)
    def llamada_no_espera(request: Request, error: LlamadaNoEsperaOperador) -> JSONResponse:
        return JSONResponse({"detail": "La llamada no está esperando al operador."}, 409)

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

    @api.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "llm_provider": configuracion.llm_provider}

    @api.get("/catalogo")
    def consultar_catalogo() -> Catalogo:
        return catalogo.cargar()

    @api.post("/llamadas", status_code=201)
    def iniciar_llamada(nueva: NuevaLlamada) -> Llamada:
        return app.state.llamadas.iniciar(nueva.turnos)

    @api.get("/llamadas/{llamada_id}")
    def consultar_llamada(llamada_id: str) -> Llamada:
        return app.state.llamadas.consultar(llamada_id)

    @api.post("/llamadas/{llamada_id}/derivar")
    def derivar_llamada(llamada_id: str, derivacion: Derivacion) -> Llamada:
        return app.state.llamadas.derivar(llamada_id, derivacion.ajustes)

    return api


app = crear_app()
