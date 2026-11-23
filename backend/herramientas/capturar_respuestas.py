"""Guarda respuestas reales del servicio para los tests del panel.

Los tests del panel no levantan el servicio: simulan `fetch` con estas respuestas. Para que no
envejezcan, `tests/test_respuestas_del_panel.py` las vuelve a capturar y las compara con las
guardadas: si la API cambia de forma, ese test falla y hay que regenerarlas.

    uv run python herramientas/capturar_respuestas.py
"""

import argparse
import json
import re
import tempfile
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from copiloto.config import Configuracion
from copiloto.esquemas import Proveedor
from copiloto.main import crear_app

SALIDA = Path(__file__).parents[2] / "frontend" / "src" / "pruebas" / "respuestas"

# Lo único que cambia de una corrida a otra: el identificador de la llamada y las horas.
_FECHA = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
FECHA_FIJA = "2026-01-01T12:00:00Z"


def _fijar(valor: Any, identificadores: dict[str, str]) -> Any:
    if isinstance(valor, dict):
        return {clave: _fijar(contenido, identificadores) for clave, contenido in valor.items()}
    if isinstance(valor, list):
        return [_fijar(contenido, identificadores) for contenido in valor]
    if isinstance(valor, str):
        return identificadores.get(valor, FECHA_FIJA if _FECHA.match(valor) else valor)
    return valor


def capturar() -> dict[str, Any]:
    """Recorre el servicio como lo hace el panel y devuelve cada respuesta con su nombre."""
    respuestas: dict[str, Any] = {}
    identificadores: dict[str, str] = {}

    def guardar(nombre: str, respuesta: Any, estado: int = 200) -> Any:
        assert respuesta.status_code == estado, (nombre, respuesta.status_code)
        respuestas[nombre] = respuesta.json()
        return respuestas[nombre]

    def iniciar(
        cliente: TestClient,
        nombre: str,
        turnos: list[dict[str, Any]],
        proveedor: Proveedor | None = None,
    ) -> str:
        pedido: dict[str, object] = {"turnos": turnos}
        if proveedor is not None:
            pedido["proveedor"] = proveedor
        llamada = guardar(nombre, cliente.post("/api/llamadas", json=pedido), 201)
        identificadores[llamada["llamada_id"]] = nombre
        return str(llamada["llamada_id"])

    with tempfile.TemporaryDirectory() as carpeta:
        configuracion = Configuracion(
            llm_provider="mock", sqlite_path=Path(carpeta) / "llamadas.sqlite", static_dir=None
        )
        with TestClient(crear_app(configuracion)) as cliente:
            guardar("salud", cliente.get("/api/health"))
            guardar("catalogo", cliente.get("/api/catalogo"))
            ejemplos = {
                ejemplo["id"]: ejemplo
                for ejemplo in guardar("ejemplos", cliente.get("/api/ejemplos"))
            }

            def texto_de(ejemplo: str) -> list[dict[str, Any]]:
                return [{"texto": ejemplos[ejemplo]["texto"]}]

            guardar(
                "error-proveedor-no-disponible",
                cliente.post(
                    "/api/llamadas", json={"turnos": texto_de("SFX-013"), "proveedor": "ollama"}
                ),
                422,
            )

            # Una llamada del dataset: trae tipo, subtipo, prioridad y una pregunta respondida.
            del_dataset = iniciar(cliente, "llamada-del-dataset", texto_de("SFX-001"))
            guardar("duplicados-sin-otra", cliente.get(f"/api/llamadas/{del_dataset}/duplicados"))
            guardar(
                "llamada-del-dataset-derivada",
                cliente.post(f"/api/llamadas/{del_dataset}/derivar", json={"ajustes": {}}),
            )
            guardar("historial-derivada", cliente.get(f"/api/llamadas/{del_dataset}/historial"))
            guardar(
                "error-ya-derivada",
                cliente.post(f"/api/llamadas/{del_dataset}/derivar", json={"ajustes": {}}),
                409,
            )

            # La misma dirección, minutos después: el aviso de otra llamada del mismo lugar.
            repetida = iniciar(cliente, "llamada-repetida", texto_de("SFX-001"))
            guardar("duplicados-con-otra", cliente.get(f"/api/llamadas/{repetida}/duplicados"))

            # Un texto nuevo: la prioridad queda sin sugerir y hay un aviso sobre la dirección.
            iniciar(cliente, "llamada-con-aviso", texto_de("nueva-3"))

            # Sin ningún dato: derivar así no pasa la validación.
            sin_datos = iniciar(cliente, "llamada-sin-datos", [{"texto": "Hola, ¿me escuchan?"}])
            guardar(
                "error-falta-lo-minimo",
                cliente.post(f"/api/llamadas/{sin_datos}/derivar", json={"ajustes": {}}),
                422,
            )

            # Una llamada que llega de a un intercambio, como la reproduce el panel: la altura
            # aparece recién en el segundo.
            turnos = ejemplos["nueva-5"]["turnos"]
            primero, segundo = (
                " ".join(f"{turno['hablante'].capitalize()}: {turno['texto']}" for turno in par)
                for par in (turnos[:2], turnos[2:4])
            )
            por_turnos = iniciar(cliente, "llamada-por-turnos", [{"texto": primero}])
            guardar(
                "llamada-por-turnos-con-altura",
                cliente.post(
                    f"/api/llamadas/{por_turnos}/turnos",
                    json={"turno": {"texto": segundo, "hablante": None}},
                ),
            )

            pedido = {"calle": "Av. Corrientes", "altura": 1540, "esquinas": []}
            guardar("plano", cliente.post("/api/mapa", json=pedido))
            guardar(
                "error-sin-plano",
                cliente.post("/api/mapa", json={**pedido, "altura": 99_999}),
                404,
            )
            guardar("error-llamada-inexistente", cliente.get("/api/llamadas/no-existe"), 404)

        con_modelo = Configuracion(
            llm_provider="ollama",
            ollama_model="qwen3.5:4b-q4_K_M",
            sqlite_path=Path(carpeta) / "llamadas-con-modelo.sqlite",
            static_dir=None,
        )
        with TestClient(crear_app(con_modelo)) as cliente:
            guardar("salud-con-modelo", cliente.get("/api/health"))
            # El alta deja pendiente la consulta para poder capturar sin conexión al modelo.
            iniciar(cliente, "llamada-con-modelo-analizando", texto_de("SFX-013"), "ollama")
            iniciar(cliente, "llamada-en-mock-con-modelo-disponible", texto_de("SFX-013"), "mock")

    return {
        f"{nombre}.json": _fijar(respuesta, identificadores)
        for nombre, respuesta in respuestas.items()
    }


def escribir(salida: Path) -> None:
    salida.mkdir(parents=True, exist_ok=True)
    for nombre, respuesta in capturar().items():
        texto = json.dumps(respuesta, ensure_ascii=False, indent=1) + "\n"
        salida.joinpath(nombre).write_text(texto, encoding="utf-8")


if __name__ == "__main__":
    argumentos = argparse.ArgumentParser(description=__doc__)
    argumentos.add_argument("--salida", type=Path, default=SALIDA)
    escribir(argumentos.parse_args().salida)
