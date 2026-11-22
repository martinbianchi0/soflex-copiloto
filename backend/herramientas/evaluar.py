"""Mide lo que propone el servicio contra las etiquetas, llamada por llamada.

Recorre las 30 llamadas del dataset y 32 sintéticas que no son del dataset
(`tests/datos/llamadas_nuevas.json`) por el mismo camino que usa el panel (el alta y, con modelo,
el análisis) y cuenta aciertos, errores y tiempos. Con `mock` mide las reglas; con `ollama`, el
modelo configurado.

    uv run python herramientas/evaluar.py --proveedor ollama --salida ../evaluacion/modelo.json
"""

import argparse
import json
import statistics
import tempfile
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from copiloto import dataset
from copiloto.config import Configuracion
from copiloto.esquemas import Turno, valor_de
from copiloto.llamadas import Llamadas
from copiloto.modelo import Modelo, de_ollama

NUEVAS = Path(__file__).parent.parent / "tests" / "datos" / "llamadas_nuevas.json"
NIVELES = ["P1", "P2", "P3", "P4"]
SIN_DETERMINAR = "NO_DETERMINADA"


class Contador:
    """Cuenta los pedidos que recibe el modelo."""

    def __init__(self, modelo: Modelo) -> None:
        self._modelo = modelo
        self.pedidos = 0

    def __call__(self, sistema: str, usuario: str, vence: float) -> str:
        self.pedidos += 1
        return self._modelo(sistema, usuario, vence)


def casos() -> list[dict[str, Any]]:
    """Las llamadas con lo que se espera de cada una."""
    lista: list[dict[str, Any]] = []
    for protocolo, texto in dataset.transcripciones():
        ficha = dataset.buscar([Turno(texto=texto)])
        assert ficha is not None
        lista.append(
            {
                "id": protocolo.id,
                "conjunto": "dataset",
                "texto": texto,
                "categoria": ficha.categoria.value,
                "subtipo": ficha.subtipo,
                "prioridad": ficha.prioridad.value,
                "admisibles": [ficha.prioridad.value],
                "respondidas": sorted(ficha.respuestas),
            }
        )
    for nueva in json.loads(NUEVAS.read_text(encoding="utf-8")):
        lista.append(
            {
                "id": nueva["id"],
                "conjunto": "nuevas",
                "texto": nueva["texto"],
                "categoria": nueva["categoria"],
                "subtipo": None,
                "prioridad": nueva["prioridad"],
                "admisibles": nueva["prioridades_admisibles"],
                "respondidas": None,
            }
        )
    return lista


def _plano(valor: object) -> object:
    return getattr(valor, "value", valor)


def medir(caso: dict[str, Any], servicio: Llamadas, contador: Contador | None) -> dict[str, Any]:
    antes = contador.pedidos if contador else 0
    inicio = time.monotonic()
    llamada = servicio.iniciar([Turno(texto=caso["texto"])])
    alta = time.monotonic() - inicio
    if llamada.estado == "analizando":
        llamada = servicio.completar_analisis(llamada.llamada_id)
    total = time.monotonic() - inicio
    sugerencia = llamada.sugerencia
    assert sugerencia is not None
    cita = getattr(sugerencia.prioridad, "cita", None)
    return {
        "id": caso["id"],
        "conjunto": caso["conjunto"],
        "esperado": {clave: caso[clave] for clave in ("categoria", "subtipo", "prioridad")}
        | {"admisibles": caso["admisibles"], "respondidas": caso["respondidas"]},
        "propuesto": {
            "categoria": _plano(valor_de(sugerencia.tipo_hecho)),
            "subtipo": valor_de(sugerencia.subtipo),
            "prioridad": _plano(valor_de(sugerencia.prioridad)),
            "cita_prioridad": cita.texto if cita else None,
            # Las que el sistema da por respondidas y las que propone como posible respuesta.
            "respondidas": [
                item.id for item in sugerencia.checklist if item.respondida or item.cita
            ],
            "citas_del_protocolo": {
                item.id: item.cita.texto for item in sugerencia.checklist if item.cita
            },
        },
        "avisos": [aviso.codigo for aviso in sugerencia.avisos],
        "mensajes": [
            aviso.mensaje
            for aviso in sugerencia.avisos
            if aviso.codigo in ("modelo_no_disponible", "dato_descartado")
        ],
        "pedidos": (contador.pedidos - antes) if contador else 0,
        "segundos_alta": round(alta, 3),
        "segundos": round(total, 3),
    }


def _percentil(valores: list[float], p: float) -> float:
    ordenados = sorted(valores)
    return ordenados[min(len(ordenados) - 1, int(p * len(ordenados)))]


def resumir(resultados: list[dict[str, Any]], con_modelo: bool) -> list[str]:
    """El resumen de un conjunto, en líneas de Markdown."""
    lineas: list[str] = []
    total = len(resultados)
    # Una llamada que cayó en el rescate no la interpretó el modelo: cuenta como sin propuesta.
    rescates = [r for r in resultados if "modelo_no_disponible" in r["avisos"] and con_modelo]
    validos = [r for r in resultados if r not in rescates]
    lineas.append(f"- Llamadas: {total}. Sin respuesta del modelo (rescate): {len(rescates)}.")

    categoria: Counter[str] = Counter()
    for r in validos:
        propuesta = r["propuesto"]["categoria"]
        if propuesta == r["esperado"]["categoria"]:
            categoria["bien"] += 1
        elif propuesta == SIN_DETERMINAR:
            categoria["sin determinar"] += 1
        else:
            categoria["mal"] += 1
    lineas.append(
        f"- Categoría: {categoria['bien']} bien, {categoria['sin determinar']} sin determinar, "
        f"{categoria['mal']} mal."
    )

    con_subtipo = [r for r in validos if r["esperado"]["subtipo"]]
    if con_subtipo:
        bien = sum(r["propuesto"]["subtipo"] == r["esperado"]["subtipo"] for r in con_subtipo)
        ninguno = sum(r["propuesto"]["subtipo"] is None for r in con_subtipo)
        lineas.append(
            f"- Subtipo: {bien} bien, {ninguno} sin subtipo, "
            f"{len(con_subtipo) - bien - ninguno} otro, de {len(con_subtipo)}."
        )

    sin_subtipo = [r for r in validos if r["esperado"]["subtipo"] is None]
    if sin_subtipo:
        propone = sum(r["propuesto"]["subtipo"] is not None for r in sin_subtipo)
        lineas.append(
            f"- Subtipo, cuando el catálogo no tiene uno para el hecho: propone uno igual en "
            f"{propone} de {len(sin_subtipo)}."
        )

    prioridad: Counter[str] = Counter()
    for r in validos:
        propuesta, admisibles = r["propuesto"]["prioridad"], r["esperado"]["admisibles"]
        if propuesta is None:
            prioridad["sin propuesta"] += 1
            continue
        prioridad["igual a la esperada"] += propuesta == r["esperado"]["prioridad"]
        nivel = NIVELES.index(propuesta)
        if propuesta in admisibles:
            prioridad["admisible"] += 1
        elif nivel > max(NIVELES.index(p) for p in admisibles):
            prioridad["menos urgente que lo admisible"] += 1
        else:
            prioridad["más urgente que lo admisible"] += 1
    lineas.append(
        "- Prioridad: "
        + ", ".join(
            f"{prioridad[clave]} {clave}"
            for clave in (
                "igual a la esperada",
                "admisible",
                "menos urgente que lo admisible",
                "más urgente que lo admisible",
                "sin propuesta",
            )
        )
        + "."
    )
    urgentes = [r for r in resultados if r["esperado"]["prioridad"] == "P1"]
    detectadas = sum(r in validos and r["propuesto"]["prioridad"] == "P1" for r in urgentes)
    lineas.append(f"- De las {len(urgentes)} llamadas P1, propone P1 en {detectadas}.")

    con_prioridad = [r for r in validos if r["propuesto"]["prioridad"]]
    if con_modelo and con_prioridad:
        citadas = sum(r["propuesto"]["cita_prioridad"] is not None for r in con_prioridad)
        lineas.append(
            f"- La prioridad lleva una cita verificada en {citadas} de {len(con_prioridad)}."
        )

    anotados = [r for r in validos if r["esperado"]["respondidas"] is not None]
    if anotados:
        esperadas = {q for r in anotados for q in r["esperado"]["respondidas"]}
        propuestas = {q for r in anotados for q in r["propuesto"]["respondidas"]}
        lineas.append(
            f"- Preguntas del protocolo: de las {len(esperadas)} anotadas como respondidas señala "
            f"{len(esperadas & propuestas)}; señala otras {len(propuestas - esperadas)}."
        )

    descartes = sum(r["avisos"].count("dato_descartado") for r in resultados)
    lineas.append(f"- Datos descartados por no poder respaldarse: {descartes}.")
    if con_modelo:
        pedidos = [r["pedidos"] for r in resultados]
        lineas.append(
            f"- Pedidos al modelo por llamada: {statistics.mean(pedidos):.1f} en promedio, "
            f"{max(pedidos)} como máximo."
        )
    tiempos = [r["segundos"] for r in resultados]
    alta_ms = statistics.median(r["segundos_alta"] for r in resultados) * 1000
    lineas.append(
        f"- Tiempo por llamada: mediana {statistics.median(tiempos):.1f} s, "
        f"percentil 95 {_percentil(tiempos, 0.95):.1f} s, máximo {max(tiempos):.1f} s. "
        f"El alta sola, que ya trae la ubicación: mediana {alta_ms:.0f} ms."
    )
    return lineas


def main() -> None:
    opciones = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    opciones.add_argument("--proveedor", choices=["mock", "ollama"], default=None)
    opciones.add_argument("--salida", type=Path, default=None, help="Dónde guardar el detalle.")
    opciones.add_argument("--solo", default=None, help="Identificadores separados por coma.")
    argumentos = opciones.parse_args()

    configuracion = Configuracion()
    proveedor = argumentos.proveedor or configuracion.llm_provider
    contador = Contador(de_ollama(configuracion)) if proveedor == "ollama" else None
    elegidos = set(argumentos.solo.split(",")) if argumentos.solo else None

    with tempfile.TemporaryDirectory() as carpeta:
        servicio = Llamadas(
            Path(carpeta) / "llamadas.sqlite", contador, configuracion.llm_timeout_s
        )
        resultados = []
        for caso in casos():
            if elegidos is None or caso["id"] in elegidos:
                resultados.append(medir(caso, servicio, contador))
                print(".", end="", flush=True)
        servicio.cerrar()
    print()

    modelo = configuracion.ollama_model if contador else None
    print(f"## Proveedor: {proveedor}" + (f" · {modelo}" if modelo else ""))
    for conjunto, titulo in (("dataset", "Dataset"), ("nuevas", "Llamadas nuevas")):
        del_conjunto = [r for r in resultados if r["conjunto"] == conjunto]
        if del_conjunto:
            print(f"\n### {titulo}\n")
            print("\n".join(resumir(del_conjunto, contador is not None)))
    if argumentos.salida:
        argumentos.salida.parent.mkdir(parents=True, exist_ok=True)
        detalle = {
            "proveedor": proveedor,
            "modelo": modelo,
            "fecha": datetime.now(UTC).isoformat(timespec="seconds"),
            "resultados": resultados,
        }
        argumentos.salida.write_text(
            json.dumps(detalle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
