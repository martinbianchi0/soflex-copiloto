import pytest
from fastapi.testclient import TestClient

from copiloto.config import Configuracion
from copiloto.main import crear_app


@pytest.fixture
def configuracion(tmp_path):
    return Configuracion(sqlite_path=tmp_path / "llamadas.sqlite")


@pytest.fixture
def cliente(configuracion):
    with TestClient(crear_app(configuracion)) as cliente:
        yield cliente
