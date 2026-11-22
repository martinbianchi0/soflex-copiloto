from datetime import UTC, datetime

import pytest
from conftest import TURNOS

from copiloto import flujo
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
    assert carta["checklist"][1]["cita"]["texto"] == "se prendió fuego la campana de la cocina"
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
    carta = derivar(sugerencia_completa, {"prioridad": "P1", "tipo_hecho": "INCENDIO_RESCATE"})

    assert carta["tipo_hecho"] == sugerencia_completa["tipo_hecho"]


def test_sin_los_datos_obligatorios_no_hay_carta(sugerencia_completa):
    with pytest.raises(flujo.FaltanDatos) as error:
        derivar(sugerencia_completa, {})
    assert error.value.campos == ["prioridad"]

    sin_nada = flujo.analizar([Turno(**turno) for turno in TURNOS]).model_dump(mode="json")
    with pytest.raises(flujo.FaltanDatos) as error:
        derivar(sin_nada, {"tipo_hecho": "ACCIDENTE_VIAL"})
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
