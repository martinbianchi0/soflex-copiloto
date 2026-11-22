"""La lógica del flujo de una llamada, en funciones comunes. Acá no se importa el grafo."""

from datetime import datetime

from copiloto.esquemas import (
    Ajustes,
    Carta,
    Categoria,
    Dato,
    Ficha,
    Sugerencia,
    Turno,
    texto_plano,
    valor_de,
)


class FaltanDatos(ValueError):
    """La carta no se puede derivar: faltan datos obligatorios."""

    def __init__(self, campos: list[str]) -> None:
        self.campos = campos
        super().__init__(f"Para derivar falta completar: {', '.join(campos)}.")


def analizar(turnos: list[Turno]) -> Sugerencia:
    """Propone ubicación, tipo de hecho y prioridad a partir de lo que se dijo en la llamada.

    Todavía no interpreta el texto, así que no afirma nada: lo que no leyó, falta.
    """
    return Sugerencia.model_validate(
        {
            "ubicacion": {
                "calle": {"origen": "falta"},
                "altura": {"origen": "falta"},
                "esquinas": [],
            },
            "tipo_hecho": {
                "origen": "inferido",
                "valor": Categoria.NO_DETERMINADA,
                "fuente": "reglas",
            },
            "prioridad": {"origen": "falta"},
        }
    )


def derivar(llamada_id: str, sugerencia: Sugerencia, ajustes: Ajustes, ahora: datetime) -> Carta:
    """Arma la Carta de Llamada: lo sugerido, con lo que el operador cambió por encima.

    Lo que el operador deja igual conserva su origen y su cita; lo que cambia pasa a ser suyo.
    """
    ubicacion = sugerencia.ubicacion.model_dump()
    if (nueva := ajustes.ubicacion) is not None:
        sugeridas = sugerencia.ubicacion.esquinas
        ubicacion = {
            "calle": _resolver(sugerencia.ubicacion.calle, nueva.calle),
            "altura": _resolver(sugerencia.ubicacion.altura, nueva.altura),
            "esquinas": [_resolver_esquina(sugeridas, nombre) for nombre in nueva.esquinas],
        }
    ficha = Ficha.model_validate(
        {
            **sugerencia.model_dump(),
            "ubicacion": ubicacion,
            "tipo_hecho": _resolver(sugerencia.tipo_hecho, ajustes.tipo_hecho, si_no_manda=True),
            "prioridad": _resolver(sugerencia.prioridad, ajustes.prioridad, si_no_manda=True),
        }
    )
    if faltan := ficha.faltantes():
        raise FaltanDatos(faltan)
    return Carta.model_validate(
        {**ficha.model_dump(), "llamada_id": llamada_id, "derivada_en": ahora}
    )


def _mismo(sugerido: object, nuevo: object) -> bool:
    # Volver a escribir lo mismo con otras mayúsculas, tildes o espacios no es un cambio.
    if isinstance(sugerido, str) and isinstance(nuevo, str):
        return texto_plano(sugerido) == texto_plano(nuevo)
    return sugerido == nuevo


def _resolver(sugerido: Dato, nuevo: object, si_no_manda: bool = False) -> dict:
    """El dato que queda en la carta: el sugerido si el operador no lo cambió; si no, el suyo.

    `si_no_manda` es para los campos sueltos, donde no mandar nada es dejar lo sugerido. En la
    ubicación, que llega entera, un campo vacío es que el operador lo vació.
    """
    if (si_no_manda and nuevo is None) or _mismo(valor_de(sugerido), nuevo):
        return sugerido.model_dump()
    return {"origen": "operador", "valor": nuevo}


def _resolver_esquina(sugeridas: list[Dato], nombre: str) -> dict:
    for sugerida in sugeridas:
        if _mismo(valor_de(sugerida), nombre):
            return sugerida.model_dump()
    return {"origen": "operador", "valor": nombre}
