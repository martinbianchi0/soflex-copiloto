"""Patentes y teléfonos dictados por el llamante.

Son reglas: no interviene el modelo. Un dato se busca después de la palabra que lo anuncia
("patente", "mi celular es") o al empezar la respuesta a una pregunta del operador que lo pide.
Lo que tiene la forma de un dato pero no llega a ser uno entero se avisa, para que el operador
pida que lo repitan. Sólo agrega: la dirección se lee del mismo texto, sin cambios.
"""

import re
from collections.abc import Iterator

from copiloto.esquemas import (
    MAXIMO_DE_DICTADOS,
    MAXIMO_DE_TEXTO,
    Aviso,
    Cita,
    DatoDictado,
    TipoDictado,
    Turno,
    texto_plano,
)
from copiloto.turnos import tramos_del_llamante

_PALABRA = re.compile(r"[\w\u0300-\u036f]+")
_ANUNCIOS: dict[tuple[str, ...], TipoDictado] = {
    ("patente",): "patente",  # También cubre «chapa patente».
    ("dominio",): "patente",
    ("telefono",): "telefono",
    ("celular",): "telefono",
    ("mi", "numero"): "telefono",
    ("llamame", "al"): "telefono",
    ("llamenme", "al"): "telefono",
    ("me", "pueden", "llamar", "al"): "telefono",
    ("me", "llaman", "al"): "telefono",
    ("contacto",): "telefono",
}
_FINALES_DE_ANUNCIO = {palabras[-1] for palabras in _ANUNCIOS}
_LARGO_DEL_ANUNCIO_MAS_LARGO = max(len(palabras) for palabras in _ANUNCIOS)
# «No le vi la patente», «sin teléfono»: nombrar el dato así no es anunciarlo.
_NEGACIONES = {"no", "sin", "ni", "nunca", "tampoco"}
_PALABRAS_ANTES_DEL_ANUNCIO = 4
# Lo que nombra el operador cuando pide que le dicten un dato.
_PEDIDOS: dict[str, TipoDictado] = {
    "patente": "patente",
    "dominio": "patente",
    "telefono": "telefono",
    "celular": "telefono",
}
# Con lo que puede arrancar una respuesta antes del dato: «Sí, era…», «Anote: …».
_ARRANQUES = re.compile(r"si|perdon|claro|dale|bueno|ok|mire|mira|anote|anota|es|era|la|el|mi|al|y")
_MAXIMO_DE_ARRANQUES = 4
_ANTES_DE_UNA_PALABRA = re.compile(r"[^\w]*")
_MAXIMO_DE_PALABRAS = 8
_PAUSA = re.compile(r"[ \t]*:?[ \t]*")
_ENLACES_PATENTE = re.compile(
    r"auto|camion|camioneta|creo|de|del|dice|decia|el|era|eran|es|ese|esa|fue|la|le|"
    r"moto|numero|otro|otra|parece|que|recuerdo|son|tenia|tiene|vehiculo"
)
_PALABRAS_CORTAS = re.compile(
    _ENLACES_PATENTE.pattern + r"|ahi|al|algo|asi|bien|cada|casi|con|como|cual|dos|donde|"
    r"en|eso|esta|este|hay|iba|iban|las|lo|los|mas|me|mi|muy|ni|no|nos|o|para|pero|"
    r"por|se|ser|si|sin|su|sus|tan|te|todo|tres|tu|un|una|y|ya"
)
# Entre los grupos de una patente: espacios, un guion o un punto pegado. Un punto seguido de un
# espacio cierra la oración.
_SEPARADOR = r"(?:[ \t]*-[ \t]*|\.|[ \t]+)?"
_PATENTE = re.compile(
    rf"(?:(?P<izquierda>[a-zA-Z]+)(?P<antes>{_SEPARADOR}))?"
    rf"(?P<cifras>[0-9]+)(?:(?P<despues>{_SEPARADOR})(?P<derecha>[a-zA-Z]+))?"
)
_FORMATOS = {(2, 3, 2), (1, 3, 3), (3, 3, 0), (0, 3, 3)}

# Entre el anuncio y el número: de quién es («del vecino», «de mi marido es») y «es», «al», «:».
_ENLACE_TELEFONO = re.compile(
    r"[ \t]*(?:fijo\b[ \t]*)?(?:del?\b(?:[ \t]+[^\W\d]+){1,3})?[ \t]*"
    r"(?:(?:es[ \t]+el|es|al|el)\b[ \t]*)?:?[ \t]*",
    re.IGNORECASE,
)
# Entre las cifras: espacios, guiones, paréntesis o un punto pegado. Un punto seguido de un
# espacio cierra la oración: lo que sigue ya no es del teléfono.
_TELEFONO = re.compile(
    r"\+?[ \t]*(?:\([ \t]*)?[0-9]+(?:(?:[ \t()-]+|\.(?=[0-9]))[0-9]+)*(?:[ \t]*\))?"
)
_DOCUMENTO = re.compile(r"\b(?:dni|documento)\b")
_SIN_SEPARADORES = re.compile(r"[^0-9]")
# Con menos cifras no es un teléfono dictado a medias: es otra cosa («llamé al 911»).
_MINIMO_DE_UN_TELEFONO = 6

_MENSAJES: dict[TipoDictado, str] = {
    "patente": "La patente dictada («{}») no tiene un formato válido. Pedí que la repitan.",
    "telefono": "El teléfono dictado («{}») no parece completo. Pedí que lo repitan.",
}


def _es_palabra(grupo: str, texto: str, palabras: re.Pattern[str]) -> bool:
    """Si un grupo de letras es una palabra de la frase y no letras de la patente.

    Escrito en mayúsculas dentro de un texto que no lo está todo, es de la patente: «AB 123 DE».
    """
    deletreado = grupo.isupper() and not texto.isupper()
    return not deletreado and palabras.fullmatch(texto_plano(grupo)) is not None


def _patente(texto: str, desde: int) -> tuple[int, int, str | None] | None:
    for _ in range(_MAXIMO_DE_PALABRAS):
        pausa = _PAUSA.match(texto, desde)
        assert pausa is not None
        desde = pausa.end()
        enlace = _PALABRA.match(texto, desde)
        if enlace is None or not _es_palabra(enlace[0], texto, _ENLACES_PATENTE):
            break
        desde = enlace.end()
    else:
        return None

    lectura = _PATENTE.match(texto, desde)
    if lectura is None:
        return None
    izquierda, cifras, derecha = (
        lectura[grupo] or "" for grupo in ("izquierda", "cifras", "derecha")
    )
    if lectura["antes"] and (len(izquierda) > 4 or _es_palabra(izquierda, texto, _PALABRAS_CORTAS)):
        return None
    hasta = lectura.end()
    resto = _PALABRA.match(texto, hasta)
    if resto and (not lectura["despues"] or resto[0][0].isdigit()):
        return (desde, resto.end(), None) if izquierda else None
    if lectura["despues"] and (
        len(derecha) > 4
        or _es_palabra(derecha, texto, _PALABRAS_CORTAS)
        or derecha.lower() == "a"
        or resto
    ):
        derecha, hasta = "", lectura.end("cifras")

    # Se valida el grupo entero: «A 123 BCD» prima sobre «123 BCD» y «ABC 123 DEF» es ambiguo.
    grupos = izquierda, cifras, derecha
    formato = (len(izquierda), len(cifras), len(derecha))
    valor = " ".join(filter(None, grupos)).upper() if formato in _FORMATOS else None
    if valor is None and not izquierda:
        # Lo que empieza con un número y no es una patente puede ser cualquier cosa: una hora,
        # una edad, una cantidad. No alcanza para pedir que la repitan.
        return None
    return desde, hasta, valor


def _telefono_valido(literal: str, digitos: str) -> bool:
    if literal.startswith("+") and not digitos.startswith("54"):
        # De otro país: se guarda como se dictó, con el largo de un número internacional.
        return 8 <= len(digitos) <= 15
    # El 54 es el código del país sólo si el número es más largo que uno nacional:
    # «5411-2233» es un número de la Ciudad.
    if digitos.startswith("54") and len(digitos) > 10:
        digitos = digitos[2:].removeprefix("9")
    digitos = digitos.removeprefix("0")
    if len(digitos) == 10:
        digitos = digitos.removeprefix("15")
    elif len(digitos) == 12:
        for despues_de_la_caracteristica in (2, 3, 4):
            if digitos.startswith("15", despues_de_la_caracteristica):
                return True
    return len(digitos) in (8, 10)


def _telefono(texto: str, desde: int) -> tuple[int, int, str | None] | None:
    enlace = _ENLACE_TELEFONO.match(texto, desde)
    assert enlace is not None
    lectura = _TELEFONO.match(texto, enlace.end())
    if lectura is None or _PALABRA.match(texto, lectura.end()):
        return None
    literal = lectura[0]
    if literal.endswith(")") and literal.count(")") > literal.count("("):
        literal = literal[:-1].rstrip()
    digitos = _SIN_SEPARADORES.sub("", literal)
    if len(digitos) < _MINIMO_DE_UN_TELEFONO:
        return None
    # «Mi número de documento es…», «…, el DNI»: es un número, pero no un teléfono.
    alrededor = texto_plano(enlace[0] + " " + texto[lectura.end() : lectura.end() + 20])
    if _DOCUMENTO.search(alrededor):
        return None
    hasta = lectura.start() + len(literal)
    return lectura.start(), hasta, digitos if _telefono_valido(literal, digitos) else None


def _negado(texto: str, posiciones: list[re.Match[str]], palabras: list[str], inicio: int) -> bool:
    """Si alguna de las palabras de corrido antes del anuncio lo niega."""
    for indice in range(inicio - 1, max(-1, inicio - 1 - _PALABRAS_ANTES_DEL_ANUNCIO), -1):
        if not texto[posiciones[indice].end() : posiciones[indice + 1].start()].isspace():
            return False
        if palabras[indice] in _NEGACIONES:
            return True
    return False


def _lecturas(texto: str) -> Iterator[tuple[TipoDictado, int, int, str | None]]:
    posiciones = list(_PALABRA.finditer(texto))
    palabras = [texto_plano(palabra[0]) for palabra in posiciones]
    for indice, palabra in enumerate(palabras):
        if palabra not in _FINALES_DE_ANUNCIO:
            continue
        fin = posiciones[indice].end()
        for inicio in range(indice, max(-1, indice - _LARGO_DEL_ANUNCIO_MAS_LARGO), -1):
            tipo = _ANUNCIOS.get(tuple(palabras[inicio : indice + 1]))
            if tipo:
                if _negado(texto, posiciones, palabras, inicio):
                    break
                lectura = _patente(texto, fin) if tipo == "patente" else _telefono(texto, fin)
                if lectura is not None:
                    yield tipo, *lectura
                break
            if (
                inicio
                and not texto[posiciones[inicio - 1].end() : posiciones[inicio].start()].isspace()
            ):
                break


def _pedidos(turno: Turno) -> list[TipoDictado]:
    """Qué datos pide el operador que le dicten.

    Cuenta un turno con una sola pregunta: con dos, no se sabe a cuál contesta el llamante.
    """
    if turno.hablante != "operador" or turno.texto.count("?") != 1:
        return []
    nombrados = {texto_plano(palabra[0]) for palabra in _PALABRA.finditer(turno.texto)}
    return sorted({_PEDIDOS[palabra] for palabra in nombrados & _PEDIDOS.keys()})


def _respuesta(
    texto: str, tipos: list[TipoDictado]
) -> Iterator[tuple[TipoDictado, int, int, str | None]]:
    """Los datos con los que empieza la respuesta a un pedido del operador."""
    pendientes = list(tipos)
    desde = 0
    for _ in range(_MAXIMO_DE_ARRANQUES + len(tipos)):
        antes = _ANTES_DE_UNA_PALABRA.match(texto, desde)
        assert antes is not None
        desde = antes.end()
        for tipo in pendientes:
            lectura = _patente(texto, desde) if tipo == "patente" else _telefono(texto, desde)
            if lectura is not None:
                yield tipo, *lectura
                pendientes.remove(tipo)
                desde = lectura[1]
                break
        else:
            arranque = _PALABRA.match(texto, desde)
            if arranque is None or not _ARRANQUES.fullmatch(texto_plano(arranque[0])):
                return
            desde = arranque.end()
        if not pendientes:
            return


def buscar(turnos: list[Turno]) -> tuple[list[DatoDictado], list[Aviso]]:
    """Encuentra lo dictado y avisa qué tendría que repetirse."""
    datos: list[DatoDictado] = []
    avisos: list[tuple[TipoDictado, Aviso]] = []
    vistos: set[tuple[TipoDictado, str]] = set()
    for numero, turno in enumerate(turnos):
        # Un pedido vale para lo primero que contesta el llamante en el turno que sigue.
        pedidos = _pedidos(turnos[numero - 1]) if numero and turno.hablante == "llamante" else []
        for tramo in tramos_del_llamante(turno):
            lecturas = sorted(
                [*_respuesta(tramo, pedidos), *_lecturas(tramo)], key=lambda lectura: lectura[1]
            )
            pedidos = []
            anterior = 0
            for tipo, desde, hasta, valor in lecturas:
                if desde < anterior:
                    continue
                anterior = hasta
                literal = tramo[desde:hasta]
                if valor is None or len(literal) > MAXIMO_DE_TEXTO:
                    muestra = (
                        literal
                        if len(literal) <= MAXIMO_DE_TEXTO
                        else literal[:MAXIMO_DE_TEXTO] + "…"
                    )
                    aviso = Aviso(
                        codigo="dictado_incompleto", mensaje=_MENSAJES[tipo].format(muestra)
                    )
                    avisos.append((tipo, aviso))
                    continue
                nuevo = (tipo, valor) not in vistos
                if nuevo and len(datos) == MAXIMO_DE_DICTADOS:
                    continue
                # Un dato entero es la repetición que pedían los avisos anteriores de su tipo.
                avisos = [(otro, aviso) for otro, aviso in avisos if otro != tipo]
                if nuevo:
                    datos.append(
                        DatoDictado(tipo=tipo, valor=valor, cita=Cita(turno=numero, texto=literal))
                    )
                    vistos.add((tipo, valor))
    return datos, [aviso for _, aviso in avisos]
