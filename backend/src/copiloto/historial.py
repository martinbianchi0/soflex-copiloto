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
    cambios = (
        comparar(llamada.sugerencia, llamada.carta)
        if llamada.sugerencia is not None and llamada.carta is not None
        else []
    )
    eventos: list[EventoHistorial] = []
    anterior: Mapping[str, object] = {}
    for punto in reversed(puntos):
        detalle = _detalle(punto, anterior, len(cambios) if llamada.carta else None)
        if detalle is not None:
            tipo, mensaje = detalle
            eventos.append(
                EventoHistorial.model_validate(
                    {"tipo": tipo, "cuando": punto.cuando, "detalle": mensaje}
                )
            )
        anterior = punto.valores
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

    # Las reglas registran cuántos turnos analizaron, aunque salga la misma sugerencia. Las
    # llamadas anteriores sólo dejan la primera sugerencia y, si cambia, la del modelo.
    if "sugerencia" in nuevas or punto.valores.get("turnos_analizados") != anterior.get(
        "turnos_analizados"
    ):
        return "analizar"
    if "ajustes" in nuevas:
        return "esperar_operador"
    if "carta" in nuevas:
        return "derivar"
    if punto.metadatos.get("source") == "loop" and _termino_el_modelo(punto, anterior):
        return "consultar_modelo"
    return None


def _termino_el_modelo(punto: PuntoGuardado, anterior: Mapping[str, object]) -> bool:
    return (
        punto.valores.get("falta_el_modelo") is False and anterior.get("falta_el_modelo") is True
    ) or punto.valores.get("sugerencia") != anterior.get("sugerencia")


def _detalle(
    punto: PuntoGuardado, anterior: Mapping[str, object], cambios: int | None
) -> tuple[TipoEvento, str] | None:
    match _nodo(punto, anterior):
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
            return "sugerencia_modelo", f"Sugerencia del modelo, {_avisos(sugerencia)}."
        case "esperar_operador":
            if cambios is None:
                return "ajustes_operador", "El operador confirmó. La carta todavía está pendiente."
            detalle = f"con {_cantidad(cambios, 'cambio')}" if cambios else "sin cambios"
            return "ajustes_operador", f"El operador confirmó {detalle}."
        case "derivar":
            return "derivada", "Carta de Llamada derivada."
    return None


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
