"""Pide otra lectura de la dirección y comprueba lo que propone el modelo."""

import json
import logging
from dataclasses import dataclass

from pydantic import ValidationError

from copiloto.callejero import Callejero, cargar, normalizar
from copiloto.esquemas import Aviso, DireccionAlternativa, Turno, texto_plano, valor_de
from copiloto.modelo import Modelo, ModeloNoDisponible, tiempo_restante
from copiloto.ubicacion import Interpretacion, interpretar

DISPARAN = {"direccion_no_cierra", "calle_ambigua", "sin_calle", "cruce_sin_confirmar"}

_registro = logging.getLogger(__name__)

_SISTEMA = """Sos un segundo lector de direcciones para un operador de emergencias de la Ciudad \
de Buenos Aires. Recibís la transcripción de una llamada, la dirección que leyó un sistema de \
reglas y los avisos que dio. Tu tarea es decir si de lo que dijo el llamante sale una dirección \
distinta y mejor.

Cómo leer:
- Cuenta sólo lo que dijo el llamante. No inventes calles ni alturas que nadie dijo.
- Si el llamante se corrige («no, perdón», «digo», «me confundí»), vale lo último que dijo.
- La altura puede venir en palabras, como se dice por teléfono: «treinta y dos cincuenta» es \
3250, «veintidós setenta» es 2270, «mil quinientos cuarenta» es 1540.
- El nombre de la calle puede venir mal escrito, como suena.
- Si aparecen dos direcciones, vale la del lugar del hecho, no el domicilio de quien llama.

Cuándo NO proponer nada:
- Si la altura y la esquina que dijo el llamante no pueden ser el mismo lugar y nada de lo dicho \
indica cuál está mal: eso lo resuelve el operador preguntando.
- Si el nombre corresponde a más de una calle y nada de lo dicho indica cuál es.
- Si sólo hay un lugar de referencia (plaza, parque, estación, hospital), si el lugar queda \
fuera de la Ciudad de Buenos Aires, o si no hay ninguna ubicación.
- Si la dirección que leyeron las reglas ya es la que dijo el llamante.

Respondé sólo con un JSON, sin texto antes ni después:
{"calle": texto o null, "altura": número o null, "esquinas": [textos], "motivo": "una oración"}
Si no proponés nada, "calle" va en null. En "esquinas" van sólo las que dijo el llamante."""

SISTEMA_CON_DATOS = (
    _SISTEMA
    + """

Al final del pedido van datos del callejero sobre las calles que leyeron las reglas: a qué \
altura queda cada esquina y qué calles limitan la cuadra de la altura leída. Usalos para decidir \
si alguna altura que dijo el llamante cierra con las esquinas que dijo."""
)


@dataclass(frozen=True)
class DireccionComprobada:
    calle_oficial: str
    altura: int | None
    esquinas: tuple[str, ...]


def corresponde(avisos: list[Aviso]) -> bool:
    return any(aviso.codigo in DISPARAN for aviso in avisos)


def usuario(
    texto: str, lectura: Interpretacion, avisos: list[str], datos: list[str] | None = None
) -> str:
    ubicacion = lectura.ubicacion
    calle = valor_de(ubicacion.calle) or "ninguna"
    numero = valor_de(ubicacion.altura)
    altura = numero if numero is not None else "sin altura"
    esquinas = (
        ", ".join(
            nombre for esquina in ubicacion.esquinas if (nombre := valor_de(esquina)) is not None
        )
        or "ninguna"
    )
    lineas = "\n".join(f"- {aviso}" for aviso in avisos) or "- ninguno"
    return (
        f"Transcripción:\n{texto}\n\n"
        f"Lo que leyeron las reglas: calle: {calle}; altura: {altura}; esquinas: {esquinas}.\n"
        f"Avisos de las reglas:\n{lineas}"
        + ("\n\nDatos del callejero:\n" + "\n".join(f"- {dato}" for dato in datos) if datos else "")
    )


def pedido(turnos: list[Turno], lectura: Interpretacion) -> str:
    texto = " ".join(
        f"{turno.hablante.capitalize()}: {turno.texto}" if turno.hablante else turno.texto
        for turno in turnos
    )
    return usuario(
        texto, lectura, [aviso.mensaje for aviso in lectura.avisos], datos_del_callejero(lectura)
    )


def resolver(callejero: Callejero, nombre: str, altura: int | None = None) -> list[str]:
    candidatos = callejero.candidatos(normalizar(nombre), difuso=False)
    nombres = [c.nombre for c in candidatos if c.puntaje == candidatos[0].puntaje]
    if altura is not None:
        nombres = [n for n in nombres if callejero.cuadras(n, altura)]
    if len(nombres) > 1:
        exactos = [
            n
            for n in nombres
            if texto_plano(callejero.nombre_para_mostrar(n)) == texto_plano(nombre)
        ]
        nombres = exactos or nombres
    return nombres


def _parecidas(callejero: Callejero, nombre: str, altura: int | None) -> list[str]:
    candidatos = callejero.candidatos(normalizar(nombre))
    nombres = [c.nombre for c in candidatos if c.puntaje == candidatos[0].puntaje]
    return [n for n in nombres if altura is None or callejero.cuadras(n, altura)]


def datos_del_callejero(lectura: Interpretacion) -> list[str]:
    oficial = lectura.calle_oficial
    if not oficial:
        return []
    callejero = cargar()
    altura = valor_de(lectura.ubicacion.altura)
    calle = callejero.nombre_para_mostrar(oficial)
    datos = []
    if altura is not None:
        entre = [callejero.nombre_para_mostrar(n) for n in callejero.entrecalles(oficial, altura)]
        datos.append(
            f"La cuadra de {calle} {altura} queda entre {' y '.join(entre)}."
            if entre
            else f"La altura {altura} no existe en {calle}."
        )
    for dato in lectura.ubicacion.esquinas:
        if dato.origen != "dicho":
            continue
        esquina = dato.valor
        alturas = [
            a
            for n in resolver(callejero, esquina)
            for a in callejero.alturas_en_esquina(oficial, n)
        ]
        datos.append(
            f"{calle} cruza {esquina} a la altura {min(alturas)}-{max(alturas)}."
            if alturas
            else f"{calle} no cruza {esquina}."
        )
    return datos


def comprobar(respuesta: object) -> tuple[DireccionComprobada | None, str]:
    """La calle y la altura existen, y la dirección cierra con las esquinas propuestas."""
    if not isinstance(respuesta, dict):
        return None, "respuesta ilegible"
    calle: object = respuesta.get("calle")
    altura: object = respuesta.get("altura")
    esquinas: object = respuesta.get("esquinas")
    if not isinstance(calle, str) or not calle.strip():
        return None, "no propone"
    if isinstance(altura, str) and altura.strip().isdigit():
        try:
            altura = int(altura)
        except ValueError:
            return None, "altura ilegible"
    if altura is not None and (isinstance(altura, bool) or not isinstance(altura, int)):
        return None, "altura ilegible"
    if altura is not None and not 1 <= altura <= 99_999:
        return None, "altura fuera de rango"

    callejero = cargar()
    oficiales = resolver(callejero, calle, altura) or _parecidas(callejero, calle, altura)
    if len(oficiales) != 1:
        motivo = (
            "la calle no corresponde a un único nombre"
            if oficiales
            else "calle o altura inexistente"
        )
        return None, motivo
    oficial = oficiales[0]
    limites = set(callejero.entrecalles(oficial, altura)) if altura is not None else None
    dichas: list[str] = []
    for esquina in esquinas if isinstance(esquinas, list) else []:
        if not isinstance(esquina, str) or not esquina.strip():
            continue
        posibles = resolver(callejero, esquina)
        if limites is not None:
            buenas = [n for n in posibles if n in limites]
        else:
            buenas = [n for n in posibles if callejero.alturas_en_esquina(oficial, n)]
        if not buenas:
            return None, f"la esquina «{esquina}» no cierra con esa dirección"
        dichas.append(buenas[0])
    if altura is None and not dichas:
        return None, "sin altura ni esquina"
    return DireccionComprobada(oficial, altura, tuple(dichas)), "pasa"


def _leer_json(texto: str) -> object:
    inicio, fin = texto.find("{"), texto.rfind("}")
    if inicio < 0 or fin <= inicio:
        return None
    try:
        respuesta: object = json.loads(texto[inicio : fin + 1])
    except (ValueError, RecursionError):
        return None
    return respuesta


def consultar(turnos: list[Turno], modelo: Modelo, vence: float) -> DireccionAlternativa | None:
    try:
        tiempo_restante(vence)
        # La sugerencia pública tiene nombres para mostrar. Para las consultas al callejero se
        # necesita también el nombre oficial que encontraron las reglas.
        lectura = interpretar(turnos)
        mensaje = pedido(turnos, lectura)
        tiempo_restante(vence)
        texto = modelo(SISTEMA_CON_DATOS, mensaje, vence)
        tiempo_restante(vence)
        propuesta, motivo = comprobar(_leer_json(texto))
        tiempo_restante(vence)
    except ModeloNoDisponible as error:
        _registro.warning("No hubo segunda lectura de la dirección: %s.", error.motivo)
        return None

    if propuesta is None:
        if motivo == "respuesta ilegible":
            _registro.warning("No hubo segunda lectura de la dirección: %s.", motivo)
        elif motivo != "no propone":
            _registro.info("Se descartó la segunda lectura de la dirección: %s.", motivo)
        return None
    if (propuesta.calle_oficial, propuesta.altura) == (
        lectura.calle_oficial,
        valor_de(lectura.ubicacion.altura),
    ):
        return None

    callejero = cargar()
    try:
        return DireccionAlternativa(
            calle=callejero.nombre_para_mostrar(propuesta.calle_oficial),
            altura=propuesta.altura,
            esquinas=[callejero.nombre_para_mostrar(n) for n in propuesta.esquinas],
        )
    except ValidationError:
        _registro.info("La segunda lectura trae esquinas que no se pueden cargar en el formulario.")
        return None
