"""Callejero oficial de CABA en memoria: nombres, alturas por tramo y esquinas."""

import csv
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import cache
from importlib import resources
from importlib.resources.abc import Traversable

from rapidfuzz import fuzz, process

ARCHIVO = "callejero_caba.csv"
ABREVIATURAS = {
    "GRAL": "GENERAL",
    "PRES": "PRESIDENTE",
    "PTE": "PRESIDENTE",
    "DR": "DOCTOR",
    "CNEL": "CORONEL",
    "CMTE": "COMANDANTE",
    "INT": "INTENDENTE",
    "ING": "INGENIERO",
    "TTE": "TENIENTE",
    "ALTE": "ALMIRANTE",
    "CAP": "CAPITAN",
    "STA": "SANTA",
    "STO": "SANTO",
    "SGTO": "SARGENTO",
    "MCAL": "MARISCAL",
    "CDOR": "COMODORO",
    "PJE": "PASAJE",
    "AVDA": "AV",
    "AVENIDA": "AV",
    "AU": "AUTOPISTA",
}
TITULOS = {
    "GENERAL",
    "PRESIDENTE",
    "DOCTOR",
    "CORONEL",
    "COMANDANTE",
    "INTENDENTE",
    "INGENIERO",
    "TENIENTE",
    "ALMIRANTE",
    "CAPITAN",
    "SARGENTO",
    "MARISCAL",
    "COMODORO",
}
CONECTORES = {"DE", "DEL", "LA", "LAS", "LOS", "EL", "Y"}
CONECTORES_DE_MAPA = {"de", "del", "la", "las", "los", "y"}


def normalizar(texto: str) -> str:
    """Mayúsculas, sin tildes ni puntuación. 'Av. Raúl Scalabrini' -> 'AV RAUL SCALABRINI'."""
    texto = unicodedata.normalize("NFD", texto.upper())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    texto = re.sub(r"[^A-Z0-9 ]+", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def expandir(tokens: list[str]) -> list[str]:
    return [ABREVIATURAS.get(t, t) for t in tokens]


def clave_fonetica(texto: str) -> str:
    """Fonética rioplatense mínima para tolerar errores de transcripción.

    b/v, s/z/c, ll/y, h muda, qu/k, letras dobles y la 'e' protética
    ('Escalabrini' -> 'Scalabrini'). Se aplica igual a la consulta y al callejero.
    """
    salida = []
    for palabra in texto.split():
        if palabra.isdigit():
            salida.append(palabra)
            continue
        if palabra == "BE":
            palabra = "B"
        palabra = re.sub(r"^ES(?=[BCDFGKLMNPQRSTVXZ])", "S", palabra)
        palabra = palabra.replace("LL", "Y").replace("V", "B").replace("Z", "S")
        palabra = re.sub(r"C(?=[EI])", "S", palabra)
        palabra = palabra.replace("QU", "K").replace("C", "K").replace("H", "")
        palabra = re.sub(r"(.)\1", r"\1", palabra)
        salida.append(palabra)
    return " ".join(salida)


@dataclass(frozen=True)
class Tramo:
    nombre: str
    tipo: str
    izq_ini: int
    izq_fin: int
    der_ini: int
    der_fin: int
    barrio_par: str
    barrio_impar: str
    comuna_par: str
    comuna_impar: str
    nodo_ini: int
    nodo_fin: int

    @property
    def desde(self) -> int:
        return min((v for v in (self.izq_ini, self.der_ini) if v), default=0)

    @property
    def hasta(self) -> int:
        return max(self.izq_fin, self.der_fin)

    def contiene(self, altura: int) -> bool:
        return bool(self.hasta) and self.desde <= altura <= self.hasta


@dataclass(frozen=True)
class Candidato:
    nombre: str
    puntaje: int
    como: str


class Callejero:
    def __init__(self, ruta_csv: Traversable) -> None:
        self.tramos: dict[str, list[Tramo]] = defaultdict(list)
        self._en_nodo: dict[int, set[str]] = defaultdict(set)
        self._nombres_para_mostrar: dict[str, str] = {}
        self._claves: dict[str, list[Candidato]] = defaultdict(list)
        self._claves_fon: dict[str, list[Candidato]] = defaultdict(list)
        self._por_token: dict[str, set[str]] = defaultdict(set)
        self.avenidas: set[str] = set()
        self._cargar(ruta_csv)
        self._lista_fon = list(self._claves_fon)

    def _cargar(self, ruta_csv: Traversable) -> None:
        nombres_de_mapa: dict[str, Counter[str]] = defaultdict(Counter)
        with ruta_csv.open("r", encoding="utf-8", newline="") as archivo:
            for fila in csv.DictReader(archivo):
                nombre = fila["nomoficial"]
                if nombre_mapa := fila["nom_mapa"].strip():
                    nombres_de_mapa[nombre][nombre_mapa] += 1
                tramo = Tramo(
                    nombre=nombre,
                    tipo=fila["tipo_c"],
                    izq_ini=int(fila["alt_izqini"] or 0),
                    izq_fin=int(fila["alt_izqfin"] or 0),
                    der_ini=int(fila["alt_derini"] or 0),
                    der_fin=int(fila["alt_derfin"] or 0),
                    barrio_par=fila["barrio_par"].strip(),
                    barrio_impar=fila["barrio_imp"].strip(),
                    comuna_par=fila["com_par"].strip().removesuffix(".0"),
                    comuna_impar=fila["com_impar"].strip().removesuffix(".0"),
                    nodo_ini=int(fila["nodo_ini"]),
                    nodo_fin=int(fila["nodo_fin"]),
                )
                if nombre not in self.tramos:
                    self._indexar_nombre(nombre, fila["tipo_c"])
                self.tramos[nombre].append(tramo)
                self._en_nodo[tramo.nodo_ini].add(nombre)
                self._en_nodo[tramo.nodo_fin].add(nombre)

        for nombre in self.tramos:
            variantes = nombres_de_mapa[nombre].most_common(1)
            # El nombre más frecuente evita mostrar el nombre de un puente o túnel aislado.
            nombre_mapa = variantes[0][0] if variantes else nombre
            palabras = re.sub(r"\.(?=\w)", ". ", nombre_mapa).lower().split()
            self._nombres_para_mostrar[nombre] = " ".join(
                palabra if palabra in CONECTORES_DE_MAPA else palabra.capitalize()
                for palabra in palabras
            )

    def nombre_para_mostrar(self, nombre: str) -> str:
        """Devuelve el nombre de mapa de una calle oficial con sus mayúsculas de lectura."""
        return self._nombres_para_mostrar[nombre]

    def _indexar_nombre(self, nombre: str, tipo: str) -> None:
        """Genera las formas en que la gente dice una calle.

        'SCALABRINI ORTIZ, RAUL AV.' -> 'RAUL SCALABRINI ORTIZ' (exacto) y 'SCALABRINI ORTIZ' (apellido).
        """
        partes = [expandir(normalizar(p).split()) for p in nombre.split(",")]
        if tipo == "AVENIDA" or any("AV" in p for p in partes):
            self.avenidas.add(nombre)
        partes = [[t for t in p if t != "AV"] for p in partes]
        partes = [p for p in partes if p]
        if not partes:
            return
        apellido = " ".join(partes[0])
        natural = " ".join(t for p in reversed(partes) for t in p)
        sin_titulos = " ".join(t for p in reversed(partes) for t in p if t not in TITULOS)
        formas = {natural: ("exacto", 100), sin_titulos: ("exacto", 98)}
        if len(partes) > 1:
            formas.setdefault(apellido, ("apellido", 94))
        for forma, (como, puntaje) in formas.items():
            if not forma:
                continue
            self._claves[forma].append(Candidato(nombre, puntaje, como))
            self._claves_fon[clave_fonetica(forma)].append(
                Candidato(nombre, puntaje - 4, "fonetico")
            )
        for token in partes[0]:
            if token not in CONECTORES and len(token) > 3:
                self._por_token[token].add(nombre)

    def candidatos(self, consulta: str, difuso: bool = True) -> list[Candidato]:
        """Calles que pueden corresponder a un texto ya normalizado, de mejor a peor."""
        tokens = [t for t in expandir(consulta.split()) if t != "AV"]
        consulta = " ".join(tokens)
        if not consulta:
            return []
        encontrados: dict[str, Candidato] = {}

        def sumar(lista: list[Candidato]) -> None:
            for c in lista:
                if c.nombre not in encontrados or c.puntaje > encontrados[c.nombre].puntaje:
                    encontrados[c.nombre] = c

        sumar(self._claves.get(consulta, []))
        fon = clave_fonetica(consulta)
        if not encontrados:
            sumar(self._claves_fon.get(fon, []))
        if not encontrados and len(tokens) == 1 and len(consulta) > 3:
            # 'VELASCO' -> 'RAMIREZ DE VELASCO, JUAN'. Vale poco: lo confirma el cruce con la otra calle.
            sumar([Candidato(n, 80, "parcial") for n in self._por_token.get(consulta, ())])
        if not encontrados and difuso and len(consulta) >= 6:
            for clave, puntaje, _ in process.extract(
                fon, self._lista_fon, scorer=fuzz.ratio, score_cutoff=86, limit=4
            ):
                sumar(
                    [
                        Candidato(c.nombre, int(puntaje) - 8, "difuso")
                        for c in self._claves_fon[clave]
                    ]
                )
        return sorted(encontrados.values(), key=lambda c: (-c.puntaje, c.nombre))

    def tramos_en(self, nombre: str, altura: int) -> list[Tramo]:
        return [t for t in self.tramos.get(nombre, []) if t.contiene(altura)]

    def _otras_en(self, nodo: int, nombre: str) -> list[str]:
        return sorted(self._en_nodo[nodo] - {nombre})

    def cuadras(self, nombre: str, altura: int) -> list[Tramo]:
        """Cuadra(s) de una altura. 'Al 800' es ambiguo: el 800 exacto cierra la cuadra del 700,
        pero en el habla porteña 'al 800' es la cuadra 800-899. Para números redondos van las dos."""
        tramos = self.tramos_en(nombre, altura)
        if altura % 100 == 0:
            tramos += [t for t in self.tramos_en(nombre, altura + 2) if t not in tramos]
        return tramos

    def entrecalles(self, nombre: str, altura: int) -> list[str]:
        """Calles que cruzan en los extremos de la(s) cuadra(s) de esa altura."""
        salida: list[str] = []
        for tramo in self.cuadras(nombre, altura):
            for nodo in (tramo.nodo_ini, tramo.nodo_fin):
                for otra in self._otras_en(nodo, nombre):
                    if otra not in salida:
                        salida.append(otra)
        return salida

    def barrios(self, nombre: str, altura: int, exacta: bool) -> list[tuple[str, str]]:
        """(barrio, comuna) posibles. Si la altura es exacta se usa la vereda par o impar;
        si es una esquina o un número redondo, van las dos veredas (las calles límite cambian de barrio)."""
        salida: list[tuple[str, str]] = []
        for tramo in self.cuadras(nombre, altura):
            lados = [(tramo.barrio_par, tramo.comuna_par), (tramo.barrio_impar, tramo.comuna_impar)]
            if exacta and altura % 100:
                lados = [lados[altura % 2]]
            for lado in lados:
                if lado[0] and lado not in salida:
                    salida.append(lado)
        return salida

    def alturas_en_esquina(self, nombre: str, otra: str) -> list[int]:
        """Alturas de `nombre` en las esquinas que comparte con `otra` (vacío si no se cruzan)."""
        alturas: list[int] = []
        for tramo in self.tramos.get(nombre, []):
            for nodo, lado in ((tramo.nodo_ini, "ini"), (tramo.nodo_fin, "fin")):
                if otra != nombre and otra in self._en_nodo[nodo]:
                    valores = (
                        (tramo.izq_ini, tramo.der_ini)
                        if lado == "ini"
                        else (tramo.izq_fin, tramo.der_fin)
                    )
                    alturas.extend(v for v in valores if v)
        return sorted(alturas)


@cache
def cargar() -> Callejero:
    """Carga una sola vez el callejero empaquetado con el servicio."""
    return Callejero(resources.files("copiloto").joinpath("datos", ARCHIVO))
