import copy

import pytest
from fastapi.testclient import TestClient

from copiloto.config import Configuracion
from copiloto.main import crear_app

TEXTO = (
    "Hola, por favor manden a los bomberos ya! En la pizzería de Av. Corrientes 1540 casi "
    "Montevideo, se prendió fuego la campana de la cocina."
)
TURNOS = [{"texto": TEXTO}]

# Una sugerencia con todos los orígenes, como las que van a armar los intérpretes.
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
    "prioridad": {"origen": "falta"},
    "checklist": [
        {
            "id": "atrapados",
            "pregunta": "¿Hay personas atrapadas?",
            "respondida": False,
            "cita": None,
        },
        {
            "id": "que-se-quema",
            "pregunta": "¿Qué se está quemando?",
            "respondida": True,
            "cita": {"turno": 0, "texto": "se prendió fuego la campana de la cocina"},
        },
    ],
    "instrucciones": [{"id": "no-reingresar", "texto": "No reingresar al local."}],
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
