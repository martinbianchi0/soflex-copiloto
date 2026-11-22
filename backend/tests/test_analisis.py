import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from threading import Event

import pytest
from conftest import FILAS_DATASET, TEXTO
from fastapi.testclient import TestClient
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from copiloto import catalogo, dataset, flujo, grafo, main
from copiloto import modelo as modelos
from copiloto.config import Configuracion
from copiloto.esquemas import Ajustes, Aviso, Cita, Falta, Turno
from copiloto.llamadas import LlamadaNoEsperaOperador, Llamadas
from copiloto.modelo import ModeloNoDisponible
from copiloto.turnos import separar_hablantes

TEXTO_001 = FILAS_DATASET["SFX-001"]["transcripcion_cruda"]
CITA = "adentro quedó el cocinero"
CITA_CHECKLIST = "quedó el cocinero"
RESPUESTA = {"categoria": "INCENDIO_RESCATE", "subtipo": "SFX-001", "prioridad": "P2", "cita": CITA}
CLASIFICACION = json.dumps(RESPUESTA)
CHECKLIST = json.dumps(
    {
        "corresponde": True,
        "respuestas": [{"id": "SFX-001-Q1", "respondida": True, "cita": CITA_CHECKLIST}],
    }
)


def aviso_rescate(motivo):
    return Aviso(
        codigo="modelo_no_disponible",
        mensaje=f"El modelo no respondió ({motivo}): esta sugerencia sale de las reglas.",
    )


class ModeloGuionado:
    def __init__(self, *respuestas: str | ModeloNoDisponible):
        self.respuestas = iter(respuestas)
        self.pedidos: list[tuple[str, str, float]] = []

    def __call__(self, sistema: str, usuario: str, vence: float) -> str:
        self.pedidos.append((sistema, usuario, vence))
        respuesta = next(self.respuestas)
        if isinstance(respuesta, ModeloNoDisponible):
            raise respuesta
        return respuesta


@pytest.fixture
def abrir_servicio(tmp_path):
    @contextmanager
    def abrir(modelo=None):
        servicio = Llamadas(tmp_path / "llamadas.sqlite", modelo)
        try:
            yield servicio
        finally:
            servicio.cerrar()

    return abrir


def alta_001(servicio):
    return servicio.iniciar([Turno(texto=TEXTO_001)])


@pytest.mark.parametrize(
    ("respuestas", "cantidad", "error", "cita"),
    [
        pytest.param([CLASIFICACION, CHECKLIST], 2, None, CITA, id="valida"),
        pytest.param(
            [f"Acá va.\n```json\n{CLASIFICACION}\n```\nEso es todo.", CHECKLIST],
            2,
            None,
            CITA,
            id="texto_alrededor",
        ),
        pytest.param(
            [CLASIFICACION[:-10], CLASIFICACION, CHECKLIST],
            3,
            "No se pudo leer un objeto JSON.",
            CITA,
            id="truncada",
        ),
        pytest.param(
            [json.dumps({**RESPUESTA, "categoria": "INVENTADA"}), CLASIFICACION, CHECKLIST],
            3,
            "La categoría no es válida.",
            CITA,
            id="categoria_invalida",
        ),
        pytest.param(
            [json.dumps({**RESPUESTA, "prioridad": ["P2"]}), CLASIFICACION, CHECKLIST],
            3,
            "La prioridad no es válida.",
            CITA,
            id="prioridad_invalida",
        ),
        pytest.param(
            [json.dumps({**RESPUESTA, "calle": "Av. Inventada"}), CHECKLIST],
            2,
            None,
            CITA,
            id="campo_de_mas",
        ),
        pytest.param(
            [json.dumps({**RESPUESTA, "cita": "voló la cocina"}), CHECKLIST],
            2,
            None,
            None,
            id="cita_inventada",
        ),
        pytest.param(["", "basura"], 2, "No se pudo leer un objeto JSON.", None, id="ilegible"),
        pytest.param(
            [ModeloNoDisponible("no hay conexión con Ollama")], 1, None, None, id="no_responde"
        ),
        pytest.param(
            ["", CLASIFICACION, "{}", CHECKLIST],
            4,
            "No se pudo leer un objeto JSON.",
            CITA,
            id="dos_reintentos",
        ),
    ],
)
def test_el_modelo_completa_la_llamada_001(abrir_servicio, respuestas, cantidad, error, cita):
    modelo = ModeloGuionado(*respuestas)
    with abrir_servicio(modelo) as servicio:
        inicial = alta_001(servicio)
        assert inicial.estado == "analizando"
        assert not modelo.pedidos
        assert inicial.sugerencia.ubicacion.calle.origen == "dicho"
        assert inicial.sugerencia.ubicacion.altura.origen == "dicho"
        assert inicial.sugerencia.tipo_hecho.fuente == "reglas"
        assert inicial.sugerencia.subtipo == inicial.sugerencia.prioridad == Falta()
        assert inicial.sugerencia.checklist == []

        final = servicio.completar_analisis(inicial.llamada_id)
        assert servicio.consultar(inicial.llamada_id) == final

    assert len(modelo.pedidos) == cantidad
    assert len({vence for _, _, vence in modelo.pedidos}) == 1
    if error is not None:
        sistema, usuario, vence = modelo.pedidos[0]
        assert modelo.pedidos[1] == (
            sistema,
            f"{usuario}\nTu respuesta anterior no sirvió: {error} Respondé de nuevo sólo con el objeto JSON.",
            vence,
        )
    assert final.estado == "esperando_operador"
    sugerencia = final.sugerencia
    assert sugerencia.ubicacion == inicial.sugerencia.ubicacion
    tipo, subtipo, prioridad = sugerencia.tipo_hecho, sugerencia.subtipo, sugerencia.prioridad
    assert [dato.origen for dato in (tipo, subtipo, prioridad)] == ["inferido"] * 3
    assert tipo.valor == "INCENDIO_RESCATE"
    assert subtipo.valor == "SFX-001"
    con_rescate = respuestas[-1] != CHECKLIST
    if con_rescate:
        assert [dato.fuente for dato in (tipo, subtipo, prioridad)] == ["dataset"] * 3
        simulada = flujo.ajustar_al_catalogo(flujo.analizar(final.turnos))
        ultima = respuestas[-1]
        motivo = (
            ultima.motivo
            if isinstance(ultima, ModeloNoDisponible)
            else "su respuesta no se pudo leer"
        )
        assert sugerencia == simulada.model_copy(
            update={"avisos": [*simulada.avisos, aviso_rescate(motivo)]}
        )
    else:
        assert [dato.fuente for dato in (tipo, subtipo, prioridad)] == ["modelo"] * 3
        assert prioridad.valor == "P2"
        assert prioridad.cita == (Cita(turno=1, texto=cita) if cita else None)
        assert sugerencia.avisos == inicial.sugerencia.avisos
        assert [item.cita for item in sugerencia.checklist] == [
            Cita(turno=1, texto=CITA_CHECKLIST),
            None,
            None,
        ]


@pytest.mark.parametrize("subtipo", ["SFX-005", "SFX-999", " SFX-001 ", {"id": "SFX-001"}])
def test_el_subtipo_invalido_se_descarta_una_vez_y_no_se_pide_el_checklist(abrir_servicio, subtipo):
    modelo = ModeloGuionado(json.dumps({**RESPUESTA, "subtipo": subtipo}))
    with abrir_servicio(modelo) as servicio:
        inicial = alta_001(servicio)
        final = servicio.completar_analisis(inicial.llamada_id)

    assert len(modelo.pedidos) == 1
    sugerencia = final.sugerencia
    assert sugerencia.subtipo == Falta()
    assert sugerencia.checklist == sugerencia.instrucciones == []
    assert sugerencia.tipo_hecho.fuente == sugerencia.prioridad.fuente == "modelo"
    (aviso,) = sugerencia.avisos[len(inicial.sugerencia.avisos) :]
    assert aviso.codigo == "dato_descartado"
    assert "subtipo" in aviso.mensaje


def test_el_checklist_solo_conserva_respuestas_respaldadas_del_protocolo(abrir_servicio):
    respuestas = [
        {"id": "SFX-001-Q1", "respondida": True, "cita": CITA, "pregunta": "Inventada"},
        {"id": "SFX-001-Q2", "respondida": True},
        {"id": "SFX-001-Q3", "respondida": True, "cita": "Se cayó la pared lindera"},
        {"id": "SFX-002-Q1", "respondida": True, "cita": CITA},
    ]
    modelo = ModeloGuionado(
        CLASIFICACION, json.dumps({"corresponde": True, "respuestas": respuestas})
    )
    with abrir_servicio(modelo) as servicio:
        inicial = alta_001(servicio)
        sugerencia = servicio.completar_analisis(inicial.llamada_id).sugerencia

    assert len(modelo.pedidos) == 2
    protocolo = catalogo.cargar().protocolo(sugerencia.tipo_hecho.valor, "SFX-001")
    assert [(item.id, item.pregunta) for item in sugerencia.checklist] == [
        (pregunta.id, pregunta.texto) for pregunta in protocolo.preguntas
    ]
    assert sugerencia.instrucciones == protocolo.instrucciones
    # Lo que propone el modelo queda como posible respuesta, con su cita y sin darse por respondido.
    assert [item.respondida for item in sugerencia.checklist] == [False, False, False]
    assert [item.cita for item in sugerencia.checklist] == [Cita(turno=1, texto=CITA), None, None]
    avisos = sugerencia.avisos[len(inicial.sugerencia.avisos) :]
    assert [aviso.codigo for aviso in avisos] == ["dato_descartado"] * 2
    assert [aviso.mensaje for aviso in avisos] == [
        f"Se descartó una respuesta del modelo a «{pregunta.texto}»: su cita no está en lo que dijo el llamante."
        for pregunta in protocolo.preguntas[1:]
    ]


def test_el_checklist_y_la_prioridad_admiten_una_tira_de_la_cita(abrir_servicio):
    propuesta = "dentro quedó el cocinero"
    respuestas = [{"id": "SFX-001-Q1", "respondida": True, "cita": propuesta}]
    modelo = ModeloGuionado(
        json.dumps({**RESPUESTA, "cita": propuesta}),
        json.dumps({"corresponde": True, "respuestas": respuestas}),
    )
    with abrir_servicio(modelo) as servicio:
        inicial = alta_001(servicio)
        sugerencia = servicio.completar_analisis(inicial.llamada_id).sugerencia

    assert len(modelo.pedidos) == 2
    assert (
        sugerencia.prioridad.cita
        == sugerencia.checklist[0].cita
        == Cita(turno=1, texto=CITA_CHECKLIST)
    )
    assert sugerencia.avisos == inicial.sugerencia.avisos


@pytest.mark.parametrize(
    ("respuestas", "motivo"),
    [
        pytest.param(
            ['{"corresponde": true}', "[]"], "su respuesta no se pudo leer", id="ilegible"
        ),
        pytest.param(
            [ModeloNoDisponible("Ollama devolvió un error")], "Ollama devolvió un error", id="caida"
        ),
    ],
)
def test_si_falla_la_revision_el_subtipo_sin_confirmar_no_se_muestra(
    abrir_servicio, respuestas, motivo
):
    modelo = ModeloGuionado(CLASIFICACION, *respuestas)
    with abrir_servicio(modelo) as servicio:
        inicial = alta_001(servicio)
        final = servicio.completar_analisis(inicial.llamada_id)

    assert len(modelo.pedidos) == 1 + len(respuestas)
    if len(respuestas) == 2:
        assert modelo.pedidos[2][0] == modelo.pedidos[1][0]
        assert "Las respuestas del protocolo deben venir en una lista." in modelo.pedidos[2][1]
    assert final.estado == "esperando_operador"
    sugerencia = final.sugerencia
    assert sugerencia.tipo_hecho.fuente == sugerencia.prioridad.fuente == "modelo"
    assert sugerencia.prioridad.valor == "P2"
    assert sugerencia.prioridad.cita == Cita(turno=1, texto=CITA)
    assert sugerencia.subtipo == Falta()
    assert sugerencia.checklist == sugerencia.instrucciones == []
    (aviso,) = sugerencia.avisos[len(inicial.sugerencia.avisos) :]
    assert aviso.codigo == "modelo_no_disponible"
    assert aviso.mensaje == (
        "El modelo propuso el subtipo «Incendio en Comercio Gastronómico» y no llegó a "
        f"confirmarlo: {motivo}. Elegí el subtipo si alguno corresponde."
    )


@pytest.mark.parametrize(
    "respuestas", [[], [{"id": "SFX-001-Q1", "respondida": True, "cita": CITA}]]
)
def test_si_el_modelo_dice_que_el_subtipo_no_corresponde_no_se_muestra(abrir_servicio, respuestas):
    revision = json.dumps({"corresponde": False, "respuestas": respuestas})
    modelo = ModeloGuionado(CLASIFICACION, revision)
    with abrir_servicio(modelo) as servicio:
        inicial = alta_001(servicio)
        sugerencia = servicio.completar_analisis(inicial.llamada_id).sugerencia

    assert len(modelo.pedidos) == 2
    assert "Tipo de hecho propuesto: «Incendio en Comercio Gastronómico»" in modelo.pedidos[1][0]
    assert sugerencia.tipo_hecho.valor == "INCENDIO_RESCATE"
    assert sugerencia.prioridad.valor == "P2"
    assert sugerencia.subtipo == Falta()
    assert sugerencia.checklist == sugerencia.instrucciones == []
    # Que el catálogo no tenga un subtipo para el hecho es lo habitual: no se avisa.
    assert sugerencia.avisos == inicial.sugerencia.avisos


def test_la_revision_sin_decir_si_corresponde_se_vuelve_a_pedir(abrir_servicio):
    sin_decirlo = json.dumps({"respuestas": []})
    modelo = ModeloGuionado(CLASIFICACION, sin_decirlo, CHECKLIST)
    with abrir_servicio(modelo) as servicio:
        inicial = alta_001(servicio)
        sugerencia = servicio.completar_analisis(inicial.llamada_id).sugerencia

    assert len(modelo.pedidos) == 3
    assert 'Falta "corresponde"' in modelo.pedidos[2][1]
    assert sugerencia.subtipo.valor == "SFX-001"
    assert sugerencia.checklist[0].cita is not None


def test_una_posible_respuesta_sin_confirmar_no_llega_respondida_a_la_carta(abrir_servicio):
    with abrir_servicio(ModeloGuionado(CLASIFICACION, CHECKLIST)) as servicio:
        llamada_id = alta_001(servicio).llamada_id
        propuesta = servicio.completar_analisis(llamada_id).sugerencia.checklist[0]
        carta = servicio.derivar(llamada_id, Ajustes()).carta
        historial = servicio.consultar_historial(llamada_id)

    assert propuesta.cita is not None and not propuesta.respondida
    assert carta.checklist[0] == propuesta
    assert not any(item.respondida for item in carta.checklist)
    assert historial.cambios == []


def test_el_operador_confirma_una_posible_respuesta_y_conserva_su_cita(abrir_servicio):
    with abrir_servicio(ModeloGuionado(CLASIFICACION, CHECKLIST)) as servicio:
        llamada_id = alta_001(servicio).llamada_id
        propuesta = servicio.completar_analisis(llamada_id).sugerencia.checklist[0]
        marca = Ajustes.model_validate({"checklist": [{"id": propuesta.id, "respondida": True}]})
        confirmada = servicio.derivar(llamada_id, marca).carta.checklist[0]
        (cambio,) = servicio.consultar_historial(llamada_id).cambios

    assert confirmada.respondida and confirmada.del_operador
    assert confirmada.cita == propuesta.cita
    assert cambio.campo == f"pregunta {propuesta.id}"
    assert cambio.sugerido.model_dump() == {"respondida": False, "propuesta": True}
    assert cambio.final.model_dump() == {"respondida": True, "propuesta": False}


def test_si_vence_antes_de_clasificar_se_rescata_sin_pedir_nada(abrir_servicio, monkeypatch):
    monkeypatch.setattr(flujo, "monotonic", lambda: 100.0)
    monkeypatch.setattr(modelos, "monotonic", lambda: 160.0)
    modelo = ModeloGuionado()
    with abrir_servicio(modelo) as servicio:
        inicial = alta_001(servicio)
        final = servicio.completar_analisis(inicial.llamada_id)

    assert not modelo.pedidos
    assert final.estado == "esperando_operador"
    assert final.sugerencia.prioridad.fuente == "dataset"
    assert final.sugerencia.avisos[-1] == aviso_rescate("se agotó el tiempo de espera")


def test_si_vence_entre_la_clasificacion_y_la_revision_se_conserva_la_clasificacion(
    abrir_servicio, monkeypatch
):
    instante = 100.0
    pedidos = []

    def clasificar(sistema, usuario, vence):
        nonlocal instante
        pedidos.append(vence)
        instante = vence
        return CLASIFICACION

    monkeypatch.setattr(flujo, "monotonic", lambda: instante)
    monkeypatch.setattr(modelos, "monotonic", lambda: instante)
    with abrir_servicio(clasificar) as servicio:
        inicial = alta_001(servicio)
        final = servicio.completar_analisis(inicial.llamada_id)

    assert pedidos == [160.0]
    assert final.estado == "esperando_operador"
    assert final.sugerencia.prioridad.fuente == "modelo"
    assert final.sugerencia.prioridad.valor == "P2"
    assert final.sugerencia.subtipo == Falta()
    assert final.sugerencia.checklist == []
    assert final.sugerencia.avisos[-1].mensaje == (
        "El modelo propuso el subtipo «Incendio en Comercio Gastronómico» y no llegó a "
        "confirmarlo: se agotó el tiempo de espera. Elegí el subtipo si alguno corresponde."
    )


def test_al_modelo_le_llegan_el_catalogo_el_criterio_y_solo_lo_que_dijo_el_llamante(abrir_servicio):
    modelo = ModeloGuionado(CLASIFICACION, CHECKLIST)
    with abrir_servicio(modelo) as servicio:
        inicial = alta_001(servicio)
        servicio.completar_analisis(inicial.llamada_id)

    (sistema, usuario, _), (sistema_checklist, usuario_checklist, _) = modelo.pedidos
    assert usuario == usuario_checklist == f"Lo que dijo el llamante:\n{TEXTO}"
    referencia = catalogo.cargar()
    for protocolo in referencia.protocolos:
        assert f"  {protocolo.id}: {protocolo.nombre}" in sistema
    assert [
        linea for linea in sistema.splitlines() if linea.isupper() and " " not in linea
    ] == list(dict.fromkeys(protocolo.categoria for protocolo in referencia.protocolos))
    for nivel in referencia.criterio.niveles:
        assert f"{nivel.id} · {nivel.nombre}: {nivel.definicion}" in sistema
        assert "; ".join(nivel.senales) in sistema
    for regla in referencia.criterio.reglas:
        assert f"- {regla}" in sistema
    for pregunta in referencia.protocolos[0].preguntas:
        assert f"{pregunta.id}: {pregunta.texto}" in sistema_checklist
    assert "SFX-002-Q1" not in sistema_checklist
    assert "911 emergencias" not in sistema + sistema_checklist


def test_la_llamada_pendiente_del_modelo_se_completa_despues_de_reiniciar(abrir_servicio):
    with abrir_servicio(ModeloGuionado()) as antes:
        inicial = alta_001(antes)

    modelo = ModeloGuionado(CLASIFICACION, CHECKLIST)
    with abrir_servicio(modelo) as despues:
        assert despues.consultar(inicial.llamada_id) == inicial
        final = despues.completar_analisis(inicial.llamada_id)
        assert final.estado == "esperando_operador"
        assert final.sugerencia.prioridad.cita == Cita(turno=1, texto=CITA)
        derivada = despues.derivar(inicial.llamada_id, Ajustes())
        assert derivada.carta.prioridad == final.sugerencia.prioridad

    assert len(modelo.pedidos) == 2


def test_la_llamada_pendiente_del_modelo_se_rescata_si_el_servicio_vuelve_en_mock(abrir_servicio):
    modelo = ModeloGuionado()
    with abrir_servicio(modelo) as antes:
        inicial = alta_001(antes)
        assert inicial.estado == "analizando"

    with abrir_servicio() as despues:
        assert despues.consultar(inicial.llamada_id) == inicial
        final = despues.completar_analisis(inicial.llamada_id)
        assert despues.completar_analisis(inicial.llamada_id) == final
        assert despues.derivar(inicial.llamada_id, Ajustes()).estado == "derivada"

    assert not modelo.pedidos
    assert final.estado == "esperando_operador"
    simulada = flujo.ajustar_al_catalogo(flujo.analizar(final.turnos))
    assert final.sugerencia == simulada.model_copy(
        update={"avisos": [*simulada.avisos, aviso_rescate("el servicio está en modo mock")]}
    )


@pytest.mark.parametrize(
    ("estado_anterior", "sumar"),
    [
        ("analizando", False),
        ("esperando_operador", False),
        ("derivada", False),
        ("esperando_operador", True),
    ],
)
def test_se_pueden_retomar_llamadas_guardadas_con_el_grafo_anterior(
    tmp_path, abrir_servicio, estado_anterior, sumar
):
    ruta = tmp_path / "llamadas.sqlite"
    pendiente = estado_anterior == "analizando"

    def analizar_sin_marca(estado):
        cambios = grafo.analizar(estado, con_modelo=pendiente)
        del cambios["falta_el_modelo"]
        del cambios["turnos_analizados"]
        return cambios

    def no_consultar(estado):
        pytest.fail("El grafo anterior se interrumpe antes de consultar el modelo.")

    def esperar_solo_ajustes(estado):
        respuesta = interrupt({"sugerencia": estado["sugerencia"]})
        return {"ajustes": respuesta["ajustes"]}

    anterior = StateGraph(grafo.Estado)
    anterior.add_node("analizar", analizar_sin_marca)
    anterior.add_node("esperar_operador", esperar_solo_ajustes)
    anterior.add_node("derivar", grafo.derivar)
    anterior.add_edge(START, "analizar")
    if pendiente:
        anterior.add_node("consultar_modelo", no_consultar)
        anterior.add_edge("analizar", "consultar_modelo")
        anterior.add_edge("consultar_modelo", "esperar_operador")
    else:
        anterior.add_edge("analizar", "esperar_operador")
    anterior.add_edge("esperar_operador", "derivar")
    anterior.add_edge("derivar", END)
    llamada_id = "llamada-anterior"
    hilo = {"configurable": {"thread_id": llamada_id}}
    turnos = separar_hablantes([Turno(texto=TEXTO_001)])
    with closing(sqlite3.connect(ruta, check_same_thread=False)) as conexion:
        compilado = anterior.compile(checkpointer=SqliteSaver(conexion))
        compilado.invoke(
            {
                "llamada_id": llamada_id,
                "turnos": [turno.model_dump(mode="json") for turno in turnos],
            },
            hilo,
            interrupt_after=["analizar"] if pendiente else None,
        )
        if estado_anterior == "derivada":
            compilado.invoke(Command(resume={"ajustes": {}}), hilo)

    with abrir_servicio() as servicio:
        llamada = servicio.consultar(llamada_id)
        assert llamada.estado == estado_anterior
        if pendiente:
            llamada = servicio.completar_analisis(llamada_id)
            assert llamada.sugerencia.avisos[-1] == aviso_rescate("el servicio está en modo mock")
        if sumar:
            nuevo = Turno(texto="¿Sigue ahí?", hablante="operador")
            llamada = servicio.sumar_turno(llamada_id, nuevo)
            assert llamada.estado == "esperando_operador"
            assert llamada.turnos == [*turnos, nuevo]
            assert [evento.tipo for evento in servicio.consultar_historial(llamada_id).eventos] == [
                "recibida",
                "sugerencia_reglas",
                "turno_agregado",
                "sugerencia_reglas",
            ]
        if llamada.estado == "esperando_operador":
            llamada = servicio.derivar(llamada_id, Ajustes())

    assert llamada.estado == "derivada"
    assert llamada.carta.prioridad.fuente == "dataset"


def test_activar_el_modelo_permite_derivar_una_llamada_que_ya_esperaba(abrir_servicio):
    with abrir_servicio() as antes:
        inicial = alta_001(antes)

    modelo = ModeloGuionado()
    with abrir_servicio(modelo) as despues:
        assert despues.completar_analisis(inicial.llamada_id) == inicial
        assert despues.derivar(inicial.llamada_id, Ajustes()).estado == "derivada"
    assert not modelo.pedidos


def test_dos_pedidos_simultaneos_completan_la_llamada_una_sola_vez(abrir_servicio):
    consultando, terminar = Event(), Event()
    pedidos = []

    def modelo(sistema, usuario, vence):
        pedidos.append(usuario)
        consultando.set()
        assert terminar.wait(5)
        return json.dumps({**RESPUESTA, "subtipo": None})

    with abrir_servicio() as anterior:
        lista = alta_001(anterior)
    with abrir_servicio(modelo) as servicio, ThreadPoolExecutor(2) as hilos:
        inicial = alta_001(servicio)
        primero = hilos.submit(servicio.completar_analisis, inicial.llamada_id)
        try:
            assert consultando.wait(5)
            segundo = hilos.submit(servicio.completar_analisis, inicial.llamada_id)
            assert servicio.consultar(inicial.llamada_id) == inicial
            with pytest.raises(LlamadaNoEsperaOperador):
                servicio.sumar_turno(inicial.llamada_id, Turno(texto="Hay humo."))
            assert servicio.derivar(lista.llamada_id, Ajustes()).estado == "derivada"
        finally:
            terminar.set()
        assert primero.result(timeout=5) == segundo.result(timeout=5)
        assert primero.result().estado == "esperando_operador"
    assert len(pedidos) == 1


def test_la_api_devuelve_el_analisis_en_dos_tiempos(tmp_path, monkeypatch):
    modelo = ModeloGuionado(CLASIFICACION, CHECKLIST)
    configuracion = Configuracion(
        llm_provider="ollama",
        sqlite_path=tmp_path / "llamadas.sqlite",
        ollama_model="de-prueba",
        llm_timeout_s=2.5,
    )
    monkeypatch.setattr(main, "de_ollama", lambda _: modelo)
    monkeypatch.setattr(flujo, "monotonic", lambda: 100.0)
    monkeypatch.setattr(modelos, "monotonic", lambda: 100.0)

    def no_buscar(_turnos):
        pytest.fail("No corresponde buscar la ficha del dataset.")

    monkeypatch.setattr(dataset, "buscar", no_buscar)
    with TestClient(main.crear_app(configuracion)) as cliente:
        health = cliente.get("/api/health")
        assert health.status_code == 200
        assert health.json() == {"status": "ok", "llm_provider": "ollama", "modelo": "de-prueba"}
        alta = cliente.post("/api/llamadas", json={"turnos": [{"texto": TEXTO_001}]})
        assert alta.status_code == 201
        inicial = alta.json()
        assert inicial["estado"] == "analizando"
        sugerencia = inicial["sugerencia"]
        assert sugerencia["ubicacion"]["calle"]["valor"] == "Av. Corrientes"
        assert sugerencia["ubicacion"]["altura"]["valor"] == 1540
        assert sugerencia["tipo_hecho"]["fuente"] == "reglas"
        assert sugerencia["prioridad"] == {"origen": "falta"}
        ruta = f"/api/llamadas/{inicial['llamada_id']}"
        assert cliente.get(ruta).json() == inicial

        intento = cliente.post(f"{ruta}/derivar", json={})
        assert intento.status_code == 409
        assert intento.json()["detail"] == "La llamada no está esperando al operador."
        assert cliente.post("/api/llamadas/no-existe/analisis").status_code == 404
        assert not modelo.pedidos

        analisis = cliente.post(f"{ruta}/analisis")
        assert analisis.status_code == 200
        final = analisis.json()
        assert final["estado"] == "esperando_operador"
        assert final["sugerencia"]["ubicacion"] == sugerencia["ubicacion"]
        assert final["sugerencia"]["prioridad"] == {
            "origen": "inferido",
            "valor": "P2",
            "fuente": "modelo",
            "cita": {"turno": 1, "texto": CITA},
        }
        assert cliente.post(f"{ruta}/analisis").json() == cliente.get(ruta).json() == final
        assert len(modelo.pedidos) == 2
        assert [vence for _, _, vence in modelo.pedidos] == [102.5, 102.5]


def test_sumar_un_turno_reanaliza_todo_y_conserva_la_confirmacion(tmp_path, monkeypatch):
    modelo = ModeloGuionado(
        CLASIFICACION, CHECKLIST, CLASIFICACION, '{"corresponde": true, "respuestas": []}'
    )
    configuracion = Configuracion(
        llm_provider="ollama", sqlite_path=tmp_path / "llamadas.sqlite", ollama_model="de-prueba"
    )
    monkeypatch.setattr(main, "de_ollama", lambda _: modelo)
    nueva_respuesta = "Los clientes ya salieron."
    with TestClient(main.crear_app(configuracion)) as cliente:
        alta = cliente.post("/api/llamadas", json={"turnos": [{"texto": TEXTO_001}]}).json()
        ruta = f"/api/llamadas/{alta['llamada_id']}"
        turno = {"texto": f"Operador: ¿Hay clientes? Llamante: {nueva_respuesta}"}
        assert cliente.post(f"{ruta}/turnos", json={"turno": turno}).status_code == 409
        assert cliente.get(ruta).json() == alta
        primera = cliente.post(f"{ruta}/analisis").json()
        propuesta = primera["sugerencia"]["checklist"][0]
        assert not propuesta["respondida"] and propuesta["cita"]

        respuesta = cliente.post(f"{ruta}/turnos", json={"turno": turno})
        assert respuesta.status_code == 200
        ampliada = respuesta.json()
        assert ampliada["estado"] == "analizando"
        assert ampliada["turnos"][:2] == primera["turnos"]
        assert ampliada["turnos"][-1] == {"texto": nueva_respuesta, "hablante": "llamante"}
        assert ampliada["sugerencia"]["ubicacion"] == primera["sugerencia"]["ubicacion"]
        assert ampliada["sugerencia"]["prioridad"] == {"origen": "falta"}
        assert ampliada["sugerencia"]["tipo_hecho"]["fuente"] == "reglas"
        assert len(modelo.pedidos) == 2
        assert cliente.post(f"{ruta}/turnos", json={"turno": turno}).status_code == 409

        final = cliente.post(f"{ruta}/analisis").json()
        assert final["estado"] == "esperando_operador"
        assert final["sugerencia"]["prioridad"]["fuente"] == "modelo"
        assert final["sugerencia"]["checklist"][0]["cita"] is None
        assert [usuario for _, usuario, _ in modelo.pedidos] == [
            f"Lo que dijo el llamante:\n{TEXTO}",
            f"Lo que dijo el llamante:\n{TEXTO}",
            f"Lo que dijo el llamante:\n{TEXTO}\n{nueva_respuesta}",
            f"Lo que dijo el llamante:\n{TEXTO}\n{nueva_respuesta}",
        ]

        marca = {"id": propuesta["id"], "respondida": True, "cita": propuesta["cita"]}
        invalida = {**marca, "cita": {"turno": 2, "texto": "¿Hay clientes?"}}
        assert (
            cliente.post(f"{ruta}/derivar", json={"ajustes": {"checklist": [invalida]}}).status_code
            == 422
        )
        assert cliente.get(ruta).json() == final
        derivada = cliente.post(f"{ruta}/derivar", json={"ajustes": {"checklist": [marca]}})
        assert derivada.status_code == 200
        assert derivada.json()["carta"]["checklist"][0] == {
            **propuesta,
            "respondida": True,
            "del_operador": True,
        }
        historial = cliente.get(f"{ruta}/historial").json()

    assert [evento["tipo"] for evento in historial["eventos"]] == [
        "recibida",
        "sugerencia_reglas",
        "sugerencia_modelo",
        "turno_agregado",
        "sugerencia_reglas",
        "sugerencia_modelo",
        "ajustes_operador",
        "derivada",
    ]
    (cambio,) = historial["cambios"]
    assert cambio["campo"] == f"pregunta {propuesta['id']}"
    assert cambio["sugerido"] == {"respondida": False, "propuesta": False}
    assert cambio["final"] == {"respondida": True, "propuesta": False}


def test_en_mock_el_alta_ya_espera_al_operador_y_completar_no_cambia_la_llamada(cliente):
    inicial = cliente.post("/api/llamadas", json={"turnos": [{"texto": TEXTO_001}]}).json()
    assert inicial["estado"] == "esperando_operador"
    assert inicial["sugerencia"]["prioridad"]["fuente"] == "dataset"
    analisis = cliente.post(f"/api/llamadas/{inicial['llamada_id']}/analisis")
    assert analisis.status_code == 200
    assert analisis.json() == inicial


@pytest.mark.parametrize(
    ("respuestas", "detalle"),
    [
        pytest.param([CLASIFICACION, CHECKLIST], "Sugerencia del modelo, sin avisos.", id="modelo"),
        pytest.param(
            [ModeloNoDisponible("el modelo no respondió a tiempo")],
            "El modelo no respondió: quedó la sugerencia de las reglas.",
            id="rescate",
        ),
    ],
)
def test_el_historial_registra_el_resultado_del_modelo_en_sqlite(
    abrir_servicio, respuestas, detalle
):
    with abrir_servicio(ModeloGuionado(*respuestas)) as servicio:
        llamada_id = alta_001(servicio).llamada_id
        inicial = servicio.consultar_historial(llamada_id)
        assert [evento.tipo for evento in inicial.eventos] == ["recibida", "sugerencia_reglas"]

        servicio.completar_analisis(llamada_id)
        servicio.derivar(llamada_id, Ajustes())
        historial = servicio.consultar_historial(llamada_id)

    assert historial.eventos[:2] == inicial.eventos
    assert [evento.tipo for evento in historial.eventos[2:]] == [
        "sugerencia_modelo",
        "ajustes_operador",
        "derivada",
    ]
    assert historial.eventos[2].detalle == detalle
    assert historial.eventos[3].detalle == "El operador confirmó sin cambios."
    assert historial.cambios == []


SIN_RESPUESTAS = '{"corresponde": true, "respuestas": []}'


def _prioridades_al_sumar_un_turno(abrir_servicio, segunda_prioridad):
    segunda = json.dumps({**RESPUESTA, "prioridad": segunda_prioridad})
    modelo = ModeloGuionado(CLASIFICACION, SIN_RESPUESTAS, segunda, SIN_RESPUESTAS)
    with abrir_servicio(modelo) as servicio:
        llamada_id = alta_001(servicio).llamada_id
        antes = servicio.completar_analisis(llamada_id).sugerencia
        a_medias = servicio.sumar_turno(llamada_id, Turno(hablante="llamante", texto="Ya salió."))
        despues = servicio.completar_analisis(llamada_id).sugerencia
        carta = servicio.derivar(llamada_id, Ajustes()).carta
    return antes, a_medias.sugerencia, despues, carta


def test_si_al_sumar_un_turno_cambia_la_prioridad_sugerida_se_avisa(abrir_servicio):
    antes, a_medias, despues, carta = _prioridades_al_sumar_un_turno(abrir_servicio, "P3")

    assert antes.prioridad.valor == "P2" and despues.prioridad.valor == "P3"
    # Mientras el modelo no respondió todavía no hay con qué comparar.
    assert "prioridad_cambiada" not in [aviso.codigo for aviso in a_medias.avisos]
    (aviso,) = [aviso for aviso in despues.avisos if aviso.codigo == "prioridad_cambiada"]
    assert aviso.mensaje == (
        "Al volver a analizar la llamada, la prioridad sugerida pasó de P2 a P3. Confirmala."
    )
    # Es para quien revisa la sugerencia: no viaja a la carta.
    assert "prioridad_cambiada" not in [aviso.codigo for aviso in carta.avisos]


def test_si_al_sumar_un_turno_la_prioridad_sugerida_no_cambia_no_se_avisa(abrir_servicio):
    antes, _, despues, _ = _prioridades_al_sumar_un_turno(abrir_servicio, "P2")

    assert antes.prioridad.valor == despues.prioridad.valor == "P2"
    assert "prioridad_cambiada" not in [aviso.codigo for aviso in despues.avisos]


def test_si_el_reanalisis_se_queda_sin_prioridad_sugerida_se_avisa(abrir_servicio):
    clasificacion = json.dumps({**RESPUESTA, "prioridad": "P1"})
    modelo = ModeloGuionado(clasificacion, SIN_RESPUESTAS, ModeloNoDisponible("sin respuesta"))
    with abrir_servicio(modelo) as servicio:
        llamada = servicio.iniciar([Turno(texto="Hay un choque en Corrientes 1540.")])
        antes = servicio.completar_analisis(llamada.llamada_id).sugerencia
        a_medias = servicio.sumar_turno(llamada.llamada_id, Turno(texto="Ya llegó la policía."))
        despues = servicio.completar_analisis(llamada.llamada_id).sugerencia

    assert antes.prioridad.valor == "P1"
    assert "prioridad_cambiada" not in [aviso.codigo for aviso in antes.avisos]
    assert "prioridad_cambiada" not in [aviso.codigo for aviso in a_medias.sugerencia.avisos]
    assert despues.prioridad == Falta()
    (aviso,) = [aviso for aviso in despues.avisos if aviso.codigo == "prioridad_cambiada"]
    assert aviso.mensaje == (
        "Antes de volver a analizar, la prioridad sugerida era P1. "
        "Ahora no hay una sugerencia: elegila."
    )
