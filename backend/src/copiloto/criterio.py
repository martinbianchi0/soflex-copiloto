"""El criterio de prioridad, de P1 a P4.

Es un dato del servicio y no un comentario: es el mismo texto que ve el operador junto a la
prioridad y el que va a recibir cualquier intérprete que tenga que proponer una. Sigue las
etiquetas del dataset provisto.
"""

from typing import Self

from pydantic import Field, model_validator

from copiloto.esquemas import Esquema, Prioridad, Texto, TextoLargo


class Nivel(Esquema):
    id: Prioridad
    nombre: Texto
    definicion: TextoLargo
    # Situaciones concretas que corresponden a este nivel.
    senales: list[Texto] = Field(min_length=1)


class Criterio(Esquema):
    niveles: list[Nivel]
    reglas: list[TextoLargo] = Field(min_length=1)

    @model_validator(mode="after")
    def con_los_cuatro_niveles_en_orden(self) -> Self:
        if [nivel.id for nivel in self.niveles] != list(Prioridad):
            raise ValueError("El criterio define P1, P2, P3 y P4, en ese orden.")
        return self


def _lineas(texto: str) -> list[str]:
    """Una señal o una regla por línea."""
    return [linea.strip() for linea in texto.strip().splitlines()]


CRITERIO = Criterio(
    niveles=[
        Nivel(
            id=Prioridad.P1,
            nombre="Riesgo de vida ahora",
            definicion="Hay una persona en peligro de muerte, o un peligro activo que puede matar "
            "a alguien en minutos.",
            senales=_lineas("""
                No respira o respira con mucha dificultad
                No responde, está inconsciente o convulsiona
                Reacción alérgica con la garganta cerrándose
                Persona atrapada o aplastada en un siniestro: bajo un vehículo, en un auto volcado, en un incendio
                Golpe de alta energía, aunque esté consciente: atropello, choque de moto, choque múltiple, vuelco, caída de altura
                Fuego, humo o explosión en un lugar con gente, o en una instalación eléctrica o de combustible
                Olor a gas dentro de viviendas, o escape de gas a presión
                Cable con chispas o en contacto con agua
                Derrame de combustible con tránsito o gente cerca
            """),
        ),
        Nivel(
            id=Prioridad.P2,
            nombre="Urgente, sin riesgo de vida inmediato",
            definicion="Hay personas afectadas pero estables, o un peligro que todavía no alcanzó "
            "a nadie y puede hacerlo.",
            senales=_lineas("""
                Herido consciente y estable: caída, golpe o fractura, incluso expuesta, sin sangrado a chorros
                Desmayo del que la persona ya se recuperó
                Personas encerradas o varadas, sin lesiones: un ascensor trabado, autos en un anegamiento
                Pelea con lesiones leves
                Árbol, cartel o estructura caída o por caer sobre la vía pública
                Cables cortados, sin chispas ni personas en contacto
                Socavón, inundación o derrumbe sin heridos
                Fuego al aire libre que avanza hacia donde hay gente
            """),
        ),
        Nivel(
            id=Prioridad.P3,
            nombre="Sin personas afectadas",
            definicion="Hay daño material o un riesgo acotado que no avanza sobre personas.",
            senales=_lineas("""
                Fuego en un contenedor
                Vehículo atascado, sin heridos
                Animal agresivo, sin personas mordidas
                Semáforos apagados
            """),
        ),
        Nivel(
            id=Prioridad.P4,
            nombre="No es una emergencia",
            definicion="Es un reclamo, una consulta o un pedido que puede esperar horas o días.",
            senales=_lineas("""
                Ruidos molestos
                Luminaria apagada
                Bache
                Pedido de poda
            """),
        ),
    ],
    reglas=_lineas("""
        Una sola señal de P1 alcanza, aunque el resto del relato suene tranquilo.
        Ante la duda entre dos niveles, va el más urgente.
        Un P2 sube a P1 según lo que respondan las preguntas del protocolo: por ejemplo, si el sangrado es a chorros o si alguien encerrado se descompensa.
        La prioridad es una propuesta: la confirma el operador.
    """),
)
