"""Reconstruye lo que pasó a partir de los puntos guardados de una llamada."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from copiloto.esquemas import (
    CambioHistorial,
    Carta,
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
        detalle = _detalle(
            punto, anterior, len(llamada.turnos), len(cambios) if llamada.carta else None
        )
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
    escrituras = punto.metadatos.get("writes")
    if isinstance(escrituras, Mapping):
        nodos = ("analizar", "consultar_modelo", "esperar_operador", "derivar")
        return next((nodo for nodo in nodos if nodo in escrituras), None)

    # Los puntos actuales de SQLite no traen writes. Cada nodo agrega su propia clave,
    # salvo el del modelo, que reemplaza la sugerencia si tiene algo distinto.
    if "sugerencia" in nuevas:
        return "analizar"
    if "ajustes" in nuevas:
        return "esperar_operador"
    if "carta" in nuevas:
        return "derivar"
    if punto.metadatos.get("source") == "loop" and _cambio_la_sugerencia(punto, anterior):
        return "consultar_modelo"
    return None


def _cambio_la_sugerencia(punto: PuntoGuardado, anterior: Mapping[str, object]) -> bool:
    return punto.valores.get("sugerencia") != anterior.get("sugerencia")


def _detalle(
    punto: PuntoGuardado, anterior: Mapping[str, object], turnos: int, cambios: int | None
) -> tuple[TipoEvento, str] | None:
    match _nodo(punto, anterior):
        case "__start__":
            return "recibida", f"Llamada recibida, con {_cantidad(turnos, 'turno')}."
        case "analizar":
            sugerencia = Sugerencia.model_validate(punto.valores.get("sugerencia"))
            return "sugerencia_reglas", f"Sugerencia de las reglas, {_avisos(sugerencia)}."
        case "consultar_modelo" if _cambio_la_sugerencia(punto, anterior):
            sugerencia = Sugerencia.model_validate(punto.valores.get("sugerencia"))
            # Si el tipo de hecho no es del modelo, la sugerencia entera volvió a las reglas. Un
            # aviso del modelo con el tipo ya propuesto es que sólo falló la revisión del subtipo.
            if getattr(sugerencia.tipo_hecho, "fuente", None) != "modelo":
                return (
                    "sugerencia_modelo",
                    "El modelo no respondió: quedó la sugerencia de las reglas.",
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
        {(item.id, item.pregunta): item.respondida for item in sugerencia.checklist}
        if valor_de(sugerencia.subtipo) == valor_de(carta.subtipo)
        else {}
    )
    for item in carta.checklist:
        respondida = sugeridas_por_pregunta.get((item.id, item.pregunta), False)
        if item.del_operador and respondida != item.respondida:
            cambios.append(
                CambioHistorial(
                    campo=f"pregunta {item.id}",
                    sugerido=EstadoPregunta(respondida=respondida),
                    final=EstadoPregunta(respondida=item.respondida),
                )
            )
    return cambios
