import csv
import subprocess
import sys
from pathlib import Path

from conftest import DATOS_EMPAQUETADOS


def test_los_extremos_tienen_coordenadas_dentro_de_la_ciudad():
    with DATOS_EMPAQUETADOS.joinpath("callejero_nodos.csv").open(encoding="utf-8") as archivo:
        nodos = list(csv.DictReader(archivo))
    ids = [int(nodo["nodo"]) for nodo in nodos]
    assert ids == sorted(set(ids))
    assert all(-58.54 <= float(nodo["lon"]) <= -58.33 for nodo in nodos)
    assert all(-34.71 <= float(nodo["lat"]) <= -34.52 for nodo in nodos)

    with DATOS_EMPAQUETADOS.joinpath("callejero_caba.csv").open(encoding="utf-8") as archivo:
        extremos = {
            int(tramo[campo])
            for tramo in csv.DictReader(archivo)
            for campo in ("nodo_ini", "nodo_fin")
        }
    assert extremos == set(ids)


def test_el_reductor_conserva_los_tramos_y_puede_escribir_los_nodos(tmp_path):
    herramienta = Path(__file__).resolve().parents[1] / "herramientas" / "reducir_callejero.py"
    oficial = tmp_path / "oficial.csv"
    reducido = tmp_path / "reducido.csv"
    con_nodos = tmp_path / "reducido_con_nodos.csv"
    nodos = tmp_path / "nodos.csv"
    columnas = (
        "nomoficial,nom_mapa,tipo_c,alt_izqini,alt_izqfin,alt_derini,alt_derfin,"
        "barrio_par,barrio_imp,com_par,com_impar"
    )
    primera = "UNA,UNA,CALLE,2,100,1,99,Flores,Flores,7,7"
    segunda = "OTRA,OTRA,CALLE,2,100,1,99,Flores,Flores,7,7"
    oficial.write_text(
        f"{columnas},geometry\n"
        f'{primera},"LINESTRING (-58.4000004 -34.6000004, -58.4015 -34.6015, -58.402 -34.602)"\n'
        f'{segunda},"LINESTRING (-58.402007 -34.602007, -58.403 -34.603)"\n',
        encoding="utf-8-sig",
    )

    subprocess.run([sys.executable, herramienta, oficial, reducido], check=True)
    assert not nodos.exists()
    subprocess.run([sys.executable, herramienta, oficial, con_nodos, "--nodos", nodos], check=True)

    assert (
        reducido.read_bytes()
        == f"{columnas},nodo_ini,nodo_fin\n{primera},0,1\n{segunda},1,2\n".encode()
    )
    assert con_nodos.read_bytes() == reducido.read_bytes()
    assert nodos.read_bytes() == (
        b"nodo,lon,lat\n0,-58.400000,-34.600000\n1,-58.402000,-34.602000\n2,-58.403000,-34.603000\n"
    )
