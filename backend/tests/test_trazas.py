import json
import subprocess
import sys
from time import monotonic

import pytest
from fastapi.testclient import TestClient
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from ollama import ChatResponse, Client, Message
from opentelemetry import trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import ValidationError

from copiloto import modelo as modelos
from copiloto.config import Configuracion
from copiloto.esquemas import Ajustes, Turno, valor_de
from copiloto.llamadas import Llamadas
from copiloto.main import crear_app
from copiloto.trazas import callbacks_de_trazas

_TURNO = Turno(texto="Hay fuego en la cocina de la pizzería de Av. Corrientes 1540.")
_CLASIFICACION = '{"categoria": "INCENDIO_RESCATE", "subtipo": "SFX-001", "prioridad": "P1"}'
_REVISION = '{"corresponde": true, "respuestas": []}'


def _respuesta_al(sistema: str) -> str:
    return _REVISION if "Tipo de hecho propuesto:" in sistema else _CLASIFICACION


class _ChatDePrueba(BaseChatModel):
    model: str

    @property
    def _llm_type(self) -> str:
        return "ollama_de_prueba"

    def _generate(self, messages: list[BaseMessage], **opciones: object) -> ChatResult:
        mensaje = AIMessage(content=_respuesta_al(messages[0].text))
        return ChatResult(generations=[ChatGeneration(message=mensaje)])


class _Grabador(BaseCallbackHandler):
    def __init__(self):
        self.raices = []
        self.pedidos = []
        self.respuestas = []

    def on_chain_start(self, serializado, entrada, *, parent_run_id, name, metadata, **otros):
        if parent_run_id is None:
            self.raices.append((name, metadata["langfuse_session_id"]))

    def on_chat_model_start(self, serializado, mensajes, *, run_id, metadata, **otros):
        self.pedidos.append((run_id, metadata["langfuse_session_id"], mensajes[0]))

    def on_llm_end(self, respuesta, *, run_id, **otros):
        self.respuestas.append((run_id, respuesta.generations[0][0].text))


@pytest.fixture(autouse=True)
def entorno_sin_langfuse(monkeypatch):
    for variable in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL"):
        monkeypatch.delenv(variable, raising=False)


@pytest.fixture
def ollama_simulado(monkeypatch):
    def responder(cliente, *, messages, **opciones):
        sistema = messages[0]["content"]
        return iter(
            [
                ChatResponse(
                    message=Message(role="assistant", content=_respuesta_al(sistema)), done=True
                )
            ]
        )

    monkeypatch.setattr(Client, "chat", responder)


def test_sin_configurar_el_servicio_no_importa_langfuse(tmp_path):
    codigo = """
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from copiloto.config import Configuracion
from copiloto.main import crear_app

app = crear_app(Configuracion(sqlite_path=Path(sys.argv[1])))
with TestClient(app):
    assert not app.state.llamadas._callbacks
    assert not any(m == 'langfuse' or m.startswith('langfuse.') for m in sys.modules)
"""
    resultado = subprocess.run(
        [sys.executable, "-c", codigo, str(tmp_path / "llamadas.sqlite")],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert resultado.returncode == 0, resultado.stderr


@pytest.mark.parametrize("clave", ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"])
def test_una_sola_clave_corta_el_arranque_sin_mostrar_su_valor(monkeypatch, clave):
    monkeypatch.setenv(clave, "valor-de-prueba-que-no-debe-aparecer")
    with pytest.raises(ValidationError, match="LANGFUSE_PUBLIC_KEY y LANGFUSE_SECRET_KEY") as error:
        crear_app()
    assert "valor-de-prueba-que-no-debe-aparecer" not in str(error.value)


def test_las_claves_y_la_base_vacias_cuentan_como_ausentes(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "")
    configuracion = Configuracion()
    assert configuracion.langfuse_base_url == "http://localhost:3000"
    with callbacks_de_trazas(configuracion) as callbacks:
        assert callbacks is None


def test_la_clave_secreta_no_figura_en_la_configuracion_impresa(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "publica-de-prueba")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "secreta-de-prueba")
    assert "secreta-de-prueba" not in repr(Configuracion())


def test_el_contexto_del_grafo_llega_a_cada_pedido_del_modelo(monkeypatch, tmp_path):
    def crear(*, model, **opciones):
        return _ChatDePrueba(model=model)

    monkeypatch.setattr(modelos, "ChatOllama", crear)
    grabador = _Grabador()
    llamadas = Llamadas(
        tmp_path / "llamadas.sqlite", modelos.de_ollama(Configuracion()), callbacks=[grabador]
    )
    try:
        alta = llamadas.iniciar([_TURNO])
        llamada_id = alta.llamada_id
        assert alta.estado == "analizando"
        analisis = llamadas.completar_analisis(llamada_id)
        assert analisis.sugerencia is not None
        assert valor_de(analisis.sugerencia.subtipo) == "SFX-001"
        llamadas.sumar_turno(llamada_id, Turno(texto="Ya salieron todos."))
        llamadas.completar_analisis(llamada_id)
        assert llamadas.derivar(llamada_id, Ajustes()).carta is not None
    finally:
        llamadas.cerrar()

    assert grabador.raices == [
        (nombre, llamada_id)
        for nombre in (
            "alta",
            "analisis_del_modelo",
            "turno_sumado",
            "analisis_del_modelo",
            "derivacion",
        )
    ]
    assert [sesion for _, sesion, _ in grabador.pedidos] == [llamada_id] * 4
    assert all(_TURNO.texto in mensajes[1].text for _, _, mensajes in grabador.pedidos)
    assert grabador.respuestas == [
        (pedido, respuesta)
        for (pedido, _, _), respuesta in zip(
            grabador.pedidos, [_CLASIFICACION, _REVISION] * 2, strict=True
        )
    ]


def test_un_error_del_handler_no_cambia_el_analisis(ollama_simulado, tmp_path):
    class HandlerQueFalla(BaseCallbackHandler):
        def on_chat_model_start(self, *argumentos, **opciones):
            raise RuntimeError("falló el handler")

    llamadas = Llamadas(
        tmp_path / "llamadas.sqlite",
        modelos.de_ollama(Configuracion()),
        callbacks=[HandlerQueFalla()],
    )
    try:
        alta = llamadas.iniciar([_TURNO])
        analisis = llamadas.completar_analisis(alta.llamada_id)
        assert analisis.sugerencia is not None
        assert valor_de(analisis.sugerencia.subtipo) == "SFX-001"
    finally:
        llamadas.cerrar()


def test_langfuse_exporta_una_generacion_por_pedido(ollama_simulado, tmp_path):
    configuracion = Configuracion.model_validate(
        {
            "langfuse_public_key": "publica-en-memoria",
            "langfuse_secret_key": "secreta-de-prueba",
            "ollama_model": "modelo-de-prueba",
        }
    )
    global_antes = trace.get_tracer_provider()
    exportador = InMemorySpanExporter()
    with callbacks_de_trazas(configuracion, exportador=exportador) as callbacks:
        assert callbacks
        llamadas = Llamadas(
            tmp_path / "llamadas.sqlite", modelos.de_ollama(configuracion), callbacks=callbacks
        )
        try:
            alta = llamadas.iniciar([_TURNO])
            analisis = llamadas.completar_analisis(alta.llamada_id)
            assert analisis.estado == "esperando_operador"
        finally:
            llamadas.cerrar()

    assert trace.get_tracer_provider() is global_antes
    spans = exportador.get_finished_spans()
    raices = {span.name: span.context for span in spans if span.parent is None}
    assert set(raices) == {"alta", "analisis_del_modelo"}
    assert {span.name for span in spans if span.parent == raices["alta"]} >= {"analizar"}
    nodos_del_analisis = {
        span.name: span for span in spans if span.parent == raices["analisis_del_modelo"]
    }
    assert set(nodos_del_analisis) >= {"consultar_modelo", "esperar_operador"}
    nodo = nodos_del_analisis["consultar_modelo"]
    generaciones = sorted(
        (span for span in spans if span.attributes["langfuse.observation.type"] == "generation"),
        key=lambda span: span.start_time,
    )
    for span, respuesta in zip(generaciones, [_CLASIFICACION, _REVISION], strict=True):
        assert span.name == "ChatOllama"
        assert span.parent.span_id == nodo.context.span_id
        assert span.attributes["langfuse.observation.model.name"] == "modelo-de-prueba"
        assert span.attributes["session.id"] == alta.llamada_id
        assert span.start_time < span.end_time
        entrada = json.loads(span.attributes["langfuse.observation.input"])
        assert _TURNO.texto in entrada[1]["content"]
        salida = json.loads(span.attributes["langfuse.observation.output"])
        assert salida["content"] == respuesta


def test_langfuse_inalcanzable_no_cambia_la_llamada_y_el_cierre_es_acotado(
    ollama_simulado, tmp_path, monkeypatch
):
    configuracion = Configuracion(llm_provider="ollama", sqlite_path=tmp_path / "sin-trazas.sqlite")
    esperado = _recorrer_app(configuracion)

    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "publica-puerto-cerrado")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "secreta-de-prueba")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    configuracion = Configuracion(llm_provider="ollama", sqlite_path=tmp_path / "con-trazas.sqlite")
    assert _recorrer_app(configuracion, con_trazas=True) == esperado


def _recorrer_app(configuracion: Configuracion, *, con_trazas: bool = False):
    app = crear_app(configuracion)
    with TestClient(app) as cliente:
        assert bool(app.state.llamadas._callbacks) is con_trazas
        alta = cliente.post("/api/llamadas", json={"turnos": [_TURNO.model_dump(mode="json")]})
        assert alta.status_code == 201
        ruta = f"/api/llamadas/{alta.json()['llamada_id']}"
        analisis = cliente.post(f"{ruta}/analisis")
        assert analisis.status_code == 200
        derivacion = cliente.post(f"{ruta}/derivar", json={})
        assert derivacion.status_code == 200
        assert derivacion.json()["carta"] is not None
        antes_del_cierre = monotonic()
    assert monotonic() - antes_del_cierre < 3
    return alta.json()["sugerencia"], analisis.json()["sugerencia"]
