"""Quién dice qué en una llamada."""

import re

from pydantic import ValidationError

from copiloto.esquemas import Turno

# Así vienen marcados los turnos en una transcripción pegada entera: "Operador: ... Llamante: ...".
MARCA_DE_HABLANTE = re.compile(r"\b(operador|llamante)\s*:", re.IGNORECASE)
_MAXIMO = 500
# Lo que está antes de la primera marca de un turno con marcas: no se sabe quién lo dijo.
_NADIE = "sin atribuir"


def _tramos(turno: Turno) -> list[tuple[str | None, str]]:
    """Quién habla y qué dice en cada tramo del turno."""
    if turno.hablante is not None:
        return [(turno.hablante, turno.texto)]
    partes = MARCA_DE_HABLANTE.split(turno.texto)
    if len(partes) == 1:
        return [(None, turno.texto)]
    # split() devuelve: lo de antes de la primera marca, y después pares (quién, qué dijo).
    pares = zip(partes[1::2], partes[2::2], strict=True)
    tramos = [(_NADIE, partes[0]), *((quien.lower(), texto) for quien, texto in pares)]
    return [(quien, texto.strip()) for quien, texto in tramos if texto.strip()]


def separar_hablantes(turnos: list[Turno]) -> list[Turno]:
    """Parte en turnos una transcripción que trae las marcas de quién habla.

    Se hace antes de guardar la llamada: las citas señalan el turno por su posición. Un turno que ya
    dice quién habla, o que no trae marcas, queda como está.
    """
    separados: list[Turno] = []
    try:
        for turno in turnos:
            tramos = _tramos(turno)
            if any(quien == _NADIE for quien, _ in tramos):
                # Partirlo sería atribuirle a alguien el tramo de nadie: se guarda entero.
                separados.append(turno)
            else:
                separados += [Turno(texto=texto, hablante=quien) for quien, texto in tramos]
    except ValidationError:
        return turnos
    # Si no quedó nada legible o son demasiados, se guarda lo que llegó, sin partir. Quien lee la
    # llamada mira las marcas igual: lo que dijo el operador no se cuenta en ningún caso.
    return separados if 0 < len(separados) <= _MAXIMO else turnos


def tramos_del_llamante(turno: Turno) -> list[str]:
    """Lo que dijo el llamante en un turno.

    Un turno sin hablante y sin marcas se toma entero: no hay nada que indique otra cosa. Con
    marcas, cuenta sólo lo que está detrás de "Llamante:"; ni lo del operador ni lo de nadie.
    """
    return [texto for quien, texto in _tramos(turno) if quien in (None, "llamante")]


def dicho_por_el_llamante(turnos: list[Turno]) -> str:
    """Todo lo que dijo el llamante, de corrido."""
    return " ".join(texto for turno in turnos for texto in tramos_del_llamante(turno))
