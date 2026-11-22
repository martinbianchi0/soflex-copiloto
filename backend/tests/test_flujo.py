from datetime import UTC, datetime

import pytest
from conftest import TURNOS

from copiloto import catalogo, flujo
from copiloto.catalogo import SubtipoInvalido
from copiloto.esquemas import Ajustes, Sugerencia, Turno

AHORA = datetime(2026, 11, 22, 3, 0, tzinfo=UTC)
COMPLETA = {"calle": "Av. Corrientes", "altura": 1540, "esquinas": ["Montevideo", "Paraná"]}


def derivar(sugerencia: dict, ajustes: dict) -> dict:
    carta = flujo.derivar(
        "abc", Sugerencia.model_validate(sugerencia), Ajustes.model_validate(ajustes), AHORA
    )
    return carta.model_dump(mode="json")


def test_analizar_no_afirma_nada_que_no_haya_leido():
    sugerencia = flujo.analizar([Turno(**turno) for turno in TURNOS])

    assert sugerencia.faltantes() == ["calle", "prioridad"]
    assert sugerencia.tipo_hecho.valor == "NO_DETERMINADA"
    assert sugerencia.citas() == []


def test_lo_que_el_operador_no_toca_conserva_su_origen_y_su_cita(sugerencia_completa):
    carta = derivar(sugerencia_completa, {"prioridad": "P1"})

    assert carta["ubicacion"] == sugerencia_completa["ubicacion"]
    assert carta["tipo_hecho"] == sugerencia_completa["tipo_hecho"]
    assert carta["subtipo"] == sugerencia_completa["subtipo"]
    assert carta["checklist"] == sugerencia_completa["checklist"]
    assert carta["instrucciones"] == sugerencia_completa["instrucciones"]
    assert carta["prioridad"] == {"origen": "operador", "valor": "P1"}
    assert carta["llamada_id"] == "abc"
    assert carta["derivada_en"] == "2026-11-22T03:00:00Z"


def test_lo_que_el_operador_cambia_pasa_a_ser_suyo_y_el_resto_no(sugerencia_completa):
    ubicacion = {**COMPLETA, "altura": 1548, "esquinas": ["Montevideo", "Uruguay"]}

    carta = derivar(sugerencia_completa, {"prioridad": "P2", "ubicacion": ubicacion})

    sugerida = sugerencia_completa["ubicacion"]
    assert carta["ubicacion"]["calle"] == sugerida["calle"]
    assert carta["ubicacion"]["altura"] == {"origen": "operador", "valor": 1548}
    assert carta["ubicacion"]["esquinas"] == [
        sugerida["esquinas"][0],
        {"origen": "operador", "valor": "Uruguay"},
    ]


def test_reescribir_lo_mismo_con_otras_mayusculas_o_tildes_no_es_un_cambio(sugerencia_completa):
    ubicacion = {"calle": " av corrientes ", "altura": 1540, "esquinas": ["PARANA", "montevideo"]}

    carta = derivar(sugerencia_completa, {"prioridad": "P1", "ubicacion": ubicacion})

    sugerida = sugerencia_completa["ubicacion"]
    assert carta["ubicacion"]["calle"] == sugerida["calle"]
    assert carta["ubicacion"]["altura"] == sugerida["altura"]
    assert carta["ubicacion"]["esquinas"] == [sugerida["esquinas"][1], sugerida["esquinas"][0]]


def test_vaciar_lo_sugerido_queda_como_decision_del_operador_no_como_falta(sugerencia_completa):
    ubicacion = {"calle": "Av. Corrientes", "altura": None, "esquinas": []}

    carta = derivar(sugerencia_completa, {"prioridad": "P1", "ubicacion": ubicacion})

    assert carta["ubicacion"]["altura"] == {"origen": "operador", "valor": None}
    assert carta["ubicacion"]["esquinas"] == []


def test_lo_que_faltaba_y_el_operador_no_completa_sigue_faltando(sugerencia_completa):
    sugerencia_completa["ubicacion"]["altura"] = {"origen": "falta"}
    ubicacion = {"calle": "Av. Corrientes", "altura": None, "esquinas": ["Montevideo", "Paraná"]}

    carta = derivar(sugerencia_completa, {"prioridad": "P1", "ubicacion": ubicacion})

    assert carta["ubicacion"]["altura"] == {"origen": "falta"}


def test_elegir_el_mismo_tipo_que_se_sugirio_no_lo_vuelve_del_operador(sugerencia_completa):
    mismo = {"categoria": "INCENDIO_RESCATE", "subtipo": "SFX-001"}

    carta = derivar(sugerencia_completa, {"prioridad": "P1", "tipo_hecho": mismo})

    assert carta["tipo_hecho"] == sugerencia_completa["tipo_hecho"]
    assert carta["subtipo"] == sugerencia_completa["subtipo"]
    assert carta["checklist"] == sugerencia_completa["checklist"]


def test_sin_los_datos_obligatorios_no_hay_carta(sugerencia_completa):
    with pytest.raises(flujo.FaltanDatos) as error:
        derivar(sugerencia_completa, {})
    assert error.value.campos == ["prioridad"]

    sin_nada = flujo.analizar([Turno(**turno) for turno in TURNOS]).model_dump(mode="json")
    with pytest.raises(flujo.FaltanDatos) as error:
        derivar(sin_nada, {"tipo_hecho": {"categoria": "ACCIDENTE_VIAL", "subtipo": None}})
    assert error.value.campos == ["calle", "prioridad"]


def test_confirmar_sin_cambios_una_sugerencia_completa_la_deja_tal_cual(sugerencia_completa):
    sugerencia_completa["prioridad"] = {"origen": "inferido", "valor": "P1", "fuente": "reglas"}

    carta = derivar(sugerencia_completa, {})

    assert carta == {
        **sugerencia_completa,
        "llamada_id": "abc",
        "derivada_en": carta["derivada_en"],
    }


def test_corregir_una_enie_es_un_cambio(sugerencia_completa):
    sugerencia_completa["ubicacion"]["calle"]["valor"] = "Cañada"
    ubicacion = {"calle": "Canada", "altura": 1540, "esquinas": []}

    carta = derivar(sugerencia_completa, {"prioridad": "P1", "ubicacion": ubicacion})

    assert carta["ubicacion"]["calle"] == {"origen": "operador", "valor": "Canada"}


# ---------- El subtipo, el checklist y las instrucciones ----------


def protocolo(subtipo: str) -> dict:
    return next(
        p for p in catalogo.cargar().model_dump(mode="json")["protocolos"] if p["id"] == subtipo
    )


def pendientes(subtipo: str) -> list[dict]:
    return [
        {"id": q["id"], "pregunta": q["texto"], "respondida": False, "cita": None}
        for q in protocolo(subtipo)["preguntas"]
    ]


def test_si_el_operador_elige_el_subtipo_la_carta_lleva_su_protocolo_textual():
    sin_nada = flujo.analizar([Turno(**turno) for turno in TURNOS]).model_dump(mode="json")
    ajustes = {
        "prioridad": "P1",
        "ubicacion": {"calle": "Av. Rivadavia", "altura": None, "esquinas": []},
        "tipo_hecho": {"categoria": "INCENDIO_RESCATE", "subtipo": "SFX-025"},
    }

    carta = derivar(sin_nada, ajustes)

    assert carta["tipo_hecho"] == {"origen": "operador", "valor": "INCENDIO_RESCATE"}
    assert carta["subtipo"] == {"origen": "operador", "valor": "SFX-025"}
    assert carta["checklist"] == pendientes("SFX-025")
    assert carta["instrucciones"] == [
        {
            "id": "SFX-025-I1",
            "texto": "NO ARROJAR AGUA COMÚN. El agua puede reaccionar violentamente con el litio. "
            "Evacuar el local inmediatamente y cerrar la persiana para frenar la dispersión del "
            "humo fluorado.",
        }
    ]


def test_si_el_operador_cambia_el_subtipo_no_se_arrastra_nada_del_anterior(sugerencia_completa):
    otro = {"categoria": "INCENDIO_RESCATE", "subtipo": "SFX-002"}

    carta = derivar(sugerencia_completa, {"prioridad": "P3", "tipo_hecho": otro})

    assert carta["tipo_hecho"] == sugerencia_completa["tipo_hecho"]
    assert carta["subtipo"] == {"origen": "operador", "valor": "SFX-002"}
    assert carta["checklist"] == pendientes("SFX-002")
    assert carta["instrucciones"] == protocolo("SFX-002")["instrucciones"]


def test_si_el_operador_cambia_la_categoria_y_no_elige_subtipo_la_carta_queda_sin_protocolo(
    sugerencia_completa,
):
    otra = {"categoria": "ACCIDENTE_VIAL", "subtipo": None}

    carta = derivar(sugerencia_completa, {"prioridad": "P2", "tipo_hecho": otra})

    assert carta["tipo_hecho"] == {"origen": "operador", "valor": "ACCIDENTE_VIAL"}
    assert carta["subtipo"] == {"origen": "operador", "valor": None}
    assert carta["checklist"] == []
    assert carta["instrucciones"] == []


@pytest.mark.parametrize(
    "tipo",
    [
        {"categoria": "ACCIDENTE_VIAL", "subtipo": "SFX-001"},
        {"categoria": "INCENDIO_RESCATE", "subtipo": "SFX-999"},
        {"categoria": "NO_DETERMINADA", "subtipo": "SFX-001"},
    ],
)
def test_un_subtipo_que_no_existe_o_es_de_otra_categoria_no_se_acepta(sugerencia_completa, tipo):
    with pytest.raises(SubtipoInvalido):
        derivar(sugerencia_completa, {"prioridad": "P1", "tipo_hecho": tipo})


def test_los_textos_de_la_carta_salen_del_catalogo_y_no_de_la_sugerencia(sugerencia_completa):
    sugerencia_completa["checklist"].append(
        {"id": "inventada", "pregunta": "¿De qué color es el humo?", "respondida": False}
    )
    sugerencia_completa["instrucciones"] = [
        {"id": "inventada", "texto": "Apagar el fuego con agua."}
    ]

    carta = derivar(sugerencia_completa, {"prioridad": "P1"})

    respondida = {**pendientes("SFX-001")[0], "respondida": True}
    respondida["cita"] = {"turno": 0, "texto": "adentro quedó el cocinero"}
    assert carta["checklist"] == [respondida, *pendientes("SFX-001")[1:]]
    assert carta["instrucciones"] == protocolo("SFX-001")["instrucciones"]


def test_una_respuesta_no_se_conserva_si_la_pregunta_no_es_la_del_catalogo(sugerencia_completa):
    sugerencia_completa["checklist"][0]["pregunta"] = "¿Hay alguien adentro, más o menos?"

    carta = derivar(sugerencia_completa, {"prioridad": "P1"})

    assert carta["checklist"] == pendientes("SFX-001")


def test_una_cita_no_pasa_a_la_pregunta_de_otro_subtipo(sugerencia_completa):
    # La sugerencia es del subtipo 002 pero trae, por error, una respuesta con el identificador de
    # una pregunta del 001. Si el operador elige el 001, esa cita no puede quedar como su respuesta.
    sugerencia_completa["subtipo"]["valor"] = "SFX-002"
    sugerencia_completa["checklist"] = [
        {
            "id": "SFX-001-Q1",
            "pregunta": "¿Hay personas atrapadas en el interior?",
            "respondida": True,
            "cita": {"turno": 0, "texto": "se prendió fuego la campana"},
        }
    ]
    elegido = {"categoria": "INCENDIO_RESCATE", "subtipo": "SFX-001"}

    carta = derivar(sugerencia_completa, {"prioridad": "P1", "tipo_hecho": elegido})

    assert carta["checklist"] == pendientes("SFX-001")


def test_un_identificador_de_subtipo_se_compara_exacto(sugerencia_completa):
    sugerencia_completa["subtipo"]["valor"] = "sfx-001"
    sugerencia_completa["checklist"] = []
    corregido = {"categoria": "INCENDIO_RESCATE", "subtipo": "SFX-001"}

    carta = derivar(sugerencia_completa, {"prioridad": "P1", "tipo_hecho": corregido})

    assert carta["subtipo"] == {"origen": "operador", "valor": "SFX-001"}
    assert carta["checklist"] == pendientes("SFX-001")


# ---------- La sugerencia se ajusta al catálogo antes de guardarse ----------


def ajustar(sugerencia: dict) -> dict:
    ajustada = flujo.ajustar_al_catalogo(Sugerencia.model_validate(sugerencia))
    return ajustada.model_dump(mode="json")


def test_una_sugerencia_que_ya_sigue_al_catalogo_no_cambia(sugerencia_completa):
    assert ajustar(sugerencia_completa) == sugerencia_completa


def test_de_una_sugerencia_se_quita_lo_que_no_es_del_catalogo(sugerencia_completa):
    sugerencia_completa["checklist"] = [
        {"id": "inventada", "pregunta": "¿De qué color es el humo?", "respondida": False}
    ]
    sugerencia_completa["instrucciones"] = [
        {"id": "inventada", "texto": "Apagar el fuego con agua."}
    ]

    ajustada = ajustar(sugerencia_completa)

    assert ajustada["checklist"] == pendientes("SFX-001")
    assert ajustada["instrucciones"] == protocolo("SFX-001")["instrucciones"]


@pytest.mark.parametrize(
    ("categoria", "subtipo"),
    [("INCENDIO_RESCATE", "SFX-999"), ("ACCIDENTE_VIAL", "SFX-001"), ("NO_DETERMINADA", "SFX-001")],
)
def test_un_subtipo_sugerido_que_el_catalogo_no_respalda_queda_como_faltante(
    sugerencia_completa, categoria, subtipo
):
    sugerencia_completa["tipo_hecho"]["valor"] = categoria
    sugerencia_completa["subtipo"]["valor"] = subtipo

    ajustada = ajustar(sugerencia_completa)

    assert ajustada["subtipo"] == {"origen": "falta"}
    assert ajustada["checklist"] == []
    assert ajustada["instrucciones"] == []
    assert ajustada["ubicacion"] == sugerencia_completa["ubicacion"]
