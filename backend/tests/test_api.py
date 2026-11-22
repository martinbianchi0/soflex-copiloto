import json
from datetime import datetime
from itertools import pairwise

import pytest
from conftest import DATOS_EMPAQUETADOS, FILAS_DATASET, REFERENCIA, TEXTO, TURNOS, TURNOS_SIN_DATOS
from fastapi.testclient import TestClient

from copiloto import ejemplos, flujo
from copiloto.esquemas import Sugerencia, Turno
from copiloto.llamadas import _hilo
from copiloto.main import crear_app
from copiloto.turnos import separar_hablantes

LLAMADA = {"turnos": TURNOS}
UBICACION = {"calle": "Av. Corrientes", "altura": 1540, "esquinas": ["Montevideo", "Paraná"]}
INCENDIO = {"categoria": "INCENDIO_RESCATE", "subtipo": None}
COMPLETOS = {"prioridad": "P2", "tipo_hecho": INCENDIO, "ubicacion": UBICACION}
EJEMPLOS_NUEVOS = {
    ejemplo["id"]: ejemplo
    for ejemplo in json.loads(
        DATOS_EMPAQUETADOS.joinpath("llamadas_de_ejemplo.json").read_text(encoding="utf-8")
    )
}


def iniciar(cliente, turnos=TURNOS) -> str:
    return cliente.post("/api/llamadas", json={"turnos": turnos}).json()["llamada_id"]


def derivar(cliente, llamada_id: str, ajustes: dict):
    return cliente.post(f"/api/llamadas/{llamada_id}/derivar", json={"ajustes": ajustes})


def test_iniciar_una_llamada_devuelve_la_sugerencia_y_queda_esperando(cliente):
    respuesta = cliente.post("/api/llamadas", json={"turnos": TURNOS_SIN_DATOS})

    assert respuesta.status_code == 201
    llamada = respuesta.json()
    assert llamada["estado"] == "esperando_operador"
    assert llamada["turnos"] == TURNOS_SIN_DATOS
    sugerencia = llamada["sugerencia"]
    assert [aviso["codigo"] for aviso in sugerencia.pop("avisos")] == ["sin_calle"]
    assert sugerencia == {
        "ubicacion": {"calle": {"origen": "falta"}, "altura": {"origen": "falta"}, "esquinas": []},
        "tipo_hecho": {"origen": "inferido", "valor": "NO_DETERMINADA", "fuente": "reglas"},
        "subtipo": {"origen": "falta"},
        "prioridad": {"origen": "falta"},
        "checklist": [],
        "instrucciones": [],
        "datos_dictados": [],
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
    alta = cliente.post("/api/llamadas", json=LLAMADA)
    assert alta.status_code == 201
    creada = alta.json()
    llamada_id = creada["llamada_id"]
    sugerencia = creada["sugerencia"]
    ubicacion = {**UBICACION, "altura": 1548, "esquinas": ["Montevideo", "Uruguay"]}
    esquinas = sugerencia["ubicacion"]["esquinas"]
    montevideo = next(esquina for esquina in esquinas if esquina["valor"] == "Montevideo")

    respuesta = derivar(cliente, llamada_id, {"prioridad": "P2", "ubicacion": ubicacion})

    assert respuesta.status_code == 200
    llamada = respuesta.json()
    assert llamada["estado"] == "derivada"
    carta = llamada["carta"]
    assert carta.pop("derivada_en").endswith("Z")
    assert carta == {
        "llamada_id": llamada_id,
        "ubicacion": {
            "calle": sugerencia["ubicacion"]["calle"],
            "altura": {"origen": "operador", "valor": 1548},
            "esquinas": [
                montevideo,
                {"origen": "operador", "valor": "Uruguay"},
            ],
        },
        "tipo_hecho": sugerencia["tipo_hecho"],
        "subtipo": sugerencia["subtipo"],
        "prioridad": {"origen": "operador", "valor": "P2"},
        "checklist": sugerencia["checklist"],
        "instrucciones": sugerencia["instrucciones"],
        "datos_dictados": [],
        "avisos": [],
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
    llamada_id = iniciar(cliente, TURNOS_SIN_DATOS)

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
    assert cliente.get("/api/llamadas/no-existe/historial").status_code == 404
    assert derivar(cliente, "no-existe", COMPLETOS).status_code == 404
    assert (
        cliente.post("/api/llamadas/no-existe/turnos", json={"turno": TURNOS[0]}).status_code == 404
    )


def test_sumar_turnos_en_mock_conserva_los_indices_y_deriva_la_ultima_sugerencia(cliente):
    turno = {"hablante": "llamante", "texto": "Hay un choque en Av. Corrientes."}
    alta = cliente.post("/api/llamadas", json={"turnos": [turno]}).json()
    ruta = f"/api/llamadas/{alta['llamada_id']}"
    pregunta = {"hablante": "operador", "texto": "¿A qué altura?"}
    respuesta = {"hablante": "llamante", "texto": "Al 1540."}

    primera = cliente.post(f"{ruta}/turnos", json={"turno": pregunta})
    segunda = cliente.post(f"{ruta}/turnos", json={"turno": respuesta})

    assert primera.status_code == segunda.status_code == 200
    ampliada = segunda.json()
    assert ampliada["estado"] == "esperando_operador"
    assert primera.json()["turnos"] == [turno, pregunta]
    assert ampliada["turnos"] == [turno, pregunta, respuesta]
    assert alta["sugerencia"]["ubicacion"]["altura"] == {"origen": "falta"}
    ubicacion = ampliada["sugerencia"]["ubicacion"]
    assert ubicacion["calle"] == alta["sugerencia"]["ubicacion"]["calle"]
    assert ubicacion["calle"]["cita"] == {"turno": 0, "texto": "Av. Corrientes"}
    assert ubicacion["altura"] == {
        "origen": "dicho",
        "valor": 1540,
        "cita": {"turno": 2, "texto": "1540"},
    }
    derivada = cliente.post(f"{ruta}/derivar", json={"ajustes": {"prioridad": "P2"}})
    assert derivada.status_code == 200
    assert derivada.json()["carta"]["ubicacion"] == ubicacion
    historial = cliente.get(f"{ruta}/historial").json()
    assert [cambio["campo"] for cambio in historial["cambios"]] == ["prioridad"]
    assert [e["detalle"] for e in historial["eventos"] if e["tipo"] == "turno_agregado"] == [
        "Se sumó un turno a la llamada: ahora tiene 2.",
        "Se sumó un turno a la llamada: ahora tiene 3.",
    ]
    rechazo = cliente.post(f"{ruta}/turnos", json={"turno": respuesta})
    assert rechazo.status_code == 409
    assert cliente.get(ruta).json() == derivada.json()


def test_sumar_un_texto_con_marcas_registra_una_vuelta_del_grafo(cliente):
    llamada_id = iniciar(
        cliente,
        [
            {"hablante": "operador", "texto": "911, ¿cuál es su emergencia?"},
            {"hablante": "llamante", "texto": "Hay un choque en Corrientes."},
            {"hablante": "operador", "texto": "Entendido."},
        ],
    )
    ruta = f"/api/llamadas/{llamada_id}"
    turno = {"texto": "Operador: ¿A qué altura? Llamante: Al 1540."}
    primer_historial = cliente.get(f"{ruta}/historial").json()["eventos"]

    ampliada = cliente.post(f"{ruta}/turnos", json={"turno": turno})
    assert ampliada.status_code == 200
    assert ampliada.json()["turnos"][3:] == [
        {"hablante": "operador", "texto": "¿A qué altura?"},
        {"hablante": "llamante", "texto": "Al 1540."},
    ]
    assert derivar(cliente, llamada_id, {"prioridad": "P2"}).status_code == 200

    eventos = cliente.get(f"{ruta}/historial").json()["eventos"]
    assert eventos[:2] == primer_historial
    assert [(evento["tipo"], evento["detalle"]) for evento in eventos] == [
        ("recibida", "Llamada recibida, con 3 turnos."),
        ("sugerencia_reglas", "Sugerencia de las reglas, con 1 aviso."),
        ("turno_agregado", "Se sumaron 2 turnos a la llamada: ahora tiene 5."),
        ("sugerencia_reglas", "Sugerencia de las reglas, sin avisos."),
        ("ajustes_operador", "El operador confirmó con 1 cambio."),
        ("derivada", "Carta de Llamada derivada."),
    ]


@pytest.mark.parametrize(
    ("turnos", "nuevo"),
    [
        pytest.param([{"texto": "a" * 20_000}] * 2 + [{"texto": "a" * 10_000}], "Hola", id="largo"),
        pytest.param([{"texto": "Hola"}] * 500, "Hola", id="cantidad"),
        pytest.param(
            [{"texto": "Hola"}] * 499, "Operador: Bien. Llamante: Sí.", id="cantidad_con_marcas"
        ),
        pytest.param([{"texto": "Hola"}], "Llamante: Sí. " * 501, id="turno_con_demasiadas_marcas"),
        pytest.param([{"texto": "Hola"}], " ", id="vacio"),
    ],
)
def test_un_turno_invalido_devuelve_422_y_deja_la_llamada_igual(cliente, turnos, nuevo):
    alta = cliente.post("/api/llamadas", json={"turnos": turnos})
    assert alta.status_code == 201
    ruta = f"/api/llamadas/{alta.json()['llamada_id']}"
    historial = cliente.get(f"{ruta}/historial").json()

    respuesta = cliente.post(f"{ruta}/turnos", json={"turno": {"texto": nuevo}})

    assert respuesta.status_code == 422
    assert cliente.get(ruta).json() == alta.json()
    assert cliente.get(f"{ruta}/historial").json() == historial


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
    llamada_id = iniciar(cliente, TURNOS_SIN_DATOS)
    ubicacion = {"calle": "Plaza de Mayo", "altura": None, "esquinas": []}

    respuesta = derivar(cliente, llamada_id, {"prioridad": "P3", "ubicacion": ubicacion})

    assert respuesta.status_code == 200
    assert respuesta.json()["carta"]["ubicacion"] == {
        "calle": {"origen": "operador", "valor": "Plaza de Mayo"},
        "altura": {"origen": "falta"},
        "esquinas": [],
    }


@pytest.mark.parametrize(
    "texto",
    [pytest.param(caso["texto"], id=caso["id"]) for caso in REFERENCIA]
    + [
        pytest.param("1234567890", id="solo_digitos"),
        pytest.param("Operador: ¿Hay fuego en Av. Corrientes 1540?", id="solo_operador"),
        pytest.param("x" * 20_000, id="veinte_mil_caracteres"),
        pytest.param("¿?!_-…", id="solo_puntuacion"),
        pytest.param("Operador: Llamante: Operador:", id="solo_marcas"),
    ],
)
def test_se_pueden_guardar_y_consultar_transcripciones_de_distintos_formatos(cliente, texto):
    alta = cliente.post("/api/llamadas", json={"turnos": [{"texto": texto}]})

    assert alta.status_code == 201
    creada = alta.json()
    consulta = cliente.get(f"/api/llamadas/{creada['llamada_id']}")
    assert consulta.status_code == 200
    assert consulta.json() == creada


def test_una_llamada_del_dataset_se_deriva_sin_cambios_con_su_protocolo(cliente):
    texto = FILAS_DATASET["SFX-001"]["transcripcion_cruda"]
    alta = cliente.post("/api/llamadas", json={"turnos": [{"texto": texto}]})

    assert alta.status_code == 201
    creada = alta.json()
    llamada_id = creada["llamada_id"]
    consulta = cliente.get(f"/api/llamadas/{llamada_id}")
    assert consulta.status_code == 200
    turnos_esperados = [
        {"hablante": "operador", "texto": "911 emergencias, ¿dónde es su urgencia?"},
        {"hablante": "llamante", "texto": TEXTO},
    ]
    assert consulta.json()["turnos"] == creada["turnos"] == turnos_esperados

    respuesta = derivar(cliente, llamada_id, {})

    assert respuesta.status_code == 200
    derivada = respuesta.json()
    assert derivada["estado"] == "derivada"
    carta = derivada["carta"]
    assert carta["llamada_id"] == llamada_id
    assert carta["ubicacion"] == creada["sugerencia"]["ubicacion"]
    for campo, valor in (
        ("tipo_hecho", "INCENDIO_RESCATE"),
        ("subtipo", "SFX-001"),
        ("prioridad", "P1"),
    ):
        assert carta[campo] == {"origen": "inferido", "valor": valor, "fuente": "dataset"}
    assert carta["checklist"] == creada["sugerencia"]["checklist"]
    assert [item for item in carta["checklist"] if item["respondida"]] == [
        {
            "id": "SFX-001-Q1",
            "pregunta": "¿Hay personas atrapadas en el interior?",
            "respondida": True,
            "cita": {"turno": 1, "texto": "adentro quedó el cocinero"},
            "del_operador": False,
        }
    ]
    assert carta["instrucciones"] == [
        {
            "id": "SFX-001-I1",
            "texto": "No reingresar al local por ningún motivo. Mantener a los peatones en la "
            "vereda de enfrente y cortar el tránsito vehicular preventivamente.",
        }
    ]
    assert cliente.get(f"/api/llamadas/{llamada_id}").json() == derivada


def test_el_historial_en_mock_usa_los_puntos_guardados_en_sqlite(cliente):
    texto = FILAS_DATASET["SFX-001"]["transcripcion_cruda"]
    llamada_id = iniciar(cliente, [{"texto": texto}])
    ruta = f"/api/llamadas/{llamada_id}/historial"
    pendiente = cliente.get(ruta)
    assert pendiente.status_code == 200
    assert pendiente.json()["cambios"] == []
    assert [evento["tipo"] for evento in pendiente.json()["eventos"]] == [
        "recibida",
        "sugerencia_reglas",
    ]

    assert derivar(cliente, llamada_id, {}).status_code == 200
    respuesta = cliente.get(ruta)

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["llamada_id"] == llamada_id
    assert cuerpo["cambios"] == []
    eventos = cuerpo["eventos"]
    assert [(evento["tipo"], evento["detalle"]) for evento in eventos] == [
        ("recibida", "Llamada recibida, con 2 turnos."),
        ("sugerencia_reglas", "Sugerencia de las reglas, sin avisos."),
        ("ajustes_operador", "El operador confirmó sin cambios."),
        ("derivada", "Carta de Llamada derivada."),
    ]
    assert eventos[:2] == pendiente.json()["eventos"]
    assert all(evento["cuando"].endswith("Z") for evento in eventos)
    horas = [datetime.fromisoformat(evento["cuando"]) for evento in eventos]
    assert all(antes < despues for antes, despues in pairwise(horas))

    grafo = cliente.app.state.llamadas._grafo
    puntos = list(reversed(list(grafo.get_state_history(_hilo(llamada_id)))))
    # El punto de entrada está vacío y el del modelo en mock conserva el estado anterior.
    assert horas == [datetime.fromisoformat(puntos[n].created_at) for n in (1, 2, 4, 5)]


def test_el_historial_devuelve_los_cambios_resueltos_de_la_carta(cliente):
    alta = cliente.post("/api/llamadas", json=LLAMADA).json()
    llamada_id = alta["llamada_id"]
    ajustes = {
        "ubicacion": {"calle": "av corrientes", "altura": 1548, "esquinas": ["Montevideo"]},
        "prioridad": "P2",
        "checklist": [{"id": "SFX-001-Q2", "respondida": True}],
    }
    derivada = derivar(cliente, llamada_id, ajustes)
    assert derivada.status_code == 200

    respuesta = cliente.get(f"/api/llamadas/{llamada_id}/historial")

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    sugerencia, carta = alta["sugerencia"], derivada.json()["carta"]
    assert cuerpo["eventos"][-2]["detalle"] == "El operador confirmó con 4 cambios."
    assert cuerpo["cambios"] == [
        {
            "campo": "altura",
            "sugerido": sugerencia["ubicacion"]["altura"],
            "final": carta["ubicacion"]["altura"],
        },
        {
            "campo": "esquinas",
            "sugerido": sugerencia["ubicacion"]["esquinas"],
            "final": carta["ubicacion"]["esquinas"],
        },
        {"campo": "prioridad", "sugerido": sugerencia["prioridad"], "final": carta["prioridad"]},
        {
            "campo": "pregunta SFX-001-Q2",
            "sugerido": {"respondida": False, "propuesta": False},
            "final": {"respondida": True, "propuesta": False},
        },
    ]


def test_derivar_con_marcas_devuelve_la_carta_con_los_cambios_en_el_checklist(cliente):
    alta = cliente.post("/api/llamadas", json=LLAMADA)
    assert alta.status_code == 201
    creada = alta.json()
    sugerencia = creada["sugerencia"]
    q1, q2, q3 = sugerencia["checklist"]
    marcas = [{"id": "SFX-001-Q1", "respondida": False}, {"id": "SFX-001-Q2", "respondida": True}]

    respuesta = derivar(cliente, creada["llamada_id"], {"checklist": marcas})

    assert respuesta.status_code == 200
    llamada = respuesta.json()
    assert llamada["estado"] == "derivada"
    assert llamada["sugerencia"] == sugerencia
    assert llamada["carta"]["checklist"] == [
        {**q1, "respondida": False, "cita": None, "del_operador": True},
        {**q2, "respondida": True, "cita": None, "del_operador": True},
        q3,
    ]
    assert cliente.get(f"/api/llamadas/{creada['llamada_id']}").json() == llamada


def test_una_marca_ajena_devuelve_422_y_se_puede_derivar_con_una_valida(cliente):
    llamada_id = iniciar(cliente)
    valida = {"id": "SFX-001-Q2", "respondida": True}
    ajena = {"id": "SFX-002-Q1", "respondida": True}

    rechazo = derivar(cliente, llamada_id, {"checklist": [valida, ajena]})

    assert rechazo.status_code == 422
    assert [error["loc"] for error in rechazo.json()["detail"]] == [["ajustes", "checklist"]]
    consulta = cliente.get(f"/api/llamadas/{llamada_id}")
    assert consulta.status_code == 200
    pendiente = consulta.json()
    assert pendiente["estado"] == "esperando_operador"
    assert pendiente["carta"] is None

    respuesta = derivar(cliente, llamada_id, {"checklist": [valida]})

    assert respuesta.status_code == 200
    llamada = respuesta.json()
    assert llamada["estado"] == "derivada"
    marcada = next(item for item in llamada["carta"]["checklist"] if item["id"] == valida["id"])
    assert marcada["respondida"] is True
    assert marcada["del_operador"] is True
    assert marcada["cita"] is None


def test_la_llamada_002_avisa_que_la_altura_no_cierra_con_las_esquinas(cliente):
    texto = FILAS_DATASET["SFX-002"]["transcripcion_cruda"]
    alta = cliente.post("/api/llamadas", json={"turnos": [{"texto": texto}]})

    assert alta.status_code == 201
    avisos = alta.json()["sugerencia"]["avisos"]
    conflictos = [aviso["mensaje"] for aviso in avisos if aviso["codigo"] == "direccion_no_cierra"]
    assert any("800" in mensaje and "Vera" in mensaje for mensaje in conflictos)
    assert any("800" in mensaje and "Velasco" in mensaje for mensaje in conflictos)


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
    assert {"Llamada", "Historial"} <= descripcion.json()["components"]["schemas"].keys()


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
    historial = cliente.get(f"/api/llamadas/{llamada_id}/historial")
    intento = derivar(cliente, llamada_id, {"prioridad": "P1"})

    assert consulta.status_code == historial.status_code == intento.status_code == 500
    assert historial.json() == consulta.json()
    assert "formato" in consulta.json()["detail"]
    assert "Corrientes" not in consulta.text


# ---------- El catálogo ----------


def test_la_api_entrega_el_catalogo_con_sus_treinta_protocolos(cliente):
    respuesta = cliente.get("/api/catalogo")

    assert respuesta.status_code == 200
    protocolos = respuesta.json()["protocolos"]
    assert [p["id"] for p in protocolos] == [f"SFX-{n:03d}" for n in range(1, 31)]
    assert protocolos[4] == {
        "id": "SFX-005",
        "categoria": "ACCIDENTE_VIAL",
        "nombre": "Colisión Vehículo vs Motovehículo",
        "preguntas": [
            {"id": "SFX-005-Q1", "texto": "¿El motociclista respira y responde al diálogo?"},
            {"id": "SFX-005-Q2", "texto": "¿Se le retiró el casco? (NO retirar)"},
            {"id": "SFX-005-Q3", "texto": "¿Hay combustible sobre el asfalto?"},
        ],
        "instrucciones": [
            {
                "id": "SFX-005-I1",
                "texto": "BAJO NINGUNA CIRCUNSTANCIA retire el casco del motociclista. No moverlo "
                "del asfalto. Desviar el tránsito con conos o balizas para evitar un segundo "
                "atropello.",
            }
        ],
    }


def test_al_derivar_con_un_subtipo_la_carta_trae_su_checklist_y_sus_instrucciones(cliente):
    llamada_id = iniciar(cliente)
    protocolo = cliente.get("/api/catalogo").json()["protocolos"][4]
    tipo = {"categoria": "ACCIDENTE_VIAL", "subtipo": "SFX-005"}

    carta = derivar(cliente, llamada_id, {**COMPLETOS, "tipo_hecho": tipo}).json()["carta"]

    assert carta["subtipo"] == {"origen": "operador", "valor": "SFX-005"}
    assert [(item["id"], item["pregunta"]) for item in carta["checklist"]] == [
        (pregunta["id"], pregunta["texto"]) for pregunta in protocolo["preguntas"]
    ]
    assert not any(item["respondida"] for item in carta["checklist"])
    assert carta["instrucciones"] == protocolo["instrucciones"]
    assert cliente.get(f"/api/llamadas/{llamada_id}").json()["carta"] == {
        **carta,
        "derivada_en": carta["derivada_en"],
    }


@pytest.mark.parametrize(
    "tipo",
    [
        {"categoria": "INCENDIO_RESCATE", "subtipo": "SFX-005"},
        {"categoria": "ACCIDENTE_VIAL", "subtipo": "SFX-999"},
    ],
)
def test_un_subtipo_invalido_devuelve_422_y_la_llamada_sigue_esperando(cliente, tipo):
    llamada_id = iniciar(cliente)

    rechazo = derivar(cliente, llamada_id, {**COMPLETOS, "tipo_hecho": tipo})

    assert rechazo.status_code == 422
    assert rechazo.json()["detail"][0]["loc"] == ["ajustes", "tipo_hecho", "subtipo"]
    assert cliente.get(f"/api/llamadas/{llamada_id}").json()["estado"] == "esperando_operador"


def test_una_llamada_guardada_antes_de_que_existiera_el_subtipo_se_sigue_leyendo(cliente):
    llamada_id = iniciar(cliente)
    sin_subtipo = cliente.get(f"/api/llamadas/{llamada_id}").json()["sugerencia"]
    del sin_subtipo["subtipo"]
    cliente.app.state.llamadas._grafo.update_state(_hilo(llamada_id), {"sugerencia": sin_subtipo})

    llamada = cliente.get(f"/api/llamadas/{llamada_id}")

    assert llamada.status_code == 200
    assert llamada.json()["sugerencia"]["subtipo"] == {"origen": "falta"}
    assert derivar(cliente, llamada_id, COMPLETOS).status_code == 200


def test_una_carta_guardada_sin_marcas_del_operador_ni_avisos_se_sigue_leyendo(cliente):
    llamada_id = iniciar(cliente)
    respuesta = derivar(cliente, llamada_id, {})
    assert respuesta.status_code == 200
    derivada = respuesta.json()
    carta = derivada["carta"]
    assert carta["checklist"]
    carta_vieja = {campo: valor for campo, valor in carta.items() if campo != "avisos"}
    carta_vieja["checklist"] = [
        {campo: valor for campo, valor in pregunta.items() if campo != "del_operador"}
        for pregunta in carta["checklist"]
    ]
    grafo = cliente.app.state.llamadas._grafo
    grafo.update_state(_hilo(llamada_id), {"carta": carta_vieja}, as_node="derivar")

    consulta = cliente.get(f"/api/llamadas/{llamada_id}")

    assert consulta.status_code == 200
    assert consulta.json() == {
        **derivada,
        "carta": {
            **carta_vieja,
            "avisos": [],
            "checklist": [
                {**pregunta, "del_operador": False} for pregunta in carta_vieja["checklist"]
            ],
        },
    }


def test_unos_ajustes_guardados_con_otro_formato_se_informan_como_ilegibles(cliente):
    # Una versión anterior guardó el tipo de hecho como texto y se cortó antes de armar la carta.
    llamada_id = iniciar(cliente)
    grafo = cliente.app.state.llamadas._grafo
    viejos = {"ajustes": {"tipo_hecho": "INCENDIO_RESCATE"}}
    grafo.update_state(_hilo(llamada_id), viejos, as_node="esperar_operador")

    historial = cliente.get(f"/api/llamadas/{llamada_id}/historial")
    consulta = cliente.get(f"/api/llamadas/{llamada_id}")
    intento = derivar(cliente, llamada_id, COMPLETOS)

    assert consulta.status_code == historial.status_code == intento.status_code == 500
    assert historial.json() == consulta.json()
    assert "formato" in consulta.json()["detail"]


def test_la_sugerencia_que_se_guarda_ya_esta_ajustada_al_catalogo(
    configuracion, monkeypatch, sugerencia_completa
):
    sugerencia_completa["subtipo"]["valor"] = "SFX-999"
    monkeypatch.setattr(flujo, "analizar", lambda _: Sugerencia.model_validate(sugerencia_completa))
    with TestClient(crear_app(configuracion)) as cliente:
        sugerencia = cliente.post("/api/llamadas", json=LLAMADA).json()["sugerencia"]

    assert sugerencia["subtipo"] == {"origen": "falta"}
    assert sugerencia["checklist"] == sugerencia["instrucciones"] == []


def test_la_api_entrega_el_criterio_de_prioridad_junto_al_catalogo(cliente):
    criterio = cliente.get("/api/catalogo").json()["criterio"]

    assert [nivel["id"] for nivel in criterio["niveles"]] == ["P1", "P2", "P3", "P4"]
    assert set(criterio["niveles"][0]) == {"id", "nombre", "definicion", "senales"}
    assert len(criterio["reglas"]) == 4


def test_lo_que_dice_el_operador_no_cuenta_aunque_la_transcripcion_no_se_pueda_partir(cliente):
    # Son más turnos de los que se guardan: la transcripción queda entera, con sus marcas.
    texto = "Operador: incendio en Av. Cabildo 1. " * 501

    respuesta = cliente.post("/api/llamadas", json={"turnos": [{"texto": texto}]})

    assert respuesta.status_code == 201
    llamada = respuesta.json()
    assert len(llamada["turnos"]) == 1
    assert llamada["sugerencia"]["ubicacion"]["calle"] == {"origen": "falta"}
    assert llamada["sugerencia"]["tipo_hecho"]["valor"] == "NO_DETERMINADA"


# ---------- Los ejemplos ----------


def test_los_ejemplos_se_cargan_al_arrancar(configuracion, monkeypatch):
    cargas = []
    cargar = ejemplos.cargar

    def registrar_carga():
        publicados = cargar()
        cargas.append(publicados)
        return publicados

    monkeypatch.setattr(ejemplos, "cargar", registrar_carga)

    with TestClient(crear_app(configuracion)):
        assert cargas


def test_la_api_entrega_los_treinta_ejemplos_del_dataset_y_los_seis_nuevos(cliente):
    respuesta = cliente.get("/api/ejemplos")

    assert respuesta.status_code == 200
    publicados = respuesta.json()
    por_id = {
        ejemplo["id"]: {campo: valor for campo, valor in ejemplo.items() if campo != "turnos"}
        for ejemplo in publicados
    }
    assert len(publicados) == len(por_id) == 36
    assert por_id == {
        **{
            subtipo: {
                "id": subtipo,
                "titulo": fila["subcategoria"],
                "origen": "dataset",
                "texto": fila["transcripcion_cruda"],
            }
            for subtipo, fila in FILAS_DATASET.items()
        },
        **{
            ejemplo_id: {**ejemplo, "origen": "nueva"}
            for ejemplo_id, ejemplo in EJEMPLOS_NUEVOS.items()
        },
    }


def test_los_ejemplos_traen_los_turnos_separados_por_hablante(cliente):
    publicados = cliente.get("/api/ejemplos").json()

    for ejemplo in publicados:
        separados = separar_hablantes([Turno(texto=ejemplo["texto"])])
        assert ejemplo["turnos"] == [turno.model_dump() for turno in separados], ejemplo["id"]

    nueva = next(ejemplo for ejemplo in publicados if ejemplo["id"] == "nueva-5")
    assert len(nueva["turnos"]) == 10


def iniciar_ejemplo(cliente, ejemplo_id):
    respuesta = cliente.get("/api/ejemplos")
    assert respuesta.status_code == 200
    ejemplo = next(ejemplo for ejemplo in respuesta.json() if ejemplo["id"] == ejemplo_id)
    alta = cliente.post("/api/llamadas", json={"turnos": [{"texto": ejemplo["texto"]}]})
    assert alta.status_code == 201
    return alta.json()["sugerencia"]


@pytest.mark.parametrize("subtipo", FILAS_DATASET)
def test_cada_ejemplo_del_dataset_se_da_de_alta_con_su_subtipo(cliente, subtipo):
    sugerencia = iniciar_ejemplo(cliente, subtipo)

    assert sugerencia["subtipo"] == {"origen": "inferido", "valor": subtipo, "fuente": "dataset"}


@pytest.mark.parametrize("ejemplo_id", EJEMPLOS_NUEVOS)
def test_cada_ejemplo_nuevo_se_da_de_alta_sin_subtipo(cliente, ejemplo_id):
    sugerencia = iniciar_ejemplo(cliente, ejemplo_id)

    assert sugerencia["subtipo"] == {"origen": "falta"}


def test_el_ejemplo_del_choque_con_moto_toma_la_altura_de_la_respuesta(cliente):
    ubicacion = iniciar_ejemplo(cliente, "nueva-5")["ubicacion"]

    assert ubicacion["calle"]["valor"] == "Av. San Juan"
    assert ubicacion["altura"] == {
        "origen": "dicho",
        "valor": 2100,
        "cita": {"turno": 3, "texto": "2100"},
    }


def test_el_ejemplo_del_choque_con_fuga_toma_el_cruce_y_los_dictados(cliente):
    sugerencia = iniciar_ejemplo(cliente, "nueva-6")

    ubicacion = sugerencia["ubicacion"]
    assert ubicacion["calle"]["valor"] == "Av. Cordoba"
    assert ubicacion["altura"] == {"origen": "falta"}
    assert [esquina["valor"] for esquina in ubicacion["esquinas"]] == ["Gascon"]
    assert sugerencia["datos_dictados"] == [
        {"tipo": "patente", "valor": "ZA 345 BD", "cita": {"turno": 1, "texto": "ZA 345 BD"}},
        {"tipo": "telefono", "valor": "1110000142", "cita": {"turno": 3, "texto": "11 1000-0142"}},
    ]


def test_al_sumar_un_turno_y_derivar_se_puede_quitar_el_telefono(cliente):
    llamada_id = iniciar(cliente, [{"texto": "Chocaron en Córdoba y Gascón. Patente ZA 345 BD."}])
    ampliada = cliente.post(
        f"/api/llamadas/{llamada_id}/turnos",
        json={"turno": {"texto": "Mi celular es 11 1000-0142. Patente AB 12 CD."}},
    )
    assert ampliada.status_code == 200
    sugerencia = ampliada.json()["sugerencia"]
    patente, telefono = sugerencia["datos_dictados"]
    assert [patente["valor"], telefono["valor"]] == ["ZA 345 BD", "1110000142"]
    assert telefono["cita"]["turno"] == 1
    assert "dictado_incompleto" in {aviso["codigo"] for aviso in sugerencia["avisos"]}

    respuesta = derivar(
        cliente,
        llamada_id,
        {"prioridad": "P2", "dictados_quitados": [{"tipo": "telefono", "valor": "1110000142"}]},
    )
    assert respuesta.status_code == 200
    carta = respuesta.json()["carta"]
    assert carta["datos_dictados"] == [patente]
    assert "dictado_incompleto" not in {aviso["codigo"] for aviso in carta["avisos"]}

    historial = cliente.get(f"/api/llamadas/{llamada_id}/historial").json()
    cambio = next(
        cambio for cambio in historial["cambios"] if cambio["campo"] == "dictado_telefono"
    )
    assert cambio["sugerido"] == {
        "origen": "dicho",
        "valor": telefono["valor"],
        "cita": telefono["cita"],
    }
    assert cambio["final"] == {"origen": "operador", "valor": None}


def test_quitar_un_dictado_que_no_esta_en_la_sugerencia_devuelve_422(cliente):
    llamada_id = iniciar(cliente)
    respuesta = derivar(
        cliente,
        llamada_id,
        {**COMPLETOS, "dictados_quitados": [{"tipo": "telefono", "valor": "1110000142"}]},
    )

    assert respuesta.status_code == 422
    assert respuesta.json()["detail"][0]["loc"] == ["ajustes", "dictados_quitados"]
    assert cliente.get(f"/api/llamadas/{llamada_id}").json()["estado"] == "esperando_operador"


def test_se_lee_una_llamada_guardada_sin_datos_dictados(cliente):
    llamada_id = iniciar(cliente)
    respuesta = derivar(cliente, llamada_id, COMPLETOS)
    assert respuesta.status_code == 200
    guardada = respuesta.json()
    sugerencia_vieja = {
        campo: valor for campo, valor in guardada["sugerencia"].items() if campo != "datos_dictados"
    }
    carta_vieja = {
        campo: valor for campo, valor in guardada["carta"].items() if campo != "datos_dictados"
    }
    grafo = cliente.app.state.llamadas._grafo
    grafo.update_state(
        _hilo(llamada_id),
        {"sugerencia": sugerencia_vieja, "carta": carta_vieja},
        as_node="derivar",
    )

    consulta = cliente.get(f"/api/llamadas/{llamada_id}")

    assert consulta.status_code == 200
    assert consulta.json() == guardada
    assert (
        consulta.json()["sugerencia"]["datos_dictados"]
        == consulta.json()["carta"]["datos_dictados"]
        == []
    )
