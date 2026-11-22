"""Las respuestas guardadas para los tests del panel son las que da hoy el servicio."""

import json
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).parents[2]
HERRAMIENTA = RAIZ / "backend" / "herramientas" / "capturar_respuestas.py"
GUARDADAS = RAIZ / "frontend" / "src" / "pruebas" / "respuestas"


def test_las_respuestas_guardadas_para_el_panel_estan_al_dia(tmp_path):
    subprocess.run([sys.executable, HERRAMIENTA, "--salida", tmp_path], check=True)

    capturadas = {archivo.name: archivo for archivo in tmp_path.glob("*.json")}
    guardadas = {archivo.name: archivo for archivo in GUARDADAS.glob("*.json")}
    assert capturadas.keys() == guardadas.keys()
    for nombre, capturada in capturadas.items():
        # Si esto falla, la API cambió: regenerar con `herramientas/capturar_respuestas.py`
        # y volver a correr los tests del panel.
        assert json.loads(guardadas[nombre].read_text(encoding="utf-8")) == json.loads(
            capturada.read_text(encoding="utf-8")
        ), nombre
