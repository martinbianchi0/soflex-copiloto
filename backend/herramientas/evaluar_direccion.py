"""Mide la segunda lectura de la dirección en llamadas sintéticas por el camino del servicio.

uv run python herramientas/evaluar_direccion.py --proveedor ollama --salida ../evaluacion/direccion-modelo.json
"""

import argparse
import json
import statistics
import tempfile
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Literal, TypedDict

from copiloto import segunda_lectura, ubicacion
from copiloto.callejero import cargar
from copiloto.config import Configuracion
from copiloto.esquemas import DireccionAlternativa, Turno, valor_de
from copiloto.llamadas import Llamadas
from copiloto.modelo import Modelo, de_ollama

if __package__:
    from .evaluar import _percentil
else:
    from evaluar import _percentil

CASOS = Path(__file__).resolve().parents[1] / "tests" / "datos" / "direcciones_dificiles.json"

type Clase = Literal["recuperable", "leer_de_vuelta", "control", "sin_direccion"]
type Resultado = Literal["bien", "corrige", "no_arregla", "equivocada", "rompe", "inventa"]
type Direccion = tuple[str | None, int | None]
RESULTADOS: tuple[Resultado, ...] = (
    "bien",
    "corrige",
    "no_arregla",
    "equivocada",
    "rompe",
    "inventa",
)

# Lo que tiene que dar esta medición para que la segunda lectura se ofrezca en el panel.
EQUIVOCADAS_MAXIMO_PCT = 5.0
CORRECCIONES_MINIMO = 0.5
MEDIANA_MAXIMA_S = 8.0
P95_MAXIMO_S = 20.0


class Esperado(TypedDict):
    calle_oficial: str | None
    altura: int | None
    esquinas_oficiales: list[str] | None
    propuesta_correcta: Literal["direccion", "ninguna"]


class Caso(TypedDict):
    id: str
    clase: Clase
    dificultad: str
    texto: str
    esperado: Esperado
    nota: str


class Medicion(TypedDict):
    id: str
    clase: Clase
    dificultad: str
    esperado: Esperado
    reglas: dict[str, object]
    con_aviso: bool
    reglas_bien: bool
    propuesta: dict[str, object] | None
    resultado: Resultado
    segundos: float
    segundos_alta: float
    segundos_segunda_lectura: float | None


class Resumen(TypedDict):
    llamadas: int
    reglas_bien: int
    resultados: dict[Resultado, int]
    equivocadas: int
    equivocadas_pct: float | None
    corrige_de_recuperables: str
    mediana: float | None
    p95: float | None
    maximo: float | None


class Cronometro:
    """Cuánto tarda el pedido de la segunda lectura: es lo que le suma al análisis."""

    def __init__(self, modelo: Modelo) -> None:
        self._modelo = modelo
        self.segundos: float | None = None

    def __call__(self, sistema: str, usuario: str, vence: float) -> str:
        if sistema != segunda_lectura.SISTEMA_CON_DATOS:
            return self._modelo(sistema, usuario, vence)
        inicio = perf_counter()
        try:
            return self._modelo(sistema, usuario, vence)
        finally:
            self.segundos = perf_counter() - inicio


def casos() -> list[Caso]:
    return json.loads(CASOS.read_text(encoding="utf-8"))


def resultado(esperado: Esperado, reglas: Direccion, propuesta: Direccion | None) -> Resultado:
    if propuesta == reglas:
        propuesta = None
    if esperado["propuesta_correcta"] == "ninguna":
        return "bien" if propuesta is None else "inventa"

    calles = {esperado["calle_oficial"]}
    # Un cruce sin altura puede quedar con cualquiera de las dos calles como principal.
    if esperado["altura"] is None:
        calles.update(esperado["esquinas_oficiales"] or [])
    if reglas[0] in calles and reglas[1] == esperado["altura"]:
        return "bien" if propuesta is None else "rompe"
    if propuesta is None:
        return "no_arregla"
    calle, altura = propuesta
    return "corrige" if calle in calles and altura == esperado["altura"] else "equivocada"


def _calle_oficial(direccion: DireccionAlternativa) -> str | None:
    callejero = cargar()
    # Algunos nombres de mapa abreviados no están indexados como texto de búsqueda.
    nombres = [
        nombre
        for nombre in callejero.tramos
        if callejero.nombre_para_mostrar(nombre) == direccion.calle
        and (direccion.altura is None or callejero.cuadras(nombre, direccion.altura))
    ]
    if len(nombres) > 1:
        posibles = segunda_lectura.resolver(callejero, direccion.calle, direccion.altura)
        nombres = [nombre for nombre in posibles if nombre in nombres]
    return nombres[0] if len(nombres) == 1 else None


def medir(caso: Caso, servicio: Llamadas, cronometro: Cronometro | None = None) -> Medicion:
    if cronometro is not None:
        cronometro.segundos = None
    inicio = time.monotonic()
    alta = servicio.iniciar([Turno(texto=caso["texto"])])
    segundos_alta = time.monotonic() - inicio
    analizada = (
        servicio.completar_analisis(alta.llamada_id) if alta.estado == "analizando" else alta
    )
    segundos = time.monotonic() - inicio
    assert alta.sugerencia is not None and analizada.sugerencia is not None
    lectura = ubicacion.interpretar(alta.turnos)
    altura = valor_de(alta.sugerencia.ubicacion.altura)
    reglas = (lectura.calle_oficial, altura)
    propuesta = analizada.sugerencia.direccion_alternativa
    oficial = _calle_oficial(propuesta) if propuesta is not None else None
    esperado = caso["esperado"]
    return {
        "id": caso["id"],
        "clase": caso["clase"],
        "dificultad": caso["dificultad"],
        "esperado": esperado,
        "reglas": {
            "calle_oficial": lectura.calle_oficial,
            "ubicacion": alta.sugerencia.ubicacion.model_dump(mode="json"),
            "avisos": [aviso.model_dump(mode="json") for aviso in alta.sugerencia.avisos],
        },
        "con_aviso": segunda_lectura.corresponde(alta.sugerencia.avisos),
        "reglas_bien": resultado(esperado, reglas, None) == "bien",
        "propuesta": (
            {**propuesta.model_dump(mode="json"), "calle_oficial": oficial}
            if propuesta is not None
            else None
        ),
        "resultado": resultado(
            esperado, reglas, (oficial, propuesta.altura) if propuesta else None
        ),
        "segundos": round(segundos, 3),
        "segundos_alta": round(segundos_alta, 3),
        "segundos_segunda_lectura": (
            round(cronometro.segundos, 3)
            if cronometro is not None and cronometro.segundos is not None
            else None
        ),
    }


def tiempo_de_la_segunda_lectura(resultados: list[Medicion]) -> dict[str, float | int | None]:
    """El tiempo que agrega el pedido, en las llamadas donde se hizo."""
    tiempos = [
        fila["segundos_segunda_lectura"]
        for fila in resultados
        if fila["segundos_segunda_lectura"] is not None
    ]
    return {
        "pedidos": len(tiempos),
        "mediana": statistics.median(tiempos) if tiempos else None,
        "p95": _percentil(tiempos, 0.95) if tiempos else None,
        "maximo": max(tiempos) if tiempos else None,
    }


def criterio(con_aviso: Resumen, agregado: dict[str, float | int | None]) -> dict[str, bool]:
    """Si lo medido en las llamadas con aviso alcanza, condición por condición."""
    corrige, recuperables = (
        int(parte) for parte in con_aviso["corrige_de_recuperables"].split("/")
    )
    equivocadas, mediana, p95 = con_aviso["equivocadas_pct"], agregado["mediana"], agregado["p95"]
    return {
        "pocas_propuestas_equivocadas": (
            equivocadas is not None and equivocadas <= EQUIVOCADAS_MAXIMO_PCT
        ),
        "corrige_al_menos_la_mitad": (
            recuperables > 0 and corrige / recuperables >= CORRECCIONES_MINIMO
        ),
        "agrega_poco_tiempo": (
            mediana is not None
            and p95 is not None
            and mediana <= MEDIANA_MAXIMA_S
            and p95 <= P95_MAXIMO_S
        ),
    }


def resumir(resultados: list[Medicion]) -> dict[str, Resumen]:
    resumen: dict[str, Resumen] = {}
    for alcance, grupo in (
        ("con_aviso", [fila for fila in resultados if fila["con_aviso"]]),
        ("todas", resultados),
    ):
        cuenta = Counter(fila["resultado"] for fila in grupo)
        equivocadas = cuenta["equivocada"] + cuenta["rompe"] + cuenta["inventa"]
        recuperables = [
            fila for fila in grupo if fila["clase"] == "recuperable" and not fila["reglas_bien"]
        ]
        corrige = sum(fila["resultado"] == "corrige" for fila in recuperables)
        tiempos = [fila["segundos"] for fila in grupo]
        resumen[alcance] = {
            "llamadas": len(grupo),
            "reglas_bien": sum(fila["reglas_bien"] for fila in grupo),
            "resultados": {nombre: cuenta[nombre] for nombre in RESULTADOS},
            "equivocadas": equivocadas,
            "equivocadas_pct": round(100 * equivocadas / len(grupo), 1) if grupo else None,
            "corrige_de_recuperables": f"{corrige}/{len(recuperables)}",
            "mediana": statistics.median(tiempos) if tiempos else None,
            "p95": _percentil(tiempos, 0.95) if tiempos else None,
            "maximo": max(tiempos) if tiempos else None,
        }
    return resumen


def markdown(resumen: dict[str, Resumen]) -> list[str]:
    lineas = [
        (
            "| Alcance | Llamadas | Reglas bien | Propuestas equivocadas | Corrige de recuperables "
            "sin resolver | Mediana (s) | P95 (s) | Máximo (s) |"
        ),
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for clave, alcance in (("con_aviso", "Con aviso que dispara"), ("todas", "Todas")):
        datos = resumen[clave]
        porcentaje = datos["equivocadas_pct"]
        equivocadas = (
            f"{datos['equivocadas']} ({porcentaje:.1f} %)" if porcentaje is not None else "—"
        )
        tiempos = " | ".join(
            f"{tiempo:.3f}" if tiempo is not None else "—"
            for tiempo in (datos["mediana"], datos["p95"], datos["maximo"])
        )
        lineas.append(
            f"| {alcance} | {datos['llamadas']} | {datos['reglas_bien']} | {equivocadas} | "
            f"{datos['corrige_de_recuperables']} | {tiempos} |"
        )
    return lineas


def main() -> None:
    opciones = argparse.ArgumentParser(description=__doc__)
    opciones.add_argument("--proveedor", choices=["mock", "ollama"], default=None)
    opciones.add_argument("--salida", type=Path, help="Dónde guardar el detalle.")
    opciones.add_argument("--solo", help="Identificadores separados por coma.")
    argumentos = opciones.parse_args()
    elegidos = (
        {identificador.strip() for identificador in argumentos.solo.split(",")}
        if argumentos.solo
        else None
    )

    configuracion = Configuracion()
    proveedor = argumentos.proveedor or configuracion.llm_provider
    modelo = Cronometro(de_ollama(configuracion)) if proveedor == "ollama" else None
    with tempfile.TemporaryDirectory() as carpeta:
        servicio = Llamadas(Path(carpeta) / "llamadas.sqlite", modelo, configuracion.llm_timeout_s)
        try:
            resultados = [
                medir(caso, servicio, modelo)
                for caso in casos()
                if elegidos is None or caso["id"] in elegidos
            ]
        finally:
            servicio.cerrar()

    resumen = resumir(resultados)
    nombre_modelo = configuracion.ollama_model if modelo else None
    print(f"## Proveedor {proveedor}" + (f" · {nombre_modelo}" if nombre_modelo else ""))
    print()
    print("\n".join(markdown(resumen)))
    agregado = tiempo_de_la_segunda_lectura(resultados)
    if agregado["pedidos"]:
        print()
        print(
            f"El pedido de la segunda lectura se hizo en {agregado['pedidos']} llamadas: "
            f"mediana {agregado['mediana']:.3f} s, percentil 95 {agregado['p95']:.3f} s, "
            f"máximo {agregado['maximo']:.3f} s."
        )
        print()
        for condicion, cumple in criterio(resumen["con_aviso"], agregado).items():
            print(f"- {condicion}: {'sí' if cumple else 'no'}")
    if argumentos.salida:
        argumentos.salida.parent.mkdir(parents=True, exist_ok=True)
        detalle = {
            "proveedor": proveedor,
            "modelo": nombre_modelo,
            "fecha": datetime.now(UTC).isoformat(timespec="seconds"),
            "resultados": resultados,
            "resumen": resumen,
            "tiempo_de_la_segunda_lectura": agregado,
        }
        argumentos.salida.write_text(
            json.dumps(detalle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
