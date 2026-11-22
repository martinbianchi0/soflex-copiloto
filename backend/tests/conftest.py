import copy

import pytest
from fastapi.testclient import TestClient

from copiloto.config import Configuracion
from copiloto.main import crear_app

TEXTO = (
    "Hola, por favor manden a los bomberos ya! En la pizzería de Av. Corrientes 1540 casi "
    "Montevideo, se prendió fuego la campana de la cocina y se está metiendo el humo negro al "
    "salón, la gente salió corriendo a la calle pero adentro quedó el cocinero!"
)
TURNOS = [{"texto": TEXTO}]

# Una sugerencia con todos los orígenes, como las que van a armar los intérpretes. El subtipo, las
# preguntas y la instrucción son los del catálogo.
_SUGERENCIA_COMPLETA = {
    "ubicacion": {
        "calle": {
            "origen": "dicho",
            "valor": "Av. Corrientes",
            "cita": {"turno": 0, "texto": "Av. Corrientes 1540"},
        },
        "altura": {
            "origen": "dicho",
            "valor": 1540,
            "cita": {"turno": 0, "texto": "Corrientes 1540"},
        },
        "esquinas": [
            {
                "origen": "dicho",
                "valor": "Montevideo",
                "cita": {"turno": 0, "texto": "casi Montevideo"},
            },
            {"origen": "inferido", "valor": "Paraná", "fuente": "callejero"},
        ],
    },
    "tipo_hecho": {"origen": "inferido", "valor": "INCENDIO_RESCATE", "fuente": "reglas"},
    "subtipo": {"origen": "inferido", "valor": "SFX-001", "fuente": "reglas"},
    "prioridad": {"origen": "falta"},
    "checklist": [
        {
            "id": "SFX-001-Q1",
            "pregunta": "¿Hay personas atrapadas en el interior?",
            "respondida": True,
            "cita": {"turno": 0, "texto": "adentro quedó el cocinero"},
        },
        {
            "id": "SFX-001-Q2",
            "pregunta": "¿Hay garrafas o cañería de gas activa?",
            "respondida": False,
            "cita": None,
        },
        {
            "id": "SFX-001-Q3",
            "pregunta": "¿Hay inmuebles linderos afectados?",
            "respondida": False,
            "cita": None,
        },
    ],
    "instrucciones": [
        {
            "id": "SFX-001-I1",
            "texto": "No reingresar al local por ningún motivo. Mantener a los peatones en la "
            "vereda de enfrente y cortar el tránsito vehicular preventivamente.",
        }
    ],
}


@pytest.fixture
def sugerencia_completa():
    return copy.deepcopy(_SUGERENCIA_COMPLETA)


@pytest.fixture
def configuracion(tmp_path):
    return Configuracion(sqlite_path=tmp_path / "llamadas.sqlite")


@pytest.fixture
def cliente(configuracion):
    with TestClient(crear_app(configuracion)) as cliente:
        yield cliente
