"""Las llamadas del servicio: iniciarlas, consultarlas, sumarles turnos y derivarlas.

Cada llamada es un hilo del grafo. Su estado se guarda en SQLite después de cada nodo, así que una
llamada que quedó esperando al operador se puede derivar aunque el servicio se haya reiniciado.
"""

import sqlite3
import threading
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command, StateSnapshot
from pydantic import ValidationError

from copiloto import flujo, historial
from copiloto.config import ESPERA_DEL_MODELO_S
from copiloto.duplicados import UbicacionesRecientes
from copiloto.esquemas import Ajustes, Historial, Llamada, NuevaLlamada, PosibleDuplicado, Turno
from copiloto.grafo import Estado, construir
from copiloto.modelo import Modelo
from copiloto.turnos import separar_hablantes


class LlamadaInexistente(LookupError):
    """No hay ninguna llamada con ese identificador."""


class LlamadaNoEsperaOperador(RuntimeError):
    """La llamada no está esperando al operador."""


class LlamadaIlegible(RuntimeError):
    """Lo guardado no cumple las reglas de esta versión del servicio."""


class TurnoNoEntra(ValueError):
    """El turno nuevo supera los límites de la transcripción."""


def _hilo(llamada_id: str) -> RunnableConfig:
    return {"configurable": {"thread_id": llamada_id}}


class Llamadas:
    def __init__(
        self,
        ruta: Path,
        modelo: Modelo | None = None,
        espera_s: float = ESPERA_DEL_MODELO_S,
        reloj: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        # Los pedidos llegan desde varios hilos: SqliteSaver ordena el acceso a la conexión.
        self._conexion = sqlite3.connect(ruta, check_same_thread=False)
        self._grafo = construir(modelo, espera_s).compile(checkpointer=SqliteSaver(self._conexion))
        self._ubicaciones_recientes = UbicacionesRecientes(ruta)
        self._reloj = reloj
        self._pausa_tras_las_reglas = ["analizar"] if modelo is not None else None
        self._analizando = threading.Lock()
        self._analisis_en_curso: str | None = None
        # Dos pedidos simultáneos no pueden contestar la misma pausa del operador.
        # Vale dentro de este proceso; el servicio corre con un solo proceso.
        self._modificando = threading.Lock()

    def cerrar(self) -> None:
        self._ubicaciones_recientes.cerrar()
        self._conexion.close()

    def iniciar(self, turnos: list[Turno]) -> Llamada:
        """Guarda lo que proponen las reglas para que el operador lo vea enseguida."""
        recibida_en = self._reloj()
        llamada_id = uuid.uuid4().hex
        # Se guarda ya partida en turnos: las citas señalan cada turno por su posición.
        planos = [turno.model_dump(mode="json") for turno in separar_hablantes(turnos)]
        self._avanzar(
            {"llamada_id": llamada_id, "turnos": planos}, llamada_id, self._pausa_tras_las_reglas
        )
        llamada = self._leer(llamada_id)
        self._ubicaciones_recientes.actualizar(llamada, recibida_en)
        return llamada

    def completar_analisis(self, llamada_id: str) -> Llamada:
        """Completa la sugerencia si todavía falta consultar al modelo."""
        with self._analizando:
            with self._modificando:
                llamada = self._leer(llamada_id)
                if llamada.estado != "analizando":
                    self._ubicaciones_recientes.actualizar(llamada)
                    return llamada
                self._analisis_en_curso = llamada_id
            try:
                self._avanzar(None, llamada_id)
                llamada = self._leer(llamada_id)
                self._ubicaciones_recientes.actualizar(llamada)
                return llamada
            finally:
                with self._modificando:
                    self._analisis_en_curso = None

    def consultar(self, llamada_id: str) -> Llamada:
        llamada = self._leer(llamada_id)
        if llamada.estado == "en_proceso":
            with self._modificando:
                if self._analisis_en_curso != llamada_id:
                    llamada = self._terminar_lo_que_quedo_a_medias(llamada_id)
        return llamada

    def consultar_duplicados(
        self, llamada_id: str
    ) -> tuple[datetime | None, list[PosibleDuplicado]]:
        self._leer(llamada_id)
        return self._ubicaciones_recientes.consultar(llamada_id)

    def consultar_historial(self, llamada_id: str) -> Historial:
        fotos = list(self._grafo.get_state_history(_hilo(llamada_id)))
        if not fotos:
            raise LlamadaInexistente(llamada_id)
        llamada = self._llamada_de(llamada_id, fotos[0])
        valores: Mapping[str, object] = fotos[0].values
        try:
            if llamada.estado == "en_proceso" and "ajustes" in valores:
                Ajustes.model_validate(valores["ajustes"])
            puntos = [
                historial.PuntoGuardado(foto.created_at, foto.values, foto.metadata or {})
                for foto in fotos
            ]
            return historial.armar(llamada, puntos)
        except ValidationError as error:
            raise LlamadaIlegible(llamada_id) from error

    def sumar_turno(self, llamada_id: str, turno: Turno) -> Llamada:
        """Agrega lo que se dijo después y vuelve a pasar por las reglas."""
        with self._modificando:
            llamada = self._leer(llamada_id)
            if llamada.estado != "esperando_operador" or self._analisis_en_curso == llamada_id:
                raise LlamadaNoEsperaOperador(llamada_id)
            try:
                # El alta controla el largo antes de separar. Acá también se controla cuántos
                # turnos van a quedar, porque se agregan a los que ya se guardaron.
                NuevaLlamada(turnos=[*llamada.turnos, turno])
                nuevos = separar_hablantes([turno], maximo=None)
                NuevaLlamada(turnos=[*llamada.turnos, *nuevos])
            except ValidationError as error:
                raise TurnoNoEntra(error.errors()[0]["msg"]) from error
            self._avanzar(
                Command(resume={"turno": turno.model_dump(mode="json")}),
                llamada_id,
                self._pausa_tras_las_reglas,
            )
            llamada = self._leer(llamada_id)
            self._ubicaciones_recientes.actualizar(llamada)
            return llamada

    def derivar(self, llamada_id: str, ajustes: Ajustes) -> Llamada:
        """Retoma la llamada con lo que cambió el operador y arma la Carta de Llamada."""
        with self._modificando:
            if self._analisis_en_curso == llamada_id:
                raise LlamadaNoEsperaOperador(llamada_id)
            llamada = self._terminar_lo_que_quedo_a_medias(llamada_id)
            if llamada.estado != "esperando_operador":
                raise LlamadaNoEsperaOperador(llamada_id)
            # Se arma la carta antes de retomar el grafo: si falta un dato obligatorio, falla acá
            # y la llamada sigue esperando. Lo que el grafo ya aceptó no se puede volver a pedir.
            # Se comprueba con los mismos datos planos que después recibe el nodo.
            planos = ajustes.model_dump(mode="json", exclude_unset=True)
            ahora = datetime.now(UTC)
            assert llamada.sugerencia is not None  # La llamada ya está esperando al operador.
            flujo.derivar(
                llamada_id,
                llamada.sugerencia,
                Ajustes.model_validate(planos),
                ahora,
                turnos=llamada.turnos,
            )
            # Los ajustes van envueltos: LangGraph lee un diccionario vacío suelto como "no se
            # contesta ninguna pausa", y una derivación sin cambios dejaría la llamada esperando.
            self._avanzar(Command(resume={"ajustes": planos}), llamada_id)
            llamada = self._leer(llamada_id)
            self._ubicaciones_recientes.actualizar(llamada)
            return llamada

    def _avanzar(
        self,
        entrada: Estado | Command[str] | None,
        llamada_id: str,
        parar_despues: list[str] | None = None,
    ) -> None:
        # `sync`: cada nodo queda guardado en disco antes de que empiece el siguiente.
        self._grafo.invoke(
            entrada, _hilo(llamada_id), durability="sync", interrupt_after=parar_despues
        )

    def _terminar_lo_que_quedo_a_medias(self, llamada_id: str) -> Llamada:
        """Retoma el análisis o arma la carta si el servicio se cortó entre nodos."""
        llamada = self._leer(llamada_id)
        if llamada.estado == "en_proceso":
            try:
                self._avanzar(None, llamada_id, self._pausa_tras_las_reglas)
            except ValidationError as error:
                # Lo que quedó guardado (por ejemplo, los ajustes) es de otra versión del servicio.
                raise LlamadaIlegible(llamada_id) from error
            llamada = self._leer(llamada_id)
        return llamada

    def _leer(self, llamada_id: str) -> Llamada:
        return self._llamada_de(llamada_id, self._grafo.get_state(_hilo(llamada_id)))

    @staticmethod
    def _llamada_de(llamada_id: str, foto: StateSnapshot) -> Llamada:
        valores: Mapping[str, object] = foto.values
        if not valores:
            raise LlamadaInexistente(llamada_id)
        carta = valores.get("carta")
        # Una llamada sólo cuenta como derivada si ya tiene su carta.
        if carta is not None:
            estado = "derivada"
        elif foto.next == ("consultar_modelo",) and valores.get("falta_el_modelo", True):
            estado = "analizando"
        elif foto.next == ("esperar_operador",) and foto.interrupts and "ajustes" not in valores:
            estado = "esperando_operador"
        else:
            estado = "en_proceso"
        # Lo guardado se valida al leerlo: de acá no sale una llamada que rompa sus propias reglas.
        try:
            return Llamada.model_validate(
                {
                    "llamada_id": llamada_id,
                    "estado": estado,
                    "turnos": valores.get("turnos"),
                    "sugerencia": valores.get("sugerencia"),
                    "carta": carta,
                }
            )
        except ValidationError as error:
            raise LlamadaIlegible(llamada_id) from error
