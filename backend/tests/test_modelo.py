from time import monotonic

import pytest
from httpx import ConnectError, ReadTimeout
from ollama import ChatResponse, Client, Message, ResponseError

from copiloto import flujo
from copiloto import modelo as modelos
from copiloto.config import Configuracion
from copiloto.esquemas import Turno
from copiloto.interprete import sistema_de_clasificacion
from copiloto.modelo import ModeloNoDisponible, de_ollama


def test_ollama_recibe_los_mensajes_y_las_opciones_al_invocarlo(monkeypatch):
    instante = 100.0
    pedidos = []
    tiempos = []

    def responder(cliente, **opciones):
        nonlocal instante
        pedidos.append(opciones)
        assert str(cliente._client.base_url) == "http://ollama:11434"
        tiempos.append(cliente._client.timeout.read)
        instante += 1
        return iter([ChatResponse(message=Message(role="assistant", content=" { } "), done=True)])

    def listar(_cliente):
        pytest.fail("La construcción del modelo no debe consultar el servidor.")

    monkeypatch.setattr(Client, "chat", responder)
    monkeypatch.setattr(Client, "list", listar)
    monkeypatch.setattr(modelos, "monotonic", lambda: instante)
    modelo = de_ollama(
        Configuracion(
            ollama_base_url="http://ollama:11434", ollama_model="de-prueba", llm_timeout_s=60
        )
    )
    assert not pedidos

    assert modelo("Reglas", "Lo que dijo el llamante", 102.5) == " { } "
    assert modelo("Reglas", "Reintento", 102.5) == " { } "
    assert tiempos == [2.5, 1.5]

    pedido = pedidos[0]
    assert pedido["model"] == "de-prueba"
    assert pedido["think"] is False
    assert pedido["keep_alive"] == "30m"
    assert [(mensaje["role"], mensaje["content"]) for mensaje in pedido["messages"]] == [
        ("system", "Reglas"),
        ("user", "Lo que dijo el llamante"),
    ]
    assert pedido["options"] == {
        "temperature": 0,
        "seed": 7,
        "num_ctx": 4096,
        "num_predict": 400,
        "presence_penalty": 0,
    }


@pytest.mark.parametrize(
    ("error", "motivo"),
    [
        (ResponseError("Modelo ausente", 404), "el modelo no está descargado en Ollama"),
        (ConnectError("Conexión rechazada"), "no hay conexión con Ollama"),
        (ReadTimeout("Sin respuesta"), "se agotó el tiempo de espera"),
        (ResponseError("Error interno", 500), "Ollama devolvió un error"),
        (RuntimeError("Error inesperado"), "Ollama devolvió un error"),
    ],
)
def test_los_errores_del_cliente_se_informan_y_registran(monkeypatch, caplog, error, motivo):
    def fallar(*_, **__):
        raise error

    monkeypatch.setattr(Client, "chat", fallar)
    modelo = de_ollama(Configuracion())

    with pytest.raises(ModeloNoDisponible) as rechazo:
        modelo("Reglas", "Lo que dijo el llamante", monotonic() + 60)
    assert rechazo.value.__cause__ is error
    assert rechazo.value.motivo == motivo

    turnos = [Turno(texto="Hay humo en Av. Corrientes al 1540.")]
    sugerencia = flujo.analizar_con_modelo(turnos, flujo.analizar_base(turnos), modelo, 60)
    assert sugerencia.avisos[-1].mensaje == (
        f"El modelo no respondió ({motivo}): esta sugerencia sale de las reglas."
    )
    (aviso,) = caplog.records
    assert aviso.levelname == "WARNING"
    assert motivo in aviso.message
    assert repr(error) in aviso.message


@pytest.mark.parametrize(("largo", "contexto"), [(100, 4096), (10_000, 8192)])
def test_ollama_usa_el_contexto_mas_chico_en_el_que_entra_el_pedido(monkeypatch, largo, contexto):
    def responder(cliente, **opciones):
        assert opciones["options"]["num_ctx"] == contexto
        return iter([ChatResponse(message=Message(role="assistant", content="{}"), done=True)])

    monkeypatch.setattr(Client, "chat", responder)
    modelo = de_ollama(Configuracion())

    assert modelo(sistema_de_clasificacion(), "a" * largo, monotonic() + 60) == "{}"


@pytest.mark.parametrize(
    ("largo", "vence", "motivo"),
    [
        (30_000, 160.0, "la llamada es demasiado larga para el modelo"),
        (100, 100.0, "se agotó el tiempo de espera"),
    ],
)
def test_si_el_pedido_no_entra_o_ya_vencio_no_se_crea_el_cliente(monkeypatch, largo, vence, motivo):
    def no_crear(**_):
        pytest.fail("No corresponde crear el cliente.")

    monkeypatch.setattr(modelos, "ChatOllama", no_crear)
    monkeypatch.setattr(modelos, "monotonic", lambda: 100.0)
    modelo = de_ollama(Configuracion())

    with pytest.raises(ModeloNoDisponible) as rechazo:
        modelo(sistema_de_clasificacion(), "a" * largo, vence)
    assert rechazo.value.motivo == motivo


def test_ollama_descarta_una_respuesta_que_llega_despues_del_vencimiento(monkeypatch):
    reloj = iter([100.0, 103.0])

    def responder(cliente, **opciones):
        return iter([ChatResponse(message=Message(role="assistant", content="{}"), done=True)])

    monkeypatch.setattr(Client, "chat", responder)
    monkeypatch.setattr(modelos, "monotonic", lambda: next(reloj))
    modelo = de_ollama(Configuracion())

    with pytest.raises(ModeloNoDisponible) as rechazo:
        modelo("Reglas", "Hay humo", 102.5)
    assert rechazo.value.motivo == "se agotó el tiempo de espera"


@pytest.mark.parametrize("tokens", [3695, 3696])
def test_ollama_descarta_la_respuesta_si_los_tokens_de_entrada_llegan_al_tope(monkeypatch, tokens):
    def responder(cliente, **opciones):
        return iter(
            [
                ChatResponse(
                    message=Message(role="assistant", content="{}"),
                    done=True,
                    prompt_eval_count=tokens,
                    eval_count=2,
                )
            ]
        )

    monkeypatch.setattr(Client, "chat", responder)
    modelo = de_ollama(Configuracion())
    vence = monotonic() + 60

    if tokens < 3696:
        assert modelo("Reglas", "Hay humo", vence) == "{}"
    else:
        with pytest.raises(ModeloNoDisponible) as rechazo:
            modelo("Reglas", "Hay humo", vence)
        assert rechazo.value.motivo == "la llamada es demasiado larga para el modelo"
