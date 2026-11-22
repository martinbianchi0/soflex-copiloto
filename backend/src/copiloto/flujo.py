"""La lógica del flujo de una llamada, en funciones comunes. Acá no se importa el grafo."""

from datetime import datetime

from copiloto import catalogo, dataset, tipo, ubicacion
from copiloto.catalogo import Pregunta, Protocolo, SubtipoInvalido
from copiloto.esquemas import (
    Ajustes,
    Aviso,
    Carta,
    Categoria,
    Cita,
    Dato,
    Ficha,
    ItemChecklist,
    Sugerencia,
    Turno,
    cita_esta_en,
    texto_plano,
    valor_de,
)
from copiloto.turnos import tramos_del_llamante


class FaltanDatos(ValueError):
    """La carta no se puede derivar: faltan datos obligatorios."""

    def __init__(self, campos: list[str]) -> None:
        self.campos = campos
        super().__init__(f"Para derivar falta completar: {', '.join(campos)}.")


def analizar(turnos: list[Turno]) -> Sugerencia:
    """Propone ubicación, tipo de hecho y prioridad a partir de lo que se dijo en la llamada.

    Es el intérprete por reglas: no usa ningún modelo. La ubicación sale del texto y del callejero.
    Si la llamada es una de las del dataset provisto, el tipo, la prioridad y las preguntas ya
    respondidas salen de su ficha. Si es un texto nuevo, se propone sólo la categoría, por palabras
    clave, y el resto queda para el operador.
    """
    lugar = ubicacion.interpretar(turnos)
    propuesta: dict = {
        "ubicacion": lugar.ubicacion,
        "prioridad": {"origen": "falta"},
        "avisos": lugar.avisos,
    }
    if (conocida := dataset.buscar(turnos)) is None:
        categoria = tipo.por_palabras_clave(turnos)
        propuesta["tipo_hecho"] = {"origen": "inferido", "valor": categoria, "fuente": "reglas"}
        return Sugerencia.model_validate(propuesta)
    protocolo = catalogo.cargar().protocolo(conocida.categoria, conocida.subtipo)
    for campo in ("categoria", "subtipo", "prioridad"):
        dato = {"origen": "inferido", "valor": getattr(conocida, campo), "fuente": "dataset"}
        propuesta["tipo_hecho" if campo == "categoria" else campo] = dato
    propuesta["checklist"] = [
        _respuesta(pregunta, conocida.respuestas.get(pregunta.id), turnos)
        for pregunta in protocolo.preguntas
    ]
    return Sugerencia.model_validate(propuesta)


def _respuesta(pregunta: Pregunta, fragmento: str | None, turnos: list[Turno]) -> dict:
    """La pregunta, respondida si el fragmento anotado está en algo que dijo el llamante."""
    item = {"id": pregunta.id, "pregunta": pregunta.texto, "respondida": False}
    if fragmento is None:
        return item
    for n, turno in enumerate(turnos):
        if any(fragmento in tramo for tramo in tramos_del_llamante(turno)):
            return {**item, "respondida": True, "cita": {"turno": n, "texto": fragmento}}
    return item


def _lo_dijo_el_llamante(cita: Cita, turnos: list[Turno]) -> bool:
    """La cita está en su turno, y en la parte que dijo el llamante."""
    if not cita_esta_en(cita, turnos):
        return False
    en_el_tramo = Cita(turno=0, texto=cita.texto)
    return any(
        cita_esta_en(en_el_tramo, [Turno(texto=tramo)])
        for tramo in tramos_del_llamante(turnos[cita.turno])
    )


_DESCARTE = "Se descartó {}: la cita que lo respaldaba no está en lo que dijo el llamante."


def quitar_lo_que_nadie_dijo(sugerencia: Sugerencia, turnos: list[Turno]) -> Sugerencia:
    """Un dato "dicho" vale por su cita. Si el llamante no dijo eso, el dato se descarta.

    Lo que dice el operador no es evidencia: una cita que sólo está en sus palabras no respalda nada.

    No se corrige ni se adivina: queda como faltante para que lo complete el operador, y la
    sugerencia lo avisa. Así un intérprete que cita mal no tira abajo la llamada ni afirma nada.
    """
    descartes: list[str] = []

    def revisar(dato: dict, nombre: str, reemplazo: dict | None = None) -> dict:
        if dato["origen"] != "dicho" or _lo_dijo_el_llamante(Cita(**dato["cita"]), turnos):
            return dato
        descartes.append(nombre)
        return reemplazo or {"origen": "falta"}

    plana = sugerencia.model_dump()
    lugar = plana["ubicacion"]
    lugar["calle"] = revisar(lugar["calle"], "la calle")
    lugar["altura"] = revisar(lugar["altura"], "la altura")
    esquinas = [revisar(esquina, "una esquina") for esquina in lugar["esquinas"]]
    lugar["esquinas"] = [esquina for esquina in esquinas if esquina["origen"] != "falta"]
    # El tipo de hecho no puede faltar: sin respaldo, vuelve a "sin determinar".
    sin_determinar = {"origen": "inferido", "valor": Categoria.NO_DETERMINADA, "fuente": "reglas"}
    plana["tipo_hecho"] = revisar(plana["tipo_hecho"], "el tipo de hecho", sin_determinar)
    plana["subtipo"] = revisar(plana["subtipo"], "el subtipo")
    plana["prioridad"] = revisar(plana["prioridad"], "la prioridad")
    for item in plana["checklist"]:
        if item["cita"] and not _lo_dijo_el_llamante(Cita(**item["cita"]), turnos):
            descartes.append("la respuesta a una pregunta del protocolo")
            item.update(respondida=False, cita=None)
    if not descartes:
        return sugerencia
    plana["avisos"] += [
        {"codigo": "dato_descartado", "mensaje": _DESCARTE.format(que)} for que in descartes
    ]
    return Sugerencia.model_validate(plana)


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
    tipo_hecho, subtipo = sugerencia.tipo_hecho.model_dump(), sugerencia.subtipo.model_dump()
    sugerido = valor_de(sugerencia.subtipo)
    if (tipo := ajustes.tipo_hecho) is not None:
        tipo_hecho = _resolver(sugerencia.tipo_hecho, tipo.categoria)
        # Un identificador se compara exacto: no es un texto que el operador pueda reescribir.
        if tipo.subtipo != sugerido:
            subtipo = {"origen": "operador", "valor": tipo.subtipo}
    # El checklist y las instrucciones son siempre los del subtipo que queda en la carta. Si el
    # operador lo cambió, del anterior no se arrastra nada: ni las respuestas ni sus citas.
    protocolo = catalogo.cargar().protocolo(tipo_hecho["valor"], subtipo.get("valor"))
    previo = sugerencia.checklist if subtipo.get("valor") == sugerido else []
    ficha = Ficha.model_validate(
        {
            "ubicacion": ubicacion,
            "tipo_hecho": tipo_hecho,
            "subtipo": subtipo,
            "prioridad": _resolver(sugerencia.prioridad, ajustes.prioridad, si_no_manda=True),
            "checklist": checklist_de(protocolo, previo),
            "instrucciones": protocolo.instrucciones if protocolo else [],
        }
    )
    if faltan := ficha.faltantes():
        raise FaltanDatos(faltan)
    return Carta.model_validate(
        {**ficha.model_dump(), "llamada_id": llamada_id, "derivada_en": ahora}
    )


def checklist_de(protocolo: Protocolo | None, previo: list[ItemChecklist]) -> list[ItemChecklist]:
    """Las preguntas del protocolo, con el texto del catálogo.

    De lo que ya se sabía se conserva sólo si cada pregunta estaba respondida y dónde, y sólo
    cuando es la misma pregunta: mismo identificador y mismo texto.
    """
    if protocolo is None:
        return []
    sabido = {(item.id, item.pregunta): item for item in previo}
    return [
        sabido.get(
            (pregunta.id, pregunta.texto),
            ItemChecklist(id=pregunta.id, pregunta=pregunta.texto, respondida=False),
        )
        for pregunta in protocolo.preguntas
    ]


def ajustar_al_catalogo(sugerencia: Sugerencia) -> Sugerencia:
    """Deja en la sugerencia sólo lo que el catálogo respalda.

    Un subtipo que no existe o que es de otra categoría se descarta y queda como faltante. Las
    preguntas y las instrucciones son siempre las del protocolo, con su texto.
    """
    subtipo, avisos = sugerencia.subtipo.model_dump(), list(sugerencia.avisos)
    try:
        protocolo = catalogo.cargar().protocolo(sugerencia.tipo_hecho.valor, subtipo.get("valor"))
    except SubtipoInvalido:
        protocolo, subtipo = None, {"origen": "falta"}
        mensaje = "Se descartó el subtipo: no está en el catálogo o es de otra categoría."
        avisos.append(Aviso(codigo="dato_descartado", mensaje=mensaje))
    return Sugerencia.model_validate(
        {
            **sugerencia.model_dump(),
            "avisos": avisos,
            "subtipo": subtipo,
            "checklist": checklist_de(protocolo, sugerencia.checklist),
            "instrucciones": protocolo.instrucciones if protocolo else [],
        }
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
