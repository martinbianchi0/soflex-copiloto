"""Interpreta lo que dijo el llamante y lo contrasta con el callejero de CABA."""

import re
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass, replace

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
    cita_esta_en,
    texto_plano,
)

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
    "CHICOS",
    "MINUTOS",
    "AUTOS",
    "CAMIONETAS",
    "PISOS",
    "CARRILES",
    "MANZANAS",
    "DISPAROS",
    "HORAS",
    "CUADRAS",
    "KM",
    "KILOMETROS",
    "CM",
    "MESES",
    "DIAS",
    "HERIDOS",
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
ANTES_DE_ALTURA = {"AL", "ALTURA", "NUMERO", "NRO", "N"}
SALTABLES = {"AV", "AVENIDA", "CALLE", "LA", "LAS", "EL", "LOS", "DE", "DEL", "VIAS", "VIA"}
MARCAS_DE_CALLE = {"AV", "AVENIDA", "AUTOPISTA", "CALLE"}
MARCAS_DE_HABLANTE = re.compile(r"\b(Operador|Llamante|operador|llamante)\s*:")
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


@dataclass(frozen=True)
class _Token:
    palabra: str
    inicio: _Posicion
    fin: _Posicion


def _bloques_del_llamante(turno: Turno) -> Iterator[tuple[int, int]]:
    if turno.hablante == "operador":
        return
    marcas = list(MARCAS_DE_HABLANTE.finditer(turno.texto)) if turno.hablante is None else []
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
            desde = hasta = inicio
            for indice in range(inicio, fin):
                caracter = turno.texto[indice]
                if unicodedata.category(caracter) == "Mn":
                    if letras:
                        hasta = indice + 1
                    continue
                parte = caracter.upper() if caracter.isascii() and caracter.isalnum() else ""
                if not caracter.isascii():
                    parte = normalizar(caracter)
                if parte:
                    if not letras:
                        desde = indice
                    letras.append(parte)
                    hasta = indice + 1
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


def _numeros_en_palabras(tokens: list[_Token]) -> list[_Token]:
    """'MIL QUINIENTOS CUARENTA' -> '1540'. No toca 'UN/UNA' sueltos ni junta números separados."""
    # `nivel` obliga a que las palabras vayan de mayor a menor: centena (3) > decena (2) > unidad (1).
    salida: list[_Token] = []
    i = 0
    while i < len(tokens):
        total, actual, nivel, hubo_mil, j = 0, 0, 4, False, i
        while j < len(tokens):
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
            ):
                actual, nivel = actual + BASICOS.get(tokens[j + 1].palabra, 1), 1
                j += 1
            else:
                break
            j += 1
        if j > i:
            salida.append(replace(tokens[i], palabra=str(total + actual), fin=tokens[j - 1].fin))
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


class _Resolvedor:
    def __init__(self, turnos: list[Turno], callejero: Callejero) -> None:
        self.turnos = turnos
        self.cj = callejero
        self.tokens = _numeros_en_palabras(list(_tokens_del_llamante(turnos)))
        self.palabras = [token.palabra for token in self.tokens]

    def _cita(self, desde: int, hasta: int) -> Cita | None:
        inicio, fin = self.tokens[desde].inicio, self.tokens[hasta].fin
        if (inicio.turno, inicio.bloque) != (fin.turno, fin.bloque):
            return None
        fragmento = self.turnos[inicio.turno].texto[inicio.indice : fin.indice]
        if len(fragmento) > 200 or not texto_plano(fragmento):
            return None
        cita = Cita(turno=inicio.turno, texto=fragmento)
        return cita if cita_esta_en(cita, self.turnos) else None

    def _calle_antes(self, fin: int, altura: int | None) -> tuple[_Mencion | None, bool]:
        """Busca la coincidencia más larga y deja la búsqueda difusa para el final."""
        for difuso in (False, True):
            for largo in range(5, 0, -1):
                ini = fin - largo + 1
                if ini < 0:
                    continue
                grama = self.palabras[ini : fin + 1]
                marca_anterior = ini > 0 and self.palabras[ini - 1] in MARCAS_DE_CALLE
                es_av = grama[0] in MARCAS_DE_CALLE or marca_anterior
                nombre = [palabra for palabra in grama if palabra != "CALLE"]
                if not nombre or (
                    difuso and (largo > 3 or nombre[0] in SALTABLES - {"AV", "AVENIDA"})
                ):
                    continue
                candidatos = self.cj.candidatos(" ".join(nombre), difuso=difuso)
                if altura is not None:
                    candidatos = [c for c in candidatos if self.cj.tramos_en(c.nombre, altura)]
                if candidatos:
                    desde = ini - 1 if marca_anterior else ini
                    cita = self._cita(desde, fin) or self._cita(ini, fin)
                    if cita:
                        return _Mencion(ini, fin, cita, candidatos), es_av
        return None, False

    def _calle_despues(self, ini: int, marca: int | None = None) -> _Mencion | None:
        inicio = ini if marca is None else marca
        prefijo = "AUTOPISTA " if marca is not None and self.palabras[marca] == "AUTOPISTA" else ""
        salteados = 0
        while ini < len(self.palabras) and self.palabras[ini] in SALTABLES and salteados < 4:
            ini, salteados = ini + 1, salteados + 1
        for difuso in (False, True):
            for largo in range(4, 0, -1):
                grama = self.palabras[ini : ini + largo]
                if len(grama) < largo or (difuso and largo > 3):
                    continue
                candidatos = self.cj.candidatos(prefijo + " ".join(grama), difuso=difuso)
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

    def _con_altura(self) -> tuple[_Mencion, str, list[str], Dicho[Altura], int] | None:
        for i, palabra in enumerate(self.palabras):
            if not palabra.isdigit():
                continue
            cifras = palabra.lstrip("0")
            if not cifras or len(cifras) > 5 or (altura := int(cifras)) > 20000:
                continue
            if i + 1 < len(self.palabras) and self.palabras[i + 1] in SE_CUENTAN:
                continue
            fin = i - 1
            while fin >= 0 and self.palabras[fin] in ANTES_DE_ALTURA:
                fin -= 1
            if fin < 0:
                continue
            mencion, es_av = self._calle_antes(fin, altura)
            if mencion is None:
                continue
            candidatos = mencion.candidatos
            if altura < 100:
                candidatos = [c for c in candidatos if c.como in ("exacto", "apellido")]
            if candidatos and (cita := self._cita(i, i)):
                nombre, alternativas = self._elegir(candidatos, es_av)
                return mencion, nombre, alternativas, Dicho[Altura](valor=altura, cita=cita), i
        return None

    def _en_esquina(self) -> tuple[_Mencion, str, _Mencion, str] | None:
        for i, palabra in enumerate(self.palabras):
            if palabra not in ("Y", "E") or i == 0:
                continue
            izquierda, _ = self._calle_antes(i - 1, None)
            if izquierda and (derecha := self._calle_despues(i + 1)):
                for a in izquierda.candidatos:
                    for b in derecha.candidatos:
                        if self.cj.alturas_en_esquina(a.nombre, b.nombre):
                            return izquierda, a.nombre, derecha, b.nombre
        return None

    def _con_marca(self) -> tuple[_Mencion, str, list[str]] | None:
        for i, palabra in enumerate(self.palabras):
            if palabra in MARCAS_DE_CALLE and (mencion := self._calle_despues(i + 1, marca=i)):
                nombre, alternativas = self._elegir(
                    mencion.candidatos, palabra in {"AV", "AVENIDA"}
                )
                return mencion, nombre, alternativas
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
            if i > ini:
                antes, despues = self.tokens[i - 1].fin, self.tokens[i].inicio
                if (antes.turno, antes.bloque) != (despues.turno, despues.bloque):
                    break
                separador = self.turnos[antes.turno].texto[antes.indice : despues.indice]
                if re.search(r"[,.;:!?…\n]", separador):
                    break
            fin = i
        if fin >= ini and (cita := self._cita(ini, fin)):
            return _Mencion(ini, fin, cita, [])
        return None

    def _cruces_marcados(self, fin_direccion: int) -> Iterator[_Mencion]:
        for i, palabra in enumerate(self.palabras):
            if palabra == "ENTRE":
                try:
                    j = self.palabras.index("Y", i + 2, i + 7)
                except ValueError:
                    continue
                consulta = " ".join(x for x in self.palabras[i + 1 : j] if x not in MARCAS_DE_CALLE)
                candidatos = self.cj.candidatos(consulta)
                derecha = self._calle_despues(j + 1)
                izquierda = None
                if candidatos and (cita := self._cita(i + 1, j - 1)):
                    izquierda = _Mencion(i + 1, j - 1, cita, candidatos)
                if i == fin_direccion + 1:
                    izquierda = izquierda or self._cruce_desconocido(i + 1, j)
                    derecha = derecha or self._cruce_desconocido(j + 1, len(self.palabras))
                if izquierda and derecha:
                    yield izquierda
                    yield derecha
            elif palabra in MARCAS_DE_CRUCE:
                mencion = self._calle_despues(i + 1)
                if not mencion and (i == fin_direccion + 1 or palabra != "CASI"):
                    mencion = self._cruce_desconocido(i + 1, len(self.palabras))
                if mencion:
                    yield mencion

    def resolver(self) -> Interpretacion:
        altura: Dicho[Altura] | Falta = Falta()
        alternativas: list[str] = []
        cruces: list[tuple[_Mencion, str]] = []
        por_marca = False
        if con_altura := self._con_altura():
            principal, calle, alternativas, altura, fin_direccion = con_altura
        elif en_esquina := self._en_esquina():
            principal, calle, mencion, nombre = en_esquina
            cruces.append((mencion, nombre))
            fin_direccion = mencion.fin
        elif con_marca := self._con_marca():
            principal, calle, alternativas = con_marca
            fin_direccion = principal.fin
            por_marca = True
        else:
            return Interpretacion(
                ubicacion=Ubicacion(calle=Falta(), altura=Falta(), esquinas=[]),
                avisos=[
                    Aviso(codigo="sin_calle", mensaje="Pedí la dirección y confirmá la calle.")
                ],
                calle_oficial=None,
            )

        avisos: list[Aviso] = []
        altura_dicha = altura.valor if isinstance(altura, Dicho) else None
        entrecalles = self.cj.entrecalles(calle, altura_dicha) if altura_dicha is not None else []
        calle_visible = self.cj.nombre_para_mostrar(calle)
        mencionados = list(self._cruces_marcados(fin_direccion))
        if por_marca:
            siguiente = principal.fin + 1
            if siguiente < len(self.palabras) and self.palabras[siguiente] in {"Y", "E"}:
                cruce = self._calle_despues(siguiente + 1) or self._cruce_desconocido(
                    siguiente + 1, len(self.palabras)
                )
                if cruce:
                    mencionados.append(cruce)
        no_confirmados: set[str] = set()
        hay_conflicto = False
        for mencion in mencionados:
            cruza = next(
                (
                    (c.nombre, alturas)
                    for c in mencion.candidatos
                    if (alturas := self.cj.alturas_en_esquina(calle, c.nombre))
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
                altura_dicha is not None
                and nombre not in entrecalles
                and min(abs(altura_dicha - a) for a in alturas) > TOLERANCIA_CASI
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
        if altura_dicha is None and not esquinas:
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


def interpretar(turnos: list[Turno]) -> Interpretacion:
    """Reconoce la dirección y conserva una cita literal por cada dato dicho."""
    return _Resolvedor(turnos, cargar()).resolver()
