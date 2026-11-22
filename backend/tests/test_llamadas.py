from concurrent.futures import ThreadPoolExecutor

import pytest

from copiloto import flujo
from copiloto.flujo import SUGERENCIA_FIJA
from copiloto.llamadas import LlamadaInexistente, LlamadaNoEsperaOperador, Llamadas

TURNOS = [{"texto": "Se prendió fuego la cocina de la pizzería de Corrientes 1540."}]


@pytest.fixture
def ruta(tmp_path):
    return tmp_path / "llamadas.sqlite"


@pytest.fixture
def llamadas(ruta):
    servicio = Llamadas(ruta)
    yield servicio
    servicio.cerrar()


def test_iniciar_deja_la_llamada_esperando_al_operador(llamadas):
    llamada = llamadas.iniciar(TURNOS)

    assert llamada["estado"] == "esperando_operador"
    assert llamada["turnos"] == TURNOS
    assert llamada["sugerencia"] == SUGERENCIA_FIJA
    assert llamada["carta"] is None


def test_derivar_arma_la_carta_con_los_ajustes_del_operador(llamadas):
    llamada_id = llamadas.iniciar(TURNOS)["llamada_id"]

    llamada = llamadas.derivar(llamada_id, {"prioridad": "P2"})

    assert llamada["estado"] == "derivada"
    assert llamada["carta"]["prioridad"] == "P2"
    assert llamada["carta"]["ubicacion"] == SUGERENCIA_FIJA["ubicacion"]
    assert llamada["carta"]["ajustado_por_operador"] == ["prioridad"]


def test_una_llamada_a_medias_se_deriva_despues_de_reiniciar(ruta):
    antes = Llamadas(ruta)
    llamada_id = antes.iniciar(TURNOS)["llamada_id"]
    antes.cerrar()

    despues = Llamadas(ruta)
    assert despues.consultar(llamada_id)["estado"] == "esperando_operador"
    llamada = despues.derivar(llamada_id, {})
    despues.cerrar()

    assert llamada["estado"] == "derivada"
    assert llamada["carta"]["llamada_id"] == llamada_id


def test_una_llamada_no_se_deriva_dos_veces(llamadas):
    llamada_id = llamadas.iniciar(TURNOS)["llamada_id"]
    primera = llamadas.derivar(llamada_id, {"prioridad": "P2"})

    with pytest.raises(LlamadaNoEsperaOperador):
        llamadas.derivar(llamada_id, {"prioridad": "P3"})

    assert llamadas.consultar(llamada_id) == primera


def test_una_llamada_que_no_existe_no_se_consulta_ni_se_deriva(llamadas):
    with pytest.raises(LlamadaInexistente):
        llamadas.consultar("no-existe")
    with pytest.raises(LlamadaInexistente):
        llamadas.derivar("no-existe", {})


def test_dos_llamadas_no_se_mezclan(llamadas):
    primera = llamadas.iniciar([{"texto": "Primera llamada."}])
    segunda = llamadas.iniciar([{"texto": "Segunda llamada."}])
    llamadas.derivar(segunda["llamada_id"], {"prioridad": "P4"})

    assert llamadas.consultar(primera["llamada_id"]) == primera
    assert llamadas.consultar(segunda["llamada_id"])["turnos"] == [{"texto": "Segunda llamada."}]


def test_de_varias_derivaciones_simultaneas_entra_una_sola(llamadas):
    llamada_id = llamadas.iniciar(TURNOS)["llamada_id"]

    def derivar(prioridad):
        try:
            return llamadas.derivar(llamada_id, {"prioridad": prioridad})["carta"]["prioridad"]
        except LlamadaNoEsperaOperador:
            return None

    with ThreadPoolExecutor(max_workers=8) as hilos:
        resultados = list(hilos.map(derivar, ["P2", "P3", "P4", "P2", "P3", "P4", "P2", "P3"]))

    aceptadas = [prioridad for prioridad in resultados if prioridad is not None]
    assert len(aceptadas) == 1
    assert llamadas.consultar(llamada_id)["carta"]["prioridad"] == aceptadas[0]


def test_si_se_corta_al_armar_la_carta_se_termina_con_los_ajustes_ya_aceptados(ruta, monkeypatch):
    antes = Llamadas(ruta)
    llamada_id = antes.iniciar(TURNOS)["llamada_id"]

    def se_corta(*args):
        raise RuntimeError("el servicio se cortó")

    with monkeypatch.context() as corte:
        corte.setattr(flujo, "derivar", se_corta)
        with pytest.raises(RuntimeError):
            antes.derivar(llamada_id, {"prioridad": "P2"})
    antes.cerrar()

    despues = Llamadas(ruta)
    llamada = despues.consultar(llamada_id)
    with pytest.raises(LlamadaNoEsperaOperador):
        despues.derivar(llamada_id, {"prioridad": "P4"})
    despues.cerrar()

    assert llamada["estado"] == "derivada"
    assert llamada["carta"]["prioridad"] == "P2"
