from time import monotonic

import pytest

from copiloto import catalogo
from copiloto.catalogo import Pregunta
from copiloto.esquemas import MAXIMO_DE_TEXTO_LARGO, Cita, Turno
from copiloto.interprete import (
    RespuestaIlegible,
    leer_json,
    mensaje_del_llamante,
    revisar_protocolo,
    verificar_cita,
)


@pytest.mark.parametrize(
    ("texto", "objeto"),
    [
        ('{"prioridad": "P2"', {"prioridad": "P2"}),
        (
            '```json\n{"respuestas": [{"id": "SFX-001-Q1"}]\n```',
            {"respuestas": [{"id": "SFX-001-Q1"}]},
        ),
        ('Acá va.\n```json\n{"prioridad": "P2"}\n```\nListo.', {"prioridad": "P2"}),
    ],
)
def test_leer_json_acepta_texto_alrededor_o_una_llave_de_cierre_faltante(texto, objeto):
    assert leer_json(texto) == objeto


@pytest.mark.parametrize("texto", ["", "sin objeto", "[1, 2]", '{"dato":', '{"dato": {"id": 1'])
def test_leer_json_devuelve_un_error_si_no_hay_un_objeto_que_se_pueda_leer(texto):
    with pytest.raises(RespuestaIlegible):
        leer_json(texto)


def test_una_cita_parcial_conserva_la_tira_mas_larga_con_su_grafia():
    turnos = [Turno(texto="Hay humo, salió la gente pero adentro Quedó el Cocinero.")]

    cita = verificar_cita("dentro quedó el cocinero", turnos)

    assert cita == Cita(turno=0, texto="Quedó el Cocinero")


def test_ante_un_empate_se_guarda_la_primera_tira_de_la_cita():
    turnos = [Turno(texto="Quedó el cocinero."), Turno(texto="Hay mucho humo.")]

    cita = verificar_cita("hay mucho humo quedó el cocinero", turnos)

    assert cita == Cita(turno=1, texto="Hay mucho humo")


def test_una_cita_que_verifica_entera_se_copia_de_la_transcripcion():
    turnos = [
        Turno(texto="¿Dónde hay humo?", hablante="operador"),
        Turno(texto="Sí, en la cocina hay HUMO.", hablante="llamante"),
    ]

    assert verificar_cita("si en la cocina hay humo", turnos) == Cita(
        turno=1, texto="Sí, en la cocina hay HUMO"
    )


def test_una_cita_entera_tiene_preferencia_aunque_una_tira_aparezca_antes():
    turnos = [Turno(texto="Quedó el cocinero."), Turno(texto="Adentro quedó el cocinero.")]

    assert verificar_cita("adentro quedó el cocinero", turnos) == Cita(
        turno=1, texto="Adentro quedó el cocinero"
    )


def test_una_cita_muy_larga_se_recorta_a_las_primeras_palabras_que_entran():
    texto = "Árbol, " * 28 + "verde"
    turnos = [Turno(texto=f"Había un {texto} en la vereda.")]

    cita = verificar_cita(texto, turnos)

    assert cita == Cita(turno=0, texto="Árbol, " * 27 + "Árbol")
    assert cita.texto in turnos[0].texto


def test_el_mensaje_separa_los_tramos_del_llamante_en_lineas():
    turnos = [
        Turno(texto="911, ¿dónde es?", hablante="operador"),
        Turno(texto="En Corrientes.", hablante="llamante"),
        Turno(texto="Sin aclarar. Operador: ¿Qué pasa? Llamante: Hay humo."),
    ]

    assert mensaje_del_llamante(turnos) == "Lo que dijo el llamante:\nEn Corrientes.\nHay humo."


@pytest.mark.parametrize(
    ("propuesta", "turnos"),
    [
        pytest.param(
            "adentro quedó el cocinero",
            [Turno(texto="Vi al dueño con el cocinero.")],
            id="dos_palabras",
        ),
        pytest.param(
            "vi que adentro quedó el cocinero solo",
            [Turno(texto="Quedó el cocinero.")],
            id="menos_de_la_mitad",
        ),
        pytest.param(
            "adentro quedó el cocinero",
            [Turno(texto="Adentro quedó."), Turno(texto="El cocinero.")],
            id="dos_turnos",
        ),
        pytest.param(
            "adentro quedó el cocinero",
            [Turno(texto="Llamante: Adentro quedó. Operador: ¿Quién? Llamante: El cocinero.")],
            id="dos_tramos_del_mismo_turno",
        ),
        pytest.param(
            "adentro quedó el cocinero",
            [
                Turno(texto="¿Adentro quedó el cocinero?", hablante="operador"),
                Turno(texto="No sé."),
            ],
            id="turno_del_operador",
        ),
        pytest.param(
            "adentro quedó el cocinero",
            [Turno(texto="Llamante: No sé. Operador: ¿Adentro quedó el cocinero?")],
            id="tramo_del_operador",
        ),
    ],
)
def test_las_citas_no_se_completan_con_palabras_ajenas(propuesta, turnos):
    assert verificar_cita(propuesta, turnos) is None


def test_el_aviso_de_descarte_recorta_la_pregunta_para_que_entre():
    pregunta = Pregunta(id="P1", texto="a" * MAXIMO_DE_TEXTO_LARGO)
    protocolo = catalogo.cargar().protocolos[0].model_copy(update={"preguntas": [pregunta]})

    def modelo(sistema, usuario, vence):
        return '{"corresponde": true, "respuestas": [{"id": "P1", "respondida": true, "cita": "Hay humo"}]}'

    respuestas, (aviso,) = revisar_protocolo(
        modelo,
        "Lo que dijo el llamante: No sé",
        protocolo,
        [Turno(texto="No sé")],
        monotonic() + 60,
    )

    assert respuestas == []
    assert len(aviso.mensaje) == MAXIMO_DE_TEXTO_LARGO
    assert aviso.mensaje.startswith("Se descartó una respuesta del modelo a «")
    assert aviso.mensaje.endswith("…»: su cita no está en lo que dijo el llamante.")
