"""Las llamadas del servicio: iniciarlas, consultarlas y derivarlas.

Cada llamada es un hilo del grafo. Su estado se guarda en SQLite después de cada nodo, así que una
llamada que quedó esperando al operador se puede derivar aunque el servicio se haya reiniciado.
"""

import sqlite3
import threading
import uuid
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from copiloto.grafo import construir


class LlamadaInexistente(LookupError):
    """No hay ninguna llamada con ese identificador."""


class LlamadaNoEsperaOperador(RuntimeError):
    """La llamada no está esperando al operador: ya se derivó."""


def _hilo(llamada_id: str) -> dict:
    return {"configurable": {"thread_id": llamada_id}}


class Llamadas:
    def __init__(self, ruta: Path) -> None:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        # Los pedidos llegan desde varios hilos: SqliteSaver ordena el acceso a la conexión.
        self._conexion = sqlite3.connect(ruta, check_same_thread=False)
        self._grafo = construir().compile(checkpointer=SqliteSaver(self._conexion))
        # Una derivación por vez: dos pedidos simultáneos no derivan la misma llamada dos veces.
        # Vale dentro de este proceso; el servicio corre con un solo proceso.
        self._derivando = threading.Lock()

    def cerrar(self) -> None:
        self._conexion.close()

    def iniciar(self, turnos: list[dict]) -> dict:
        """Analiza la llamada y la deja esperando al operador."""
        llamada_id = uuid.uuid4().hex
        self._avanzar({"llamada_id": llamada_id, "turnos": turnos}, llamada_id)
        return self._leer(llamada_id)

    def consultar(self, llamada_id: str) -> dict:
        llamada = self._leer(llamada_id)
        if llamada["estado"] == "en_proceso":
            with self._derivando:
                llamada = self._terminar_lo_que_quedo_a_medias(llamada_id)
        return llamada

    def derivar(self, llamada_id: str, ajustes: dict) -> dict:
        """Retoma la llamada con lo que cambió el operador y arma la Carta de Llamada."""
        with self._derivando:
            if self._terminar_lo_que_quedo_a_medias(llamada_id)["estado"] != "esperando_operador":
                raise LlamadaNoEsperaOperador(llamada_id)
            # Los ajustes van envueltos: LangGraph lee un diccionario vacío suelto como "no se
            # contesta ninguna pausa", y una derivación sin cambios dejaría la llamada esperando.
            self._avanzar(Command(resume={"ajustes": ajustes}), llamada_id)
            return self._leer(llamada_id)

    def _avanzar(self, entrada: dict | Command | None, llamada_id: str) -> None:
        # `sync`: cada nodo queda guardado en disco antes de que empiece el siguiente.
        self._grafo.invoke(entrada, _hilo(llamada_id), durability="sync")

    def _terminar_lo_que_quedo_a_medias(self, llamada_id: str) -> dict:
        """Si el servicio se cortó después de que el operador confirmó, arma la carta ahora.

        Los ajustes ya estaban guardados, así que se retoma desde ahí sin volver a pedirlos.
        """
        llamada = self._leer(llamada_id)
        if llamada["estado"] == "en_proceso":
            self._avanzar(None, llamada_id)
            llamada = self._leer(llamada_id)
        return llamada

    def _leer(self, llamada_id: str) -> dict:
        foto = self._grafo.get_state(_hilo(llamada_id))
        if not foto.values:
            raise LlamadaInexistente(llamada_id)
        carta = foto.values.get("carta")
        # El estado sale de lo que hay guardado, no de qué nodo sigue: una llamada sólo cuenta
        # como derivada si tiene su carta.
        if carta is not None:
            estado = "derivada"
        elif foto.next == ("esperar_operador",) and "ajustes" not in foto.values:
            estado = "esperando_operador"
        else:
            estado = "en_proceso"
        return {
            "llamada_id": llamada_id,
            "estado": estado,
            "turnos": foto.values["turnos"],
            "sugerencia": foto.values.get("sugerencia"),
            "carta": carta,
        }
