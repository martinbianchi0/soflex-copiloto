"""La aplicación web: expone la API bajo `/api`."""

from fastapi import FastAPI

from copiloto.config import Configuracion

configuracion = Configuracion()
app = FastAPI(title="Copiloto para Operadores de Sala")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "llm_provider": configuracion.llm_provider}
