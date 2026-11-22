from concurrent.futures import ThreadPoolExecutor

import pytest
from conftest import TEXTO_SIN_DATOS, TURNOS

from copiloto import flujo
from copiloto.esquemas import Ajustes, Sugerencia, Turno
from copiloto.flujo import FaltanDatos
from copiloto.llamadas import LlamadaInexistente, LlamadaNoEsperaOperador, Llamadas

UBICACION = {"calle": "Av. Corrientes", "altura": 1540, "esquinas": ["Montevideo"]}
COMPLETOS = {"prioridad": "P2", "ubicacion": UBICACION}


def turnos(*textos: str) -> list[Turno]:
    return [Turno(texto=texto) for texto in textos] or [Turno(**turno) for turno in TURNOS]


def ajustes(**campos) -> Ajustes:
    return Ajustes.model_validate(campos)


@pytest.fixture
def ruta(tmp_path):
    return tmp_path / "llamadas.sqlite"


@pytest.fixture
def llamadas(ruta):
    servicio = Llamadas(ruta)
    yield servicio
    servicio.cerrar()


def test_iniciar_deja_la_llamada_esperando_al_operador(llamadas):
    llamada = llamadas.iniciar(turnos())

    assert llamada.estado == "esperando_operador"
    assert llamada.turnos == turnos()
    assert llamada.sugerencia == flujo.ajustar_al_catalogo(flujo.analizar(turnos()))
    assert llamada.carta is None


def test_derivar_arma_la_carta_con_los_ajustes_del_operador(llamadas):
    llamada_id = llamadas.iniciar(turnos()).llamada_id

    llamada = llamadas.derivar(llamada_id, ajustes(**COMPLETOS))

    assert llamada.estado == "derivada"
    assert llamada.carta.llamada_id == llamada_id
    assert llamada.carta.prioridad.model_dump() == {"origen": "operador", "valor": "P2"}
    assert llamada.carta.ubicacion.calle.valor == "Av. Corrientes"
    assert llamada.carta.tipo_hecho == llamada.sugerencia.tipo_hecho


def test_si_falta_un_dato_obligatorio_no_se_deriva_y_la_llamada_sigue_esperando(llamadas):
    llamada_id = llamadas.iniciar(turnos(TEXTO_SIN_DATOS)).llamada_id

    with pytest.raises(FaltanDatos) as error:
        llamadas.derivar(llamada_id, ajustes(prioridad="P2"))

    assert error.value.campos == ["calle"]
    assert llamadas.consultar(llamada_id).estado == "esperando_operador"
    assert llamadas.derivar(llamada_id, ajustes(**COMPLETOS)).estado == "derivada"


def test_una_llamada_a_medias_se_deriva_despues_de_reiniciar(ruta):
    antes = Llamadas(ruta)
    llamada_id = antes.iniciar(turnos()).llamada_id
    antes.cerrar()

    despues = Llamadas(ruta)
    assert despues.consultar(llamada_id).estado == "esperando_operador"
    llamada = despues.derivar(llamada_id, ajustes(**COMPLETOS))
    despues.cerrar()

    assert llamada.estado == "derivada"
    assert llamada.carta.llamada_id == llamada_id


def test_los_origenes_y_las_citas_sobreviven_al_grafo_al_disco_y_al_reinicio(
    ruta, monkeypatch, sugerencia_completa
):
    monkeypatch.setattr(flujo, "analizar", lambda _: Sugerencia.model_validate(sugerencia_completa))
    antes = Llamadas(ruta)
    llamada_id = antes.iniciar(turnos()).llamada_id
    antes.cerrar()

    despues = Llamadas(ruta)
    guardada = despues.consultar(llamada_id).sugerencia.model_dump(mode="json")
    cambio = {"calle": "Av. Corrientes", "altura": 1548, "esquinas": ["Montevideo", "Paraná"]}
    despues.derivar(llamada_id, ajustes(prioridad="P1", ubicacion=cambio))
    despues.cerrar()

    al_final = Llamadas(ruta)
    carta = al_final.consultar(llamada_id).carta.model_dump(mode="json")
    al_final.cerrar()

    assert guardada == {**sugerencia_completa, "avisos": []}
    assert carta["ubicacion"]["calle"] == sugerencia_completa["ubicacion"]["calle"]
    assert carta["ubicacion"]["esquinas"] == sugerencia_completa["ubicacion"]["esquinas"]
    assert carta["ubicacion"]["altura"] == {"origen": "operador", "valor": 1548}
    assert carta["checklist"] == sugerencia_completa["checklist"]


def test_una_llamada_no_se_deriva_dos_veces(llamadas):
    llamada_id = llamadas.iniciar(turnos()).llamada_id
    primera = llamadas.derivar(llamada_id, ajustes(**COMPLETOS))

    with pytest.raises(LlamadaNoEsperaOperador):
        llamadas.derivar(llamada_id, ajustes(**{**COMPLETOS, "prioridad": "P3"}))

    assert llamadas.consultar(llamada_id) == primera


def test_una_llamada_que_no_existe_no_se_consulta_ni_se_deriva(llamadas):
    with pytest.raises(LlamadaInexistente):
        llamadas.consultar("no-existe")
    with pytest.raises(LlamadaInexistente):
        llamadas.derivar("no-existe", ajustes(**COMPLETOS))


def test_dos_llamadas_no_se_mezclan(llamadas):
    primera = llamadas.iniciar(turnos("Primera llamada."))
    segunda = llamadas.iniciar(turnos("Segunda llamada."))
    llamadas.derivar(segunda.llamada_id, ajustes(**COMPLETOS))

    assert llamadas.consultar(primera.llamada_id) == primera
    assert llamadas.consultar(segunda.llamada_id).turnos == turnos("Segunda llamada.")


def test_de_varias_derivaciones_simultaneas_entra_una_sola(llamadas):
    llamada_id = llamadas.iniciar(turnos()).llamada_id

    def derivar(prioridad):
        try:
            carta = llamadas.derivar(llamada_id, ajustes(**{**COMPLETOS, "prioridad": prioridad}))
            return carta.carta.prioridad.valor
        except LlamadaNoEsperaOperador:
            return None

    with ThreadPoolExecutor(max_workers=8) as hilos:
        resultados = list(hilos.map(derivar, ["P2", "P3", "P4", "P2", "P3", "P4", "P2", "P3"]))

    aceptadas = [prioridad for prioridad in resultados if prioridad is not None]
    assert len(aceptadas) == 1
    assert llamadas.consultar(llamada_id).carta.prioridad.valor == aceptadas[0]


def test_si_se_corta_al_armar_la_carta_se_termina_con_los_ajustes_ya_aceptados(ruta, monkeypatch):
    antes = Llamadas(ruta)
    llamada_id = antes.iniciar(turnos()).llamada_id
    derivar_de_verdad = flujo.derivar
    veces = []

    def se_corta_en_el_grafo(*argumentos):
        # La primera vez es la comprobación previa; la segunda, el nodo del grafo.
        veces.append(1)
        if len(veces) == 2:
            raise RuntimeError("el servicio se cortó")
        return derivar_de_verdad(*argumentos)

    with monkeypatch.context() as corte:
        corte.setattr(flujo, "derivar", se_corta_en_el_grafo)
        with pytest.raises(RuntimeError):
            antes.derivar(llamada_id, ajustes(**COMPLETOS))
    antes.cerrar()

    despues = Llamadas(ruta)
    llamada = despues.consultar(llamada_id)
    with pytest.raises(LlamadaNoEsperaOperador):
        despues.derivar(llamada_id, ajustes(**{**COMPLETOS, "prioridad": "P4"}))
    despues.cerrar()

    assert llamada.estado == "derivada"
    assert llamada.carta.prioridad.valor == "P2"


def test_una_llamada_se_guarda_con_un_aviso_si_se_descarta_una_cita_falsa(llamadas, monkeypatch):
    def inventa(_turnos):
        calle = {"origen": "dicho", "valor": "Rivadavia", "cita": {"turno": 0, "texto": "al 9999"}}
        ubicacion = {"calle": calle, "altura": {"origen": "falta"}, "esquinas": []}
        tipo = {"origen": "inferido", "valor": "NO_DETERMINADA", "fuente": "reglas"}
        return Sugerencia.model_validate(
            {"ubicacion": ubicacion, "tipo_hecho": tipo, "prioridad": {"origen": "falta"}}
        )

    monkeypatch.setattr(flujo, "analizar", inventa)

    llamada = llamadas.iniciar(turnos())

    assert llamada.estado == "esperando_operador"
    assert llamada.sugerencia.ubicacion.calle.model_dump() == {"origen": "falta"}
    (aviso,) = llamada.sugerencia.avisos
    assert aviso.codigo == "dato_descartado"
    assert "calle" in aviso.mensaje
    assert llamadas.consultar(llamada.llamada_id) == llamada
