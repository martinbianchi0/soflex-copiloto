"""Cuadras del callejero cerca de una dirección para que el operador la confirme."""

import csv
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache
from importlib import resources
from math import ceil, cos, floor, hypot, radians
from threading import Lock

from copiloto.callejero import Callejero, Tramo, cargar, expandir, normalizar
from copiloto.esquemas import CuadraDelPlano, Plano, texto_plano

RADIO_DEL_PLANO_M = 250
METROS_POR_GRADO_DE_LATITUD = 110_540
METROS_POR_GRADO_DE_LONGITUD = 111_320
# -34,6 es la latitud media de la Ciudad.
_ESCALA_LONGITUD_GRILLA = METROS_POR_GRADO_DE_LONGITUD * cos(radians(-34.6))
_candado_de_carga = Lock()

type Coordenada = tuple[float, float]
type Grilla = dict[tuple[int, int], list[Tramo]]


def _celda(lon: float, lat: float) -> tuple[int, int]:
    return (
        floor(lon * _ESCALA_LONGITUD_GRILLA / RADIO_DEL_PLANO_M),
        floor(lat * METROS_POR_GRADO_DE_LATITUD / RADIO_DEL_PLANO_M),
    )


@cache
def _cargar_mapa() -> tuple[dict[int, Coordenada], Grilla]:
    ruta = resources.files("copiloto").joinpath("datos", "callejero_nodos.csv")
    with ruta.open("r", encoding="utf-8") as archivo:
        nodos = {
            int(fila["nodo"]): (float(fila["lon"]), float(fila["lat"]))
            for fila in csv.DictReader(archivo)
        }

    grilla: Grilla = defaultdict(list)
    for tramos in cargar().tramos.values():
        for tramo in tramos:
            for celda in _celdas_que_cruza(nodos[tramo.nodo_ini], nodos[tramo.nodo_fin]):
                grilla[celda].append(tramo)
    return nodos, grilla


def _celdas_que_cruza(inicio: Coordenada, fin: Coordenada) -> set[tuple[int, int]]:
    """Las celdas por las que pasa una cuadra, aunque no tenga un extremo en ellas.

    Toma un punto cada 125 m como mucho: la mitad del radio del plano.
    """
    (lon1, lat1), (lon2, lat2) = inicio, fin
    largo = hypot(
        (lon2 - lon1) * _ESCALA_LONGITUD_GRILLA, (lat2 - lat1) * METROS_POR_GRADO_DE_LATITUD
    )
    pasos = max(1, ceil(2 * largo / RADIO_DEL_PLANO_M))
    return {
        _celda(lon1 + (lon2 - lon1) * paso / pasos, lat1 + (lat2 - lat1) * paso / pasos)
        for paso in range(pasos + 1)
    }


def _distancia_al_origen(x1: float, y1: float, x2: float, y2: float) -> float:
    dx, dy = x2 - x1, y2 - y1
    largo2 = dx * dx + dy * dy
    fraccion = max(0.0, min(1.0, -(x1 * dx + y1 * dy) / largo2)) if largo2 else 0.0
    return hypot(x1 + fraccion * dx, y1 + fraccion * dy)


@cache
def _por_nombre_para_mostrar() -> dict[str, str | None]:
    """El nombre que muestra el formulario, de vuelta a su calle oficial (None si es de dos)."""
    callejero = cargar()
    indice: dict[str, str | None] = {}
    for oficial in callejero.tramos:
        clave = normalizar(callejero.nombre_para_mostrar(oficial))
        indice[clave] = None if clave in indice else oficial
    return indice


def _calles_posibles(callejero: Callejero, calle: str) -> list[str]:
    """Las calles oficiales que pueden ser `calle`; cuál es la decide dónde existe la dirección."""
    consulta = normalizar(calle)
    candidatos = callejero.candidatos(consulta, difuso=False)
    # El índice de candidatos omite "Av." al buscar. Si se escribió, distingue las avenidas.
    if "AV" in expandir(consulta.split()):
        candidatos = [
            candidato for candidato in candidatos if candidato.nombre in callejero.avenidas
        ]
    nombres = [c.nombre for c in candidatos if c.puntaje == candidatos[0].puntaje]
    como_se_muestra = _por_nombre_para_mostrar().get(consulta)
    if como_se_muestra is not None and como_se_muestra not in nombres:
        nombres.append(como_se_muestra)
    return nombres


def _ubicar_esquina(
    callejero: Callejero, nombre: str, esquinas: Sequence[str]
) -> tuple[int, int, str] | None:
    for esquina in esquinas:
        if esquina == nombre:
            continue
        extremos = {
            nodo for tramo in callejero.tramos[esquina] for nodo in (tramo.nodo_ini, tramo.nodo_fin)
        }
        for tramo in callejero.tramos[nombre]:
            for nodo, altura in ((tramo.nodo_ini, tramo.desde), (tramo.nodo_fin, tramo.hasta)):
                if nodo in extremos:
                    return nodo, altura, esquina
    return None


def _punto_a_la_altura(tramo: Tramo, altura: int, nodos: dict[int, Coordenada]) -> Coordenada:
    lon1, lat1 = nodos[tramo.nodo_ini]
    lon2, lat2 = nodos[tramo.nodo_fin]
    diferencia = tramo.hasta - tramo.desde
    fraccion = max(0.0, min(1.0, (altura - tramo.desde) / diferencia)) if diferencia else 0.5
    return lon1 + (lon2 - lon1) * fraccion, lat1 + (lat2 - lat1) * fraccion


def _cuadras_cercanas(
    callejero: Callejero,
    nombre: str,
    punto: Coordenada,
    nodos: dict[int, Coordenada],
    grilla: Grilla,
) -> list[CuadraDelPlano]:
    lon0, lat0 = punto
    radio = RADIO_DEL_PLANO_M
    escala_lon = METROS_POR_GRADO_DE_LONGITUD * cos(radians(lat0))
    delta_lon, delta_lat = radio / escala_lon, radio / METROS_POR_GRADO_DE_LATITUD
    col_min, fila_min = _celda(lon0 - delta_lon, lat0 - delta_lat)
    col_max, fila_max = _celda(lon0 + delta_lon, lat0 + delta_lat)
    tramos = dict.fromkeys(
        tramo
        for columna in range(col_min, col_max + 1)
        for fila in range(fila_min, fila_max + 1)
        for tramo in grilla.get((columna, fila), ())
    )

    def proyectar(nodo: int) -> Coordenada:
        lon, lat = nodos[nodo]
        return (lon - lon0) * escala_lon, (lat - lat0) * METROS_POR_GRADO_DE_LATITUD

    cuadras = []
    for tramo in tramos:
        x1, y1 = proyectar(tramo.nodo_ini)
        x2, y2 = proyectar(tramo.nodo_fin)
        if _distancia_al_origen(x1, y1, x2, y2) <= radio:
            cuadras.append(
                CuadraDelPlano(
                    nombre=callejero.nombre_para_mostrar(tramo.nombre),
                    x1=round(x1, 1),
                    y1=round(y1, 1),
                    x2=round(x2, 1),
                    y2=round(y2, 1),
                    principal=tramo.nombre == nombre,
                )
            )
    return cuadras


def _leyenda(
    callejero: Callejero,
    nombre: str,
    altura: int | None,
    altura_del_punto: int,
    esquina: str | None,
) -> str:
    texto = callejero.nombre_para_mostrar(nombre)
    if esquina is not None:
        # El punto es la esquina: una altura que no está en la calle no se repite como si valiera.
        texto += f" y {callejero.nombre_para_mostrar(esquina)}"
    else:
        texto += f" {altura_del_punto}"
        # En una esquina el callejero devuelve las calles de las dos cuadras: ahí no se nombran.
        cruces = [
            callejero.nombre_para_mostrar(cruce)
            for cruce in callejero.entrecalles(nombre, altura_del_punto)
        ]
        if len(cruces) == 2:
            texto += f", entre {cruces[0]} y {cruces[1]}"
    barrios = callejero.barrios(nombre, altura_del_punto, exacta=esquina is None)
    if barrios:
        texto += " · " + " / ".join(dict.fromkeys(barrio for barrio, _ in barrios))
    if esquina is not None and altura is not None:
        texto += f". La altura {altura} no figura en esa calle."
    return texto


@dataclass(frozen=True)
class _Lugar:
    nombre: str
    punto: Coordenada
    altura: int
    esquina: str | None


def _ubicar(calle: str, altura: int | None, esquinas: Sequence[str]) -> _Lugar | None:
    """La calle oficial y el punto de la dirección, o None si no hay una sola forma de ubicarla."""
    callejero = cargar()
    # Una esquina que no se reconoce no impide ubicar la dirección por su altura.
    cruces = [cruce for esquina in esquinas for cruce in _calles_posibles(callejero, esquina)]
    ubicadas: list[tuple[str, Tramo | None, tuple[int, int, str] | None]] = []
    for nombre in _calles_posibles(callejero, calle):
        tramo = (
            next(iter(callejero.tramos_en(nombre, altura)), None) if altura is not None else None
        )
        en_la_esquina = None if tramo else _ubicar_esquina(callejero, nombre, cruces)
        if tramo is not None or en_la_esquina is not None:
            ubicadas.append((nombre, tramo, en_la_esquina))
    if len(ubicadas) > 1:
        # La misma regla que al completar las entrecalles: si la dirección existe en dos calles,
        # vale la que se llama exactamente así; si no hay una sola, no se elige.
        ubicadas = [
            ubicada
            for ubicada in ubicadas
            if texto_plano(callejero.nombre_para_mostrar(ubicada[0])) == texto_plano(calle)
        ]
    if len(ubicadas) != 1:
        return None
    ((nombre, tramo, en_la_esquina),) = ubicadas

    # Dos pedidos simultáneos en la primera consulta comparten una sola carga.
    with _candado_de_carga:
        nodos, _ = _cargar_mapa()
    if tramo is not None and altura is not None:
        return _Lugar(nombre, _punto_a_la_altura(tramo, altura, nodos), altura, None)
    if en_la_esquina is not None:
        nodo, altura_de_la_esquina, esquina = en_la_esquina
        return _Lugar(nombre, nodos[nodo], altura_de_la_esquina, esquina)
    return None


def plano(calle: str, altura: int | None, esquinas: Sequence[str]) -> Plano | None:
    lugar = _ubicar(calle, altura, esquinas)
    if lugar is None:
        return None
    callejero = cargar()
    nodos, grilla = _cargar_mapa()
    return Plano(
        radio_m=RADIO_DEL_PLANO_M,
        exacto=lugar.esquina is None,
        leyenda=_leyenda(callejero, lugar.nombre, altura, lugar.altura, lugar.esquina),
        cuadras=_cuadras_cercanas(callejero, lugar.nombre, lugar.punto, nodos, grilla),
    )
