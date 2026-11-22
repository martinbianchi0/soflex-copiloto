"""Las llamadas del dataset provisto y lo que se sabe de cada una.

Es para el modo simulado. Si lo primero que dice el llamante es exactamente el relato de una de
esas treinta, su tipo, su subtipo y su prioridad se leen de su fila, y qué preguntas del protocolo
responde el relato sale de `datos/respuestas_anotadas.json`. No se interpreta nada: es una
búsqueda, y el origen de esos datos lo dice.
"""

import csv
import io
import json
from functools import cache
from importlib import resources

from copiloto import catalogo
from copiloto.esquemas import Categoria, Esquema, Prioridad, Texto, Turno
from copiloto.turnos import tramos_del_llamante

RESPUESTAS = "respuestas_anotadas.json"


class LlamadaConocida(Esquema):
    categoria: Categoria
    subtipo: Texto
    prioridad: Prioridad
    # Qué preguntas del protocolo responde el relato, y con qué palabras lo dice el llamante.
    respuestas: dict[str, Texto]


def _tramos(turnos: list[Turno]) -> list[str]:
    return [tramo for turno in turnos for tramo in tramos_del_llamante(turno)]


def _relato(turnos: list[Turno]) -> str | None:
    """Lo primero que dijo el llamante, de un tirón. Sólo se emparejan los espacios."""
    tramos = _tramos(turnos)
    return " ".join(tramos[0].split()) if tramos else None


def se_dijo_algo_mas(turnos: list[Turno]) -> bool:
    """Si el llamante siguió hablando después de su relato."""
    return len(_tramos(turnos)) > 1


@cache
def _filas() -> list[dict[str, str]]:
    archivo = resources.files("copiloto").joinpath("datos", catalogo.ARCHIVO)
    # La firma tipada de Traversable.open omite newline, que el recurso admite en modo texto.
    with archivo.open("r", encoding="utf-8-sig", newline="") as abierto:  # type: ignore[call-overload]
        return list(csv.DictReader(io.StringIO(abierto.read(), newline="")))


def transcripciones() -> list[tuple[catalogo.Protocolo, str]]:
    """Cada llamada del dataset: su protocolo y su transcripción tal como viene."""
    protocolos = catalogo.cargar().protocolos
    return [
        (protocolo, fila["transcripcion_cruda"])
        for fila, protocolo in zip(_filas(), protocolos, strict=True)
    ]


@cache
def _conocidas() -> dict[str, LlamadaConocida]:
    datos = resources.files("copiloto").joinpath("datos")
    filas = _filas()
    anotadas: dict[str, str] = json.loads(datos.joinpath(RESPUESTAS).read_text(encoding="utf-8"))
    conocidas: dict[str, LlamadaConocida] = {}
    for fila, protocolo in zip(filas, catalogo.cargar().protocolos, strict=True):
        relato = _relato([Turno(texto=fila["transcripcion_cruda"])])
        if relato is None or relato in conocidas:
            raise ValueError(
                f"El registro {fila['id_registro']} no sirve para reconocer su llamada."
            )
        respuestas = {q.id: anotadas[q.id] for q in protocolo.preguntas if q.id in anotadas}
        if ajenas := [cita for cita in respuestas.values() if cita not in relato]:
            raise ValueError(f"La anotación {ajenas[0]!r} no está en el relato de su llamada.")
        conocidas[relato] = LlamadaConocida(
            categoria=protocolo.categoria,
            subtipo=protocolo.id,
            prioridad=fila["prioridad_sugerida"],
            respuestas=respuestas,
        )
    if sobran := set(anotadas) - {q for c in conocidas.values() for q in c.respuestas}:
        raise ValueError(f"Hay anotaciones de preguntas que no existen: {sorted(sobran)}.")
    return conocidas


def cargar() -> None:
    """Lee las llamadas conocidas. Se llama al arrancar: si los datos están mal, se sabe ahí."""
    _conocidas()


def buscar(turnos: list[Turno]) -> LlamadaConocida | None:
    """La llamada del dataset cuyo relato es lo primero que dice el llamante, o ninguna.

    Tiene que coincidir letra por letra: mayúsculas, acentos y puntuación. Una búsqueda no
    generaliza: un relato parecido, o partido en dos, es un texto nuevo. Lo que el llamante diga
    después no cambia cuál es la llamada, ni tampoco su ficha.
    """
    relato = _relato(turnos)
    return _conocidas().get(relato) if relato else None
