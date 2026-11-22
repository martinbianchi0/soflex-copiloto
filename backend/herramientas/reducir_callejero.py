"""Fuente: Callejero de BA Data (GCBA), licencia CC BY 2.5 AR.

Conserva los atributos y los nodos extremos de cada tramo del callejero.
"""

import argparse
import csv
import re
from pathlib import Path

TIPOS_VALIDOS = {
    "CALLE",
    "AVENIDA",
    "PASAJE",
    "BOULEVARD",
    "AUTOPISTA",
    "CALLE PEATONAL",
    "PASAJE PARTICULAR",
    "PUENTE",
}
COLUMNAS = (
    "nomoficial",
    "nom_mapa",
    "tipo_c",
    "alt_izqini",
    "alt_izqfin",
    "alt_derini",
    "alt_derfin",
    "barrio_par",
    "barrio_imp",
    "com_par",
    "com_impar",
)
COORDENADAS = re.compile(r"(-?\d+\.\d+) (-?\d+\.\d+)")


def _nodo(x: str, y: str, nodos: dict[tuple[int, int], int]) -> int:
    """Agrupa extremos a unos 3 m de distancia, en el orden del archivo oficial."""
    cx, cy = round(float(x) / 3e-5), round(float(y) / 3e-5)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if (cx + dx, cy + dy) in nodos:
                return nodos[cx + dx, cy + dy]
    nodos[cx, cy] = len(nodos)
    return nodos[cx, cy]


def reducir(origen: Path, salida: Path) -> None:
    nodos: dict[tuple[int, int], int] = {}
    with (
        origen.open(encoding="utf-8-sig", newline="") as entrada,
        salida.open("w", encoding="utf-8", newline="") as destino,
    ):
        escritor = csv.writer(destino, lineterminator="\n")
        escritor.writerow((*COLUMNAS, "nodo_ini", "nodo_fin"))
        for fila in csv.DictReader(entrada):
            nombre = fila["nomoficial"]
            if (
                fila["tipo_c"] not in TIPOS_VALIDOS
                or "SIN NOMBRE" in nombre
                or "NO OFICIAL" in nombre
            ):
                continue
            puntos = COORDENADAS.findall(fila["geometry"])
            if len(puntos) >= 2:
                inicio = _nodo(*puntos[0], nodos)
                fin = _nodo(*puntos[-1], nodos)
                escritor.writerow([*(fila[columna] for columna in COLUMNAS), inicio, fin])


if __name__ == "__main__":
    argumentos = argparse.ArgumentParser(description="Reduce el callejero oficial de CABA.")
    argumentos.add_argument("callejero_oficial", type=Path)
    argumentos.add_argument("salida", type=Path)
    opciones = argumentos.parse_args()
    reducir(opciones.callejero_oficial, opciones.salida)
