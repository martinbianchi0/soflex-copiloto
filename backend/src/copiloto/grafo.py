"""El recorrido de una llamada: analizar, consultar al modelo, esperar al operador y derivar.

Los nodos sólo conectan las funciones de `flujo.py`; la lógica no vive acá. El estado guarda datos
planos (lo que se puede escribir en JSON): cada nodo los valida al entrar y los aplana al salir.
"""

import logging
from datetime import UTC, datetime
from functools import partial
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from copiloto import flujo
from copiloto.esquemas import Ajustes, Prioridad, Sugerencia, Turno, valor_de
from copiloto.modelo import Modelo
from copiloto.turnos import separar_hablantes


class Estado(TypedDict, total=False):
    """Lo que se sabe de una llamada. Cada nodo devuelve sólo las claves que cambia."""

    llamada_id: str
    turnos: list[dict[str, object]]
    turnos_analizados: int
    # La prioridad que se sugería antes de sumar el último turno, para avisar si cambia.
    prioridad_previa: str | None
    sugerencia: dict[str, object]
    falta_el_modelo: bool
    ajustes: dict[str, object]
    carta: dict[str, object]


class _RespuestaOperador(TypedDict, total=False):
    turno: dict[str, object]
    ajustes: dict[str, object]


def analizar(estado: Estado, *, con_modelo: bool = False) -> Estado:
    turnos = [Turno.model_validate(turno) for turno in estado["turnos"]]
    sugerencia = flujo.analizar_base(turnos) if con_modelo else flujo.analizar(turnos)
    if not con_modelo:
        sugerencia = flujo.avisar_cambio_de_prioridad(sugerencia, _prioridad_previa(estado))
    return {
        **_preparar_sugerencia(sugerencia, turnos),
        "turnos_analizados": len(turnos),
        "falta_el_modelo": con_modelo,
    }


def consultar_modelo(estado: Estado, *, modelo: Modelo | None, espera_s: float) -> Estado:
    # Antes de guardar la marca, sólo se llegaba a este nodo si faltaba consultar al modelo.
    if not estado.get("falta_el_modelo", True):
        return {}
    turnos = [Turno.model_validate(turno) for turno in estado["turnos"]]
    if modelo is None:
        motivo = "el servicio está en modo mock"
        logging.getLogger(__name__).warning("%s", motivo)
        sugerencia = flujo.rescatar_analisis(turnos, motivo)
    else:
        base = Sugerencia.model_validate(estado["sugerencia"])
        sugerencia = flujo.analizar_con_modelo(turnos, base, modelo, espera_s)
    sugerencia = flujo.avisar_cambio_de_prioridad(sugerencia, _prioridad_previa(estado))
    return {**_preparar_sugerencia(sugerencia, turnos), "falta_el_modelo": False}


def _prioridad_previa(estado: Estado) -> Prioridad | None:
    previa = estado.get("prioridad_previa")
    return Prioridad(previa) if previa else None


def _preparar_sugerencia(sugerencia: Sugerencia, turnos: list[Turno]) -> Estado:
    # Antes de guardar: lo que cita algo que nadie dijo se descarta, y lo que no está en el
    # catálogo también. Lo que llega al disco es sólo lo que se puede respaldar.
    sugerencia = flujo.quitar_lo_que_nadie_dijo(sugerencia, turnos)
    sugerencia = flujo.ajustar_al_catalogo(sugerencia)
    return {"sugerencia": sugerencia.model_dump(mode="json")}


def esperar_operador(estado: Estado) -> Estado:
    # interrupt() guarda el estado y corta la ejecución. Al retomar, este nodo corre de nuevo desde
    # el principio e interrupt() devuelve lo que mandó el operador: por eso acá no se hace nada más.
    respuesta: _RespuestaOperador = interrupt({"sugerencia": estado["sugerencia"]})
    if "turno" in respuesta:
        turno = Turno.model_validate(respuesta["turno"])
        nuevos = separar_hablantes([turno], maximo=None)
        previa = valor_de(Sugerencia.model_validate(estado["sugerencia"]).prioridad)
        return {
            "turnos": [*estado["turnos"], *(t.model_dump(mode="json") for t in nuevos)],
            "prioridad_previa": previa.value if previa else None,
        }
    return {"ajustes": respuesta["ajustes"]}


def despues_del_operador(estado: Estado) -> Literal["analizar", "derivar"]:
    return "derivar" if "ajustes" in estado else "analizar"


def derivar(estado: Estado) -> Estado:
    carta = flujo.derivar(
        estado["llamada_id"],
        Sugerencia.model_validate(estado["sugerencia"]),
        Ajustes.model_validate(estado["ajustes"]),
        datetime.now(UTC),
        turnos=[Turno.model_validate(turno) for turno in estado["turnos"]],
    )
    return {"carta": carta.model_dump(mode="json")}


def construir(modelo: Modelo | None, espera_s: float) -> StateGraph[Estado]:
    grafo: StateGraph[Estado] = StateGraph(Estado)
    # Las sobrecargas piden un parámetro llamado «state», pero el grafo lo pasa por posición.
    grafo.add_node("analizar", partial(analizar, con_modelo=modelo is not None))
    grafo.add_node("consultar_modelo", partial(consultar_modelo, modelo=modelo, espera_s=espera_s))
    grafo.add_node("esperar_operador", esperar_operador)  # type: ignore[call-overload]
    grafo.add_node("derivar", derivar)  # type: ignore[call-overload]
    grafo.add_edge(START, "analizar")
    grafo.add_edge("analizar", "consultar_modelo")
    grafo.add_edge("consultar_modelo", "esperar_operador")
    grafo.add_conditional_edges("esperar_operador", despues_del_operador)
    grafo.add_edge("derivar", END)
    return grafo
