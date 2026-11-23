"""Las llamadas del servicio: iniciarlas, consultarlas, sumarles turnos, derivarlas y terminarlas.

Cada llamada es un hilo del grafo. Su estado se guarda en SQLite después de cada nodo, así que una
llamada que quedó esperando al operador se puede derivar aunque el servicio se haya reiniciado.
"""

import sqlite3
import threading
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command, StateSnapshot
from pydantic import ValidationError

from copiloto import flujo, historial
from copiloto.config import ESPERA_DEL_MODELO_S
from copiloto.duplicados import UbicacionesRecientes
from copiloto.esquemas import (
    Ajustes,
    Historial,
    Llamada,
    NuevaLlamada,
    PosibleDuplicado,
    Proveedor,
    Turno,
)
from copiloto.grafo import Estado, construir, proveedor_efectivo
from copiloto.modelo import Modelo
from copiloto.turnos import separar_hablantes


class LlamadaInexistente(LookupError):
    """No hay ninguna llamada con ese identificador."""


class LlamadaNoEsperaOperador(RuntimeError):
    """La llamada no está esperando al operador."""

    detalle = "La llamada no está esperando al operador."


class LlamadaYaDerivada(LlamadaNoEsperaOperador):
    """La carta ya se derivó: lo que cambie va como actualización."""

    detalle = "La carta ya se derivó: los cambios se mandan como actualización."


class LlamadaSinDerivar(LlamadaNoEsperaOperador):
    """Todavía no hay carta para actualizar ni llamada derivada para terminar."""

    detalle = "Primero hay que derivar la carta."


class LlamadaIlegible(RuntimeError):
    """Lo guardado no cumple las reglas de esta versión del servicio."""


class TurnoNoEntra(ValueError):
    """El turno nuevo supera los límites de la transcripción."""


class ProveedorNoDisponible(ValueError):
    """Se pidió un proveedor que el servicio no tiene configurado."""


def _hilo(llamada_id: str) -> RunnableConfig:
    return {"configurable": {"thread_id": llamada_id}}


class Llamadas:
    def __init__(
        self,
        ruta: Path,
        modelo: Modelo | None = None,
        espera_s: float = ESPERA_DEL_MODELO_S,
        reloj: Callable[[], datetime] = lambda: datetime.now(UTC),
        *,
        callbacks: Sequence[BaseCallbackHandler] | None = None,
    ) -> None:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        # Los pedidos llegan desde varios hilos: SqliteSaver ordena el acceso a la conexión.
        self._conexion = sqlite3.connect(ruta, check_same_thread=False)
        self._grafo = construir(modelo, espera_s).compile(checkpointer=SqliteSaver(self._conexion))
        self._ubicaciones_recientes = UbicacionesRecientes(ruta)
        self._reloj = reloj
        self._callbacks = tuple(callbacks) if callbacks else ()
        self._hay_modelo = modelo is not None
        self._analizando = threading.Lock()
        self._analisis_en_curso: str | None = None
        # Dos pedidos simultáneos no pueden contestar la misma pausa del operador.
        # Vale dentro de este proceso; el servicio corre con un solo proceso.
        self._modificando = threading.Lock()

    def cerrar(self) -> None:
        self._ubicaciones_recientes.cerrar()
        self._conexion.close()

    def iniciar(self, turnos: list[Turno], proveedor: Proveedor | None = None) -> Llamada:
        """Guarda lo que proponen las reglas para que el operador lo vea enseguida."""
        if proveedor == "ollama" and not self._hay_modelo:
            raise ProveedorNoDisponible("Este servicio no tiene un modelo configurado.")
        proveedor = proveedor_efectivo(proveedor, hay_modelo=self._hay_modelo)
        recibida_en = self._reloj()
        llamada_id = uuid.uuid4().hex
        # Se guarda ya partida en turnos: las citas señalan cada turno por su posición.
        planos = [turno.model_dump(mode="json") for turno in separar_hablantes(turnos)]
        self._avanzar(
            {"llamada_id": llamada_id, "turnos": planos, "proveedor": proveedor},
            llamada_id,
            operacion="alta",
            proveedor=proveedor,
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
                self._avanzar(None, llamada_id, operacion="analisis_del_modelo")
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
            if llamada.estado == "en_proceso" and valores.get("respuesta", "ajustes") == "ajustes":
                Ajustes.model_validate(valores.get("ajustes", {}))
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
                operacion="turno_sumado",
                proveedor=llamada.proveedor,
            )
            llamada = self._leer(llamada_id)
            self._ubicaciones_recientes.actualizar(llamada)
            return llamada

    def derivar(self, llamada_id: str, ajustes: Ajustes) -> Llamada:
        """Retoma la llamada con lo que cambió el operador y arma la Carta de Llamada.

        La llamada sigue abierta: el operador puede sumar turnos y actualizar la carta.
        """
        with self._modificando:
            llamada = self._esperando_al_operador(llamada_id)
            if llamada.carta is not None:
                raise LlamadaYaDerivada(llamada_id)
            planos = self._comprobar(llamada, ajustes)
            # Los ajustes van envueltos: LangGraph lee un diccionario vacío suelto como "no se
            # contesta ninguna pausa", y una derivación sin cambios dejaría la llamada esperando.
            self._avanzar(Command(resume={"ajustes": planos}), llamada_id, operacion="derivacion")
            return self._leer_y_registrar(llamada_id)

    def actualizar(self, llamada_id: str, ajustes: Ajustes) -> Llamada:
        """Arma una versión nueva de la carta ya derivada, con lo que el operador tiene ahora.

        Los ajustes son, como al derivar, todo lo que difiere de la sugerencia vigente. Se guardan
        siempre, porque son los que retoma el panel; si la carta que sale es igual a la que ya
        tiene el despacho, la carta no cambia.
        """
        with self._modificando:
            llamada = self._esperando_al_operador(llamada_id)
            if llamada.carta is None:
                raise LlamadaSinDerivar(llamada_id)
            planos = self._comprobar(llamada, ajustes)
            self._avanzar(
                Command(resume={"ajustes": planos}), llamada_id, operacion="actualizacion"
            )
            return self._leer_y_registrar(llamada_id)

    def terminar(self, llamada_id: str) -> Llamada:
        """Cierra una llamada derivada: su carta queda como está."""
        with self._modificando:
            llamada = self._esperando_al_operador(llamada_id)
            if llamada.carta is None:
                raise LlamadaSinDerivar(llamada_id)
            self._avanzar(Command(resume={"terminar": True}), llamada_id, operacion="cierre")
            return self._leer_y_registrar(llamada_id)

    def _esperando_al_operador(self, llamada_id: str) -> Llamada:
        if self._analisis_en_curso == llamada_id:
            raise LlamadaNoEsperaOperador(llamada_id)
        llamada = self._terminar_lo_que_quedo_a_medias(llamada_id)
        if llamada.estado != "esperando_operador":
            raise LlamadaNoEsperaOperador(llamada_id)
        return llamada

    def _comprobar(self, llamada: Llamada, ajustes: Ajustes) -> dict[str, object]:
        """Arma la carta antes de retomar el grafo y devuelve los ajustes como los recibe el nodo.

        Si falta un dato obligatorio, falla acá y la llamada sigue esperando: lo que el grafo ya
        aceptó no se puede volver a pedir. Se comprueba con los mismos datos planos que después
        recibe el nodo.
        """
        planos = ajustes.model_dump(mode="json", exclude_unset=True)
        assert llamada.sugerencia is not None  # La llamada ya está esperando al operador.
        flujo.derivar(
            llamada.llamada_id,
            llamada.sugerencia,
            Ajustes.model_validate(planos),
            datetime.now(UTC),
            turnos=llamada.turnos,
        )
        return planos

    def _leer_y_registrar(self, llamada_id: str) -> Llamada:
        llamada = self._leer(llamada_id)
        self._ubicaciones_recientes.actualizar(llamada)
        return llamada

    def _avanzar(
        self,
        entrada: Estado | Command[str] | None,
        llamada_id: str,
        *,
        operacion: str,
        proveedor: Proveedor | None = None,
    ) -> None:
        configuracion = _hilo(llamada_id)
        if self._callbacks:
            configuracion["callbacks"] = list(self._callbacks)
            configuracion["metadata"] = {"langfuse_session_id": llamada_id}
            configuracion["run_name"] = operacion
        parar_despues = ["analizar"] if proveedor == "ollama" else None
        # `sync`: cada nodo queda guardado en disco antes de que empiece el siguiente.
        self._grafo.invoke(entrada, configuracion, durability="sync", interrupt_after=parar_despues)

    def _terminar_lo_que_quedo_a_medias(self, llamada_id: str) -> Llamada:
        """Retoma el análisis o arma la carta si el servicio se cortó entre nodos."""
        llamada = self._leer(llamada_id)
        if llamada.estado == "en_proceso":
            try:
                self._avanzar(
                    None, llamada_id, operacion="retomar_llamada", proveedor=llamada.proveedor
                )
            except ValidationError as error:
                # Lo que quedó guardado (por ejemplo, los ajustes) es de otra versión del servicio.
                raise LlamadaIlegible(llamada_id) from error
            llamada = self._leer(llamada_id)
        return llamada

    def _leer(self, llamada_id: str) -> Llamada:
        return self._llamada_de(llamada_id, self._grafo.get_state(_hilo(llamada_id)))

    def _llamada_de(self, llamada_id: str, foto: StateSnapshot) -> Llamada:
        valores: Mapping[str, object] = foto.values
        if not valores:
            raise LlamadaInexistente(llamada_id)
        carta = valores.get("carta")
        # Terminada es la que llegó al final del recorrido con su carta (las guardadas con el
        # grafo anterior también: ahí derivar era el último paso). Con carta y en otro punto, la
        # llamada está derivada y sigue abierta.
        if not foto.next and carta is not None:
            estado = "terminada"
        elif foto.next == ("consultar_modelo",) and valores.get("falta_el_modelo", True):
            estado = "analizando"
        elif foto.next == ("esperar_operador",) and foto.interrupts:
            estado = "esperando_operador"
        else:
            estado = "en_proceso"
        # Lo guardado se valida al leerlo: de acá no sale una llamada que rompa sus propias reglas.
        try:
            llamada = Llamada.model_validate(
                {
                    "llamada_id": llamada_id,
                    "estado": estado,
                    "proveedor": proveedor_efectivo(
                        valores.get("proveedor"), hay_modelo=self._hay_modelo
                    ),
                    "turnos": valores.get("turnos"),
                    "sugerencia": valores.get("sugerencia"),
                    "carta": carta,
                    "ajustes": _ajustes_legibles(valores.get("ajustes"))
                    if carta is not None
                    else None,
                }
            )
        except ValidationError as error:
            raise LlamadaIlegible(llamada_id) from error
        if llamada.carta is None or llamada.estado == "terminada":
            return llamada
        return llamada.model_copy(update={"carta_al_dia": _carta_al_dia(llamada)})


def _ajustes_legibles(guardados: object) -> Ajustes | None:
    """Los últimos ajustes del operador, si esta versión los puede leer.

    Los de una llamada guardada con una versión anterior pueden tener otra forma (el tipo de hecho
    era una categoría suelta). La llamada se lee igual, sin ellos: su carta es la que vale.
    """
    try:
        return Ajustes.model_validate(guardados)
    except ValidationError:
        return None


def _carta_al_dia(llamada: Llamada) -> bool:
    """Si la carta tiene lo que saldría hoy de la sugerencia vigente con los últimos ajustes.

    Deja de estarlo cuando un turno sumado cambia la sugerencia: entonces el operador tiene algo
    para mandarle al despacho aunque no haya tocado nada.
    """
    assert llamada.carta is not None
    if llamada.sugerencia is None:
        return False
    try:
        hoy = flujo.derivar(
            llamada.llamada_id,
            llamada.sugerencia,
            llamada.ajustes or Ajustes(),
            datetime.now(UTC),
            turnos=llamada.turnos,
        )
    except ValueError:
        # Con la sugerencia nueva, lo que mandó el operador ya no arma una carta (por ejemplo,
        # falta la calle): la que tiene el despacho no es la que saldría.
        return False
    return hoy.mismo_contenido(llamada.carta)
