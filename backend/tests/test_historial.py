from datetime import UTC, datetime

import pytest
from conftest import TURNOS

from copiloto import flujo, historial
from copiloto.esquemas import Ajustes, Llamada, Sugerencia
from copiloto.historial import PuntoGuardado

AHORA = datetime(2026, 11, 22, 6, 45, tzinfo=UTC)
UBICACION = {"calle": "av corrientes", "altura": 1540, "esquinas": ["Montevideo", "Parana"]}


@pytest.fixture
def sugerencia(sugerencia_completa):
    sugerencia_completa["prioridad"] = {"origen": "inferido", "valor": "P1", "fuente": "reglas"}
    # El tipo de hecho propuesto por el modelo es lo que distingue su sugerencia de un rescate.
    tipo = sugerencia_completa["tipo_hecho"]["valor"]
    sugerencia_completa["tipo_hecho"] = {"origen": "inferido", "valor": tipo, "fuente": "modelo"}
    return Sugerencia.model_validate(sugerencia_completa)


@pytest.mark.parametrize("con_escrituras", [False, True])
def test_los_eventos_salen_de_los_puntos_guardados(sugerencia, con_escrituras):
    def punto(segundo, nodo, valores):
        metadatos = {"source": "loop", "step": segundo}
        if con_escrituras:
            metadatos["writes"] = {nodo: valores}
        return PuntoGuardado(AHORA.replace(second=segundo).isoformat(), valores, metadatos)

    inicial = {"turnos": TURNOS}
    regla = sugerencia.model_dump(mode="json")
    regla["avisos"] = [
        {"codigo": "direccion_no_cierra", "mensaje": "La altura no cierra."},
        {"codigo": "cruce_sin_confirmar", "mensaje": "Hay que confirmar el cruce."},
    ]
    reglas = {**inicial, "sugerencia": regla}
    modelo = {**inicial, "sugerencia": sugerencia.model_dump(mode="json")}
    carta = flujo.derivar("abc", sugerencia, Ajustes(), AHORA)
    confirmada = {**modelo, "ajustes": {}}
    derivada = {**confirmada, "carta": carta.model_dump(mode="json")}
    llamada = Llamada.model_validate(
        {
            "llamada_id": "abc",
            "estado": "derivada",
            "turnos": TURNOS,
            "sugerencia": sugerencia,
            "carta": carta,
        }
    )
    puntos = [
        punto(0, "__start__", {}),
        punto(1, "__start__", inicial),
        punto(2, "analizar", reglas),
        punto(3, "consultar_modelo", reglas),
        punto(4, "consultar_modelo", modelo),
        punto(5, "esperar_operador", confirmada),
        punto(6, "derivar", derivada),
    ]

    resultado = historial.armar(llamada, puntos[::-1])

    assert [(evento.tipo, evento.detalle) for evento in resultado.eventos] == [
        ("recibida", "Llamada recibida, con 1 turno."),
        ("sugerencia_reglas", "Sugerencia de las reglas, con 2 avisos."),
        ("sugerencia_modelo", "Sugerencia del modelo, sin avisos."),
        ("ajustes_operador", "El operador confirmó sin cambios."),
        ("derivada", "Carta de Llamada derivada."),
    ]
    assert [evento.cuando.second for evento in resultado.eventos] == [1, 2, 4, 5, 6]
    assert resultado.cambios == []


def test_reescribir_los_mismos_datos_no_es_un_cambio(sugerencia):
    ajustes = Ajustes.model_validate(
        {
            "ubicacion": UBICACION,
            "prioridad": "P1",
            "checklist": [{"id": "SFX-001-Q1", "respondida": True}],
        }
    )
    carta = flujo.derivar("abc", sugerencia, ajustes, AHORA)

    assert historial.comparar(sugerencia, carta) == []


def test_el_historial_compara_los_valores_que_quedaron_en_la_carta(sugerencia):
    ajustes = Ajustes.model_validate(
        {
            "ubicacion": {**UBICACION, "altura": 1548, "esquinas": ["Montevideo"]},
            "prioridad": "P2",
            "checklist": [{"id": "SFX-001-Q2", "respondida": True}],
        }
    )
    carta = flujo.derivar("abc", sugerencia, ajustes, AHORA)
    esquinas = sugerencia.ubicacion.model_dump(mode="json")["esquinas"]

    assert [cambio.model_dump(mode="json") for cambio in historial.comparar(sugerencia, carta)] == [
        {
            "campo": "altura",
            "sugerido": {
                "origen": "dicho",
                "valor": 1540,
                "cita": {"turno": 0, "texto": "Corrientes 1540"},
            },
            "final": {"origen": "operador", "valor": 1548},
        },
        {"campo": "esquinas", "sugerido": esquinas, "final": esquinas[:1]},
        {
            "campo": "prioridad",
            "sugerido": {"origen": "inferido", "valor": "P1", "fuente": "reglas"},
            "final": {"origen": "operador", "valor": "P2"},
        },
        {
            "campo": "pregunta SFX-001-Q2",
            "sugerido": {"respondida": False, "propuesta": False},
            "final": {"respondida": True, "propuesta": False},
        },
    ]


def test_el_historial_incluye_la_esquina_que_la_carta_descarta(sugerencia):
    ajustes = Ajustes.model_validate({"ubicacion": {**UBICACION, "altura": 300}})
    carta = flujo.derivar("abc", sugerencia, ajustes, AHORA)

    cambios = historial.comparar(sugerencia, carta)

    assert [cambio.campo for cambio in cambios] == ["altura", "esquinas"]
    assert cambios[1].sugerido == sugerencia.ubicacion.esquinas
    assert cambios[1].final == sugerencia.ubicacion.esquinas[:1]


def test_del_protocolo_nuevo_solo_cuentan_las_preguntas_que_se_marcaron(sugerencia):
    ajustes = Ajustes.model_validate(
        {
            "tipo_hecho": {"categoria": "ACCIDENTE_VIAL", "subtipo": "SFX-005"},
            "checklist": [{"id": "SFX-005-Q1", "respondida": True}],
        }
    )
    carta = flujo.derivar("abc", sugerencia, ajustes, AHORA)

    cambios = historial.comparar(sugerencia, carta)

    assert [cambio.campo for cambio in cambios] == ["tipo_hecho", "subtipo", "pregunta SFX-005-Q1"]
    assert cambios[-1].sugerido.model_dump() == {"respondida": False, "propuesta": False}
    assert cambios[-1].final.model_dump() == {"respondida": True, "propuesta": False}
