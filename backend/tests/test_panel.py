import pytest
from fastapi.testclient import TestClient

from copiloto.config import Configuracion
from copiloto.main import crear_app


@pytest.fixture
def con_panel(tmp_path):
    panel = tmp_path / "panel"
    panel.mkdir()
    (panel / "index.html").write_text("<title>Copiloto</title>", encoding="utf-8")
    (panel / "assets").mkdir()
    (panel / "assets" / "index-abc123.js").write_text("// panel", encoding="utf-8")
    configuracion = Configuracion(sqlite_path=tmp_path / "llamadas.sqlite", static_dir=panel)
    with TestClient(crear_app(configuracion)) as cliente:
        yield cliente


def test_la_raiz_sirve_el_panel_compilado(con_panel):
    respuesta = con_panel.get("/")

    assert respuesta.status_code == 200
    assert "<title>Copiloto</title>" in respuesta.text


def test_la_pagina_se_vuelve_a_pedir_siempre_y_los_archivos_con_huella_no(con_panel):
    pagina = con_panel.get("/")
    sin_cambios = con_panel.get("/", headers={"If-None-Match": pagina.headers["etag"]})
    archivo = con_panel.get("/assets/index-abc123.js")

    assert pagina.headers["cache-control"] == "no-cache"
    assert sin_cambios.status_code == 304
    assert sin_cambios.headers["cache-control"] == "no-cache"
    assert archivo.status_code == 200
    assert "cache-control" not in archivo.headers


def test_el_panel_no_tapa_la_api(con_panel):
    creada = con_panel.post("/api/llamadas", json={"turnos": [{"texto": "Hola."}]}).json()

    assert con_panel.get("/api/health").json()["status"] == "ok"
    assert con_panel.get(f"/api/llamadas/{creada['llamada_id']}").json() == creada


def test_con_el_panel_montado_los_errores_de_la_api_siguen_siendo_de_la_api(con_panel):
    inexistente = con_panel.get("/api/llamadas/no-existe")
    ruta_desconocida = con_panel.get("/api/no-hay-nada-aca")
    metodo_equivocado = con_panel.get("/api/llamadas/x/derivar")

    assert inexistente.status_code == 404
    assert inexistente.json() == {"detail": "No existe una llamada con ese identificador."}
    assert ruta_desconocida.status_code == 404
    assert ruta_desconocida.headers["content-type"] == "application/json"
    assert metodo_equivocado.status_code == 405
    assert metodo_equivocado.headers["allow"] == "POST"


def test_sin_panel_compilado_el_servicio_expone_solo_la_api(cliente):
    assert cliente.get("/api/health").status_code == 200
    assert cliente.get("/").status_code == 404


def test_una_carpeta_de_panel_que_no_existe_corta_el_arranque(tmp_path):
    configuracion = Configuracion(static_dir=tmp_path / "no-existe")

    with pytest.raises(RuntimeError):
        crear_app(configuracion)
