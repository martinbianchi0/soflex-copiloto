"""El tipo de hecho por palabras clave. Es lo que puede hacer el modo simulado con un texto nuevo.

No entiende el relato: cuenta palabras. No distingue una negación ("no hay fuego") ni algo que
ya pasó ("el choque fue ayer"). Por eso propone sólo la categoría, nunca un subtipo ni una
prioridad, y si no hay una categoría que gane con claridad dice "sin determinar".
"""

from copiloto.esquemas import Categoria, Turno, texto_plano
from copiloto.turnos import dicho_por_el_llamante

# Por categoría: palabras que la deciden casi solas (3), que la señalan (2) y que apenas suman (1).
# Se escriben como las deja `texto_plano` (sin acentos). Cuenta la palabra entera: "gas" no vale
# para "Gaspar" ni "llamas" para "llamaste". Con "*" al final vale cualquier terminación, para las
# raíces que no se confunden con otra cosa: "inund*" cuenta para "inundó" e "inundada".
_PALABRAS: dict[Categoria, dict[int, str]] = {
    Categoria.EMERGENCIA_MEDICA: {
        3: "convulsion* ambulancia ambulancias desmay* broncoespasmo anafila* infarto*",
        2: "inconsciente alergi* fractura* tropezo desplomo descompens* sangra* respira* pulso",
        1: "dolor duele años medic*",
    },
    Categoria.ACCIDENTE_VIAL: {
        3: "choco choque chocaron atropell* embisti* colision*",
        2: "volco volcado volcaron moto motos autopista ciclista guardarrail acoplado",
        1: "taxi colectivo colectivos camion camiones camioneta camionetas carril auto autos "
        "bicicleta",
    },
    Categoria.INCENDIO_RESCATE: {
        3: "incendi* bomberos ascensor llamas llamarada",
        2: "fuego humo explot* explosion gasoil nafta combustible cisterna quema quemando",
        1: "bateria baterias chispas quemado",
    },
    Categoria.DEFENSA_CIVIL: {
        3: "derrumb* desmoron* marquesina medianera inund* anegad*",
        2: "arbol gas colaps* desprend* temporal",
        1: "viento ladrillos tipa obra",
    },
    Categoria.SERVICIOS_PUBLICOS: {
        3: "semaforo semaforos socavon alumbrado luminaria luminarias bache baches cloaca cloacas",
        2: "cable cables poste postes pozo caño apag*",
        1: "fosa luz agua",
    },
    Categoria.CONVIVENCIA_SEGURIDAD: {
        3: "pelea peleando perro perros robo robaron asalt* disturbio disturbios",
        2: "arma armas armado amenaz* ruidos musica",
        1: "botellas gruñ* bar",
    },
}


def _aparece(palabra: str, dichas: set[str]) -> bool:
    if palabra.endswith("*"):
        return any(dicha.startswith(palabra[:-1]) for dicha in dichas)
    return palabra in dichas


def puntajes(turnos: list[Turno]) -> dict[Categoria, int]:
    dichas = set(texto_plano(dicho_por_el_llamante(turnos)).split())
    return {
        categoria: sum(
            peso
            for peso, palabras in pesos.items()
            for palabra in palabras.split()
            if _aparece(palabra, dichas)
        )
        for categoria, pesos in _PALABRAS.items()
    }


def por_palabras_clave(turnos: list[Turno]) -> Categoria:
    """La categoría con más señales, si le saca ventaja a la segunda; si no, sin determinar."""
    primero, segundo = sorted(puntajes(turnos).items(), key=lambda par: -par[1])[:2]
    if primero[1] >= 2 and primero[1] > segundo[1]:
        return primero[0]
    return Categoria.NO_DETERMINADA
