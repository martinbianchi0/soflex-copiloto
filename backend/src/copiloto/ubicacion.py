"""Interpreta lo que dijo el llamante y lo contrasta con el callejero de CABA."""

import re
import unicodedata
from bisect import bisect_left
from collections.abc import Iterator
from dataclasses import dataclass, replace
from functools import cache
from itertools import groupby

from copiloto.callejero import Callejero, Candidato, cargar, normalizar
from copiloto.esquemas import (
    Altura,
    Aviso,
    Cita,
    Dicho,
    Esquema,
    Falta,
    Inferido,
    Texto,
    Turno,
    Ubicacion,
    texto_plano,
)
from copiloto.turnos import MARCA_DE_HABLANTE

BASICOS = {
    "DOS": 2,
    "TRES": 3,
    "CUATRO": 4,
    "CINCO": 5,
    "SEIS": 6,
    "SIETE": 7,
    "OCHO": 8,
    "NUEVE": 9,
    "DIEZ": 10,
    "ONCE": 11,
    "DOCE": 12,
    "TRECE": 13,
    "CATORCE": 14,
    "QUINCE": 15,
    "DIECISEIS": 16,
    "DIECISIETE": 17,
    "DIECIOCHO": 18,
    "DIECINUEVE": 19,
    "VEINTE": 20,
    "VEINTIUNO": 21,
    "VEINTIDOS": 22,
    "VEINTITRES": 23,
    "VEINTICUATRO": 24,
    "VEINTICINCO": 25,
    "VEINTISEIS": 26,
    "VEINTISIETE": 27,
    "VEINTIOCHO": 28,
    "VEINTINUEVE": 29,
}
DECENAS = {
    "TREINTA": 30,
    "CUARENTA": 40,
    "CINCUENTA": 50,
    "SESENTA": 60,
    "SETENTA": 70,
    "OCHENTA": 80,
    "NOVENTA": 90,
}
CENTENAS = {
    "CIEN": 100,
    "CIENTO": 100,
    "DOSCIENTOS": 200,
    "TRESCIENTOS": 300,
    "CUATROCIENTOS": 400,
    "QUINIENTOS": 500,
    "SEISCIENTOS": 600,
    "SETECIENTOS": 700,
    "OCHOCIENTOS": 800,
    "NOVECIENTOS": 900,
}
# Sustantivos que se cuentan: "82 años", "180 chicos". Un número seguido de esto no es una altura.
SE_CUENTAN = {
    "ANOS",
    "ANO",
    "METROS",
    "METRO",
    "PERSONAS",
    "PERSONA",
    "VECINOS",
    "VECINO",
    "VECINAS",
    "VECINA",
    "CHICOS",
    "CHICO",
    "CHICAS",
    "CHICA",
    "NENES",
    "NENE",
    "NENAS",
    "NENA",
    "NINOS",
    "NINO",
    "NINAS",
    "NINA",
    "MINUTOS",
    "MINUTO",
    "SEGUNDOS",
    "SEGUNDO",
    "AUTOS",
    "AUTO",
    "MOTOS",
    "MOTO",
    "CAMIONETAS",
    "PISOS",
    "PISO",
    "CARRILES",
    "MANZANAS",
    "DISPAROS",
    "HORAS",
    "HORA",
    "CUADRAS",
    "CUADRA",
    "KM",
    "KILOMETROS",
    "CM",
    "MESES",
    "DIAS",
    "HERIDOS",
    "HERIDAS",
    "TIPOS",
    "TIPO",
    "HOMBRES",
    "HOMBRE",
    "MUJERES",
    "MUJER",
    "PIBES",
    "PIBE",
    "PIBAS",
    "PIBA",
    "GENTE",
    "ADULTOS",
    "ADULTAS",
    "PASAJEROS",
    "PASAJERAS",
    "CAMIONES",
    "COLECTIVOS",
    "VEHICULOS",
    "RODADOS",
    "ALUMNOS",
    "VECES",
    "POSTES",
    "ANCLAJES",
    "SUBSUELOS",
    "KILOS",
    "LITROS",
}
NUMERO_CON_FORMATO = re.compile(
    r"[0-9]{1,2}[ \t]*:[ \t]*[0-9]{2}(?::[0-9]{2})?(?:HS?)?\b"
    r"|[0-9]+(?:[ \t]*\.?[ºª°]|\.?(?:ER|RO|DO|TO|TA|MO|MA|VO|VA|NO|NA|RA|DA)\b)"
    r"|(?P<miles>[0-9]{1,3}(?:\.[0-9]{3})+)(?!\w|\.[0-9])",
    re.IGNORECASE,
)
CIERRE_DE_FRASE = re.compile(r"[^\S\n]*[.!?…\n]")
CORTE_ENTRE_PALABRAS = re.compile(r"[,.;:!?…\n]")
ANTES_DE_ALTURA = {"AL", "ALTURA", "NUMERO", "NRO", "N"}
FRASE_DEL_OPERADOR = re.compile(r"¿[^¿?¡!\n]*\??|(?:\b(?:AV|NRO)\.|[^¿?¡!.\n;])+\??", re.IGNORECASE)
PEDIDO_VERBAL = r"(?:DECIME|DIGAME|INDIQUE|INDICAME|ME DECIS|ME DICE)"
OTRO_PEDIDO = re.compile(rf"^(?:{PEDIDO_VERBAL}|A QUE|QUE|CUAL ES|CUANT[OA]S?|DONDE|CUANDO)\b")
# «¿A qué altura está la escuela?» pide la altura de la calle igual que «¿A qué altura?». Esa cola
# libre vale sólo detrás de «altura» o «numeración»: «¿Qué número tiene el colectivo?» pide otra
# cosa. Y no puede traer otra pregunta («¿a qué altura está y cuántos son?»).
OTRA_PREGUNTA = r"(?:QUE|CUAL|CUALES|CUANT[OA]S?|DONDE|CUANDO|QUIEN|QUIENES|COMO)"
PREGUNTA_POR_ALTURA = re.compile(
    rf"(?:{PEDIDO_VERBAL} )?"
    r"(?:(?:A QUE|EN QUE|QUE|CUAL ES) )?(?:LA |EL )?"
    r"(?:"
    r"(?:ALTURA|NUMERACION|NUMERO)(?: (?:DE|EN) (?P<calle>.+)| (?:ES|ESTA|ESTAN|TIENE))?"
    rf"|(?:ALTURA|NUMERACION) (?:ES|ESTA|ESTAN|QUEDA|FUE) (?!.*\b{OTRA_PREGUNTA}\b).+"
    r")"
)
CALLE_YA_DICHA = {
    "LA CALLE",
    "ESA CALLE",
    "ESTA CALLE",
    "LA AVENIDA",
    "ESA AVENIDA",
    "ESTA AVENIDA",
    "LA AV",
    "ESA AV",
    "ESTA AV",
    "LA DIRECCION",
}
MARCA_ANTES_DEL_NOMBRE = re.compile(r"^(?:LA )?(?:CALLE|AVENIDA|AV) ")
# Después de la calle, la pregunta puede seguir («¿A qué número de Argerich mandamos la
# ambulancia?»), salvo que siga con otra calle.
SIGUE_OTRA_CALLE = {"O", "Y", "E", "CON", "ESQUINA", "ESQ", "CASI"}
CONFIRMACION_DE_ALTURA = re.compile(r"AL [0-9]+(?: [0-9]{3})?")
CONTINUACION_DE_ALTURA = re.compile(r"(?:MAS O MENOS|APROXIMADAMENTE|APROXIMADO|Y PICO)")
# «Al 1500 frente a una farmacia»: lo que sigue ubica el lugar en la cuadra, no es otro número.
LUGAR_EN_LA_CUADRA = re.compile(
    rf"(?:{CONTINUACION_DE_ALTURA.pattern} )?(?:FRENTE|ENFRENTE|CERCA|AL LADO|PEGADO|JUSTO)\b"
)
OTRA_CIFRA_U_HORA = re.compile(
    r"(?:(?:(?:Y|O) (?:AL )?)?[0-9]+|Y (?:MEDIA|CUARTO)|DE LA (?:TARDE|NOCHE|MANANA))\b"
)
ETIQUETA_DEL_NUMERO = re.compile(r"(?:(?:ES|SON) )?(?:(?:EL|LA|MI|SU) )?(\w+)")
OTROS_NUMEROS = SE_CUENTAN | {
    "AMBULANCIA",
    "AMBULANCIAS",
    "TELEFONO",
    "CELULAR",
    "EDAD",
    "H",
    "HS",
    "AM",
    "PM",
}
INICIO_DE_RESPUESTA = ANTES_DE_ALTURA | {
    "",
    "NUMERACION",
    "EL",
    "EL NUMERO",
    "A LA ALTURA",
    "A LA ALTURA DE",
    "A LA ALTURA DEL",
}
SALTABLES = {"AV", "AVENIDA", "CALLE", "LA", "LAS", "EL", "LOS", "DE", "DEL", "VIAS", "VIA"}
MARCAS_DE_CALLE = {"AV", "AVENIDA", "AUTOPISTA", "CALLE"}
MARCAS_DE_CRUCE = {"CASI", "ESQUINA", "ESQ"}
MARCAS_DE_LUGAR = {
    "PARQUE",
    "PLAZA",
    "ESTACION",
    "PUENTE",
    "VIADUCTO",
    "BAJADA",
    "ROTONDA",
    "VIAS",
    "VIA",
}
CORTA_CRUCE = {
    "AHI",
    "AL",
    "CASI",
    "CERCA",
    "CON",
    "CUANDO",
    "DONDE",
    "E",
    "EN",
    "ESA",
    "ESQ",
    "ESQUINA",
    "ESTA",
    "ESTABA",
    "ESTAMOS",
    "HAY",
    "NO",
    "PARA",
    "QUE",
    "SE",
    "SENTIDO",
    "SON",
    "UN",
    "UNA",
    "VEO",
    "Y",
}
TOLERANCIA_CASI = 150


class Interpretacion(Esquema):
    ubicacion: Ubicacion
    avisos: list[Aviso]
    calle_oficial: str | None


@dataclass(frozen=True)
class _Posicion:
    turno: int
    bloque: int
    indice: int

    @property
    def tramo(self) -> tuple[int, int]:
        return self.turno, self.bloque


@dataclass(frozen=True)
class _Token:
    palabra: str
    inicio: _Posicion
    fin: _Posicion


def _calles_preguntadas(texto: str) -> list[str] | None:
    """Las calles nombradas en una pregunta por la altura. Una lista vacía deja la calle implícita."""
    calles: list[str] = []
    hubo_pedido = False
    for frase in FRASE_DEL_OPERADOR.findall(texto):
        frase = frase.strip()
        palabras = normalizar(frase)
        pregunta = frase.startswith("¿") or frase.endswith("?") or OTRO_PEDIDO.match(palabras)
        pedido = PREGUNTA_POR_ALTURA.fullmatch(palabras)
        if pedido:
            hubo_pedido = True
            calle = pedido["calle"]
            if calle and calle not in CALLE_YA_DICHA:
                calles.append(MARCA_ANTES_DEL_NOMBRE.sub("", calle))
        elif pregunta and not (hubo_pedido and CONFIRMACION_DE_ALTURA.fullmatch(palabras)):
            return None
    return calles if hubo_pedido else None


def _bloques_del_llamante(turno: Turno) -> Iterator[tuple[int, int]]:
    if turno.hablante == "operador":
        return
    marcas = list(MARCA_DE_HABLANTE.finditer(turno.texto))
    if not marcas:
        yield 0, len(turno.texto)
        return
    for marca, siguiente in zip(marcas, [*marcas[1:], None], strict=True):
        if marca[1].lower() == "llamante":
            yield marca.end(), siguiente.start() if siguiente else len(turno.texto)


def _tokens_del_llamante(turnos: list[Turno]) -> Iterator[_Token]:
    for numero, turno in enumerate(turnos):
        for inicio, fin in _bloques_del_llamante(turno):
            letras: list[str] = []
            desde = hasta = indice = inicio
            while indice < fin:
                caracter = turno.texto[indice]
                if (
                    not letras
                    and "0" <= caracter <= "9"
                    and (numero_escrito := NUMERO_CON_FORMATO.match(turno.texto, indice, fin))
                ):
                    palabra = numero_escrito[0]
                    if numero_escrito["miles"]:
                        palabra = palabra.replace(".", "")
                    yield _Token(
                        palabra.upper(),
                        _Posicion(numero, inicio, indice),
                        _Posicion(numero, inicio, numero_escrito.end()),
                    )
                    indice = numero_escrito.end()
                    continue
                indice += 1
                if unicodedata.category(caracter) == "Mn":
                    if letras:
                        hasta = indice
                    continue
                parte = caracter.upper() if caracter.isascii() and caracter.isalnum() else ""
                if not caracter.isascii():
                    parte = normalizar(caracter)
                if parte:
                    if not letras:
                        desde = indice - 1
                    letras.append(parte)
                    hasta = indice
                elif letras:
                    yield _Token(
                        "".join(letras),
                        _Posicion(numero, inicio, desde),
                        _Posicion(numero, inicio, hasta),
                    )
                    letras.clear()
            if letras:
                yield _Token(
                    "".join(letras),
                    _Posicion(numero, inicio, desde),
                    _Posicion(numero, inicio, hasta),
                )


def _numeros_en_palabras(tokens: list[_Token], turnos: list[Turno]) -> list[_Token]:
    """'MIL QUINIENTOS CUARENTA' -> '1540'. No toca 'UN/UNA' sueltos ni junta números separados."""

    def sigue_numero(antes: _Token, despues: _Token) -> bool:
        fin = antes.fin
        return fin.tramo == despues.inicio.tramo or not CIERRE_DE_FRASE.match(
            turnos[fin.turno].texto, fin.indice
        )

    # `nivel` obliga a que las palabras vayan de mayor a menor: centena (3) > decena (2) > unidad (1).
    salida: list[_Token] = []
    i = 0
    while i < len(tokens):
        total, actual, nivel, hubo_mil, j = 0, 0, 4, False, i
        while j < len(tokens):
            if j > i and not sigue_numero(tokens[j - 1], tokens[j]):
                break
            t = tokens[j].palabra
            if t == "MIL" and not hubo_mil:
                total, actual, nivel, hubo_mil = (actual or 1) * 1000, 0, 4, True
            elif t in CENTENAS and nivel > 3:
                actual, nivel = actual + CENTENAS[t], 3
            elif t in DECENAS and nivel > 2:
                actual, nivel = actual + DECENAS[t], 2
            elif t in BASICOS and nivel > 2:
                actual, nivel = actual + BASICOS[t], 1
            elif (
                t == "Y"
                and nivel == 2
                and j + 1 < len(tokens)
                and tokens[j + 1].palabra in BASICOS.keys() | {"UN", "UNO", "UNA"}
                and sigue_numero(tokens[j], tokens[j + 1])
            ):
                actual, nivel = actual + BASICOS.get(tokens[j + 1].palabra, 1), 1
                j += 1
            else:
                break
            j += 1
        if j > i:
            fin = tokens[j - 1].fin
            if tokens[i].inicio.tramo == fin.tramo:
                salida.append(replace(tokens[i], palabra=str(total + actual), fin=fin))
            else:
                # Un número interrumpido queda sin leer, tampoco vale una parte como altura.
                salida.extend(tokens[i:j])
            i = j
        else:
            salida.append(tokens[i])
            i += 1
    return salida


@dataclass(frozen=True)
class _Mencion:
    inicio: int
    fin: int
    cita: Cita
    candidatos: list[Candidato]


@dataclass(frozen=True)
class _Direccion:
    mencion: _Mencion
    calle: str
    alternativas: list[str]
    altura: Dicho[Altura]
    fin: int
    existe: bool

    def coincide_con(self, otra: "_Direccion") -> bool:
        return self.altura.valor == otra.altura.valor and bool(
            {self.calle, *self.alternativas} & {otra.calle, *otra.alternativas}
        )


class _Resolvedor:
    def __init__(self, turnos: list[Turno], callejero: Callejero) -> None:
        self.turnos = turnos
        self.cj = callejero
        self.candidatos = cache(callejero.candidatos)
        self.alturas_en_esquina = cache(callejero.alturas_en_esquina)
        self.planos: dict[int, str] = {}
        self.tokens = _numeros_en_palabras(list(_tokens_del_llamante(turnos)), turnos)
        self.palabras = [token.palabra for token in self.tokens]
        self.tramos: list[range] = []
        for _, tokens in groupby(self.tokens, key=lambda token: token.inicio.tramo):
            cantidad = sum(1 for _ in tokens)
            inicio = len(self.tramos)
            self.tramos.extend([range(inicio, inicio + cantidad)] * cantidad)

    def _cita(self, desde: int, hasta: int) -> Cita | None:
        if hasta not in self.tramos[desde]:
            return None
        inicio, fin = self.tokens[desde].inicio, self.tokens[hasta].fin
        if fin.indice - inicio.indice > 200:
            return None
        fragmento = self.turnos[inicio.turno].texto[inicio.indice : fin.indice]
        buscado = texto_plano(fragmento)
        if not buscado:
            return None
        # La cita tiene que coincidir por palabras enteras, igual que en cita_esta_en.
        if inicio.turno not in self.planos:
            self.planos[inicio.turno] = f" {texto_plano(self.turnos[inicio.turno].texto)} "
        if f" {buscado} " in self.planos[inicio.turno]:
            return Cita(turno=inicio.turno, texto=fragmento)
        return None

    def _separador(self, izquierda: int, derecha: int) -> str:
        antes, despues = self.tokens[izquierda].fin, self.tokens[derecha].inicio
        return self.turnos[antes.turno].texto[antes.indice : despues.indice]

    def _calle_antes(self, fin: int, altura: int | None) -> tuple[_Mencion | None, bool]:
        """Busca la coincidencia más larga y deja la búsqueda difusa para el final."""
        inicio_tramo = self.tramos[fin].start
        for difuso in (False, True):
            for largo in range(5, 0, -1):
                ini = fin - largo + 1
                if ini < inicio_tramo:
                    continue
                grama = self.palabras[ini : fin + 1]
                marca_anterior = ini > inicio_tramo and self.palabras[ini - 1] in MARCAS_DE_CALLE
                es_av = grama[0] in MARCAS_DE_CALLE or marca_anterior
                nombre = [palabra for palabra in grama if palabra != "CALLE"]
                if not nombre or (
                    difuso and (largo > 3 or nombre[0] in SALTABLES - {"AV", "AVENIDA"})
                ):
                    continue
                candidatos = self.candidatos(" ".join(nombre), difuso=difuso)
                if altura is not None:
                    candidatos = [c for c in candidatos if self.cj.tramos_en(c.nombre, altura)]
                if candidatos:
                    desde = ini - 1 if marca_anterior else ini
                    cita = self._cita(desde, fin) or self._cita(ini, fin)
                    if cita:
                        return _Mencion(ini, fin, cita, candidatos), es_av
        return None, False

    def _calle_despues(
        self, ini: int, limite: int, marca: int | None = None, *, exacta: bool = False
    ) -> _Mencion | None:
        inicio = ini if marca is None else marca
        prefijo = "AUTOPISTA " if marca is not None and self.palabras[marca] == "AUTOPISTA" else ""
        salteados = 0
        while ini < limite and self.palabras[ini] in SALTABLES and salteados < 4:
            ini, salteados = ini + 1, salteados + 1
        for difuso in (False,) if exacta else (False, True):
            for largo in range(4, 0, -1):
                if ini + largo > limite or (difuso and largo > 3):
                    continue
                grama = self.palabras[ini : ini + largo]
                candidatos = self.candidatos(prefijo + " ".join(grama), difuso=difuso)
                if exacta:
                    candidatos = [c for c in candidatos if c.como in ("exacto", "apellido")]
                if candidatos:
                    fin = ini + largo - 1
                    cita = self._cita(inicio, fin)
                    if cita is None and not prefijo:
                        cita = self._cita(ini, fin)
                    if cita:
                        return _Mencion(ini, fin, cita, candidatos)
        return None

    def _elegir(self, candidatos: list[Candidato], es_av: bool) -> tuple[str, list[str]]:
        if es_av and any(c.nombre in self.cj.avenidas for c in candidatos):
            candidatos = [c for c in candidatos if c.nombre in self.cj.avenidas]
        elegido, *otros = candidatos
        return elegido.nombre, [c.nombre for c in otros if c.puntaje == elegido.puntaje]

    def _altura_en(self, i: int) -> Dicho[Altura] | None:
        cifras = self.palabras[i].lstrip("0")
        if not cifras.isdigit() or len(cifras) > 5:
            return None
        if (
            i + 1 in self.tramos[i]
            and self.palabras[i + 1] in SE_CUENTAN
            and not CORTE_ENTRE_PALABRAS.search(self._separador(i, i + 1))
        ):
            return None
        cita = self._cita(i, i)
        return Dicho[Altura](valor=int(cifras), cita=cita) if cita else None

    def _direcciones(self) -> Iterator[_Direccion]:
        for i, palabra in enumerate(self.palabras):
            if not palabra.isdigit():
                continue
            tramo = self.tramos[i]
            fin = i - 1
            while fin in tramo and self.palabras[fin] in ANTES_DE_ALTURA:
                fin -= 1
            if fin not in tramo or not (dicha := self._altura_en(i)):
                continue
            altura = dicha.valor
            mencion, es_av = self._calle_antes(fin, altura)
            existe = mencion is not None
            if mencion is None:
                mencion, es_av = self._calle_antes(fin, None)
                if mencion is None:
                    continue
            candidatos = mencion.candidatos
            # Una altura fuera de rango no sirve para respaldar una coincidencia débil.
            if altura < 100 or not existe:
                candidatos = [c for c in candidatos if c.como in ("exacto", "apellido")]
            if candidatos:
                nombre, alternativas = self._elegir(candidatos, es_av)
                yield _Direccion(mencion, nombre, alternativas, dicha, i, existe)

    def _alturas_preguntadas(self, limite: int) -> Iterator[tuple[Dicho[Altura], list[str]]]:
        for inicio, tramo in enumerate(self.tramos[:limite]):
            if inicio != tramo.start or self.tokens[inicio].inicio.bloque != 0:
                continue
            numero_turno = self.tokens[inicio].inicio.turno
            if numero_turno == 0:
                continue
            anterior = self.turnos[numero_turno - 1]
            if anterior.hablante != "operador":
                continue
            calles = _calles_preguntadas(anterior.texto)
            if calles is None:
                continue
            # La respuesta a la pregunta empieza con el número o una fórmula como «al 1540».
            for i in range(inicio, min(inicio + 5, tramo.stop)):
                if " ".join(self.palabras[inicio:i]) in INICIO_DE_RESPUESTA and (
                    (altura := self._altura_en(i)) is not None and self._termina_la_altura(i, tramo)
                ):
                    yield altura, calles
                    break

    def _termina_la_altura(self, i: int, tramo: range) -> bool:
        if i + 1 not in tramo:
            return True
        despues = " ".join(self.palabras[i + 1 : tramo.stop])
        if OTRA_CIFRA_U_HORA.match(despues):
            return False
        # Una aclaración puede decir qué era el número, incluso después de una coma.
        etiqueta = ETIQUETA_DEL_NUMERO.match(despues)
        if etiqueta and etiqueta[1] in OTROS_NUMEROS:
            return False
        if (
            re.search(r"[,.;!?…\n]", self._separador(i, i + 1))
            or CONTINUACION_DE_ALTURA.fullmatch(despues)
            or LUGAR_EN_LA_CUADRA.match(despues)
        ):
            return True
        # «Al 800 más o menos, frente a…»: la pausa puede venir después de la aproximación.
        if aproximacion := CONTINUACION_DE_ALTURA.match(despues):
            fin = i + len(aproximacion[0].split())
            return fin + 1 in tramo and bool(
                re.search(r"[,.;!?…\n]", self._separador(fin, fin + 1))
            )
        return False

    def _calles_para_altura_preguntada(self, limite: int) -> Iterator[_Mencion]:
        """Busca calles dichas sin altura, incluso en «hay un choque en Corrientes»."""
        fin = -1
        for i, palabra in enumerate(self.palabras[:limite]):
            if i <= fin:
                continue
            tramo = self.tramos[i]
            if palabra in MARCAS_DE_CALLE:
                mencion = self._calle_despues(i + 1, tramo.stop, marca=i, exacta=True)
            elif (
                i == tramo.start
                or self.palabras[i - 1]
                in {
                    "EN",
                    "ES",
                    "POR",
                    "SOBRE",
                    "CON",
                    "DESDE",
                    "HASTA",
                    "O",
                    "Y",
                    "E",
                    *MARCAS_DE_CRUCE,
                }
                or CORTE_ENTRE_PALABRAS.search(self._separador(i - 1, i))
            ):
                mencion = self._calle_despues(i, tramo.stop, exacta=True)
            else:
                continue
            if mencion:
                fin = mencion.fin
                yield mencion

    def _direcciones_preguntadas(
        self,
        calles_dichas: list[_Mencion],
        respuestas: list[tuple[Dicho[Altura], list[str]]],
        limite: int,
    ) -> Iterator[_Direccion]:
        if not calles_dichas or self._en_esquina(limite):
            return
        principal = calles_dichas[0]
        es_av = normalizar(principal.cita.texto).split()[0] in {"AV", "AVENIDA"}
        elegida, alternativas = self._elegir(principal.candidatos, es_av)
        for altura, calles in respuestas:
            if altura.cita.turno <= principal.cita.turno:
                continue
            calle = elegida
            if alternativas:
                # Un nombre de dos calles: decide dónde existe la altura, como cuando se dice de corrido.
                con_altura = [
                    nombre
                    for nombre in (elegida, *alternativas)
                    if self.cj.tramos_en(nombre, altura.valor)
                ]
                if len(con_altura) != 1:
                    continue
                calle = con_altura[0]
            if any(
                c.nombre != calle and self.alturas_en_esquina(calle, c.nombre)
                for mencion in self._cruces_marcados(principal.fin, limite)
                for c in mencion.candidatos
            ):
                return
            otras = [
                normalizar(mencion.cita.texto)
                for mencion in calles_dichas
                if calle not in {c.nombre for c in mencion.candidatos}
            ]
            if any(not self._nombra_a(nombre, calle) for nombre in calles):
                continue
            # «Al 4528, en Saavedra»: si es el barrio de esa altura, no es otra calle.
            barrios = {
                normalizar(barrio) for barrio, _ in self.cj.barrios(calle, altura.valor, False)
            }
            if any(otra not in barrios for otra in otras):
                continue
            existe = bool(self.cj.tramos_en(calle, altura.valor))
            yield _Direccion(principal, calle, [], altura, principal.fin, existe)

    def _nombra_a(self, nombrada: str, calle: str) -> bool:
        """Si lo que nombró el operador al pedir la altura empieza con esa calle y no con otra."""
        palabras = nombrada.split()
        for fin in range(len(palabras), 0, -1):
            nombres = {
                c.nombre
                for c in self.candidatos(" ".join(palabras[:fin]), difuso=False)
                if c.como in ("exacto", "apellido")
            }
            if nombres:
                sigue = palabras[fin] if fin < len(palabras) else None
                return calle in nombres and sigue not in SIGUE_OTRA_CALLE
        return False

    def _en_esquina(self, limite: int | None = None) -> tuple[_Mencion, str, _Mencion, str] | None:
        """Una esquina sin altura: «X y Z», «X esquina Z», «X casi Z» o «X casi esquina Z».

        Vale sólo si las dos calles se cruzan en el callejero.
        """
        entre = -1
        y_de_entre = None
        for i, palabra in enumerate(self.palabras[:limite]):
            if palabra == "ENTRE":
                entre, y_de_entre = i, self._y_de_entre(i)
            if palabra not in ("Y", "E", *MARCAS_DE_CRUCE):
                continue
            # En «casi esquina» manda «casi»: la calle de la izquierda está antes de las dos.
            if i > 0 and self._casi_esquina(i - 1):
                continue
            tramo = self.tramos[i]
            if i - 1 not in tramo:
                continue
            siguiente = i + 2 if self._casi_esquina(i) else i + 1
            izquierda, _ = self._calle_antes(i - 1, None)
            # En «entre X y Z» las calles son entrecalles. «Entre Ríos» es un nombre.
            if izquierda and i == y_de_entre and izquierda.inicio > entre:
                continue
            if izquierda and (derecha := self._calle_despues(siguiente, tramo.stop)):
                for a in izquierda.candidatos:
                    for b in derecha.candidatos:
                        if self.alturas_en_esquina(a.nombre, b.nombre):
                            return izquierda, a.nombre, derecha, b.nombre
        return None

    def _casi_esquina(self, i: int) -> bool:
        """«Casi esquina»: las dos palabras marcan un solo cruce."""
        return (
            self.palabras[i] == "CASI"
            and i + 1 in self.tramos[i]
            and self.palabras[i + 1] in {"ESQUINA", "ESQ"}
        )

    def _con_marca(self) -> tuple[_Mencion, str, list[str]] | None:
        for i, palabra in enumerate(self.palabras):
            if palabra in MARCAS_DE_CALLE and (
                mencion := self._calle_despues(i + 1, self.tramos[i].stop, marca=i)
            ):
                nombre, alternativas = self._elegir(
                    mencion.candidatos, palabra in {"AV", "AVENIDA"}
                )
                return mencion, nombre, alternativas
        return None

    def _calle_sola(self) -> tuple[_Mencion, str, list[str]] | None:
        for i, tramo in enumerate(self.tramos):
            if i != tramo.start or len(tramo) > 5:
                continue
            fin = tramo.stop - 1
            if self.palabras[fin] in {"Y", "E"}:
                fin -= 1
            consulta = " ".join(self.palabras[i : fin + 1])
            if len(consulta) > 200:
                continue
            candidatos = [
                c
                for c in self.candidatos(consulta, difuso=False)
                if c.como in ("exacto", "apellido")
            ]
            if candidatos and (cita := self._cita(i, fin)):
                nombre, alternativas = self._elegir(candidatos, False)
                return _Mencion(i, fin, cita, candidatos), nombre, alternativas
        return None

    def _cruce_desconocido(self, ini: int, limite: int) -> _Mencion | None:
        while ini < limite and self.palabras[ini] in SALTABLES - MARCAS_DE_LUGAR:
            ini += 1
        if ini == limite or self.palabras[ini] in MARCAS_DE_LUGAR:
            return None
        fin = ini - 1
        for i in range(ini, min(limite, ini + 4)):
            palabra = self.palabras[i]
            if palabra in CORTA_CRUCE or palabra.isdigit():
                break
            if i > ini and CORTE_ENTRE_PALABRAS.search(self._separador(i - 1, i)):
                break
            fin = i
        if fin >= ini and (cita := self._cita(ini, fin)):
            return _Mencion(ini, fin, cita, [])
        return None

    def _y_de_entre(self, i: int) -> int | None:
        try:
            return self.palabras.index("Y", i + 2, min(i + 7, self.tramos[i].stop))
        except ValueError:
            return None

    def _cruces_marcados(self, fin_direccion: int, hasta: int | None = None) -> Iterator[_Mencion]:
        for i, palabra in enumerate(self.palabras[:hasta]):
            if palabra == "ENTRE":
                limite = self.tramos[i].stop
                j = self._y_de_entre(i)
                if j is None:
                    continue
                consulta = " ".join(x for x in self.palabras[i + 1 : j] if x not in MARCAS_DE_CALLE)
                candidatos = self.candidatos(consulta)
                derecha = self._calle_despues(j + 1, limite)
                izquierda = None
                if candidatos and (cita := self._cita(i + 1, j - 1)):
                    izquierda = _Mencion(i + 1, j - 1, cita, candidatos)
                if i == fin_direccion + 1:
                    izquierda = izquierda or self._cruce_desconocido(i + 1, j)
                    derecha = derecha or self._cruce_desconocido(j + 1, limite)
                if izquierda and derecha:
                    yield izquierda
                    yield derecha
            # En «casi esquina» el cruce lo lee «esquina».
            elif palabra in MARCAS_DE_CRUCE and not self._casi_esquina(i):
                limite = self.tramos[i].stop
                mencion = self._calle_despues(i + 1, limite)
                if not mencion and (i == fin_direccion + 1 or palabra != "CASI"):
                    mencion = self._cruce_desconocido(i + 1, limite)
                if mencion:
                    yield mencion

    def resolver(self) -> Interpretacion:
        altura: Dicho[Altura] | Falta = Falta()
        alternativas: list[str] = []
        cruces: list[tuple[_Mencion, str]] = []
        por_marca = False
        direcciones = list(self._direcciones())
        # Una dirección de corrido ya dicha no se reescribe con una respuesta que viene después.
        # Las respuestas anteriores sí entran en la comparación con las direcciones posteriores.
        limite = (
            bisect_left(self.tokens, direcciones[0].altura.cita.turno, key=lambda t: t.inicio.turno)
            if direcciones
            else len(self.tokens)
        )
        respuestas = list(self._alturas_preguntadas(limite))
        calles_dichas = list(self._calles_para_altura_preguntada(limite)) if respuestas else []
        preguntadas = list(self._direcciones_preguntadas(calles_dichas, respuestas, limite))
        conflicto = None
        if preguntadas:
            primera = preguntadas[0]
            distinta = next((otra for otra in preguntadas if not primera.coincide_con(otra)), None)
            if distinta:
                conflicto = (primera, distinta)
            else:
                direcciones.insert(0, primera)
        direccion = next(
            (direccion for direccion in direcciones if direccion.existe),
            direcciones[0] if direcciones else None,
        )
        if conflicto:
            direccion = None
            primera = conflicto[0]
            principal, calle, fin_direccion = primera.mencion, primera.calle, primera.fin
        elif direccion:
            principal, calle = direccion.mencion, direccion.calle
            alternativas, altura, fin_direccion = (
                direccion.alternativas,
                direccion.altura,
                direccion.fin,
            )
        elif en_esquina := self._en_esquina():
            principal, calle, mencion, nombre = en_esquina
            cruces.append((mencion, nombre))
            fin_direccion = mencion.fin
        elif con_marca := self._con_marca():
            principal, calle, alternativas = con_marca
            fin_direccion = principal.fin
            por_marca = True
        elif calle_sola := self._calle_sola():
            principal, calle, alternativas = calle_sola
            fin_direccion = principal.fin
        elif calles_dichas:
            principal = calles_dichas[0]
            calle, alternativas = self._elegir(principal.candidatos, False)
            fin_direccion = principal.fin
        else:
            return Interpretacion(
                ubicacion=Ubicacion(calle=Falta(), altura=Falta(), esquinas=[]),
                avisos=[
                    Aviso(codigo="sin_calle", mensaje="Pedí la dirección y confirmá la calle.")
                ],
                calle_oficial=None,
            )

        mencionados = list(self._cruces_marcados(fin_direccion))
        if por_marca:
            siguiente = principal.fin + 1
            tramo = self.tramos[principal.fin]
            if siguiente in tramo and self.palabras[siguiente] in {"Y", "E"}:
                cruce = self._calle_despues(siguiente + 1, tramo.stop) or self._cruce_desconocido(
                    siguiente + 1, tramo.stop
                )
                if cruce:
                    mencionados.append(cruce)

        avisos: list[Aviso] = []
        altura_dicha = altura.valor if isinstance(altura, Dicho) else None
        entrecalles = []
        calle_visible = self.cj.nombre_para_mostrar(calle)
        if direccion:
            if direccion.existe:
                entrecalles = self.cj.entrecalles(calle, direccion.altura.valor)
            else:
                avisos.append(
                    Aviso(
                        codigo="direccion_no_cierra",
                        mensaje=(
                            f"La altura {direccion.altura.valor} no existe en {calle_visible}. "
                            "Leele la dirección de vuelta al llamante."
                        ),
                    )
                )
            otra = next((otra for otra in direcciones if not direccion.coincide_con(otra)), None)
            if otra:
                conflicto = (direccion, otra)
        if conflicto:
            primera, segunda = conflicto
            calle_primera = self.cj.nombre_para_mostrar(primera.calle)
            calle_segunda = self.cj.nombre_para_mostrar(segunda.calle)
            avisos.append(
                Aviso(
                    codigo="direccion_no_cierra",
                    mensaje=(
                        f"Se mencionaron {calle_primera} {primera.altura.valor} y "
                        f"{calle_segunda} {segunda.altura.valor}. "
                        "Confirmá con el llamante cuál es la dirección."
                    ),
                )
            )
        no_confirmados: set[str] = set()
        # Con dos direcciones en el relato no se sabe cuál completar: no se infiere nada.
        hay_conflicto = conflicto is not None
        for mencion in mencionados:
            cruza = next(
                (
                    (c.nombre, alturas)
                    for c in mencion.candidatos
                    if (alturas := self.alturas_en_esquina(calle, c.nombre))
                ),
                None,
            )
            if cruza is None:
                dicho = mencion.cita.texto
                if mencion.candidatos and mencion.candidatos[0].nombre == calle:
                    continue
                if dicho not in no_confirmados:
                    no_confirmados.add(dicho)
                    avisos.append(
                        Aviso(
                            codigo="cruce_sin_confirmar",
                            mensaje=f"Confirmá si «{dicho}» cruza {calle_visible}.",
                        )
                    )
                continue
            nombre, alturas = cruza
            cruces.append((mencion, nombre))
            if (
                direccion is not None
                and direccion.existe
                and nombre not in entrecalles
                and min(abs(direccion.altura.valor - a) for a in alturas) > TOLERANCIA_CASI
            ):
                hay_conflicto = True
                avisos.append(
                    Aviso(
                        codigo="direccion_no_cierra",
                        mensaje=(
                            f"La altura {altura_dicha} no coincide con "
                            f"{self.cj.nombre_para_mostrar(nombre)}. "
                            "Leele la dirección de vuelta al llamante."
                        ),
                    )
                )

        esquinas = self._esquinas(
            principal, calle_visible, cruces, [] if hay_conflicto else entrecalles
        )
        if altura_dicha is None and not esquinas and conflicto is None:
            avisos.append(
                Aviso(
                    codigo="falta_altura",
                    mensaje=f"Preguntá la altura o la esquina de {calle_visible}.",
                )
            )
        if alternativas:
            nombres = ", ".join(self.cj.nombre_para_mostrar(nombre) for nombre in alternativas)
            avisos.append(
                Aviso(
                    codigo="calle_ambigua", mensaje=f"Confirmá si es {calle_visible} o {nombres}."
                )
            )

        return Interpretacion(
            ubicacion=Ubicacion(
                calle=Dicho[Texto](valor=calle_visible, cita=principal.cita),
                altura=altura,
                esquinas=esquinas,
            ),
            avisos=avisos,
            calle_oficial=calle,
        )

    def _esquinas(
        self,
        principal: _Mencion,
        calle_visible: str,
        cruces: list[tuple[_Mencion, str]],
        inferidas: list[str],
    ) -> list[Dicho[Texto] | Inferido[Texto]]:
        esquinas: list[Dicho[Texto] | Inferido[Texto]] = []
        vistos = {texto_plano(calle_visible)}
        # Una marca puede volver a leer la mención principal como otra calle homónima.
        cruces.sort(key=lambda par: (par[0].inicio <= principal.fin <= par[0].fin, par[0].inicio))
        for mencion, nombre in cruces:
            valor = self.cj.nombre_para_mostrar(nombre)
            clave = texto_plano(valor)
            if clave not in vistos:
                esquinas.append(Dicho[Texto](valor=valor, cita=mencion.cita))
                vistos.add(clave)
            if len(esquinas) == 2:
                return esquinas
        for nombre in inferidas:
            valor = self.cj.nombre_para_mostrar(nombre)
            clave = texto_plano(valor)
            if clave not in vistos:
                esquinas.append(Inferido[Texto](valor=valor, fuente="callejero"))
                vistos.add(clave)
            if len(esquinas) == 2:
                break
        return esquinas


def entrecalles_de(calle: str, altura: int) -> list[str]:
    """Las entrecalles que el callejero da para una dirección ya escrita, como se muestran.

    Ninguna si el texto no nombra una sola calle con esa altura: sin esa certeza no se afirma nada.
    """
    callejero = cargar()
    candidatos = callejero.candidatos(normalizar(calle), difuso=False)
    # Un mismo nombre puede ser una calle y una avenida: decide cuál tiene esa altura y, si las
    # dos la tienen, cuál se llama exactamente así.
    nombres = [
        candidato.nombre
        for candidato in candidatos
        if candidato.puntaje == candidatos[0].puntaje
        and callejero.cuadras(candidato.nombre, altura)
    ]
    if len(nombres) > 1:
        nombres = [
            nombre
            for nombre in nombres
            if texto_plano(callejero.nombre_para_mostrar(nombre)) == texto_plano(calle)
        ]
    if len(nombres) != 1:
        return []
    cruces = callejero.entrecalles(nombres[0], altura)
    return [callejero.nombre_para_mostrar(cruce) for cruce in cruces]


def interpretar(turnos: list[Turno]) -> Interpretacion:
    """Reconoce la dirección y conserva una cita literal por cada dato dicho."""
    return _Resolvedor(turnos, cargar()).resolver()
