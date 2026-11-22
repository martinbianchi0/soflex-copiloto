import pytest
from fastapi.testclient import TestClient

from copiloto.flujo import SUGERENCIA_FIJA
from copiloto.main import crear_app

LLAMADA = {"turnos": [{"texto": "Se prendió fuego la cocina de la pizzería de Corrientes 1540."}]}


def iniciar(cliente) -> str:
    return cliente.post("/api/llamadas", json=LLAMADA).json()["llamada_id"]


def test_iniciar_una_llamada_devuelve_la_sugerencia_y_queda_esperando(cliente):
    respuesta = cliente.post("/api/llamadas", json=LLAMADA)

    assert respuesta.status_code == 201
    llamada = respuesta.json()
    assert llamada["estado"] == "esperando_operador"
    assert llamada["turnos"] == LLAMADA["turnos"]
    assert llamada["sugerencia"] == SUGERENCIA_FIJA
    assert llamada["carta"] is None


def test_cada_llamada_se_consulta_por_su_identificador(cliente):
    primera = cliente.post("/api/llamadas", json=LLAMADA).json()
    segunda = cliente.post("/api/llamadas", json={"turnos": [{"texto": "Otra llamada."}]}).json()

    respuesta = cliente.get(f"/api/llamadas/{primera['llamada_id']}")

    assert respuesta.status_code == 200
    assert respuesta.json() == primera
    assert cliente.get(f"/api/llamadas/{segunda['llamada_id']}").json() == segunda


def test_derivar_devuelve_la_carta_con_los_ajustes_del_operador(cliente):
    llamada_id = iniciar(cliente)
    ubicacion = {"calle": "Av. Corrientes", "altura": 1548, "esquinas": ["Montevideo", "Paraná"]}

    respuesta = cliente.post(
        f"/api/llamadas/{llamada_id}/derivar",
        json={"ajustes": {"prioridad": "P2", "ubicacion": ubicacion}},
    )

    assert respuesta.status_code == 200
    llamada = respuesta.json()
    assert llamada["estado"] == "derivada"
    assert llamada["carta"] == {
        "llamada_id": llamada_id,
        "ubicacion": ubicacion,
        "tipo_hecho": SUGERENCIA_FIJA["tipo_hecho"],
        "prioridad": "P2",
        "ajustado_por_operador": ["prioridad", "ubicacion"],
    }


def test_derivar_sin_ajustes_confirma_la_sugerencia(cliente):
    llamada_id = iniciar(cliente)

    respuesta = cliente.post(f"/api/llamadas/{llamada_id}/derivar", json={})

    assert respuesta.status_code == 200
    carta = respuesta.json()["carta"]
    assert carta == {"llamada_id": llamada_id, **SUGERENCIA_FIJA, "ajustado_por_operador": []}


def test_derivar_dos_veces_devuelve_409_y_no_cambia_la_carta(cliente):
    llamada_id = iniciar(cliente)
    primera = cliente.post(f"/api/llamadas/{llamada_id}/derivar", json={}).json()

    segunda = cliente.post(
        f"/api/llamadas/{llamada_id}/derivar", json={"ajustes": {"prioridad": "P4"}}
    )

    assert segunda.status_code == 409
    assert cliente.get(f"/api/llamadas/{llamada_id}").json() == primera


def test_una_llamada_que_no_existe_devuelve_404(cliente):
    assert cliente.get("/api/llamadas/no-existe").status_code == 404
    assert cliente.post("/api/llamadas/no-existe/derivar", json={}).status_code == 404


@pytest.mark.parametrize(
    "ajustes",
    [
        {"prioridad": "P9"},
        {"campo_inventado": "x"},
        {"tipo_hecho": "   "},
        {"prioridad": None},
        {"ubicacion": None},
        {"ubicacion": {"calle": "Av. Corrientes"}},
        {"ubicacion": {"calle": "Av. Corrientes", "altura": 0, "esquinas": []}},
        {"ubicacion": {"calle": "Av. Corrientes", "altura": "1540", "esquinas": []}},
        {"ubicacion": {"calle": "Av. Corrientes", "altura": 1540.0, "esquinas": []}},
        {"ubicacion": {"calle": "Av. Corrientes", "altura": True, "esquinas": []}},
        {"ubicacion": {"calle": "Av. Corrientes", "altura": 10**100, "esquinas": []}},
        {"ubicacion": {"calle": "Av. Corrientes", "altura": None, "esquinas": ["a", "b", "c"]}},
        {
            "ubicacion": {
                "calle": "Av. Corrientes",
                "altura": None,
                "esquinas": ["Paraná", "paraná"],
            }
        },
        {"ubicacion": {"calle": "Paraná", "altura": None, "esquinas": [" PARANÁ "]}},
        {"tipo_hecho": "x" * 201},
    ],
)
def test_un_ajuste_invalido_devuelve_422_y_la_llamada_sigue_esperando(cliente, ajustes):
    llamada_id = iniciar(cliente)

    rechazo = cliente.post(f"/api/llamadas/{llamada_id}/derivar", json={"ajustes": ajustes})

    assert rechazo.status_code == 422
    assert cliente.get(f"/api/llamadas/{llamada_id}").json()["estado"] == "esperando_operador"
    valida = cliente.post(
        f"/api/llamadas/{llamada_id}/derivar", json={"ajustes": {"prioridad": "P3"}}
    )
    assert valida.status_code == 200
    assert valida.json()["carta"]["prioridad"] == "P3"


def test_una_ubicacion_sin_altura_ni_esquinas_es_valida(cliente):
    llamada_id = iniciar(cliente)
    ubicacion = {"calle": "Plaza de Mayo", "altura": None, "esquinas": []}

    respuesta = cliente.post(
        f"/api/llamadas/{llamada_id}/derivar", json={"ajustes": {"ubicacion": ubicacion}}
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["carta"]["ubicacion"] == ubicacion


@pytest.mark.parametrize(
    "cuerpo",
    [
        {},
        {"turnos": []},
        {"turnos": [{"texto": "  "}]},
        {"turnos": [{"texto": "hola", "x": 1}]},
        {"turnos": [{"texto": "x" * 20_001}]},
        {"turnos": [{"texto": "hola"}] * 501},
    ],
)
def test_una_llamada_mal_armada_devuelve_422(cliente, cuerpo):
    assert cliente.post("/api/llamadas", json=cuerpo).status_code == 422


def test_una_llamada_a_medias_se_deriva_despues_de_reiniciar_el_servicio(configuracion):
    with TestClient(crear_app(configuracion)) as antes:
        llamada_id = iniciar(antes)

    with TestClient(crear_app(configuracion)) as despues:
        consulta = despues.get(f"/api/llamadas/{llamada_id}").json()
        derivada = despues.post(f"/api/llamadas/{llamada_id}/derivar", json={})

    assert consulta["estado"] == "esperando_operador"
    assert derivada.status_code == 200
    assert derivada.json()["estado"] == "derivada"
