import pytest
from conftest import TURNOS
from fastapi.testclient import TestClient

from copiloto import flujo
from copiloto.esquemas import Sugerencia
from copiloto.llamadas import _hilo
from copiloto.main import crear_app

LLAMADA = {"turnos": TURNOS}
UBICACION = {"calle": "Av. Corrientes", "altura": 1540, "esquinas": ["Montevideo", "Paraná"]}
COMPLETOS = {"prioridad": "P2", "tipo_hecho": "INCENDIO_RESCATE", "ubicacion": UBICACION}


def iniciar(cliente) -> str:
    return cliente.post("/api/llamadas", json=LLAMADA).json()["llamada_id"]


def derivar(cliente, llamada_id: str, ajustes: dict):
    return cliente.post(f"/api/llamadas/{llamada_id}/derivar", json={"ajustes": ajustes})


def test_iniciar_una_llamada_devuelve_la_sugerencia_y_queda_esperando(cliente):
    respuesta = cliente.post("/api/llamadas", json=LLAMADA)

    assert respuesta.status_code == 201
    llamada = respuesta.json()
    assert llamada["estado"] == "esperando_operador"
    assert llamada["turnos"] == TURNOS
    assert llamada["sugerencia"] == {
        "ubicacion": {"calle": {"origen": "falta"}, "altura": {"origen": "falta"}, "esquinas": []},
        "tipo_hecho": {"origen": "inferido", "valor": "NO_DETERMINADA", "fuente": "reglas"},
        "prioridad": {"origen": "falta"},
        "checklist": [],
        "instrucciones": [],
    }
    assert llamada["carta"] is None


def test_cada_llamada_se_consulta_por_su_identificador(cliente):
    primera = cliente.post("/api/llamadas", json=LLAMADA).json()
    segunda = cliente.post("/api/llamadas", json={"turnos": [{"texto": "Otra llamada."}]}).json()

    respuesta = cliente.get(f"/api/llamadas/{primera['llamada_id']}")

    assert respuesta.status_code == 200
    assert respuesta.json() == primera
    assert cliente.get(f"/api/llamadas/{segunda['llamada_id']}").json() == segunda


def test_derivar_devuelve_la_carta_con_lo_que_completo_el_operador(cliente):
    llamada_id = iniciar(cliente)

    respuesta = derivar(cliente, llamada_id, COMPLETOS)

    assert respuesta.status_code == 200
    llamada = respuesta.json()
    assert llamada["estado"] == "derivada"
    carta = llamada["carta"]
    assert carta.pop("derivada_en").endswith("Z")
    assert carta == {
        "llamada_id": llamada_id,
        "ubicacion": {
            "calle": {"origen": "operador", "valor": "Av. Corrientes"},
            "altura": {"origen": "operador", "valor": 1540},
            "esquinas": [
                {"origen": "operador", "valor": "Montevideo"},
                {"origen": "operador", "valor": "Paraná"},
            ],
        },
        "tipo_hecho": {"origen": "operador", "valor": "INCENDIO_RESCATE"},
        "prioridad": {"origen": "operador", "valor": "P2"},
        "checklist": [],
        "instrucciones": [],
    }


def test_la_api_devuelve_cada_dato_con_su_origen_y_su_cita(
    configuracion, monkeypatch, sugerencia_completa
):
    monkeypatch.setattr(flujo, "analizar", lambda _: Sugerencia.model_validate(sugerencia_completa))
    with TestClient(crear_app(configuracion)) as cliente:
        creada = cliente.post("/api/llamadas", json=LLAMADA).json()
        derivada = derivar(cliente, creada["llamada_id"], {"prioridad": "P1"}).json()

    assert creada["sugerencia"] == sugerencia_completa
    carta = derivada["carta"]
    assert carta.pop("derivada_en").endswith("Z")
    assert carta == {
        **sugerencia_completa,
        "prioridad": {"origen": "operador", "valor": "P1"},
        "llamada_id": creada["llamada_id"],
    }


def test_la_api_distingue_lo_que_el_operador_vacio_de_lo_que_nunca_se_dijo(
    configuracion, monkeypatch, sugerencia_completa
):
    monkeypatch.setattr(flujo, "analizar", lambda _: Sugerencia.model_validate(sugerencia_completa))
    sin_altura = {"calle": "Av. Corrientes", "altura": None, "esquinas": []}
    with TestClient(crear_app(configuracion)) as cliente:
        llamada_id = cliente.post("/api/llamadas", json=LLAMADA).json()["llamada_id"]
        carta = derivar(cliente, llamada_id, {"prioridad": "P1", "ubicacion": sin_altura}).json()

    assert carta["carta"]["ubicacion"]["altura"] == {"origen": "operador", "valor": None}
    assert carta["carta"]["ubicacion"]["esquinas"] == []


def test_una_calle_invisible_no_alcanza_para_derivar(cliente):
    llamada_id = iniciar(cliente)
    invisible = {"calle": "\u200b", "altura": None, "esquinas": []}

    rechazo = derivar(cliente, llamada_id, {"prioridad": "P2", "ubicacion": invisible})

    assert rechazo.status_code == 422
    assert cliente.get(f"/api/llamadas/{llamada_id}").json()["estado"] == "esperando_operador"


def test_un_error_de_validacion_no_devuelve_lo_que_mando_el_cliente(cliente):
    rechazo = cliente.post(
        "/api/llamadas",
        content=b'{"turnos":[{"texto":"\\ud800"}]}',
        headers={"Content-Type": "application/json"},
    )

    assert rechazo.status_code == 422
    assert all(set(error) == {"type", "loc", "msg"} for error in rechazo.json()["detail"])


def test_sin_los_datos_obligatorios_devuelve_422_y_la_llamada_sigue_esperando(cliente):
    llamada_id = iniciar(cliente)

    rechazo = cliente.post(f"/api/llamadas/{llamada_id}/derivar", json={})

    assert rechazo.status_code == 422
    assert [error["loc"] for error in rechazo.json()["detail"]] == [
        ["ajustes", "calle"],
        ["ajustes", "prioridad"],
    ]
    assert cliente.get(f"/api/llamadas/{llamada_id}").json()["estado"] == "esperando_operador"
    assert derivar(cliente, llamada_id, COMPLETOS).status_code == 200


def test_derivar_dos_veces_devuelve_409_y_no_cambia_la_carta(cliente):
    llamada_id = iniciar(cliente)
    primera = derivar(cliente, llamada_id, COMPLETOS).json()

    segunda = derivar(cliente, llamada_id, {**COMPLETOS, "prioridad": "P4"})

    assert segunda.status_code == 409
    assert cliente.get(f"/api/llamadas/{llamada_id}").json() == primera


def test_una_llamada_que_no_existe_devuelve_404(cliente):
    assert cliente.get("/api/llamadas/no-existe").status_code == 404
    assert derivar(cliente, "no-existe", COMPLETOS).status_code == 404


@pytest.mark.parametrize(
    "ajustes",
    [
        {**COMPLETOS, "prioridad": "P9"},
        {**COMPLETOS, "campo_inventado": "x"},
        {**COMPLETOS, "prioridad": None},
        {**COMPLETOS, "ubicacion": {"calle": "Av. Corrientes"}},
        {**COMPLETOS, "ubicacion": {**UBICACION, "altura": 1540.0}},
        {**COMPLETOS, "ubicacion": {**UBICACION, "altura": 10**100}},
        {**COMPLETOS, "ubicacion": {**UBICACION, "esquinas": ["Paraná", "paraná"]}},
    ],
)
def test_un_ajuste_invalido_devuelve_422_y_la_llamada_sigue_esperando(cliente, ajustes):
    llamada_id = iniciar(cliente)

    rechazo = derivar(cliente, llamada_id, ajustes)

    assert rechazo.status_code == 422
    assert cliente.get(f"/api/llamadas/{llamada_id}").json()["estado"] == "esperando_operador"
    valida = derivar(cliente, llamada_id, {**COMPLETOS, "prioridad": "P3"})
    assert valida.status_code == 200
    assert valida.json()["carta"]["prioridad"]["valor"] == "P3"


def test_una_ubicacion_sin_altura_ni_esquinas_es_valida(cliente):
    llamada_id = iniciar(cliente)
    ubicacion = {"calle": "Plaza de Mayo", "altura": None, "esquinas": []}

    respuesta = derivar(cliente, llamada_id, {"prioridad": "P3", "ubicacion": ubicacion})

    assert respuesta.status_code == 200
    assert respuesta.json()["carta"]["ubicacion"] == {
        "calle": {"origen": "operador", "valor": "Plaza de Mayo"},
        "altura": {"origen": "falta"},
        "esquinas": [],
    }


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
        derivada = derivar(despues, llamada_id, COMPLETOS)

    assert consulta["estado"] == "esperando_operador"
    assert derivada.status_code == 200
    assert derivada.json()["estado"] == "derivada"


def test_la_descripcion_de_la_api_se_genera_con_los_esquemas(cliente):
    descripcion = cliente.get("/api/openapi.json")

    assert descripcion.status_code == 200
    assert "Llamada" in descripcion.json()["components"]["schemas"]


def test_una_llamada_guardada_con_otro_formato_se_informa_como_ilegible(cliente):
    llamada_id = iniciar(cliente)
    de_otra_version = {
        "ubicacion": {"calle": "Av. Corrientes", "altura": 1540, "esquinas": ["Montevideo"]},
        "tipo_hecho": "Incendio",
        "prioridad": "P2",
    }
    grafo = cliente.app.state.llamadas._grafo
    grafo.update_state(_hilo(llamada_id), {"sugerencia": de_otra_version})

    consulta = cliente.get(f"/api/llamadas/{llamada_id}")
    intento = derivar(cliente, llamada_id, {"prioridad": "P1"})

    assert consulta.status_code == intento.status_code == 500
    assert "formato" in consulta.json()["detail"]
    assert "Corrientes" not in consulta.text
