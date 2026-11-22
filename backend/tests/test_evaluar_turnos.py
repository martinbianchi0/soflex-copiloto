"""La evaluación de una llamada que llega de a un intercambio."""

import json
import subprocess
import sys
from importlib import import_module
from pathlib import Path
from unittest.mock import Mock, call

import pytest
from test_analisis import ModeloGuionado

from copiloto.esquemas import Turno
from copiloto.llamadas import Llamadas

RAIZ = Path(__file__).resolve().parents[1]
CATEGORIA = "ACCIDENTE_VIAL"
SUBTIPO = "SFX-005"
Q1, Q2, Q3 = (f"{SUBTIPO}-Q{numero}" for numero in (1, 2, 3))
PRIMER_RELATO = "Estoy en avenida Corrientes."
SEGUNDO_RELATO = (
    "En avenida Corrientes 1540 chocó un auto con una moto. El motociclista tiene el casco puesto."
)


@pytest.fixture
def evaluar(monkeypatch):
    monkeypatch.syspath_prepend(str(RAIZ))
    return import_module("herramientas.evaluar_turnos")


@pytest.fixture
def guion():
    calle = {
        "calle_oficial": "CORRIENTES AV.",
        "altura": None,
        "esquina_oficial": None,
    }
    return {
        "id": "G01",
        "titulo": "Choque en avenida Corrientes",
        "categoria": CATEGORIA,
        "subtipo": SUBTIPO,
        "intercambios": [
            {
                "turnos": [
                    {"hablante": "operador", "texto": "¿Dónde es la emergencia?"},
                    {"hablante": "llamante", "texto": PRIMER_RELATO},
                ],
                "esperado": {**calle, "categoria": None, "subtipo": None, "respondidas": []},
            },
            {
                "turnos": [
                    {"hablante": "operador", "texto": "¿A qué altura? ¿Qué pasó?"},
                    {"hablante": "llamante", "texto": SEGUNDO_RELATO},
                ],
                "esperado": {
                    **calle,
                    "altura": 1540,
                    "categoria": CATEGORIA,
                    "subtipo": SUBTIPO,
                    "respondidas": [Q2],
                },
            },
        ],
    }


@pytest.mark.parametrize(
    "hay_datos,categoria,subtipo,clase_categoria,clase_subtipo",
    [
        (True, CATEGORIA, SUBTIPO, "acierta", "acierta"),
        (True, "NO_DETERMINADA", None, "sin_determinar", "sin_subtipo"),
        (True, "INCENDIO_RESCATE", "SFX-001", "mal", "mal"),
        (False, "NO_DETERMINADA", None, "espera", "espera"),
        (False, CATEGORIA, SUBTIPO, "se_adelanta", "se_adelanta"),
        (False, "INCENDIO_RESCATE", "SFX-001", "mal", "mal"),
    ],
)
def test_clases_de_categoria_y_subtipo(
    evaluar, guion, hay_datos, categoria, subtipo, clase_categoria, clase_subtipo
):
    propuesto = {"categoria": categoria, "subtipo": subtipo, "calle": None, "checklist": []}
    esperado = guion["intercambios"][int(hay_datos)]["esperado"]
    lectura = evaluar.leer(propuesto, esperado, guion)
    assert lectura["categoria"] == clase_categoria
    assert lectura["subtipo"] == clase_subtipo
    assert ("respuestas" in lectura) == (clase_subtipo == "acierta")
    assert ("proxima_pregunta" in lectura) == (clase_subtipo == "acierta")


@pytest.mark.parametrize(
    "oficial,altura_esperada,cruce,calle,altura,esquinas,clase",
    [
        ("CORRIENTES AV.", 1540, None, "av CORRIÉNTES", 1540, [], "acierta"),
        ("CORRIENTES AV.", None, None, "Av. Corrientes", None, [], "acierta"),
        ("CORRIENTES AV.", 1540, None, "Av. Corrientes", None, [], "incompleta"),
        ("CORRIENTES AV.", 1540, None, "Av. Corrientes", 1500, [], "mal"),
        ("CORRIENTES AV.", None, None, "Av. Corrientes", 1540, [], "mal"),
        ("CORRIENTES AV.", 1540, None, "Av. San Juan", 1540, [], "mal"),
        ("CORRIENTES AV.", 1540, None, None, None, [], "sin_calle"),
        (None, None, None, None, None, [], "espera"),
        (None, None, None, "Av. Corrientes", None, [], "mal"),
        (
            "SAN JUAN AV.",
            None,
            "ENTRE RIOS AV.",
            "Av. San Juan",
            None,
            ["Av. Entre Ríos"],
            "acierta",
        ),
        (
            "SAN JUAN AV.",
            None,
            "ENTRE RIOS AV.",
            "Av. Entre Ríos",
            None,
            ["Av. San Juan"],
            "acierta",
        ),
        ("SAN JUAN AV.", None, "ENTRE RIOS AV.", "Av. San Juan", None, [], "mal"),
        ("SAN JUAN AV.", None, "ENTRE RIOS AV.", "Av. Entre Ríos", None, ["Av. Corrientes"], "mal"),
        ("SAN JUAN AV.", None, "ENTRE RIOS AV.", "Av. San Juan", 1800, ["Av. Entre Ríos"], "mal"),
    ],
)
def test_clases_de_ubicacion(
    evaluar, oficial, altura_esperada, cruce, calle, altura, esquinas, clase
):
    esperado = {"calle_oficial": oficial, "altura": altura_esperada, "esquina_oficial": cruce}
    propuesto = {"calle": calle, "altura": altura, "esquinas": esquinas}
    assert evaluar.clasificar_ubicacion(propuesto, esperado) == clase


def _item(identificador, respondida=False, con_cita=False):
    return {"id": identificador, "respondida": respondida, "con_cita": con_cita}


def test_respuestas_bien_de_mas_y_faltantes(evaluar):
    checklist = [_item(Q1, respondida=True, con_cita=True), _item(Q2, con_cita=True), _item(Q3)]
    assert evaluar.clasificar_respuestas(checklist, {Q1, Q3}) == {
        "bien": 1,
        "de_mas": 1,
        "faltan": 1,
    }


@pytest.mark.parametrize(
    "checklist,respondidas,orden,salteando",
    [
        ([_item(Q1), _item(Q2)], set(), (Q1, "bien"), (Q1, "bien")),
        ([_item(Q1, con_cita=True), _item(Q2)], {Q1}, (Q1, "ya_respondida"), (Q2, "bien")),
        ([_item(Q1), _item(Q2)], {Q1}, (Q1, "ya_respondida"), (Q1, "ya_respondida")),
        (
            [_item(Q1, con_cita=True), _item(Q2), _item(Q3)],
            {Q2},
            (Q1, "bien"),
            (Q2, "saltea_una_pendiente"),
        ),
        (
            [_item(Q1, respondida=True), _item(Q2)],
            {Q2},
            (Q2, "saltea_una_pendiente"),
            (Q2, "saltea_una_pendiente"),
        ),
        ([_item(Q1, respondida=True)], {Q1}, (None, "bien"), (None, "bien")),
        (
            [_item(Q1, respondida=True)],
            set(),
            (None, "saltea_una_pendiente"),
            (None, "saltea_una_pendiente"),
        ),
    ],
)
def test_proxima_pregunta_por_politica(evaluar, checklist, respondidas, orden, salteando):
    for saltear, (identificador, clase) in ((False, orden), (True, salteando)):
        assert evaluar.clasificar_proxima_pregunta(
            checklist, respondidas, saltear_posibles=saltear
        ) == {
            "id": identificador,
            "clase": clase,
        }


def test_recorre_la_misma_llamada_y_completa_cada_analisis(evaluar, guion, tmp_path, monkeypatch):
    clasificacion = json.dumps({"categoria": CATEGORIA, "subtipo": SUBTIPO, "prioridad": "P2"})
    modelo = ModeloGuionado(
        clasificacion,
        '{"corresponde": true, "respuestas": []}',
        clasificacion,
        json.dumps(
            {
                "corresponde": True,
                "respuestas": [
                    {"id": Q2, "respondida": True, "cita": "tiene el casco puesto"},
                    {"id": Q1, "respondida": True, "cita": "respondió cuando le hablé"},
                ],
            }
        ),
    )
    contador = evaluar.Contador(modelo)
    servicio = Llamadas(tmp_path / "llamadas.sqlite", contador)
    pasos = Mock()
    try:
        for nombre in ("iniciar", "sumar_turno", "completar_analisis"):
            seguimiento = Mock(wraps=getattr(servicio, nombre))
            pasos.attach_mock(seguimiento, nombre)
            monkeypatch.setattr(servicio, nombre, seguimiento)
        resultado = evaluar.medir(guion, servicio, contador)
    finally:
        servicio.cerrar()

    llamada_id = pasos.completar_analisis.call_args.args[0]
    assert pasos.mock_calls == [
        call.iniciar(
            [Turno(texto=f"Operador: ¿Dónde es la emergencia? Llamante: {PRIMER_RELATO}")]
        ),
        call.completar_analisis(llamada_id),
        call.sumar_turno(
            llamada_id,
            Turno(texto=f"Operador: ¿A qué altura? ¿Qué pasó? Llamante: {SEGUNDO_RELATO}"),
        ),
        call.completar_analisis(llamada_id),
    ]
    assert [usuario for _, usuario, _ in modelo.pedidos] == [
        *[f"Lo que dijo el llamante:\n{PRIMER_RELATO}"] * 2,
        *[f"Lo que dijo el llamante:\n{PRIMER_RELATO}\n{SEGUNDO_RELATO}"] * 2,
    ]
    primero, segundo = resultado["intercambios"]
    assert (primero["pedidos"], segundo["pedidos"], contador.pedidos) == (2, 2, 4)
    assert [dato["esperado"] for dato in (primero, segundo)] == [
        intercambio["esperado"] for intercambio in guion["intercambios"]
    ]
    assert primero["propuesto"]["altura"] is None and segundo["propuesto"]["altura"] == 1540
    assert primero["lectura"] == {
        "categoria": "se_adelanta",
        "subtipo": "se_adelanta",
        "ubicacion": "acierta",
    }
    assert "falta_altura" in primero["avisos"]
    assert "dato_descartado" in segundo["avisos"]
    assert segundo["propuesto"]["checklist"] == [_item(Q1), _item(Q2, con_cita=True), _item(Q3)]
    assert segundo["lectura"] == {
        "categoria": "acierta",
        "subtipo": "acierta",
        "ubicacion": "acierta",
        "respuestas": {"bien": 1, "de_mas": 0, "faltan": 0},
        "proxima_pregunta": {
            "orden_del_catalogo": {"id": Q1, "clase": "bien"},
            "salteando_posibles": {"id": Q1, "clase": "bien"},
        },
    }
    primera = evaluar.primera_vez(guion, resultado)
    assert primera["subtipo"] == {"esperado": 2, "propuesto": 1, "clase": "antes"}
    assert primera["direccion_completa"] == {"esperado": 2, "propuesto": 2, "clase": "igual"}
    total = evaluar.resumir([resultado], [primera])["total"]
    assert total["respuestas"] == {"bien": 1, "de_mas": 0, "faltan": 0}
    assert all(conteo["bien"] == 1 for conteo in total["proxima_pregunta"].values())


def test_resume_intercambios_desde_el_cuarto_y_primeras_propuestas_tardias(evaluar, guion):
    calle = {"calle": "Av. Corrientes", "esquinas": [], "checklist": []}
    datos = []
    for numero in range(1, 6):
        esperado = guion["intercambios"][int(numero >= 2)]["esperado"]
        propuesto = {
            **calle,
            "altura": 1540 if numero >= 4 else None,
            "subtipo": SUBTIPO if numero >= 4 else None,
            "categoria": esperado["categoria"] or "NO_DETERMINADA",
        }
        datos.append(
            {
                "esperado": esperado,
                "propuesto": propuesto,
                "lectura": evaluar.leer(propuesto, esperado, guion),
                "pedidos": numero,
                "segundos": float(numero),
            }
        )
    resultado = {"intercambios": datos}
    primera = evaluar.primera_vez(guion, resultado)
    resumen = evaluar.resumir([resultado], [primera])
    assert primera["subtipo"] == {"esperado": 2, "propuesto": 4, "clase": "despues"}
    assert primera["direccion_completa"] == primera["subtipo"]
    assert resumen["primera_vez"]["subtipo"]["despues"] == 1
    assert resumen["por_intercambio"]["4+"]["intercambios"] == 2
    assert resumen["por_intercambio"]["4+"]["segundos"] == {"mediana": 4.5, "p95": 5, "maximo": 5}
    assert resumen["total"]["intercambios"] == 5
    assert resumen["total"]["pedidos"] == {"mediana": 3, "maximo": 5}


def test_mock_de_punta_a_punta(guion, tmp_path):
    entrada = tmp_path / "guiones.json"
    entrada.write_text(json.dumps([guion, {**guion, "id": "G02"}]), encoding="utf-8")
    salida = tmp_path / "medicion" / "turnos.json"
    proceso = subprocess.run(
        [
            sys.executable,
            RAIZ / "herramientas" / "evaluar_turnos.py",
            "--proveedor",
            "mock",
            "--guiones",
            entrada,
            "--solo",
            "G03, G01",
            "--salida",
            salida,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    detalle = json.loads(salida.read_text(encoding="utf-8"))
    assert set(detalle) == {"proveedor", "modelo", "fecha", "guiones", "resumen"}
    assert detalle["proveedor"] == "mock" and detalle["modelo"] is None
    (resultado,) = detalle["guiones"]
    assert resultado["id"] == guion["id"] and resultado["titulo"] == guion["titulo"]
    primero, segundo = resultado["intercambios"]
    assert (primero["pedidos"], segundo["pedidos"]) == (0, 0)
    assert primero["lectura"] == {
        "categoria": "espera",
        "subtipo": "espera",
        "ubicacion": "acierta",
    }
    assert segundo["lectura"] == {
        "categoria": "acierta",
        "subtipo": "sin_subtipo",
        "ubicacion": "acierta",
    }
    resumen = detalle["resumen"]
    assert resumen["total"]["intercambios"] == 2
    assert resumen["por_intercambio"]["3"]["segundos"]["p95"] is None
    assert resumen["primera_vez"]["subtipo"]["nunca"] == 1
    assert resumen["primera_vez"]["direccion_completa"]["igual"] == 1
    assert "| Intercambios | 1 | 1 | 0 | 0 | 2 |" in proceso.stdout
    assert "| Subtipo correcto | 0 | 0 | 0 | 1 |" in proceso.stdout


def test_lo_que_miden_las_reglas_sobre_los_guiones(evaluar):
    """Los números del modo `mock` que publican el README y DECISIONS.

    Si una regla los mueve, este test falla: hay que regenerar `evaluacion/turnos-reglas.json` y
    actualizar los dos documentos.
    """
    guiones = json.loads(evaluar.GUIONES.read_text(encoding="utf-8"))
    with evaluar._abrir_servicio(None, 60.0) as servicio:
        resultados = [evaluar.medir(guion, servicio, None) for guion in guiones]
    primeras = [
        evaluar.primera_vez(guion, resultado)
        for guion, resultado in zip(guiones, resultados, strict=True)
    ]
    resumen = evaluar.resumir(resultados, primeras)

    assert resumen["total"]["intercambios"] == 49
    assert resumen["total"]["ubicacion"] == {
        "acierta": 49,
        "incompleta": 0,
        "sin_calle": 0,
        "espera": 0,
        "mal": 0,
    }
    assert resumen["primera_vez"]["direccion_completa"] == {
        "antes": 0,
        "igual": 14,
        "despues": 0,
        "nunca": 0,
    }
    assert resumen["total"]["categoria"] == {
        "acierta": 29,
        "sin_determinar": 11,
        "espera": 3,
        "se_adelanta": 0,
        "mal": 6,
    }
    assert resumen["por_intercambio"]["1"]["categoria"]["mal"] == 0
