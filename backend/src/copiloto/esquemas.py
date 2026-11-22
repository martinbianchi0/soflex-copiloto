"""Los datos del servicio y sus reglas. Lo que no cumple un esquema no entra al flujo ni sale de él."""

import re
import unicodedata
from enum import StrEnum
from typing import Annotated, Literal, Protocol, Self

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

_TILDE_DE_LA_ENIE = "̃"


def texto_plano(texto: str) -> str:
    """El texto reducido a sus palabras: sin mayúsculas, sin acentos y sin puntuación.

    La ñ se conserva: "Cañada" y "Canada" son nombres distintos.
    """
    letras = (
        letra
        for letra in unicodedata.normalize("NFD", texto.lower())
        if unicodedata.category(letra) != "Mn" or letra == _TILDE_DE_LA_ENIE
    )
    sin_acentos = unicodedata.normalize("NFC", "".join(letras))
    return " ".join(re.sub(r"[\W_]+", " ", sin_acentos).split())


def _con_contenido(texto: str) -> str:
    # Un espacio invisible o pura puntuación pasan el largo mínimo pero no dicen nada.
    if not texto_plano(texto):
        raise ValueError("Tiene que tener al menos una letra o un número.")
    return texto


MAXIMO_DE_TEXTO = 200
MAXIMO_DE_TEXTO_LARGO = 1_000
Texto = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAXIMO_DE_TEXTO),
    AfterValidator(_con_contenido),
]
TextoLargo = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAXIMO_DE_TEXTO_LARGO),
    AfterValidator(_con_contenido),
]
TextoDeTurno = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20_000)
]
MAXIMO_DE_LA_LLAMADA = 50_000
MAXIMO_DE_TURNOS = 500
MAXIMO_DE_DICTADOS = 10
# Tiene que ser un entero de verdad: ni "1540" ni 1540.0.
Altura = Annotated[int, Field(ge=1, le=99_999, strict=True)]


class Esquema(BaseModel):
    # Un campo que no existe es un error, no algo para ignorar en silencio. Un dato ya armado no
    # se modifica, y si llega como parte de otro se vuelve a validar.
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")


class Categoria(StrEnum):
    INCENDIO_RESCATE = "INCENDIO_RESCATE"
    EMERGENCIA_MEDICA = "EMERGENCIA_MEDICA"
    ACCIDENTE_VIAL = "ACCIDENTE_VIAL"
    DEFENSA_CIVIL = "DEFENSA_CIVIL"
    SERVICIOS_PUBLICOS = "SERVICIOS_PUBLICOS"
    CONVIVENCIA_SEGURIDAD = "CONVIVENCIA_SEGURIDAD"
    # Lo dicho no alcanza para reconocer el tipo. Es un valor válido, no un dato que falta.
    NO_DETERMINADA = "NO_DETERMINADA"


class Prioridad(StrEnum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


# ---------- La llamada: una lista de turnos ----------


class Turno(Esquema):
    texto: TextoDeTurno
    # Quién habla, cuando se sabe. Lo que dice el operador no es evidencia de lo que pasó.
    hablante: Literal["operador", "llamante"] | None = None


class Cita(Esquema):
    """Un fragmento textual de la llamada: en qué turno está y qué dice."""

    turno: int = Field(ge=0)
    texto: Texto


def cita_esta_en(cita: Cita, turnos: list[Turno]) -> bool:
    """La cita vale si sus palabras aparecen, enteras y de corrido, en el turno que indica.

    No distingue mayúsculas, acentos ni puntuación; todo lo demás tiene que coincidir. Las palabras
    van enteras: "Corrientes 154" no es una cita de "Corrientes 1540".
    """
    buscado = texto_plano(cita.texto)
    if not buscado or not 0 <= cita.turno < len(turnos):
        return False
    return f" {buscado} " in f" {texto_plano(turnos[cita.turno].texto)} "


def citas_que_no_estan(ficha: "Ficha", turnos: list[Turno]) -> list[Cita]:
    return [cita for cita in ficha.citas() if not cita_esta_en(cita, turnos)]


# ---------- El origen de cada dato ----------
# Cada origen es una forma distinta, con exactamente los campos que le corresponden: un dato
# "dicho" sin su cita, o uno que "falta" con un valor, no se pueden construir.


class Dicho[T](Esquema):
    """Lo dijo alguien en la llamada. Lleva la cita que lo respalda."""

    origen: Literal["dicho"] = "dicho"
    valor: T
    cita: Cita


class Inferido[T](Esquema):
    """No se dijo: lo completó el sistema, y dice con qué."""

    origen: Literal["inferido"] = "inferido"
    valor: T
    # "dataset": la llamada es una de las del dataset provisto y el dato sale de su ficha.
    fuente: Literal["callejero", "reglas", "modelo", "dataset"]
    cita: Cita | None = Field(default=None, exclude_if=lambda cita: cita is None)


class DelOperador[T](Esquema):
    """Lo escribió o lo corrigió el operador. Sin valor: el operador vació lo sugerido."""

    origen: Literal["operador"] = "operador"
    valor: T | None


class Falta(Esquema):
    """Nadie lo dijo y nada lo completa: es una pregunta pendiente para el operador."""

    origen: Literal["falta"] = "falta"


type Dato[T] = Annotated[
    Dicho[T] | Inferido[T] | DelOperador[T] | Falta, Field(discriminator="origen")
]


class _ConValor[T](Protocol):
    @property
    def valor(self) -> T | None: ...


def valor_de[T](dato: _ConValor[T] | Falta) -> T | None:
    if isinstance(dato, Falta):
        return None
    return dato.valor


# ---------- Lo que se sabe del hecho ----------


def _distintos(nombres: list[str]) -> bool:
    planos = [texto_plano(nombre) for nombre in nombres]
    return len(set(planos)) == len(planos)


class Ubicacion(Esquema):
    calle: Dato[Texto]
    altura: Dato[Altura]
    esquinas: list[Dato[Texto]] = Field(max_length=2)

    @model_validator(mode="after")
    def esquinas_con_nombre_y_distintas(self) -> Self:
        nombres: list[str] = []
        for esquina in self.esquinas:
            nombre = valor_de(esquina)
            if nombre is None:
                raise ValueError("Una esquina sin nombre no va en la lista.")
            nombres.append(nombre)
        calle = valor_de(self.calle)
        if not _distintos(nombres + ([calle] if calle else [])):
            raise ValueError("La calle y las esquinas tienen que ser distintas entre sí.")
        return self


class ItemChecklist(Esquema):
    """Una pregunta del protocolo y si ya quedó respondida en la llamada.

    Una pendiente con cita es una posible respuesta: el sistema la propone y todavía no la confirmó
    nadie. Si el operador la marca, queda respondida por él y conserva la cita que se le mostró.
    """

    id: Texto
    pregunta: TextoLargo
    respondida: bool
    # Dónde lo dijo el llamante, cuando lo detecta el sistema.
    cita: Cita | None = None
    # La marcó o la desmarcó el operador. Su palabra no necesita cita.
    del_operador: bool = False

    @model_validator(mode="after")
    def con_respaldo(self) -> Self:
        if self.cita is not None and self.del_operador and not self.respondida:
            raise ValueError("Una pregunta que el operador desmarcó no lleva cita.")
        if self.respondida and self.cita is None and not self.del_operador:
            raise ValueError("Una pregunta respondida lleva su cita, o la marcó el operador.")
        return self


class Instruccion(Esquema):
    """Una instrucción de pre-arribo: se lee textual, no se redacta."""

    id: Texto
    texto: TextoLargo


type TipoDictado = Literal["patente", "telefono"]


class DictadoQuitado(Esquema):
    tipo: TipoDictado
    valor: Texto


class DatoDictado(DictadoQuitado):
    cita: Cita


OBLIGATORIOS_PARA_DERIVAR = ("calle", "tipo_hecho", "prioridad")


class Aviso(Esquema):
    """Algo que conviene confirmar con el llamante. En la carta: lo que quedó sin confirmar."""

    codigo: Literal[
        "sin_calle",
        "falta_altura",
        "calle_ambigua",
        "direccion_no_cierra",
        "cruce_sin_confirmar",
        "ficha_sin_actualizar",
        "prioridad_cambiada",
        "dato_descartado",
        "modelo_no_disponible",
        "dictado_incompleto",
    ]
    mensaje: TextoLargo


class Ficha(Esquema):
    """Lo que se sabe del hecho. Es la base de la sugerencia del sistema y de la carta."""

    ubicacion: Ubicacion
    tipo_hecho: Dato[Categoria]
    # El identificador de un protocolo del catálogo. De él salen el checklist y las instrucciones.
    subtipo: Dato[Texto] = Field(default_factory=Falta)
    prioridad: Dato[Prioridad]
    checklist: list[ItemChecklist] = Field(default_factory=list)
    instrucciones: list[Instruccion] = Field(default_factory=list)
    avisos: list[Aviso] = Field(default_factory=list)
    datos_dictados: list[DatoDictado] = Field(default_factory=list, max_length=MAXIMO_DE_DICTADOS)

    @model_validator(mode="after")
    def sin_preguntas_ni_instrucciones_repetidas(self) -> Self:
        for nombre, ids in (
            ("pregunta", [item.id for item in self.checklist]),
            ("instrucción", [instruccion.id for instruccion in self.instrucciones]),
        ):
            if len(set(ids)) != len(ids):
                raise ValueError(f"Hay una {nombre} repetida.")
        return self

    def datos(self) -> dict[str, Dato[str] | Dato[int] | Dato[Categoria] | Dato[Prioridad]]:
        esquinas = {f"esquinas.{n}": esquina for n, esquina in enumerate(self.ubicacion.esquinas)}
        return {
            "calle": self.ubicacion.calle,
            "altura": self.ubicacion.altura,
            **esquinas,
            "tipo_hecho": self.tipo_hecho,
            "subtipo": self.subtipo,
            "prioridad": self.prioridad,
        }

    def citas(self) -> list[Cita]:
        de_los_datos = [
            dato.cita
            for dato in self.datos().values()
            if isinstance(dato, (Dicho, Inferido)) and dato.cita is not None
        ]
        del_checklist = [item.cita for item in self.checklist if item.cita is not None]
        return de_los_datos + del_checklist + [dato.cita for dato in self.datos_dictados]

    def faltantes(self) -> list[str]:
        """Los datos sin los que la carta no se puede derivar."""
        datos = self.datos()
        return [campo for campo in OBLIGATORIOS_PARA_DERIVAR if valor_de(datos[campo]) is None]


class Sugerencia(Ficha):
    """Lo que propone el sistema. El operador todavía no tocó nada."""

    @model_validator(mode="after")
    def es_del_sistema(self) -> Self:
        del_operador = [n for n, dato in self.datos().items() if isinstance(dato, DelOperador)]
        if del_operador:
            raise ValueError(
                f"Una sugerencia no trae datos del operador: {', '.join(del_operador)}."
            )
        if self.tipo_hecho.origen == "falta":
            raise ValueError("El tipo de hecho nunca falta: si no se reconoce, es NO_DETERMINADA.")
        if any(item.del_operador for item in self.checklist):
            raise ValueError("Una sugerencia no trae preguntas marcadas por el operador.")
        return self


class Carta(Ficha):
    """La Carta de Llamada: lo que el operador confirmó y derivó."""

    llamada_id: Texto
    derivada_en: AwareDatetime

    @model_validator(mode="after")
    def con_lo_minimo_para_derivar(self) -> Self:
        if faltan := self.faltantes():
            raise ValueError(f"Para derivar falta completar: {', '.join(faltan)}.")
        return self


class Llamada(Esquema):
    """Una llamada con todo lo suyo: lo que se dijo, lo que se sugirió y, si se derivó, su carta."""

    llamada_id: Texto
    estado: Literal["en_proceso", "analizando", "esperando_operador", "derivada"]
    turnos: list[Turno] = Field(min_length=1, max_length=MAXIMO_DE_TURNOS)
    sugerencia: Sugerencia | None
    carta: Carta | None

    @model_validator(mode="after")
    def el_estado_coincide_con_lo_que_hay(self) -> Self:
        if (self.estado == "derivada") != (self.carta is not None):
            raise ValueError("Una llamada está derivada si y sólo si tiene su carta.")
        if self.estado != "en_proceso" and self.sugerencia is None:
            raise ValueError("Una llamada que ya se analizó tiene su sugerencia.")
        if self.carta is not None and self.carta.llamada_id != self.llamada_id:
            raise ValueError("La carta es de otra llamada.")
        return self

    @model_validator(mode="after")
    def las_citas_estan_en_la_llamada(self) -> Self:
        for ficha in (self.sugerencia, self.carta):
            for cita in citas_que_no_estan(ficha, self.turnos) if ficha else []:
                raise ValueError(f"La cita no aparece en el turno {cita.turno}: {cita.texto!r}")
        return self


# ---------- Otras llamadas del mismo lugar ----------


class PosibleDuplicado(Esquema):
    llamada_id: Texto
    recibida_en: AwareDatetime
    ubicacion: str
    categoria: Categoria
    derivada: bool


class Duplicados(Esquema):
    llamada_id: Texto
    recibida_en: AwareDatetime | None
    posibles: list[PosibleDuplicado]


# ---------- Plano para confirmar la dirección ----------


class PedidoDePlano(Esquema):
    calle: Texto
    altura: Altura | None
    esquinas: list[Texto] = Field(max_length=2)


class CuadraDelPlano(Esquema):
    nombre: str
    x1: float
    y1: float
    x2: float
    y2: float
    principal: bool


class Plano(Esquema):
    radio_m: int
    exacto: bool
    leyenda: str
    cuadras: list[CuadraDelPlano]


# ---------- El historial de la llamada ----------


type TipoEvento = Literal[
    "recibida",
    "sugerencia_reglas",
    "sugerencia_modelo",
    "turno_agregado",
    "ajustes_operador",
    "derivada",
]


class EventoHistorial(Esquema):
    tipo: TipoEvento
    cuando: AwareDatetime
    detalle: TextoLargo


class EstadoPregunta(Esquema):
    respondida: bool
    # El sistema la proponía como posible respuesta, sin darla por respondida.
    propuesta: bool = False


type ValorCambio = Dato[Texto | Altura] | list[Dato[Texto]] | EstadoPregunta


class CambioHistorial(Esquema):
    campo: Texto
    sugerido: ValorCambio
    final: ValorCambio


class Historial(Esquema):
    llamada_id: Texto
    eventos: list[EventoHistorial]
    cambios: list[CambioHistorial]


# ---------- Lo que la API acepta ----------


class NuevaLlamada(Esquema):
    turnos: list[Turno] = Field(min_length=1, max_length=MAXIMO_DE_TURNOS)

    @model_validator(mode="after")
    def de_un_largo_razonable(self) -> Self:
        # Una llamada de diez minutos son unos 10.000 caracteres. El tope acota lo que tarda el
        # análisis, que tiene que responder mientras el operador sigue atendiendo.
        if sum(len(turno.texto) for turno in self.turnos) > MAXIMO_DE_LA_LLAMADA:
            raise ValueError(
                f"La transcripción completa puede tener hasta {MAXIMO_DE_LA_LLAMADA} caracteres."
            )
        return self


class NuevoTurno(Esquema):
    turno: Turno


class UbicacionAjustada(Esquema):
    """Se manda entera y con los valores a secas: el origen de cada uno lo resuelve el servicio."""

    calle: Texto
    altura: Altura | None
    esquinas: list[Texto] = Field(max_length=2)

    @model_validator(mode="after")
    def calle_y_esquinas_distintas(self) -> Self:
        if not _distintos([self.calle, *self.esquinas]):
            raise ValueError("La calle y las esquinas tienen que ser distintas entre sí.")
        return self


class TipoAjustado(Esquema):
    """Se manda entero: la categoría y, si lo hay, el subtipo. Sin subtipo, `null`."""

    categoria: Categoria
    subtipo: Texto | None


class MarcaChecklist(Esquema):
    """Una pregunta del protocolo que el operador marca como respondida o como pendiente."""

    id: Texto
    respondida: bool
    # Si se manda, es la cita que se tenía a la vista al marcar, incluso si era ninguna.
    cita: Cita | None = None

    @model_validator(mode="after")
    def cita_solo_si_respondida(self) -> Self:
        if self.cita is not None and not self.respondida:
            raise ValueError("Una pregunta que el operador desmarcó no lleva cita.")
        return self


class Ajustes(Esquema):
    """Lo que el operador cambia de la sugerencia. Lo que no manda queda como estaba."""

    ubicacion: UbicacionAjustada | None = None
    tipo_hecho: TipoAjustado | None = None
    prioridad: Prioridad | None = None
    # Sólo las preguntas que el operador marcó o desmarcó.
    checklist: list[MarcaChecklist] | None = Field(default=None, max_length=50)
    dictados_quitados: list[DictadoQuitado] | None = Field(
        default=None, max_length=MAXIMO_DE_DICTADOS
    )

    @model_validator(mode="after")
    def sin_marcas_repetidas(self) -> Self:
        ids = [marca.id for marca in self.checklist or []]
        if len(set(ids)) != len(ids):
            raise ValueError("Cada pregunta se marca una sola vez.")
        return self

    @model_validator(mode="after")
    def sin_campos_vacios(self) -> Self:
        # Omitir un campo y mandarlo en `null` no son lo mismo: lo segundo es un pedido mal armado.
        vacios = sorted(campo for campo in self.model_fields_set if getattr(self, campo) is None)
        if vacios:
            raise ValueError(f"Para dejar un campo como está, no lo mandes: {', '.join(vacios)}.")
        return self


class Derivacion(Esquema):
    ajustes: Ajustes = Field(default_factory=Ajustes)
