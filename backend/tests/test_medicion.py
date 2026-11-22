"""Cuánto aciertan las reglas, como test: los números que publica DECISIONS.md salen de acá.

Las 30 llamadas del dataset son las que se miraron para escribir las reglas. Las 32 de
`datos/llamadas_nuevas.json` son sintéticas y no son del dataset: miden mejor que las 30, pero no
reemplazan una medición con llamadas reales. Si una regla cambia y un número se mueve, este test
falla y hay que actualizar los dos.
"""

import csv
import json
import re
from collections import Counter
from importlib import resources
from pathlib import Path

from copiloto import callejero, tipo, ubicacion
from copiloto.callejero import normalizar
from copiloto.esquemas import Turno, texto_plano, valor_de

NUEVAS = json.loads(Path(__file__).with_name("datos").joinpath("llamadas_nuevas.json").read_text())


def _dataset() -> list[dict[str, str]]:
    archivo = resources.files("copiloto").joinpath("datos", "dataset_challenge_soflex.csv")
    with archivo.open("r", encoding="utf-8-sig", newline="") as abierto:
        return list(csv.DictReader(abierto))


def _leer(texto: str) -> ubicacion.Interpretacion:
    return ubicacion.interpretar([Turno(texto=texto)])


def test_ubicacion_en_las_llamadas_del_dataset():
    cj = callejero.cargar()
    calles = alturas = con_altura = 0
    for fila in _dataset():
        leida = _leer(fila["transcripcion_cruda"])
        # El dataset escribe la calle a su manera ("Av. Raúl Scalabrini Ortiz"): se busca en el
        # callejero y se compara con la que leyó el intérprete.
        escrita = normalizar(re.sub(r"\(.*?\)", "", fila["calle_detectada"]))
        del_dataset = {c.nombre for c in cj.candidatos(escrita)}
        acierta = leida.calle_oficial in del_dataset
        if not acierta and "(esquina)" in fila["altura_detectada"]:
            # En una esquina no hay calle principal: "Escalada y Castañares" es el mismo lugar que
            # "Castañares y Escalada". Vale si la del dataset es la esquina que dijo el llamante.
            dichas = {
                texto_plano(esquina.valor)
                for esquina in leida.ubicacion.esquinas
                if esquina.origen == "dicho"
            }
            acierta = bool(dichas & {texto_plano(cj.nombre_para_mostrar(n)) for n in del_dataset})
        calles += acierta
        if (altura := fila["altura_detectada"].strip()).isdigit():
            con_altura += 1
            if valor_de(leida.ubicacion.altura) == int(altura):
                alturas += 1
            else:
                # La única que no lee es una altura que el dataset agregó: nadie la dijo.
                assert altura not in fila["transcripcion_cruda"]
    # La calle que falta es una estación de subte ("estación Carlos Pellegrini"), no una dirección.
    assert (calles, alturas, con_altura) == (29, 17, 18)


def test_ubicacion_en_las_llamadas_nuevas():
    cuenta: Counter[str] = Counter()
    avisos_al_fallar: dict[str, set[str]] = {}
    for caso in NUEVAS:
        leida = _leer(caso["texto"])
        calle_bien = leida.calle_oficial == caso["calle_oficial"]
        altura_bien = valor_de(leida.ubicacion.altura) == caso["altura"]
        if caso["calle_oficial"]:
            cuenta["con calle"] += 1
            cuenta["calle bien"] += calle_bien
        else:
            cuenta["sin calle"] += 1
            cuenta["no propone calle"] += leida.calle_oficial is None
        if caso["altura"]:
            cuenta["con altura"] += 1
            cuenta["altura bien"] += altura_bien
        cuenta["todo bien"] += calle_bien and altura_bien
        if not (calle_bien and altura_bien):
            avisos_al_fallar[caso["id"]] = {aviso.codigo for aviso in leida.avisos}
    assert cuenta == {
        "con calle": 28,
        "calle bien": 27,
        "sin calle": 4,
        "no propone calle": 3,
        "con altura": 22,
        "altura bien": 19,
        "todo bien": 28,
    }
    # En las cuatro que falla, el operador tiene a la vista un aviso sobre ese mismo dato.
    assert {
        caso: avisos & ESPERADOS[caso] for caso, avisos in avisos_al_fallar.items()
    } == ESPERADOS


# Qué aviso corresponde a cada falla: una calle con dos candidatas, dos direcciones que no cierran
# y una calle que no se reconoció.
ESPERADOS = {
    "L02": {"calle_ambigua"},
    "L04": {"direccion_no_cierra"},
    "R03": {"sin_calle"},
    "R06": {"direccion_no_cierra"},
}


def _categorias(casos: list[tuple[str, str]]) -> Counter[str]:
    cuenta: Counter[str] = Counter()
    for texto, esperada in casos:
        propuesta = tipo.por_palabras_clave([Turno(texto=texto)])
        if propuesta == esperada:
            cuenta["bien"] += 1
        elif propuesta == "NO_DETERMINADA":
            cuenta["sin determinar"] += 1
        else:
            cuenta["mal"] += 1
    return cuenta


def test_categoria_en_las_llamadas_del_dataset():
    casos = [(fila["transcripcion_cruda"], fila["categoria"]) for fila in _dataset()]
    assert _categorias(casos) == {"bien": 27, "sin determinar": 3}


def test_categoria_en_las_llamadas_nuevas():
    casos = [(caso["texto"], caso["categoria"]) for caso in NUEVAS]
    # La equivocada es una consulta que dice "no me robaron": las reglas no entienden una negación.
    assert _categorias(casos) == {"bien": 23, "sin determinar": 8, "mal": 1}
