"""Mide lo que propone el servicio a medida que llega cada intercambio de un guion."""

import argparse
import json
import statistics
import tempfile
import time
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from copiloto import callejero
from copiloto.config import Configuracion
from copiloto.esquemas import Categoria, Sugerencia, Turno, texto_plano, valor_de
from copiloto.llamadas import Llamadas
from copiloto.modelo import de_ollama

if __package__:
    from .evaluar import Contador, _percentil
else:
    from evaluar import Contador, _percentil

GUIONES = Path(__file__).resolve().parents[1] / "tests" / "datos" / "guiones.json"
SIN_DETERMINAR = Categoria.NO_DETERMINADA.value
CLASES = {
    "categoria": ("acierta", "sin_determinar", "espera", "se_adelanta", "mal"),
    "subtipo": ("acierta", "sin_subtipo", "espera", "se_adelanta", "mal"),
    "ubicacion": ("acierta", "incompleta", "sin_calle", "espera", "mal"),
    "proxima_pregunta": ("bien", "ya_respondida", "saltea_una_pendiente"),
    "primera_vez": ("antes", "igual", "despues", "nunca"),
}
POLITICAS = ("orden_del_catalogo", "salteando_posibles")
RESPUESTAS = ("bien", "de_mas", "faltan")


def clasificar_valor(
    propuesto: str | None,
    esperado: str | None,
    final: str | None,
    sin_valor: str | None,
    clase_sin_valor: str,
) -> str:
    if esperado is None:
        if propuesto == sin_valor:
            return "espera"
        return "se_adelanta" if propuesto == final else "mal"
    if propuesto == esperado:
        return "acierta"
    return clase_sin_valor if propuesto == sin_valor else "mal"


def _ubicacion_esperada(esperado: dict[str, Any]) -> dict[str, Any]:
    nombre = callejero.cargar().nombre_para_mostrar
    calle = esperado["calle_oficial"]
    esquina = esperado["esquina_oficial"]
    return {
        "calle": nombre(calle) if calle is not None else None,
        "altura": esperado["altura"],
        "esquinas": [nombre(esquina)] if esquina is not None else [],
    }


def clasificar_ubicacion(propuesto: dict[str, Any], esperado: dict[str, Any]) -> str:
    calle = propuesto["calle"]
    if esperado["calle_oficial"] is None:
        return "espera" if calle is None else "mal"
    if calle is None:
        return "sin_calle"
    referencia = _ubicacion_esperada(esperado)
    principal = texto_plano(calle)
    calle_esperada = texto_plano(referencia["calle"])
    altura, altura_esperada = propuesto["altura"], referencia["altura"]
    if altura_esperada is None and referencia["esquinas"]:
        par = {calle_esperada, texto_plano(referencia["esquinas"][0])}
        cruces = {texto_plano(esquina) for esquina in propuesto["esquinas"]}
        coincide = principal in par and par - {principal} <= cruces
        return "acierta" if coincide and altura is None else "mal"
    if principal != calle_esperada:
        return "mal"
    if altura == altura_esperada:
        return "acierta"
    return "incompleta" if altura is None else "mal"


def clasificar_respuestas(checklist: list[dict[str, Any]], respondidas: set[str]) -> dict[str, int]:
    senaladas = {item["id"] for item in checklist if item["respondida"] or item["con_cita"]}
    return {
        "bien": len(senaladas & respondidas),
        "de_mas": len(senaladas - respondidas),
        "faltan": len(respondidas - senaladas),
    }


def clasificar_proxima_pregunta(
    checklist: list[dict[str, Any]], respondidas: set[str], *, saltear_posibles: bool
) -> dict[str, str | None]:
    pendiente = next(
        (pos for pos, item in enumerate(checklist) if item["id"] not in respondidas),
        len(checklist),
    )
    sugerida = next(
        (
            pos
            for pos, item in enumerate(checklist)
            if not item["respondida"] and not (saltear_posibles and item["con_cita"])
        ),
        len(checklist),
    )
    if sugerida > pendiente:
        clase = "saltea_una_pendiente"
    elif sugerida < pendiente:
        clase = "ya_respondida"
    else:
        clase = "bien"
    return {
        "id": checklist[sugerida]["id"] if sugerida < len(checklist) else None,
        "clase": clase,
    }


def leer(
    propuesto: dict[str, Any], esperado: dict[str, Any], guion: dict[str, Any]
) -> dict[str, Any]:
    lectura: dict[str, Any] = {
        "categoria": clasificar_valor(
            propuesto["categoria"],
            esperado["categoria"],
            guion["categoria"],
            SIN_DETERMINAR,
            "sin_determinar",
        ),
        "subtipo": clasificar_valor(
            propuesto["subtipo"], esperado["subtipo"], guion["subtipo"], None, "sin_subtipo"
        ),
        "ubicacion": clasificar_ubicacion(propuesto, esperado),
    }
    if esperado["subtipo"] is not None and propuesto["subtipo"] == esperado["subtipo"]:
        checklist = propuesto["checklist"]
        respondidas = set(esperado["respondidas"])
        lectura["respuestas"] = clasificar_respuestas(checklist, respondidas)
        lectura["proxima_pregunta"] = {
            politica: clasificar_proxima_pregunta(
                checklist, respondidas, saltear_posibles=politica == "salteando_posibles"
            )
            for politica in POLITICAS
        }
    return lectura


def _propuesta(sugerencia: Sugerencia) -> dict[str, Any]:
    categoria = valor_de(sugerencia.tipo_hecho)
    ubicacion = sugerencia.ubicacion
    return {
        "categoria": categoria.value if categoria is not None else SIN_DETERMINAR,
        "subtipo": valor_de(sugerencia.subtipo),
        "calle": valor_de(ubicacion.calle),
        "altura": valor_de(ubicacion.altura),
        "esquinas": [valor_de(esquina) for esquina in ubicacion.esquinas],
        "checklist": [
            {"id": item.id, "respondida": item.respondida, "con_cita": item.cita is not None}
            for item in sugerencia.checklist
        ],
    }


def medir(guion: dict[str, Any], servicio: Llamadas, contador: Contador | None) -> dict[str, Any]:
    intercambios = []
    llamada_id = None
    for intercambio in guion["intercambios"]:
        texto = " ".join(
            f"{turno['hablante'].capitalize()}: {turno['texto']}" for turno in intercambio["turnos"]
        )
        turno = Turno(texto=texto)
        antes = contador.pedidos if contador else 0
        inicio = time.monotonic()
        if llamada_id is None:
            llamada = servicio.iniciar([turno])
            llamada_id = llamada.llamada_id
        else:
            llamada = servicio.sumar_turno(llamada_id, turno)
        if llamada.estado == "analizando":
            llamada = servicio.completar_analisis(llamada_id)
        segundos = time.monotonic() - inicio

        sugerencia = llamada.sugerencia
        assert sugerencia is not None
        esperado = intercambio["esperado"]
        propuesto = _propuesta(sugerencia)
        intercambios.append(
            {
                "esperado": esperado,
                "propuesto": propuesto,
                "avisos": [aviso.codigo for aviso in sugerencia.avisos],
                "pedidos": contador.pedidos - antes if contador else 0,
                "segundos": round(segundos, 3),
                "lectura": leer(propuesto, esperado, guion),
            }
        )
    return {"id": guion["id"], "titulo": guion["titulo"], "intercambios": intercambios}


def _comparar_primera_vez(esperado: int | None, propuesto: int | None) -> dict[str, Any]:
    if esperado is None or propuesto is None:
        clase = "nunca"
    elif propuesto < esperado:
        clase = "antes"
    elif propuesto > esperado:
        clase = "despues"
    else:
        clase = "igual"
    return {"esperado": esperado, "propuesto": propuesto, "clase": clase}


def _primer_intercambio(
    intercambios: list[dict[str, Any]], cumple: Callable[[dict[str, Any]], bool]
) -> int | None:
    return next((numero for numero, datos in enumerate(intercambios, 1) if cumple(datos)), None)


def primera_vez(guion: dict[str, Any], resultado: dict[str, Any]) -> dict[str, Any]:
    intercambios = resultado["intercambios"]
    subtipo = guion["subtipo"]
    subtipo_esperado = subtipo_propuesto = None
    if subtipo is not None:
        subtipo_esperado = _primer_intercambio(
            intercambios, lambda datos: datos["esperado"]["subtipo"] == subtipo
        )
        subtipo_propuesto = _primer_intercambio(
            intercambios, lambda datos: datos["propuesto"]["subtipo"] == subtipo
        )

    direccion_esperada = direccion_propuesta = None
    if intercambios:
        final = intercambios[-1]["esperado"]
        if final["calle_oficial"] is not None and (
            final["altura"] is not None or final["esquina_oficial"] is not None
        ):
            direccion_esperada = _primer_intercambio(
                intercambios,
                lambda datos: (
                    clasificar_ubicacion(_ubicacion_esperada(datos["esperado"]), final) == "acierta"
                ),
            )
            direccion_propuesta = _primer_intercambio(
                intercambios,
                lambda datos: clasificar_ubicacion(datos["propuesto"], final) == "acierta",
            )
    return {
        "id": guion["id"],
        "subtipo": _comparar_primera_vez(subtipo_esperado, subtipo_propuesto),
        "direccion_completa": _comparar_primera_vez(direccion_esperada, direccion_propuesta),
    }


def _cuenta(clases: tuple[str, ...], conteo: Counter[str]) -> dict[str, int]:
    return {clase: conteo[clase] for clase in clases}


def _resumir_intercambios(intercambios: list[dict[str, Any]]) -> dict[str, Any]:
    lecturas = [intercambio["lectura"] for intercambio in intercambios]
    tiempos = [intercambio["segundos"] for intercambio in intercambios]
    pedidos = [intercambio["pedidos"] for intercambio in intercambios]
    return {
        "intercambios": len(lecturas),
        **{
            campo: _cuenta(CLASES[campo], Counter(lectura[campo] for lectura in lecturas))
            for campo in ("categoria", "subtipo", "ubicacion")
        },
        "respuestas": {
            clase: sum(
                lectura["respuestas"][clase] for lectura in lecturas if "respuestas" in lectura
            )
            for clase in RESPUESTAS
        },
        "proxima_pregunta": {
            politica: _cuenta(
                CLASES["proxima_pregunta"],
                Counter(
                    lectura["proxima_pregunta"][politica]["clase"]
                    for lectura in lecturas
                    if "proxima_pregunta" in lectura
                ),
            )
            for politica in POLITICAS
        },
        "segundos": {
            "mediana": statistics.median(tiempos) if tiempos else None,
            "p95": _percentil(tiempos, 0.95) if tiempos else None,
            "maximo": max(tiempos, default=None),
        },
        "pedidos": {
            "mediana": statistics.median(pedidos) if pedidos else None,
            "maximo": max(pedidos, default=None),
        },
    }


def resumir(resultados: list[dict[str, Any]], primeras: list[dict[str, Any]]) -> dict[str, Any]:
    grupos: dict[str, list[dict[str, Any]]] = {grupo: [] for grupo in ("1", "2", "3", "4+")}
    todos = []
    for resultado in resultados:
        for numero, intercambio in enumerate(resultado["intercambios"], 1):
            grupos[str(numero) if numero < 4 else "4+"].append(intercambio)
            todos.append(intercambio)
    return {
        "por_intercambio": {grupo: _resumir_intercambios(datos) for grupo, datos in grupos.items()},
        "total": _resumir_intercambios(todos),
        "primera_vez": {
            **{
                campo: _cuenta(
                    CLASES["primera_vez"], Counter(item[campo]["clase"] for item in primeras)
                )
                for campo in ("subtipo", "direccion_completa")
            },
            "por_guion": primeras,
        },
    }


def markdown(resumen: dict[str, Any]) -> list[str]:
    grupos = [*resumen["por_intercambio"].values(), resumen["total"]]

    def fila(titulo: str, *claves: str) -> str:
        celdas = []
        for grupo in grupos:
            valor = grupo
            for clave in claves:
                valor = valor[clave]
            if valor is None:
                celdas.append("—")
            elif claves[0] == "segundos":
                celdas.append(f"{valor:.3f}")
            else:
                celdas.append(str(valor))
        return f"| {titulo} | " + " | ".join(celdas) + " |"

    lineas = [
        "| Medición por intercambio | 1 | 2 | 3 | 4+ | Total |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
        fila("Intercambios", "intercambios"),
    ]
    for campo, titulo in (
        ("categoria", "Categoría"),
        ("subtipo", "Subtipo"),
        ("ubicacion", "Ubicación"),
    ):
        lineas.extend(fila(f"{titulo} · {clase}", campo, clase) for clase in CLASES[campo])
    lineas.extend(fila(f"Respuestas · {clase}", "respuestas", clase) for clase in RESPUESTAS)
    for politica in POLITICAS:
        lineas.extend(
            fila(f"{politica} · {clase}", "proxima_pregunta", politica, clase)
            for clase in CLASES["proxima_pregunta"]
        )
    lineas.extend(
        [
            fila("Tiempo (s) · mediana", "segundos", "mediana"),
            fila("Tiempo (s) · percentil 95", "segundos", "p95"),
            fila("Tiempo (s) · máximo", "segundos", "maximo"),
            fila("Pedidos al modelo · mediana", "pedidos", "mediana"),
            fila("Pedidos al modelo · máximo", "pedidos", "maximo"),
            "",
            "| Primera vez por guion | Antes | Igual | Después | Nunca |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for campo, titulo in (
        ("subtipo", "Subtipo correcto"),
        ("direccion_completa", "Dirección completa"),
    ):
        conteo = resumen["primera_vez"][campo]
        lineas.append(f"| {titulo} | " + " | ".join(str(n) for n in conteo.values()) + " |")
    return lineas


@contextmanager
def _abrir_servicio(contador: Contador | None, espera_s: float) -> Iterator[Llamadas]:
    with tempfile.TemporaryDirectory() as carpeta:
        servicio = Llamadas(Path(carpeta) / "llamadas.sqlite", contador, espera_s)
        try:
            yield servicio
        finally:
            servicio.cerrar()


def main() -> None:
    opciones = argparse.ArgumentParser(description=__doc__)
    opciones.add_argument("--proveedor", choices=["mock", "ollama"], default=None)
    opciones.add_argument("--salida", type=Path, help="Dónde guardar el detalle.")
    opciones.add_argument("--solo", help="Identificadores separados por coma.")
    opciones.add_argument(
        "--guiones", type=Path, default=GUIONES, help="Ruta al archivo de guiones."
    )
    argumentos = opciones.parse_args()

    try:
        guiones = json.loads(argumentos.guiones.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        opciones.error(f"No se pudieron leer los guiones: {error}")
    if argumentos.solo:
        elegidos = {identificador.strip() for identificador in argumentos.solo.split(",")}
        guiones = [guion for guion in guiones if guion["id"] in elegidos]

    configuracion = Configuracion()
    proveedor = argumentos.proveedor or configuracion.llm_provider
    contador = Contador(de_ollama(configuracion)) if proveedor == "ollama" else None
    with _abrir_servicio(contador, configuracion.llm_timeout_s) as servicio:
        resultados = [medir(guion, servicio, contador) for guion in guiones]
    primeras = [
        primera_vez(guion, resultado) for guion, resultado in zip(guiones, resultados, strict=True)
    ]
    resumen = resumir(resultados, primeras)
    modelo = configuracion.ollama_model if contador else None
    print(f"## Proveedor {proveedor}" + (f" · {modelo}" if modelo else ""))
    print()
    print("\n".join(markdown(resumen)))
    if argumentos.salida:
        argumentos.salida.parent.mkdir(parents=True, exist_ok=True)
        detalle = {
            "proveedor": proveedor,
            "modelo": modelo,
            "fecha": datetime.now(UTC).isoformat(timespec="seconds"),
            "guiones": resultados,
            "resumen": resumen,
        }
        argumentos.salida.write_text(
            json.dumps(detalle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
