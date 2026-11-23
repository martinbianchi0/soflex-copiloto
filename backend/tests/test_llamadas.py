import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, datetime

import pytest
from conftest import TEXTO_SIN_DATOS, TURNOS
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from copiloto import flujo, grafo
from copiloto.esquemas import Ajustes, Sugerencia, Turno
from copiloto.flujo import FaltanDatos
from copiloto.llamadas import (
    LlamadaInexistente,
    LlamadaNoEsperaOperador,
    Llamadas,
    LlamadaSinDerivar,
    LlamadaYaDerivada,
)
from copiloto.llamadas import _hilo as hilo
from copiloto.turnos import separar_hablantes

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

    assert llamada.estado == "esperando_operador"
    assert llamada.carta is not None
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
    assert llamadas.derivar(llamada_id, ajustes(**COMPLETOS)).carta is not None


def test_una_llamada_a_medias_se_deriva_despues_de_reiniciar(ruta):
    antes = Llamadas(ruta)
    llamada_id = antes.iniciar(turnos()).llamada_id
    antes.cerrar()

    despues = Llamadas(ruta)
    assert despues.consultar(llamada_id).estado == "esperando_operador"
    llamada = despues.derivar(llamada_id, ajustes(**COMPLETOS))
    despues.cerrar()

    assert llamada.estado == "esperando_operador"
    assert llamada.carta is not None
    assert llamada.carta.llamada_id == llamada_id


def test_se_puede_sumar_un_turno_despues_de_reiniciar(ruta):
    antes = Llamadas(ruta)
    inicial = antes.iniciar(turnos("Se prendió fuego un local."))
    antes.cerrar()

    despues = Llamadas(ruta)
    nueva = Turno(texto="En Av. Corrientes 1540.", hablante="llamante")
    ampliada = despues.sumar_turno(inicial.llamada_id, nueva)
    despues.cerrar()

    assert ampliada.estado == "esperando_operador"
    assert ampliada.turnos == [*inicial.turnos, nueva]
    assert ampliada.sugerencia.ubicacion.altura.valor == 1540
    assert ampliada.sugerencia.ubicacion.calle.cita.turno == 1


def test_si_se_corta_al_reanalizar_se_retoma_con_el_turno_ya_guardado(ruta, monkeypatch):
    antes = Llamadas(ruta)
    inicial = antes.iniciar(turnos("Hubo un choque."))
    nuevo = Turno(texto="Av. Corrientes 1540", hablante="llamante")

    def se_corta(_turnos):
        raise RuntimeError("el servicio se cortó")

    with monkeypatch.context() as corte:
        corte.setattr(flujo, "analizar", se_corta)
        with pytest.raises(RuntimeError, match="se cortó"):
            antes.sumar_turno(inicial.llamada_id, nuevo)
    antes.cerrar()

    despues = Llamadas(ruta)
    ampliada = despues.consultar(inicial.llamada_id)
    historial = despues.consultar_historial(inicial.llamada_id)
    despues.cerrar()

    assert ampliada.estado == "esperando_operador"
    assert ampliada.turnos == [*inicial.turnos, nuevo]
    assert ampliada.sugerencia.ubicacion.altura.valor == 1540
    assert [evento.tipo for evento in historial.eventos] == [
        "recibida",
        "sugerencia_reglas",
        "turno_agregado",
        "sugerencia_reglas",
    ]


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
    historial = despues.consultar_historial(llamada_id)
    despues.cerrar()

    al_final = Llamadas(ruta)
    carta = al_final.consultar(llamada_id).carta.model_dump(mode="json")
    assert al_final.consultar_historial(llamada_id) == historial
    al_final.cerrar()

    assert guardada == {**sugerencia_completa, "direccion_alternativa": None}
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

    def se_corta_en_el_grafo(*argumentos, **opciones):
        # La primera vez es la comprobación previa; la segunda, el nodo del grafo.
        veces.append(1)
        if len(veces) == 2:
            raise RuntimeError("el servicio se cortó")
        return derivar_de_verdad(*argumentos, **opciones)

    with monkeypatch.context() as corte:
        corte.setattr(flujo, "derivar", se_corta_en_el_grafo)
        with pytest.raises(RuntimeError):
            antes.derivar(llamada_id, ajustes(**COMPLETOS))
    antes.cerrar()

    despues = Llamadas(ruta)
    pendiente = despues.consultar_historial(llamada_id)
    assert pendiente.cambios == []
    assert pendiente.eventos[-1].tipo == "ajustes_operador"
    assert pendiente.eventos[-1].detalle == "El operador confirmó. La carta todavía está pendiente."
    assert despues.consultar_historial(llamada_id) == pendiente

    llamada = despues.consultar(llamada_id)
    completo = despues.consultar_historial(llamada_id)
    assert completo.eventos[-2].cuando == pendiente.eventos[-1].cuando
    assert completo.eventos[-1].tipo == "derivada"
    with pytest.raises(LlamadaNoEsperaOperador):
        despues.derivar(llamada_id, ajustes(**{**COMPLETOS, "prioridad": "P4"}))
    despues.cerrar()

    assert llamada.estado == "esperando_operador"
    assert llamada.carta is not None
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


# ---------- Después de derivar ----------


def puntos_guardados(llamadas: Llamadas, llamada_id: str) -> int:
    return len(list(llamadas._grafo.get_state_history(hilo(llamada_id))))


def test_derivar_no_cierra_la_llamada_y_una_segunda_derivacion_se_rechaza(llamadas):
    llamada_id = llamadas.iniciar(turnos()).llamada_id
    derivada = llamadas.derivar(llamada_id, ajustes(**COMPLETOS))

    assert derivada.estado == "esperando_operador"
    assert derivada.carta.actualizada_en is None
    assert "actualizada_en" not in derivada.carta.model_dump(mode="json")
    with pytest.raises(LlamadaYaDerivada):
        llamadas.derivar(llamada_id, ajustes(**{**COMPLETOS, "prioridad": "P1"}))
    assert llamadas.consultar(llamada_id) == derivada


def test_actualizar_arma_otra_version_y_conserva_la_hora_de_la_derivacion(llamadas):
    llamada_id = llamadas.iniciar(turnos()).llamada_id
    derivada = llamadas.derivar(llamada_id, ajustes(**COMPLETOS))

    actualizada = llamadas.actualizar(llamada_id, ajustes(**{**COMPLETOS, "prioridad": "P1"}))

    assert actualizada.estado == "esperando_operador"
    assert actualizada.carta.prioridad.valor == "P1"
    assert actualizada.carta.ubicacion == derivada.carta.ubicacion
    assert actualizada.carta.derivada_en == derivada.carta.derivada_en
    assert actualizada.carta.actualizada_en >= derivada.carta.derivada_en
    assert llamadas.consultar(llamada_id) == actualizada


def test_los_ajustes_de_una_actualizacion_son_todo_lo_que_difiere_de_la_sugerencia(llamadas):
    # Lo que no se manda vuelve a ser lo sugerido: el panel manda siempre lo que tiene en pantalla.
    llamada_id = llamadas.iniciar(turnos()).llamada_id
    llamadas.derivar(llamada_id, ajustes(**COMPLETOS))

    actualizada = llamadas.actualizar(llamada_id, ajustes(prioridad="P3"))

    assert actualizada.carta.prioridad.valor == "P3"
    assert actualizada.carta.ubicacion == actualizada.sugerencia.ubicacion


def test_una_actualizacion_que_no_cambia_la_carta_la_deja_igual_y_guarda_los_ajustes(llamadas):
    # Otros ajustes que arman la misma carta: se guardan, porque son los que retoma el panel.
    llamada_id = llamadas.iniciar(turnos()).llamada_id
    derivada = llamadas.derivar(llamada_id, ajustes(**COMPLETOS))
    mismos = {**COMPLETOS, "checklist": []}

    igual = llamadas.actualizar(llamada_id, ajustes(**mismos))

    assert igual.carta == derivada.carta
    assert igual.carta.actualizada_en is None
    assert igual.ajustes == ajustes(**mismos)
    tipos = [evento.tipo for evento in llamadas.consultar_historial(llamada_id).eventos]
    assert "carta_actualizada" not in tipos


def test_la_llamada_devuelve_los_ajustes_de_su_carta(llamadas):
    llamada_id = llamadas.iniciar(turnos()).llamada_id
    assert llamadas.consultar(llamada_id).ajustes is None

    derivada = llamadas.derivar(llamada_id, ajustes(**COMPLETOS))

    assert derivada.ajustes == ajustes(**COMPLETOS)
    assert llamadas.consultar(llamada_id).ajustes == ajustes(**COMPLETOS)
    # Se devuelven como se mandaron, sin los campos que no se mandaron.
    assert derivada.model_dump(mode="json")["ajustes"] == ajustes(**COMPLETOS).model_dump(
        mode="json", exclude_unset=True
    )


def test_la_carta_deja_de_estar_al_dia_si_un_turno_cambia_la_sugerencia(llamadas):
    llamada_id = llamadas.iniciar(turnos(TEXTO_SIN_DATOS)).llamada_id
    derivada = llamadas.derivar(llamada_id, ajustes(**COMPLETOS))
    assert derivada.carta_al_dia is True

    igual = llamadas.sumar_turno(
        llamada_id, Turno(texto="No sé, no veo nada más.", hablante="llamante")
    )
    assert igual.carta_al_dia is True

    cambio = llamadas.sumar_turno(
        llamada_id,
        Turno(texto="Ahora veo humo, hay un incendio en la cocina.", hablante="llamante"),
    )
    assert cambio.sugerencia != igual.sugerencia
    assert cambio.carta_al_dia is False
    assert cambio.carta == derivada.carta

    actualizada = llamadas.actualizar(llamada_id, ajustes(**COMPLETOS))
    assert actualizada.carta_al_dia is True
    assert llamadas.terminar(llamada_id).carta_al_dia is None


def test_sin_carta_no_se_actualiza_ni_se_termina(llamadas):
    llamada_id = llamadas.iniciar(turnos()).llamada_id

    with pytest.raises(LlamadaSinDerivar):
        llamadas.actualizar(llamada_id, ajustes(**COMPLETOS))
    with pytest.raises(LlamadaSinDerivar):
        llamadas.terminar(llamada_id)
    assert llamadas.consultar(llamada_id).carta is None


def test_si_falta_un_dato_obligatorio_la_actualizacion_falla_y_la_carta_no_cambia(llamadas):
    # Sin calle sugerida: si la actualización no manda la ubicación, la carta se queda sin calle.
    llamada_id = llamadas.iniciar(turnos(TEXTO_SIN_DATOS)).llamada_id
    derivada = llamadas.derivar(llamada_id, ajustes(**COMPLETOS))

    with pytest.raises(FaltanDatos):
        llamadas.actualizar(llamada_id, ajustes(prioridad="P1"))

    assert llamadas.consultar(llamada_id) == derivada


def test_sumar_un_turno_despues_de_derivar_vuelve_a_analizar_y_no_cambia_la_carta(llamadas):
    llamada_id = llamadas.iniciar(turnos()).llamada_id
    derivada = llamadas.derivar(llamada_id, ajustes(**COMPLETOS))

    ampliada = llamadas.sumar_turno(llamada_id, Turno(texto="Ahora sale humo del primer piso."))

    assert ampliada.estado == "esperando_operador"
    assert len(ampliada.turnos) == len(derivada.turnos) + 1
    assert ampliada.carta == derivada.carta
    # Después del turno se puede seguir actualizando: el turno no se toma como una derivación.
    actualizada = llamadas.actualizar(llamada_id, ajustes(**{**COMPLETOS, "prioridad": "P1"}))
    assert actualizada.carta.prioridad.valor == "P1"
    assert actualizada.turnos == ampliada.turnos


def test_terminar_cierra_la_llamada_y_su_carta_queda_como_esta(llamadas):
    llamada_id = llamadas.iniciar(turnos()).llamada_id
    actualizada = llamadas.derivar(llamada_id, ajustes(**COMPLETOS))
    actualizada = llamadas.actualizar(llamada_id, ajustes(**{**COMPLETOS, "prioridad": "P1"}))

    terminada = llamadas.terminar(llamada_id)

    assert terminada.estado == "terminada"
    assert terminada.carta == actualizada.carta
    for intento in (
        lambda: llamadas.derivar(llamada_id, ajustes(**COMPLETOS)),
        lambda: llamadas.actualizar(llamada_id, ajustes(**COMPLETOS)),
        lambda: llamadas.sumar_turno(llamada_id, Turno(texto="Hola.")),
        lambda: llamadas.terminar(llamada_id),
    ):
        with pytest.raises(LlamadaNoEsperaOperador):
            intento()
    assert llamadas.consultar(llamada_id) == terminada


def test_una_llamada_derivada_sigue_abierta_despues_de_reiniciar(ruta):
    antes = Llamadas(ruta)
    llamada_id = antes.iniciar(turnos()).llamada_id
    derivada = antes.derivar(llamada_id, ajustes(**COMPLETOS))
    antes.cerrar()

    despues = Llamadas(ruta)
    assert despues.consultar(llamada_id) == derivada
    actualizada = despues.actualizar(llamada_id, ajustes(**{**COMPLETOS, "prioridad": "P1"}))
    assert despues.terminar(llamada_id).carta == actualizada.carta
    despues.cerrar()


def test_si_se_corta_al_actualizar_la_carta_se_termina_con_los_ajustes_ya_aceptados(
    ruta, monkeypatch
):
    antes = Llamadas(ruta)
    llamada_id = antes.iniciar(turnos()).llamada_id
    derivada = antes.derivar(llamada_id, ajustes(**COMPLETOS))
    derivar_de_verdad = flujo.derivar
    veces = []

    def se_corta_en_el_grafo(llamada_id, sugerencia, ajustes, *argumentos, **opciones):
        # Con los ajustes nuevos, la primera vez es la comprobación previa y la segunda, el nodo.
        if ajustes.prioridad == "P1":
            veces.append(1)
            if len(veces) == 2:
                raise RuntimeError("el servicio se cortó")
        return derivar_de_verdad(llamada_id, sugerencia, ajustes, *argumentos, **opciones)

    with monkeypatch.context() as corte:
        corte.setattr(flujo, "derivar", se_corta_en_el_grafo)
        with pytest.raises(RuntimeError):
            antes.actualizar(llamada_id, ajustes(**{**COMPLETOS, "prioridad": "P1"}))
    antes.cerrar()

    despues = Llamadas(ruta)
    llamada = despues.consultar(llamada_id)
    despues.cerrar()

    assert llamada.estado == "esperando_operador"
    assert llamada.carta.prioridad.valor == "P1"
    assert llamada.carta.derivada_en == derivada.carta.derivada_en
    assert llamada.carta.actualizada_en is not None


def test_el_historial_cuenta_la_derivacion_las_actualizaciones_y_el_cierre(llamadas):
    llamada_id = llamadas.iniciar(turnos()).llamada_id
    llamadas.derivar(llamada_id, ajustes(**COMPLETOS))
    llamadas.sumar_turno(llamada_id, Turno(texto="Ahora sale humo del primer piso."))
    llamadas.actualizar(llamada_id, ajustes(**{**COMPLETOS, "prioridad": "P1"}))
    llamadas.terminar(llamada_id)

    historial = llamadas.consultar_historial(llamada_id)

    assert [(evento.tipo, evento.detalle) for evento in historial.eventos] == [
        ("recibida", "Llamada recibida, con 1 turno."),
        ("sugerencia_reglas", "Sugerencia de las reglas, sin avisos."),
        ("ajustes_operador", "El operador confirmó con 2 cambios."),
        ("derivada", "Carta de Llamada derivada."),
        ("turno_agregado", "Se sumó un turno a la llamada: ahora tiene 2."),
        ("sugerencia_reglas", "Sugerencia de las reglas, con 1 aviso."),
        ("carta_actualizada", "Carta actualizada: prioridad P2 → P1."),
        ("terminada", "Llamada terminada."),
    ]
    # La sugerencia (la ficha del dataset) ya decía P1: después de actualizar, lo único que el
    # operador cambió es haber quitado una esquina.
    assert [cambio.campo for cambio in historial.cambios] == ["esquinas"]


def test_una_llamada_con_ajustes_de_una_version_anterior_se_lee_sin_ellos(ruta):
    # Antes de que existiera el subtipo, el tipo de hecho de los ajustes era una categoría suelta.
    llamada_id = "llamada-anterior"
    lista = separar_hablantes(turnos())
    sugerencia = flujo.analizar(lista)
    carta = flujo.derivar(
        llamada_id, sugerencia, ajustes(**COMPLETOS), datetime.now(UTC), turnos=lista
    )
    guardada = {
        "sugerencia": sugerencia.model_dump(mode="json"),
        "carta": carta.model_dump(mode="json"),
        "ajustes": {"prioridad": "P2", "tipo_hecho": "INCENDIO_RESCATE"},
    }
    anterior = StateGraph(grafo.Estado)
    anterior.add_node("guardar", lambda estado: guardada)
    anterior.add_edge(START, "guardar")
    anterior.add_edge("guardar", END)
    with closing(sqlite3.connect(ruta, check_same_thread=False)) as conexion:
        anterior.compile(checkpointer=SqliteSaver(conexion)).invoke(
            {"llamada_id": llamada_id, "turnos": [t.model_dump(mode="json") for t in lista]},
            hilo(llamada_id),
        )

    servicio = Llamadas(ruta)
    llamada = servicio.consultar(llamada_id)
    servicio.cerrar()

    assert llamada.estado == "terminada"
    assert llamada.carta == carta
    assert llamada.ajustes is None
