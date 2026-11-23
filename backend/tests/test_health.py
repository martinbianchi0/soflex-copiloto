import pytest
from pydantic import ValidationError

from copiloto.config import Configuracion


def test_health_responde_ok_y_dice_el_proveedor(cliente):
    respuesta = cliente.get("/api/health")

    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "status": "ok",
        "llm_provider": "mock",
        "modelo": None,
        "proveedores": ["mock"],
    }


def test_un_proveedor_desconocido_no_arranca(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "inventado")

    with pytest.raises(ValidationError):
        Configuracion()


def test_la_configuracion_del_modelo_se_lee_del_entorno(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    predeterminada = Configuracion()
    assert predeterminada.ollama_model == "qwen3.5:4b-q4_K_M"
    assert predeterminada.ollama_base_url == "http://localhost:11434"
    assert predeterminada.llm_timeout_s == 60

    monkeypatch.setenv("OLLAMA_MODEL", "modelo-de-prueba")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama:11434")
    monkeypatch.setenv("LLM_TIMEOUT_S", "0.5")
    configurada = Configuracion()
    assert configurada.llm_provider == "ollama"
    assert configurada.ollama_model == "modelo-de-prueba"
    assert configurada.ollama_base_url == "http://ollama:11434"
    assert configurada.llm_timeout_s == 0.5


@pytest.mark.parametrize("tiempo", [0, -1])
def test_el_tiempo_del_modelo_tiene_que_ser_positivo(tiempo):
    with pytest.raises(ValidationError):
        Configuracion(llm_timeout_s=tiempo)
