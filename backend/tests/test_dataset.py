import json
import re

import pytest
from conftest import DATOS_EMPAQUETADOS, FILAS_DATASET, TEXTO, TEXTO_SIN_DATOS

from copiloto import catalogo, dataset
from copiloto.esquemas import Turno

ANOTADAS = json.loads(
    DATOS_EMPAQUETADOS.joinpath("respuestas_anotadas.json").read_text(encoding="utf-8")
)


def test_el_csv_empaqueta_las_treinta_llamadas():
    assert set(FILAS_DATASET) == {f"SFX-{numero:03d}" for numero in range(1, 31)}


@pytest.mark.parametrize("subtipo", FILAS_DATASET)
def test_cada_llamada_del_dataset_se_reconoce_con_sus_datos(subtipo):
    fila = FILAS_DATASET[subtipo]

    conocida = dataset.buscar([Turno(texto=fila["transcripcion_cruda"])])

    assert conocida is not None
    assert conocida.categoria == fila["categoria"]
    assert conocida.subtipo == subtipo
    assert conocida.prioridad == fila["prioridad_sugerida"]
    assert conocida.respuestas == {
        pregunta: fragmento
        for pregunta, fragmento in ANOTADAS.items()
        if pregunta.rsplit("-Q", 1)[0] == subtipo
    }


@pytest.mark.parametrize(
    "relato",
    [
        pytest.param(TEXTO.upper(), id="mayusculas"),
        pytest.param(TEXTO.translate(str.maketrans("áéíóú", "aeiou")), id="sin_acentos"),
        pytest.param(re.sub(r"[^\w\s]", "", TEXTO), id="sin_puntuacion"),
    ],
)
def test_con_otra_escritura_ya_no_es_la_llamada_del_dataset(relato):
    # Reconocer es buscar, no interpretar: tiene que decir lo mismo letra por letra.
    assert dataset.buscar([Turno(texto=relato)]) is None


def test_un_signo_que_cambia_el_sentido_no_se_reconoce():
    original = FILAS_DATASET["SFX-022"]["transcripcion_cruda"]
    assert "No hay fuego por ahora" in original

    assert dataset.buscar([Turno(texto=original)]) is not None
    cambiada = original.replace("No hay fuego por ahora", "No: hay fuego por ahora")
    assert dataset.buscar([Turno(texto=cambiada)]) is None


def test_si_el_llamante_dice_algo_mas_ya_no_es_la_llamada_del_dataset():
    turnos = [
        Turno(hablante="llamante", texto=TEXTO),
        Turno(hablante="llamante", texto="Apúrense."),
    ]

    assert dataset.buscar(turnos) is None


def test_el_relato_partido_por_el_operador_no_se_reconoce():
    mitad = TEXTO.index("adentro quedó") + len("adentro quedó")
    turnos = [
        Turno(hablante="llamante", texto=TEXTO[:mitad]),
        Turno(hablante="operador", texto="¿Quién?"),
        Turno(hablante="llamante", texto=TEXTO[mitad:]),
    ]

    assert dataset.buscar(turnos) is None


def test_los_espacios_de_mas_no_cambian_el_reconocimiento():
    assert dataset.buscar([Turno(texto="  " + TEXTO.replace(" ", "  ") + "\n")]) is not None


def test_la_llamada_se_reconoce_en_dos_turnos_aunque_cambie_lo_que_dijo_el_operador():
    original = FILAS_DATASET["SFX-001"]["transcripcion_cruda"]
    turnos = [
        Turno(hablante="operador", texto="¿Puede confirmar la dirección?"),
        Turno(hablante="llamante", texto=TEXTO),
    ]

    conocida = dataset.buscar(turnos)

    assert conocida is not None
    assert conocida == dataset.buscar([Turno(texto=original)])


def test_cambiar_una_palabra_del_relato_impide_reconocer_la_llamada():
    relato = TEXTO.replace("cocinero", "mozo")

    assert dataset.buscar([Turno(texto=relato)]) is None


def test_un_texto_ajeno_al_dataset_no_se_reconoce():
    assert dataset.buscar([Turno(texto=TEXTO_SIN_DATOS)]) is None


@pytest.mark.parametrize("pregunta", ANOTADAS)
def test_cada_respuesta_anotada_es_una_cita_literal_del_llamante(pregunta):
    protocolos = {
        item.id: protocolo.id
        for protocolo in catalogo.cargar().protocolos
        for item in protocolo.preguntas
    }
    assert pregunta in protocolos
    texto = FILAS_DATASET[protocolos[pregunta]]["transcripcion_cruda"]
    operador, marca, llamante = texto.partition("Llamante:")
    assert marca

    fragmento = ANOTADAS[pregunta]
    assert fragmento in llamante
    assert fragmento not in operador
