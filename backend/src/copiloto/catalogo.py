"""El catálogo de protocolos: por cada subtipo de hecho, sus preguntas clave y sus instrucciones.

Se arma del dataset provisto, una fila por subtipo. Los textos se muestran tal cual están ahí: el
sistema elige un protocolo por su identificador, nunca redacta una pregunta ni una instrucción.
"""

import csv
import io
import re
from functools import cache
from importlib import resources
from typing import Self

from pydantic import Field, ValidationError, model_validator

from copiloto.criterio import CRITERIO, Criterio
from copiloto.esquemas import Categoria, Esquema, Instruccion, Texto, TextoLargo

ARCHIVO = "dataset_challenge_soflex.csv"
COLUMNAS = (
    "id_registro",
    "categoria",
    "subcategoria",
    "preguntas_protocolo_mandatorias",
    "instrucciones_prearribo",
)


class CatalogoInvalido(ValueError):
    """El archivo del catálogo no tiene la forma esperada."""


class SubtipoInvalido(ValueError):
    """El subtipo no existe en el catálogo o es de otra categoría."""


class Pregunta(Esquema):
    id: Texto
    texto: TextoLargo


class Protocolo(Esquema):
    """Lo que el catálogo trae para un subtipo de hecho."""

    id: Texto
    categoria: Categoria
    nombre: Texto
    preguntas: list[Pregunta] = Field(min_length=1)
    instrucciones: list[Instruccion] = Field(min_length=1)

    @model_validator(mode="after")
    def de_una_categoria_reconocida(self) -> Self:
        if self.categoria is Categoria.NO_DETERMINADA:
            raise ValueError("Un protocolo es de una categoría reconocida.")
        return self


class Catalogo(Esquema):
    """Lo que el servicio trae de referencia: los protocolos y el criterio de prioridad."""

    protocolos: list[Protocolo] = Field(min_length=1)
    criterio: Criterio = CRITERIO

    @model_validator(mode="after")
    def sin_identificadores_repetidos(self) -> Self:
        # Un identificador nombra una sola cosa: con dos iguales no se sabría qué texto mostrar.
        grupos = {
            "protocolo": [p.id for p in self.protocolos],
            "subtipo": [p.nombre for p in self.protocolos],
            "pregunta": [q.id for p in self.protocolos for q in p.preguntas],
            "instrucción": [i.id for p in self.protocolos for i in p.instrucciones],
        }
        for que, valores in grupos.items():
            if len(set(valores)) != len(valores):
                raise ValueError(f"Hay un identificador de {que} repetido.")
        return self

    def protocolo(self, categoria: Categoria, subtipo: str | None) -> Protocolo | None:
        """El protocolo de un subtipo. Sin subtipo no hay protocolo: no se elige uno parecido."""
        if subtipo is None:
            return None
        for protocolo in self.protocolos:
            if protocolo.id == subtipo:
                if protocolo.categoria != categoria:
                    raise SubtipoInvalido("El subtipo es de otra categoría.")
                return protocolo
        raise SubtipoInvalido("El subtipo no está en el catálogo.")


def leer(texto: str) -> Catalogo:
    """Arma el catálogo a partir del contenido del CSV."""
    lector = csv.DictReader(io.StringIO(texto, newline=""), strict=True)
    try:
        columnas = list(lector.fieldnames or [])
        filas = list(lector)
    except csv.Error as error:
        raise CatalogoInvalido(
            f"El archivo del catálogo no se puede leer (línea {lector.line_num}): {error}."
        ) from error
    if faltan := sorted(set(COLUMNAS) - set(columnas)):
        raise CatalogoInvalido(f"Al archivo del catálogo le faltan columnas: {', '.join(faltan)}.")
    if len(set(columnas)) != len(columnas):
        raise CatalogoInvalido("El archivo del catálogo tiene columnas repetidas.")
    for fila in filas:
        # Con celdas de más o de menos no se sabe qué texto corresponde a qué columna.
        if None in fila or None in fila.values():
            registro = fila.get("id_registro") or "sin identificador"
            raise CatalogoInvalido(
                f"El registro {registro} no tiene las mismas columnas que el encabezado."
            )
    try:
        return Catalogo(protocolos=[_protocolo(fila) for fila in filas])
    except ValidationError as error:
        raise CatalogoInvalido(f"El catálogo no es válido: {error}") from error


def _protocolo(fila: dict[str, str]) -> Protocolo:
    fila = {columna: fila[columna].strip() for columna in COLUMNAS}
    registro = fila["id_registro"]
    # El número es el del registro del dataset: SFX-REC-2026-001 da el protocolo SFX-001.
    if (numero := re.fullmatch(r"SFX-REC-\d{4}-(\d{3})", registro)) is None:
        raise CatalogoInvalido(f"Identificador de registro inesperado: {registro!r}.")
    codigo = f"SFX-{numero[1]}"
    preguntas = fila["preguntas_protocolo_mandatorias"].split(" | ")
    try:
        return Protocolo.model_validate(
            {
                "id": codigo,
                "categoria": fila["categoria"],
                "nombre": fila["subcategoria"],
                "preguntas": [
                    {"id": f"{codigo}-Q{n}", "texto": texto}
                    for n, texto in enumerate(preguntas, start=1)
                ],
                # La instrucción va entera y sin tocar: es para leerla textual.
                "instrucciones": [{"id": f"{codigo}-I1", "texto": fila["instrucciones_prearribo"]}],
            }
        )
    except ValidationError as error:
        raise CatalogoInvalido(
            f"El registro {registro} no sirve para el catálogo: {error}"
        ) from error


@cache
def cargar() -> Catalogo:
    """El catálogo que viene con el servicio. Se lee una sola vez."""
    archivo = resources.files("copiloto").joinpath("datos", ARCHIVO)
    # El archivo puede venir con la marca de orden de bytes que agregan algunas planillas. Los
    # saltos de línea se leen sin traducir, para no tocar los que haya dentro de un texto.
    # La firma tipada de Traversable.open omite newline, que el recurso admite en modo texto.
    with archivo.open("r", encoding="utf-8-sig", newline="") as abierto:  # type: ignore[call-overload]
        return leer(abierto.read())
