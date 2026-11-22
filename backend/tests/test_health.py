import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from copiloto.config import Configuracion
from copiloto.main import app


def test_health_responde_ok_y_dice_el_proveedor():
    respuesta = TestClient(app).get("/api/health")

    assert respuesta.status_code == 200
    assert respuesta.json() == {"status": "ok", "llm_provider": "mock"}


def test_un_proveedor_desconocido_no_arranca(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "inventado")

    with pytest.raises(ValidationError):
        Configuracion()
