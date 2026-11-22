"""La aplicación web: la API vive bajo `/api`."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from copiloto.config import Configuracion
from copiloto.esquemas import Derivacion, NuevaLlamada
from copiloto.llamadas import LlamadaInexistente, LlamadaNoEsperaOperador, Llamadas


def crear_app(configuracion: Configuracion | None = None) -> FastAPI:
    configuracion = configuracion or Configuracion()

    @asynccontextmanager
    async def ciclo_de_vida(app: FastAPI):
        app.state.llamadas = Llamadas(configuracion.sqlite_path)
        yield
        app.state.llamadas.cerrar()

    # La aplicación de afuera sólo reparte: lo que empieza con `/api` va a la API, que contesta
    # también sus propios errores (404, 405), siempre en JSON.
    app = FastAPI(lifespan=ciclo_de_vida, docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/api", crear_api(app, configuracion))
    return app


def crear_api(app: FastAPI, configuracion: Configuracion) -> FastAPI:
    api = FastAPI(title="Copiloto para Operadores de Sala")

    @api.exception_handler(LlamadaInexistente)
    def llamada_inexistente(request: Request, error: LlamadaInexistente) -> JSONResponse:
        return JSONResponse({"detail": "No existe una llamada con ese identificador."}, 404)

    @api.exception_handler(LlamadaNoEsperaOperador)
    def llamada_no_espera(request: Request, error: LlamadaNoEsperaOperador) -> JSONResponse:
        return JSONResponse({"detail": "La llamada no está esperando al operador."}, 409)

    @api.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "llm_provider": configuracion.llm_provider}

    @api.post("/llamadas", status_code=201)
    def iniciar_llamada(nueva: NuevaLlamada) -> dict:
        return app.state.llamadas.iniciar(nueva.model_dump()["turnos"])

    @api.get("/llamadas/{llamada_id}")
    def consultar_llamada(llamada_id: str) -> dict:
        return app.state.llamadas.consultar(llamada_id)

    @api.post("/llamadas/{llamada_id}/derivar")
    def derivar_llamada(llamada_id: str, derivacion: Derivacion) -> dict:
        return app.state.llamadas.derivar(llamada_id, derivacion.ajustes.cambios())

    return api


app = crear_app()
