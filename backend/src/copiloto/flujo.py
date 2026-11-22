"""La lógica del flujo de una llamada, en funciones comunes. Acá no se importa el grafo."""

import logging
from datetime import datetime
from time import monotonic
from typing import Any, Literal, NotRequired, TypedDict

from copiloto import catalogo, dataset, interprete, tipo, ubicacion
from copiloto.catalogo import Pregunta, Protocolo, SubtipoInvalido
from copiloto.esquemas import (
    Ajustes,
    Aviso,
    Carta,
    Categoria,
    Cita,
    Dato,
    Falta,
    Ficha,
    Inferido,
    ItemChecklist,
    MarcaChecklist,
    Prioridad,
    Sugerencia,
    Turno,
    Ubicacion,
    cita_esta_en,
    texto_plano,
    valor_de,
)
from copiloto.modelo import Modelo, ModeloNoDisponible
from copiloto.turnos import tramos_del_llamante

_registro = logging.getLogger(__name__)


class _CitaPlana(TypedDict):
    turno: int
    texto: str


class _DatoPlano(TypedDict):
    origen: Literal["dicho", "inferido", "operador", "falta"]
    valor: NotRequired[object]
    cita: NotRequired[_CitaPlana]
    fuente: NotRequired[str]


class _Respuesta(TypedDict):
    id: str
    pregunta: str
    respondida: bool
    cita: NotRequired[_CitaPlana]


class FaltanDatos(ValueError):
    """La carta no se puede derivar: faltan datos obligatorios."""

    def __init__(self, campos: list[str]) -> None:
        self.campos = campos
        super().__init__(f"Para derivar falta completar: {', '.join(campos)}.")


class MarcaInvalida(ValueError):
    """Se marcó una pregunta que no es del protocolo que queda en la carta."""

    def __init__(self, preguntas: list[str]) -> None:
        self.preguntas = preguntas
        super().__init__(f"No son preguntas del protocolo de esta carta: {', '.join(preguntas)}.")


def analizar(turnos: list[Turno]) -> Sugerencia:
    """Propone ubicación, tipo de hecho y prioridad a partir de lo que se dijo en la llamada.

    Es el intérprete por reglas: no usa ningún modelo. La ubicación sale del texto y del callejero.
    Si la llamada es una de las del dataset provisto, el tipo, la prioridad y las preguntas ya
    respondidas salen de su ficha. Si es un texto nuevo, se propone sólo la categoría, por palabras
    clave, y el resto queda para el operador.
    """
    if (conocida := dataset.buscar(turnos)) is None:
        return analizar_base(turnos)
    lugar = ubicacion.interpretar(turnos)
    protocolo = catalogo.cargar().protocolo(conocida.categoria, conocida.subtipo)
    assert protocolo is not None  # La llamada conocida siempre trae un subtipo del catálogo.
    return Sugerencia.model_validate(
        {
            "ubicacion": lugar.ubicacion,
            "avisos": lugar.avisos,
            "tipo_hecho": Inferido[Categoria](valor=conocida.categoria, fuente="dataset"),
            "subtipo": Inferido[str](valor=conocida.subtipo, fuente="dataset"),
            "prioridad": Inferido[Prioridad](valor=conocida.prioridad, fuente="dataset"),
            "checklist": [
                _respuesta(pregunta, conocida.respuestas.get(pregunta.id), turnos)
                for pregunta in protocolo.preguntas
            ],
        }
    )


def analizar_base(turnos: list[Turno]) -> Sugerencia:
    """Arma la sugerencia del alta con el callejero y palabras clave."""
    lugar = ubicacion.interpretar(turnos)
    return Sugerencia(
        ubicacion=lugar.ubicacion,
        avisos=lugar.avisos,
        tipo_hecho=Inferido[Categoria](valor=tipo.por_palabras_clave(turnos), fuente="reglas"),
        prioridad=Falta(),
    )


def rescatar_analisis(turnos: list[Turno], motivo: str) -> Sugerencia:
    rescate = analizar(turnos)
    aviso = Aviso(
        codigo="modelo_no_disponible",
        mensaje=f"El modelo no respondió ({motivo}): esta sugerencia sale de las reglas.",
    )
    return rescate.model_copy(update={"avisos": [*rescate.avisos, aviso]})


def _motivo_de_falla(error: ModeloNoDisponible | interprete.RespuestaIlegible) -> str:
    motivo = (
        error.motivo if isinstance(error, ModeloNoDisponible) else "su respuesta no se pudo leer"
    )
    _registro.warning("%s: %r", motivo, error.__cause__ or error)
    return motivo


def analizar_con_modelo(
    turnos: list[Turno], base: Sugerencia, modelo: Modelo, espera_s: float
) -> Sugerencia:
    vence = monotonic() + espera_s
    usuario = interprete.mensaje_del_llamante(turnos)
    try:
        propuesta = interprete.clasificar(modelo, usuario, vence)
    except (ModeloNoDisponible, interprete.RespuestaIlegible) as error:
        return rescatar_analisis(turnos, _motivo_de_falla(error))

    avisos = list(base.avisos)
    protocolo = None
    if propuesta.subtipo is not None:
        try:
            if not isinstance(propuesta.subtipo, str):
                raise SubtipoInvalido("El identificador del subtipo debe ser texto.")
            protocolo = catalogo.cargar().protocolo(propuesta.categoria, propuesta.subtipo)
        except SubtipoInvalido:
            avisos.append(_SUBTIPO_DESCARTADO)

    respuestas: list[ItemChecklist] = []
    if protocolo is not None:
        try:
            respuestas, descartes = interprete.revisar_protocolo(
                modelo, usuario, protocolo, turnos, vence
            )
            avisos.extend(descartes)
        except interprete.SubtipoNoCorresponde:
            # No es un aviso para el operador: el subtipo queda sin elegir, que es lo habitual
            # cuando el catálogo no tiene uno para ese hecho.
            _registro.info("El modelo descartó al revisarlo el subtipo %s.", protocolo.id)
            protocolo = None
        except (ModeloNoDisponible, interprete.RespuestaIlegible) as error:
            # Un subtipo sin confirmar no se muestra: traería las preguntas y las instrucciones
            # de un caso que puede no ser este.
            avisos.append(_subtipo_sin_confirmar(protocolo, _motivo_de_falla(error)))
            protocolo = None

    return Sugerencia(
        ubicacion=base.ubicacion,
        avisos=avisos,
        tipo_hecho=Inferido[Categoria](valor=propuesta.categoria, fuente="modelo"),
        subtipo=Inferido[str](valor=protocolo.id, fuente="modelo") if protocolo else Falta(),
        prioridad=Inferido[Prioridad](
            valor=propuesta.prioridad,
            fuente="modelo",
            cita=interprete.verificar_cita(propuesta.cita, turnos),
        ),
        checklist=checklist_de(protocolo, respuestas),
        instrucciones=protocolo.instrucciones if protocolo else [],
    )


def _subtipo_sin_confirmar(protocolo: Protocolo, motivo: str) -> Aviso:
    mensaje = (
        f"El modelo propuso el subtipo «{protocolo.nombre}» y no llegó a confirmarlo: {motivo}. "
        "Elegí el subtipo si alguno corresponde."
    )
    return Aviso(codigo="modelo_no_disponible", mensaje=mensaje)


def _respuesta(pregunta: Pregunta, fragmento: str | None, turnos: list[Turno]) -> _Respuesta:
    """La pregunta, respondida si el fragmento anotado está en algo que dijo el llamante."""
    item: _Respuesta = {"id": pregunta.id, "pregunta": pregunta.texto, "respondida": False}
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
_SUBTIPO_DESCARTADO = Aviso(
    codigo="dato_descartado",
    mensaje="Se descartó el subtipo: no está en el catálogo o es de otra categoría.",
)


def quitar_lo_que_nadie_dijo(sugerencia: Sugerencia, turnos: list[Turno]) -> Sugerencia:
    """Verifica que cada cita salga de lo que dijo el llamante.

    Un dato dicho o una respuesta sin respaldo quedan pendientes, con un aviso. De una inferencia
    se conserva el valor y se quita la cita que no verificó.
    """
    descartes: list[str] = []
    cambio = False

    def revisar(dato: _DatoPlano, nombre: str, reemplazo: _DatoPlano | None = None) -> _DatoPlano:
        nonlocal cambio
        cita = dato.get("cita")
        if cita is None or _lo_dijo_el_llamante(Cita(**cita), turnos):
            return dato
        if dato["origen"] == "inferido":
            cambio = True
            dato.pop("cita")
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
    sin_determinar: _DatoPlano = {
        "origen": "inferido",
        "valor": Categoria.NO_DETERMINADA,
        "fuente": "reglas",
    }
    plana["tipo_hecho"] = revisar(plana["tipo_hecho"], "el tipo de hecho", sin_determinar)
    plana["subtipo"] = revisar(plana["subtipo"], "el subtipo")
    plana["prioridad"] = revisar(plana["prioridad"], "la prioridad")
    for item in plana["checklist"]:
        if item["cita"] and not _lo_dijo_el_llamante(Cita(**item["cita"]), turnos):
            descartes.append("la respuesta a una pregunta del protocolo")
            item.update(respondida=False, cita=None)
    if not descartes and not cambio:
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
    vigentes = _esquinas_vigentes(sugerencia.ubicacion, ubicacion)
    se_quitaron_esquinas = len(vigentes) < len(ubicacion["esquinas"])
    ubicacion["esquinas"] = vigentes
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
    # Un aviso sobre la dirección viaja en la carta sólo si el operador la dejó como estaba: si la
    # corrigió, se da por atendido. Lo que el sistema descartó no es asunto de quien despacha.
    sin_confirmar = [
        aviso
        for aviso in sugerencia.avisos
        if aviso.codigo not in ("dato_descartado", "modelo_no_disponible")
        and ubicacion == sugerencia.ubicacion.model_dump()
    ]
    if se_quitaron_esquinas:
        sin_confirmar.append(_ESQUINAS_DE_OTRA_DIRECCION)
    ficha = Ficha.model_validate(
        {
            "ubicacion": ubicacion,
            "tipo_hecho": tipo_hecho,
            "subtipo": subtipo,
            "prioridad": _resolver(sugerencia.prioridad, ajustes.prioridad, si_no_manda=True),
            "checklist": _marcar(checklist_de(protocolo, previo), ajustes.checklist or []),
            "instrucciones": protocolo.instrucciones if protocolo else [],
            "avisos": sin_confirmar,
        }
    )
    if faltan := ficha.faltantes():
        raise FaltanDatos(faltan)
    return Carta.model_validate(
        {**ficha.model_dump(), "llamada_id": llamada_id, "derivada_en": ahora}
    )


def _marcar(checklist: list[ItemChecklist], marcas: list[MarcaChecklist]) -> list[ItemChecklist]:
    """El checklist con lo que marcó el operador por encima.

    Confirmar lo que el sistema ya había detectado no cambia nada: la respuesta conserva su cita.
    Marcar una pendiente, o desmarcar una detectada, pasa a ser una decisión del operador.
    """
    marcadas = {marca.id: marca.respondida for marca in marcas}
    if ajenas := sorted(set(marcadas) - {item.id for item in checklist}):
        raise MarcaInvalida(ajenas)
    return [
        item
        if marcadas.get(item.id, item.respondida) == item.respondida
        else ItemChecklist(
            id=item.id, pregunta=item.pregunta, respondida=marcadas[item.id], del_operador=True
        )
        for item in checklist
    ]


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
    categoria = valor_de(sugerencia.tipo_hecho)
    assert categoria is not None  # Una sugerencia validada siempre tiene categoría.
    try:
        protocolo = catalogo.cargar().protocolo(categoria, subtipo.get("valor"))
    except SubtipoInvalido:
        protocolo, subtipo = None, {"origen": "falta"}
        avisos.append(_SUBTIPO_DESCARTADO)
    return Sugerencia.model_validate(
        {
            **sugerencia.model_dump(),
            "avisos": avisos,
            "subtipo": subtipo,
            "checklist": checklist_de(protocolo, sugerencia.checklist),
            "instrucciones": protocolo.instrucciones if protocolo else [],
        }
    )


_ESQUINAS_DE_OTRA_DIRECCION = Aviso(
    codigo="cruce_sin_confirmar",
    mensaje="Faltan las entrecalles: las que se habían propuesto eran de la dirección anterior.",
)


def _esquinas_vigentes(sugerida: Ubicacion, nueva: dict[str, Any]) -> list[dict[str, object]]:
    """Las esquinas que siguen valiendo para la dirección que queda en la carta.

    Una entrecalle que completó el callejero vale para la calle y la altura con las que se
    calculó. Si el operador cambia alguna de las dos y deja esa entrecalle, se vuelve a comprobar:
    queda sólo si el callejero la sigue dando para la dirección nueva.
    """
    esquinas: list[dict[str, object]] = nueva["esquinas"]
    if all(nueva[dato] == getattr(sugerida, dato).model_dump() for dato in ("calle", "altura")):
        return esquinas
    calle, altura = nueva["calle"].get("valor"), nueva["altura"].get("valor")
    del_callejero = ubicacion.entrecalles_de(calle, altura) if calle and altura else []
    return [
        esquina
        for esquina in esquinas
        if esquina.get("fuente") != "callejero"
        or any(_mismo(esquina["valor"], cruce) for cruce in del_callejero)
    ]


def _mismo(sugerido: object, nuevo: object) -> bool:
    # Volver a escribir lo mismo con otras mayúsculas, tildes o espacios no es un cambio.
    if isinstance(sugerido, str) and isinstance(nuevo, str):
        return texto_plano(sugerido) == texto_plano(nuevo)
    return sugerido == nuevo


def _resolver[T](
    sugerido: Dato[T], nuevo: T | None, si_no_manda: bool = False
) -> dict[str, object]:
    """El dato que queda en la carta: el sugerido si el operador no lo cambió; si no, el suyo.

    `si_no_manda` es para los campos sueltos, donde no mandar nada es dejar lo sugerido. En la
    ubicación, que llega entera, un campo vacío es que el operador lo vació.
    """
    if (si_no_manda and nuevo is None) or _mismo(valor_de(sugerido), nuevo):
        return sugerido.model_dump()
    return {"origen": "operador", "valor": nuevo}


def _resolver_esquina(sugeridas: list[Dato[str]], nombre: str) -> dict[str, object]:
    for sugerida in sugeridas:
        if _mismo(valor_de(sugerida), nombre):
            return sugerida.model_dump()
    return {"origen": "operador", "valor": nombre}
