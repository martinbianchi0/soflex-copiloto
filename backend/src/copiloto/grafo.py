"""El recorrido de una llamada como grafo de LangGraph: analizar, esperar al operador, derivar.

Los nodos sólo conectan las funciones de `flujo.py`; la lógica no vive acá. El estado guarda datos
planos (lo que se puede escribir en JSON): cada nodo los valida al entrar y los aplana al salir.
"""

from datetime import UTC, datetime
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from copiloto import flujo
from copiloto.esquemas import Ajustes, Sugerencia, Turno


class Estado(TypedDict, total=False):
    """Lo que se sabe de una llamada. Cada nodo devuelve sólo las claves que cambia."""

    llamada_id: str
    turnos: list[dict]
    sugerencia: dict
    ajustes: dict
    carta: dict


def analizar(estado: Estado) -> Estado:
    turnos = [Turno.model_validate(turno) for turno in estado["turnos"]]
    # Antes de guardar: lo que cita algo que nadie dijo se descarta, y lo que no está en el
    # catálogo también. Lo que llega al disco es sólo lo que se puede respaldar.
    sugerencia = flujo.quitar_lo_que_nadie_dijo(flujo.analizar(turnos), turnos)
    sugerencia = flujo.ajustar_al_catalogo(sugerencia)
    return {"sugerencia": sugerencia.model_dump(mode="json")}


def esperar_operador(estado: Estado) -> Estado:
    # interrupt() guarda el estado y corta la ejecución. Al retomar, este nodo corre de nuevo desde
    # el principio e interrupt() devuelve lo que mandó el operador: por eso acá no se hace nada más.
    respuesta = interrupt({"sugerencia": estado["sugerencia"]})
    return {"ajustes": respuesta["ajustes"]}


def derivar(estado: Estado) -> Estado:
    carta = flujo.derivar(
        estado["llamada_id"],
        Sugerencia.model_validate(estado["sugerencia"]),
        Ajustes.model_validate(estado["ajustes"]),
        datetime.now(UTC),
    )
    return {"carta": carta.model_dump(mode="json")}


def construir() -> StateGraph:
    grafo = StateGraph(Estado)
    grafo.add_node("analizar", analizar)
    grafo.add_node("esperar_operador", esperar_operador)
    grafo.add_node("derivar", derivar)
    grafo.add_edge(START, "analizar")
    grafo.add_edge("analizar", "esperar_operador")
    grafo.add_edge("esperar_operador", "derivar")
    grafo.add_edge("derivar", END)
    return grafo
