import json
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_analisis import ModeloGuionado

from copiloto.callejero import cargar
from copiloto.llamadas import Llamadas

RAIZ = Path(__file__).resolve().parents[1]
CLASIFICACION = '{"categoria": "ACCIDENTE_VIAL", "subtipo": null, "prioridad": "P2"}'
ARAOZ = '{"calle": "Araoz", "altura": 1236, "esquinas": ["Cabrera"]}'


@pytest.fixture
def evaluar(monkeypatch):
    monkeypatch.syspath_prepend(str(RAIZ))
    return import_module("herramientas.evaluar_direccion")


def test_coherencia_de_las_direcciones_dificiles(evaluar):
    casos = evaluar.casos()
    assert len(casos) == len({caso["id"] for caso in casos}) == 48
    callejero = cargar()
    for caso in casos:
        esperado = caso["esperado"]
        calle, altura = esperado["calle_oficial"], esperado["altura"]
        esquinas = esperado["esquinas_oficiales"] or []
        if calle is not None:
            assert calle in callejero.tramos, caso["id"]
        if altura is not None:
            assert calle is not None and callejero.cuadras(calle, altura), caso["id"]
            assert set(esquinas) <= set(callejero.entrecalles(calle, altura)), caso["id"]
        else:
            for esquina in esquinas:
                assert calle is not None and callejero.alturas_en_esquina(calle, esquina), caso[
                    "id"
                ]


def test_lo_medido_con_el_modelo_alcanza_para_ofrecer_la_segunda_lectura(evaluar):
    """Fija las cuentas que citan los documentos. Los tiempos dependen de la máquina: no se fijan."""
    medido = json.loads(
        (RAIZ.parent / "evaluacion" / "direccion-modelo.json").read_text(encoding="utf-8")
    )
    con_aviso = medido["resumen"]["con_aviso"]

    assert (con_aviso["llamadas"], con_aviso["reglas_bien"]) == (29, 16)
    assert con_aviso["resultados"] == {
        "bien": 16,
        "corrige": 7,
        "no_arregla": 5,
        "equivocada": 1,
        "rompe": 0,
        "inventa": 0,
    }
    cumple = evaluar.criterio(con_aviso, medido["tiempo_de_la_segunda_lectura"])
    assert cumple["pocas_propuestas_equivocadas"] and cumple["corrige_al_menos_la_mitad"]


def test_el_criterio_falla_con_una_correccion_menos_o_una_equivocada_mas(evaluar):
    tiempo = {"pedidos": 29, "mediana": 4.7, "p95": 7.2, "maximo": 8.6}
    base = {"equivocadas_pct": 3.4, "corrige_de_recuperables": "7/13"}

    assert all(evaluar.criterio(base, tiempo).values())
    assert not evaluar.criterio(base | {"corrige_de_recuperables": "6/13"}, tiempo)[
        "corrige_al_menos_la_mitad"
    ]
    assert not evaluar.criterio(base | {"equivocadas_pct": 6.9}, tiempo)[
        "pocas_propuestas_equivocadas"
    ]
    assert not evaluar.criterio(base, tiempo | {"mediana": 8.1})["agrega_poco_tiempo"]
    assert not evaluar.criterio(base | {"corrige_de_recuperables": "0/0"}, tiempo)[
        "corrige_al_menos_la_mitad"
    ]


def test_clasifica_las_seis_salidas_y_resume_el_camino_del_servicio(evaluar, tmp_path, monkeypatch):
    casos = {caso["id"]: caso for caso in evaluar.casos()}
    guion = [
        ("D01", '{"calle": "Vidal", "altura": 2686}', "corrige"),
        ("D04", '{"calle": "Venezuela", "altura": 3246}', "corrige"),
        ("D05", '{"calle": null}', "no_arregla"),
        ("D12", ARAOZ, "equivocada"),
        ("D10", ARAOZ, "rompe"),
        ("D41", ARAOZ, "inventa"),
        ("D33", None, "bien"),
    ]
    modelo = ModeloGuionado(
        *(r for _, direccion, _ in guion for r in (CLASIFICACION, direccion) if r is not None)
    )
    instantes = iter(t for n in range(1, 8) for t in (0.0, 0.01, float(n)))
    monkeypatch.setattr(evaluar, "time", SimpleNamespace(monotonic=lambda: next(instantes)))
    servicio = Llamadas(tmp_path / "llamadas.sqlite", modelo)
    try:
        mediciones = [
            evaluar.medir(casos[identificador], servicio) for identificador, _, _ in guion
        ]
    finally:
        servicio.cerrar()
    assert [fila["resultado"] for fila in mediciones] == [salida for _, _, salida in guion]
    assert len(modelo.pedidos) == 13
    assert mediciones[1]["propuesta"]["calle_oficial"] == "REPUBLICA BOLIVARIANA DE VENEZUELA"
    assert all(fila["segundos_alta"] == 0.01 for fila in mediciones)

    resumen = evaluar.resumir(mediciones)
    con_aviso, todas = resumen["con_aviso"], resumen["todas"]
    assert con_aviso == {
        "llamadas": 6,
        "reglas_bien": 2,
        "resultados": {
            "bien": 0,
            "corrige": 2,
            "no_arregla": 1,
            "equivocada": 1,
            "rompe": 1,
            "inventa": 1,
        },
        "equivocadas": 3,
        "equivocadas_pct": 50.0,
        "corrige_de_recuperables": "2/4",
        "mediana": 3.5,
        "p95": 6.0,
        "maximo": 6.0,
    }
    assert todas == {
        **con_aviso,
        "llamadas": 7,
        "reglas_bien": 3,
        "resultados": {**con_aviso["resultados"], "bien": 1},
        "equivocadas_pct": 42.9,
        "mediana": 4.0,
        "p95": 7.0,
        "maximo": 7.0,
    }
    assert evaluar.markdown(resumen)[2:] == [
        "| Con aviso que dispara | 6 | 2 | 3 (50.0 %) | 2/4 | 3.500 | 6.000 | 6.000 |",
        "| Todas | 7 | 3 | 3 (42.9 %) | 2/4 | 4.000 | 7.000 | 7.000 |",
    ]


def test_resultado_acepta_un_cruce_nombrandolo_al_reves_y_descarta_repeticiones(evaluar):
    esperado = {
        "calle_oficial": "CONDE",
        "altura": None,
        "esquinas_oficiales": ["LORETO, VIRREY"],
        "propuesta_correcta": "direccion",
    }
    assert evaluar.resultado(esperado, (None, None), ("LORETO, VIRREY", None)) == "corrige"
    assert evaluar.resultado(esperado, ("CONDE", None), ("CONDE", None)) == "bien"
    assert evaluar.resultado(esperado, ("LORETO, VIRREY", None), None) == "bien"


def test_el_cronometro_mide_solo_el_pedido_de_la_segunda_lectura(evaluar, tmp_path):
    casos = {caso["id"]: caso for caso in evaluar.casos()}
    modelo = evaluar.Cronometro(ModeloGuionado(CLASIFICACION, ARAOZ, CLASIFICACION))
    servicio = Llamadas(tmp_path / "llamadas.sqlite", modelo)
    try:
        con_pedido = evaluar.medir(casos["D12"], servicio, modelo)
        sin_pedido = evaluar.medir(casos["D33"], servicio, modelo)
    finally:
        servicio.cerrar()

    assert con_pedido["segundos_segunda_lectura"] is not None
    assert sin_pedido["segundos_segunda_lectura"] is None
    agregado = evaluar.tiempo_de_la_segunda_lectura([con_pedido, sin_pedido])
    assert agregado["pedidos"] == 1
    assert agregado["mediana"] == agregado["maximo"] == con_pedido["segundos_segunda_lectura"]
    assert evaluar.tiempo_de_la_segunda_lectura([sin_pedido]) == {
        "pedidos": 0,
        "mediana": None,
        "p95": None,
        "maximo": None,
    }
