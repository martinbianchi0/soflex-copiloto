"""Las llamadas del dataset provisto y lo que se sabe de cada una.

Es para el modo simulado. Si en la llamada que entra el llamante dice exactamente lo mismo que en
una de esas treinta, su tipo, su subtipo y su prioridad se leen de su fila, y qué preguntas del
protocolo responde el relato sale de `datos/respuestas_anotadas.json`. No se interpreta nada: es
una búsqueda, y el origen de esos datos lo dice.
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


def _relato(turnos: list[Turno]) -> str | None:
    """Lo que dijo el llamante, si lo dijo de un tirón. Sólo se emparejan los espacios."""
    tramos = [tramo for turno in turnos for tramo in tramos_del_llamante(turno)]
    return " ".join(tramos[0].split()) if len(tramos) == 1 else None


@cache
def _conocidas() -> dict[str, LlamadaConocida]:
    datos = resources.files("copiloto").joinpath("datos")
    archivo = datos.joinpath(catalogo.ARCHIVO)
    # La firma tipada de Traversable.open omite newline, que el recurso admite en modo texto.
    with archivo.open("r", encoding="utf-8-sig", newline="") as abierto:  # type: ignore[call-overload]
        filas = list(csv.DictReader(io.StringIO(abierto.read(), newline="")))
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
    """La llamada del dataset en la que el llamante dice exactamente lo mismo, o ninguna.

    Tiene que coincidir letra por letra: mayúsculas, acentos y puntuación. Una búsqueda no
    generaliza: un relato parecido, o el mismo con algo más, es un texto nuevo.
    """
    relato = _relato(turnos)
    return _conocidas().get(relato) if relato else None
