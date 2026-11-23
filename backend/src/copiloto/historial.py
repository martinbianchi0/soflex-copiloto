"""Reconstruye lo que pasó a partir de los puntos guardados de una llamada."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from copiloto.esquemas import (
    CambioHistorial,
    Carta,
    DelOperador,
    Dicho,
    EstadoPregunta,
    EventoHistorial,
    Historial,
    Llamada,
    Sugerencia,
    TipoEvento,
    valor_de,
)


@dataclass(frozen=True)
class PuntoGuardado:
    cuando: str | None
    valores: Mapping[str, object]
    metadatos: Mapping[str, object]


def armar(llamada: Llamada, puntos: Sequence[PuntoGuardado]) -> Historial:
    """Lee los puntos del más nuevo al más viejo y devuelve los eventos en el orden en que pasaron."""
    ordenados = list(reversed(puntos))
    nodos: list[str | None] = []
    anterior: Mapping[str, object] = {}
    for punto in ordenados:
        nodos.append(_nodo(punto, anterior))
        anterior = punto.valores

    eventos: list[EventoHistorial] = []
    carta_previa: Carta | None = None
    # La sugerencia y la carta de la última versión: lo que el operador cambió se mide contra la
    # sugerencia que tenía a la vista cuando la armó, no contra una que llegó después.
    ultima: tuple[Sugerencia, Carta] | None = None
    anterior = {}
    for indice, (punto, nodo) in enumerate(zip(ordenados, nodos, strict=True)):
        detalle: tuple[TipoEvento, str] | None
        if nodo == "esperar_operador":
            siguientes = zip(ordenados[indice + 1 :], nodos[indice + 1 :], strict=True)
            derivacion = next((otro for otro, cual in siguientes if cual == "derivar"), None)
            detalle = _respuesta_del_operador(punto, carta_previa, derivacion)
        elif nodo == "derivar":
            carta = Carta.model_validate(punto.valores["carta"])
            if carta_previa is None:
                detalle = "derivada", "Carta de Llamada derivada."
            else:
                detalle = (
                    "carta_actualizada",
                    f"Carta actualizada: {_resumen(carta_previa, carta)}.",
                )
            carta_previa = carta
            ultima = Sugerencia.model_validate(punto.valores["sugerencia"]), carta
        else:
            detalle = _detalle(nodo, punto, anterior)
        if detalle is not None:
            tipo, mensaje = detalle
            eventos.append(
                EventoHistorial.model_validate(
                    {"tipo": tipo, "cuando": punto.cuando, "detalle": mensaje}
                )
            )
        anterior = punto.valores

    if ultima is None and llamada.sugerencia is not None and llamada.carta is not None:
        ultima = llamada.sugerencia, llamada.carta
    cambios = comparar(*ultima) if ultima is not None else []
    return Historial(llamada_id=llamada.llamada_id, eventos=eventos, cambios=cambios)


def _nodo(punto: PuntoGuardado, anterior: Mapping[str, object]) -> str | None:
    nuevas = punto.valores.keys() - anterior.keys()
    if "turnos" in nuevas:
        return "__start__"
    turnos, previos = punto.valores.get("turnos"), anterior.get("turnos")
    if isinstance(turnos, list) and isinstance(previos, list) and len(turnos) > len(previos):
        return "turno_agregado"
    escrituras = punto.metadatos.get("writes")
    if isinstance(escrituras, Mapping):
        nodos = ("analizar", "consultar_modelo", "esperar_operador", "derivar")
        return next((nodo for nodo in nodos if nodo in escrituras), None)

    # El grafo no guarda qué nodo escribió cada punto: se deduce de lo que cambió. Las reglas
    # registran cuántos turnos analizaron, aunque salga la misma sugerencia. Las llamadas
    # anteriores sólo dejan la primera sugerencia y, si cambia, la del modelo.
    if "sugerencia" in nuevas or punto.valores.get("turnos_analizados") != anterior.get(
        "turnos_analizados"
    ):
        return "analizar"
    if "ajustes" in nuevas:
        return "esperar_operador"
    if "carta" in punto.valores and punto.valores["carta"] != anterior.get("carta"):
        return "derivar"
    if punto.valores.get("respuesta") == "terminar" != anterior.get("respuesta"):
        return "esperar_operador"
    if punto.metadatos.get("source") == "loop" and _termino_el_modelo(punto, anterior):
        return "consultar_modelo"
    return None


def _termino_el_modelo(punto: PuntoGuardado, anterior: Mapping[str, object]) -> bool:
    return (
        punto.valores.get("falta_el_modelo") is False and anterior.get("falta_el_modelo") is True
    ) or punto.valores.get("sugerencia") != anterior.get("sugerencia")


def _respuesta_del_operador(
    punto: PuntoGuardado, carta_previa: Carta | None, derivacion: PuntoGuardado | None
) -> tuple[TipoEvento, str] | None:
    if punto.valores.get("respuesta") == "terminar":
        return "terminada", "Llamada terminada."
    # Lo que el operador manda después de derivar se cuenta en la actualización de la carta.
    if carta_previa is not None:
        return None
    if derivacion is None:
        return "ajustes_operador", "El operador confirmó. La carta todavía está pendiente."
    cambios = comparar(
        Sugerencia.model_validate(punto.valores["sugerencia"]),
        Carta.model_validate(derivacion.valores["carta"]),
    )
    detalle = f"con {_cantidad(len(cambios), 'cambio')}" if cambios else "sin cambios"
    return "ajustes_operador", f"El operador confirmó {detalle}."


def _detalle(
    nodo: str | None, punto: PuntoGuardado, anterior: Mapping[str, object]
) -> tuple[TipoEvento, str] | None:
    match nodo:
        case ("__start__" | "turno_agregado") as nodo:
            turnos = punto.valores["turnos"]
            assert isinstance(turnos, list)
            if nodo == "__start__":
                return "recibida", f"Llamada recibida, con {_cantidad(len(turnos), 'turno')}."
            previos = anterior["turnos"]
            assert isinstance(previos, list)
            nuevos = len(turnos) - len(previos)
            agregado = "sumó un turno" if nuevos == 1 else f"sumaron {nuevos} turnos"
            return "turno_agregado", f"Se {agregado} a la llamada: ahora tiene {len(turnos)}."
        case "analizar":
            sugerencia = Sugerencia.model_validate(punto.valores.get("sugerencia"))
            return "sugerencia_reglas", f"Sugerencia de las reglas, {_avisos(sugerencia)}."
        case "consultar_modelo" if _termino_el_modelo(punto, anterior):
            sugerencia = Sugerencia.model_validate(punto.valores.get("sugerencia"))
            # Si el tipo de hecho no es del modelo, la sugerencia entera volvió a las reglas. Un
            # aviso del modelo con el tipo ya propuesto es que sólo falló la revisión del subtipo.
            if getattr(sugerencia.tipo_hecho, "fuente", None) != "modelo":
                return (
                    "sugerencia_modelo",
                    "No hubo sugerencia del modelo: quedó la de las reglas.",
                )
            mensaje = f"Sugerencia del modelo, {_avisos(sugerencia)}."
            if (otra := sugerencia.direccion_alternativa) is not None:
                direccion = otra.calle if otra.altura is None else f"{otra.calle} {otra.altura}"
                if otra.esquinas:
                    # Con altura, dos calles son las que limitan la cuadra; una sola, la esquina.
                    entre = otra.altura is not None and len(otra.esquinas) == 2
                    direccion += f", {'entre' if entre else 'esquina'} {' y '.join(otra.esquinas)}"
                mensaje += f" Propuso otra dirección: {direccion}."
            return "sugerencia_modelo", mensaje
    return None


_NOMBRES = {
    "calle": "calle",
    "altura": "altura",
    "tipo_hecho": "tipo de hecho",
    "subtipo": "subtipo",
}


def _resumen(antes: Carta, despues: Carta) -> str:
    """Qué cambió de una versión de la carta a la siguiente, para quien sigue el incidente."""
    partes: list[str] = []
    previos, nuevos = antes.datos(), despues.datos()
    for campo, nombre in _NOMBRES.items():
        if valor_de(previos[campo]) != valor_de(nuevos[campo]):
            partes.append(nombre)
    if [valor_de(d) for d in antes.ubicacion.esquinas] != [
        valor_de(d) for d in despues.ubicacion.esquinas
    ]:
        partes.append("esquinas")
    if (previa := valor_de(antes.prioridad)) != (nueva := valor_de(despues.prioridad)):
        partes.append(f"prioridad {previa or 'sin dato'} → {nueva or 'sin dato'}")
    respondidas_antes = {item.id for item in antes.checklist if item.respondida}
    respondidas = {item.id for item in despues.checklist if item.respondida}
    if sumadas := len(respondidas - respondidas_antes):
        partes.append(f"{_cantidad(sumadas, 'pregunta')} {_plural(sumadas, 'respondida')}")
    if quitadas := len(respondidas_antes & {item.id for item in despues.checklist} - respondidas):
        partes.append(f"{_cantidad(quitadas, 'pregunta')} {_plural(quitadas, 'desmarcada')}")
    if sacados := len(antes.datos_dictados) - len(despues.datos_dictados):
        partes.append(f"{_cantidad(sacados, 'dato dictado')} {_plural(sacados, 'quitado')}")
    if not partes:
        return "sin cambios en los datos"
    return partes[0] if len(partes) == 1 else f"{', '.join(partes[:-1])} y {partes[-1]}"


def _plural(cantidad: int, palabra: str) -> str:
    return palabra if cantidad == 1 else palabra + "s"


def _cantidad(cantidad: int, singular: str) -> str:
    return f"{cantidad} {singular if cantidad == 1 else singular + 's'}"


def _avisos(sugerencia: Sugerencia) -> str:
    cantidad = len(sugerencia.avisos)
    return f"con {_cantidad(cantidad, 'aviso')}" if cantidad else "sin avisos"


def comparar(sugerencia: Sugerencia, carta: Carta) -> list[CambioHistorial]:
    antes, despues = sugerencia.datos(), carta.datos()
    cambios: list[CambioHistorial] = []
    for campo in ("calle", "altura", "esquinas", "tipo_hecho", "subtipo", "prioridad"):
        if campo == "esquinas":
            sugeridas, finales = sugerencia.ubicacion.esquinas, carta.ubicacion.esquinas
            if [valor_de(dato) for dato in sugeridas] != [valor_de(dato) for dato in finales]:
                cambios.append(CambioHistorial(campo=campo, sugerido=sugeridas, final=finales))
        elif valor_de(antes[campo]) != valor_de(despues[campo]):
            cambios.append(
                CambioHistorial.model_validate(
                    {"campo": campo, "sugerido": antes[campo], "final": despues[campo]}
                )
            )

    # Al cambiar de protocolo, sus preguntas arrancan pendientes. Sólo cuentan las que se marcaron.
    sugeridas_por_pregunta = (
        {(item.id, item.pregunta): item for item in sugerencia.checklist}
        if valor_de(sugerencia.subtipo) == valor_de(carta.subtipo)
        else {}
    )
    for item in carta.checklist:
        sugerida = sugeridas_por_pregunta.get((item.id, item.pregunta))
        respondida = sugerida is not None and sugerida.respondida
        propuesta = sugerida is not None and not respondida and sugerida.cita is not None
        if item.del_operador and (respondida != item.respondida or propuesta):
            cambios.append(
                CambioHistorial(
                    campo=f"pregunta {item.id}",
                    sugerido=EstadoPregunta(respondida=respondida, propuesta=propuesta),
                    final=EstadoPregunta(respondida=item.respondida),
                )
            )
    conservados = {(dato.tipo, dato.valor) for dato in carta.datos_dictados}
    for dato in sugerencia.datos_dictados:
        if (dato.tipo, dato.valor) not in conservados:
            cambios.append(
                CambioHistorial(
                    campo=f"dictado_{dato.tipo}",
                    sugerido=Dicho[str | int](valor=dato.valor, cita=dato.cita),
                    final=DelOperador[str | int](valor=None),
                )
            )
    return cambios
