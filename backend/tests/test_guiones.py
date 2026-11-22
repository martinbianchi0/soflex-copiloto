import csv
import json
from collections import Counter
from importlib import resources
from itertools import pairwise
from pathlib import Path

import pytest

from copiloto import callejero, catalogo
from copiloto.esquemas import Categoria

GUIONES = json.loads((Path(__file__).parent / "datos" / "guiones.json").read_text(encoding="utf-8"))
CASOS = [pytest.param(guion, id=guion["id"]) for guion in GUIONES]

DATOS_EMPAQUETADOS = resources.files("copiloto").joinpath("datos")
with DATOS_EMPAQUETADOS.joinpath(catalogo.ARCHIVO).open(
    encoding="utf-8-sig", newline=""
) as archivo:
    TRANSCRIPCIONES = [
        callejero.normalizar(fila["transcripcion_cruda"]) for fila in csv.DictReader(archivo)
    ]


def test_hay_catorce_guiones_de_subtipos_distintos_y_al_menos_dos_por_categoria():
    assert len(GUIONES) == 14
    assert len({guion["id"] for guion in GUIONES}) == 14
    assert len({guion["subtipo"] for guion in GUIONES}) == 14

    cantidades = Counter(guion["categoria"] for guion in GUIONES)
    assert set(cantidades) == {p.categoria.value for p in catalogo.cargar().protocolos}
    assert min(cantidades.values()) >= 2


@pytest.mark.parametrize("guion", CASOS)
def test_el_subtipo_es_de_la_categoria_y_las_respuestas_son_de_su_protocolo(guion):
    protocolo = catalogo.cargar().protocolo(Categoria(guion["categoria"]), guion["subtipo"])
    assert protocolo is not None
    preguntas = {pregunta.id for pregunta in protocolo.preguntas}
    for intercambio in guion["intercambios"]:
        respondidas = intercambio["esperado"]["respondidas"]
        assert len(respondidas) == len(set(respondidas))
        assert set(respondidas) <= preguntas


@pytest.mark.parametrize("guion", CASOS)
def test_lo_que_ya_se_sabe_se_conserva_en_los_intercambios_siguientes(guion):
    esperados = [intercambio["esperado"] for intercambio in guion["intercambios"]]
    for campo in ("categoria", "subtipo"):
        assert esperados[-1][campo] == guion[campo]
    for esperado in esperados:
        assert esperado["subtipo"] is None or esperado["categoria"] is not None
    for anterior, siguiente in pairwise(esperados):
        for campo in ("categoria", "subtipo", "calle_oficial", "altura", "esquina_oficial"):
            assert anterior[campo] is None or siguiente[campo] == anterior[campo], campo
        assert set(anterior["respondidas"]) <= set(siguiente["respondidas"])


@pytest.mark.parametrize("guion", CASOS)
def test_las_calles_las_alturas_y_los_cruces_existen_en_el_callejero(guion):
    mapa = callejero.cargar()
    for intercambio in guion["intercambios"]:
        esperado = intercambio["esperado"]
        calle = esperado["calle_oficial"]
        altura = esperado["altura"]
        esquina = esperado["esquina_oficial"]
        if calle is not None:
            assert calle in mapa.tramos
        if altura is not None:
            assert calle is not None
            assert esquina is None
            assert type(altura) is int
            assert mapa.tramos_en(calle, altura), (calle, altura)
        if esquina is not None:
            assert calle is not None
            assert esquina in mapa.tramos
            assert mapa.alturas_en_esquina(calle, esquina), (calle, esquina)


@pytest.mark.parametrize("guion", CASOS)
def test_los_intercambios_tienen_preguntas_y_relato_propio(guion):
    intercambios = guion["intercambios"]
    assert 3 <= len(intercambios) <= 5
    saludo = intercambios[0]["turnos"][0]["texto"]
    assert saludo.startswith(("911", "SAME 107", "Guardia de Auxilio 103", "147"))
    protocolo = catalogo.cargar().protocolo(Categoria(guion["categoria"]), guion["subtipo"])
    assert protocolo is not None
    nombre = callejero.normalizar(protocolo.nombre)

    for intercambio in intercambios:
        turnos = intercambio["turnos"]
        assert [turno["hablante"] for turno in turnos] in (
            ["operador", "llamante"],
            ["operador", "llamante", "operador", "llamante"],
        )
        for turno in turnos:
            texto = callejero.normalizar(turno["texto"])
            assert texto
            assert nombre not in texto
            if turno["hablante"] == "llamante":
                assert 15 <= len(turno["texto"].split()) <= 45, turno["texto"]
                assert all(texto not in original for original in TRANSCRIPCIONES), turno["texto"]


def test_cuando_se_aclaran_la_categoria_y_el_subtipo():
    primeros = [guion["intercambios"][0]["esperado"] for guion in GUIONES]
    assert Counter(
        (esperado["categoria"] is not None, esperado["subtipo"] is not None)
        for esperado in primeros
    ) == {(False, False): 3, (True, False): 4, (True, True): 7}


def test_cuando_se_completa_la_ubicacion_y_que_no_se_repite():
    primeras_con_altura_final = []
    direcciones = set()
    esquinas = set()
    for guion in GUIONES:
        intercambios = guion["intercambios"]
        ultimo = intercambios[-1]["esperado"]
        calle = ultimo["calle_oficial"]
        if ultimo["altura"] is not None:
            primeras_con_altura_final.append(intercambios[0]["esperado"])
            direcciones.add((calle, ultimo["altura"]))
        else:
            assert ultimo["esquina_oficial"] is not None
            esquinas.add(frozenset((calle, ultimo["esquina_oficial"])))

    assert len(primeras_con_altura_final) == len(direcciones) == 12
    assert all(primera["calle_oficial"] is not None for primera in primeras_con_altura_final)
    assert sum(primera["altura"] is not None for primera in primeras_con_altura_final) == 6
    assert len(esquinas) == 2


def test_cuantas_preguntas_se_responden_y_cuando():
    cantidad_por_guion = Counter()
    con_respuestas_posteriores = 0
    for guion in GUIONES:
        esperados = [intercambio["esperado"] for intercambio in guion["intercambios"]]
        al_aclarar_el_subtipo = next(paso for paso in esperados if paso["subtipo"] is not None)
        total = len(esperados[-1]["respondidas"])
        cantidad_por_guion[total] += 1
        con_respuestas_posteriores += len(al_aclarar_el_subtipo["respondidas"]) < total

    assert cantidad_por_guion == {2: 9, 3: 3, 1: 2}
    assert con_respuestas_posteriores >= 7
