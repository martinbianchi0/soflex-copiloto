"""Llamadas listas para probar el panel sin tener que buscar ni pegar una transcripción."""

import json
from functools import cache
from importlib import resources
from typing import Literal

from copiloto import dataset
from copiloto.esquemas import Esquema, Texto, TextoDeTurno

NUEVAS = "llamadas_de_ejemplo.json"


class Ejemplo(Esquema):
    id: Texto
    titulo: Texto
    # "dataset": una de las llamadas provistas. "nueva": una que el servicio no conoce.
    origen: Literal["dataset", "nueva"]
    texto: TextoDeTurno


@cache
def cargar() -> list[Ejemplo]:
    """Las llamadas del dataset y unas pocas nuevas, que muestran qué pasa con un texto distinto."""
    del_dataset = [
        Ejemplo(id=protocolo.id, titulo=protocolo.nombre, origen="dataset", texto=texto)
        for protocolo, texto in dataset.transcripciones()
    ]
    archivo = resources.files("copiloto").joinpath("datos", NUEVAS)
    nuevas = [
        Ejemplo(origen="nueva", **ejemplo)
        for ejemplo in json.loads(archivo.read_text(encoding="utf-8"))
    ]
    return [*del_dataset, *nuevas]
