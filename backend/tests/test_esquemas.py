import pytest
from conftest import TURNOS
from pydantic import TypeAdapter, ValidationError

from copiloto.esquemas import (
    Ajustes,
    Altura,
    Carta,
    Cita,
    Dato,
    ItemChecklist,
    Llamada,
    Sugerencia,
    Texto,
    Turno,
    Ubicacion,
    cita_esta_en,
)

DICHA = {"origen": "dicho", "valor": "Av. Corrientes", "cita": {"turno": 0, "texto": "Corrientes"}}
FALTA = {"origen": "falta"}


# ---------- El origen de cada dato ----------


@pytest.mark.parametrize(
    "dato",
    [
        DICHA,
        {"origen": "inferido", "valor": "Paraná", "fuente": "callejero"},
        {"origen": "operador", "valor": "Av. Corrientes"},
        {"origen": "operador", "valor": None},
        FALTA,
    ],
)
def test_cada_origen_tiene_su_forma(dato):
    assert TypeAdapter(Dato[Texto]).validate_python(dato).model_dump() == dato


@pytest.mark.parametrize(
    "dato",
    [
        {"origen": "dicho", "valor": "Av. Corrientes"},
        {"origen": "inferido", "valor": "Paraná"},
        {"origen": "inferido", "valor": "Paraná", "fuente": "intuición"},
        {"origen": "falta", "valor": "Av. Corrientes"},
        {"origen": "adivinado", "valor": "Av. Corrientes"},
        {"valor": "Av. Corrientes"},
        {"origen": "operador", "valor": "   "},
        {"origen": "operador", "valor": "\u200b"},
        {"origen": "operador", "valor": "¡¿...?!"},
    ],
)
def test_un_dato_que_no_cumple_la_forma_de_su_origen_no_se_construye(dato):
    with pytest.raises(ValidationError):
        TypeAdapter(Dato[Texto]).validate_python(dato)


@pytest.mark.parametrize("altura", ["1540", 1540.0, True, 0, 100_000])
def test_la_altura_es_un_entero_de_verdad_y_dentro_de_rango(altura):
    with pytest.raises(ValidationError):
        TypeAdapter(Dato[Altura]).validate_python({"origen": "operador", "valor": altura})


# ---------- Ubicación, checklist y fichas ----------


def test_la_calle_y_las_esquinas_no_se_repiten():
    repetida = {"origen": "inferido", "valor": "av corrientes", "fuente": "callejero"}

    with pytest.raises(ValidationError, match="distintas"):
        Ubicacion.model_validate({"calle": DICHA, "altura": FALTA, "esquinas": [repetida]})


@pytest.mark.parametrize("esquina", [FALTA, {"origen": "operador", "valor": None}])
def test_una_esquina_sin_nombre_no_va_en_la_lista(esquina):
    with pytest.raises(ValidationError, match="sin nombre"):
        Ubicacion.model_validate({"calle": DICHA, "altura": FALTA, "esquinas": [esquina]})


def test_una_pregunta_pendiente_no_lleva_cita():
    with pytest.raises(ValidationError, match="pendiente"):
        ItemChecklist.model_validate(
            {
                "id": "a",
                "pregunta": "¿Hay humo?",
                "respondida": False,
                "cita": {"turno": 0, "texto": "x"},
            }
        )


def test_una_sugerencia_no_trae_datos_del_operador(sugerencia_completa):
    sugerencia_completa["prioridad"] = {"origen": "operador", "valor": "P1"}

    with pytest.raises(ValidationError, match="del operador"):
        Sugerencia.model_validate(sugerencia_completa)


def test_el_tipo_de_hecho_de_una_sugerencia_nunca_falta(sugerencia_completa):
    sugerencia_completa["tipo_hecho"] = FALTA

    with pytest.raises(ValidationError, match="NO_DETERMINADA"):
        Sugerencia.model_validate(sugerencia_completa)


def test_una_carta_sin_lo_minimo_no_se_construye(sugerencia_completa):
    carta = {**sugerencia_completa, "llamada_id": "abc", "derivada_en": "2026-11-22T03:00:00Z"}

    with pytest.raises(ValidationError, match="falta completar: prioridad"):
        Carta.model_validate(carta)

    carta["prioridad"] = {"origen": "operador", "valor": "P1"}
    assert Carta.model_validate(carta).faltantes() == []


def test_una_carta_necesita_la_hora_con_su_zona(sugerencia_completa):
    carta = {**sugerencia_completa, "prioridad": {"origen": "operador", "valor": "P1"}}

    with pytest.raises(ValidationError):
        Carta.model_validate({**carta, "llamada_id": "abc", "derivada_en": "2026-11-22T03:00:00"})


# ---------- Las citas se verifican contra la llamada ----------


@pytest.mark.parametrize(
    "texto",
    ["Av. Corrientes 1540", "av corrientes 1540", "PIZZERIA de av. corrientes", "se prendió fuego"],
)
def test_una_cita_vale_si_esta_en_su_turno_sin_mirar_mayusculas_tildes_ni_puntuacion(texto):
    assert cita_esta_en(Cita(turno=0, texto=texto), [Turno(**TURNOS[0])])


@pytest.mark.parametrize(
    "cita",
    [
        {"turno": 0, "texto": "Av. Corrientes 1450"},
        {"turno": 0, "texto": "Av. Corrientes 154"},
        {"turno": 0, "texto": "orrientes 1540"},
        {"turno": 0, "texto": "54"},
        {"turno": 0, "texto": "Corrientes casi Montevideo"},
        {"turno": 1, "texto": "Av. Corrientes 1540"},
    ],
)
def test_una_cita_que_no_esta_en_su_turno_no_vale(cita):
    assert not cita_esta_en(Cita(**cita), [Turno(**TURNOS[0])])


@pytest.mark.parametrize("texto", ["¡¿...?!", "\u200b", "   "])
def test_una_cita_sin_palabras_no_se_puede_armar(texto):
    with pytest.raises(ValidationError):
        Cita(turno=0, texto=texto)


def llamada(sugerencia, **cambios):
    base = {
        "llamada_id": "abc",
        "estado": "esperando_operador",
        "turnos": TURNOS,
        "sugerencia": sugerencia,
        "carta": None,
    }
    return {**base, **cambios}


def test_una_llamada_con_sus_citas_en_sus_turnos_es_valida(sugerencia_completa):
    assert Llamada.model_validate(llamada(sugerencia_completa)).estado == "esperando_operador"


def test_una_llamada_con_un_dato_citado_que_nadie_dijo_no_es_valida(sugerencia_completa):
    sugerencia_completa["ubicacion"]["calle"]["cita"]["texto"] = "Av. Rivadavia 4500"

    with pytest.raises(ValidationError, match="La cita no aparece"):
        Llamada.model_validate(llamada(sugerencia_completa))


def test_la_cita_de_una_respuesta_del_checklist_tambien_se_verifica(sugerencia_completa):
    sugerencia_completa["checklist"][1]["cita"]["texto"] = "no hay nadie adentro"

    with pytest.raises(ValidationError, match="La cita no aparece"):
        Llamada.model_validate(llamada(sugerencia_completa))


def test_las_citas_de_la_carta_tambien_se_verifican(sugerencia_completa):
    carta = {
        **sugerencia_completa,
        "prioridad": {"origen": "operador", "valor": "P1"},
        "llamada_id": "abc",
        "derivada_en": "2026-11-22T03:00:00Z",
    }

    assert Llamada.model_validate(llamada(sugerencia_completa, estado="derivada", carta=carta))
    carta["ubicacion"]["altura"]["cita"] = {"turno": 0, "texto": "al 1540"}
    with pytest.raises(ValidationError, match="La cita no aparece"):
        Llamada.model_validate(llamada(sugerencia_completa, estado="derivada", carta=carta))


@pytest.mark.parametrize(
    "cambios",
    [
        {"estado": "derivada"},
        {"estado": "esperando_operador", "sugerencia": None},
        {"estado": "en_proceso", "carta": "pendiente"},
    ],
)
def test_el_estado_de_una_llamada_coincide_con_lo_que_tiene(sugerencia_completa, cambios):
    if cambios.get("carta") == "pendiente":
        cambios["carta"] = {
            **sugerencia_completa,
            "prioridad": {"origen": "operador", "valor": "P1"},
            "llamada_id": "abc",
            "derivada_en": "2026-11-22T03:00:00Z",
        }

    with pytest.raises(ValidationError):
        Llamada.model_validate({**llamada(sugerencia_completa), **cambios})


# ---------- Lo que manda el operador ----------


@pytest.mark.parametrize(
    "ajustes",
    [
        {"prioridad": "P9"},
        {"tipo_hecho": "INCENDIO"},
        {"campo_inventado": "x"},
        {"prioridad": None},
        {"ubicacion": None},
        {"ubicacion": {"calle": "Av. Corrientes"}},
        {"ubicacion": {"calle": "  ", "altura": None, "esquinas": []}},
        {"ubicacion": {"calle": "Av. Corrientes", "altura": "1540", "esquinas": []}},
        {"ubicacion": {"calle": "Av. Corrientes", "altura": 10**100, "esquinas": []}},
        {"ubicacion": {"calle": "Av. Corrientes", "altura": None, "esquinas": ["a", "b", "c"]}},
        {"ubicacion": {"calle": "Paraná", "altura": None, "esquinas": [" PARANA "]}},
    ],
)
def test_un_ajuste_mal_armado_se_rechaza(ajustes):
    with pytest.raises(ValidationError):
        Ajustes.model_validate(ajustes)


def test_un_ajuste_sin_nada_es_valido_y_no_cambia_nada():
    assert Ajustes.model_validate({}).model_dump(exclude_unset=True) == {}


def test_una_cita_se_busca_en_su_turno_y_no_en_otro():
    dos_turnos = [Turno(texto="¿Dónde es la emergencia?"), Turno(texto="En Corrientes 1540.")]

    assert cita_esta_en(Cita(turno=1, texto="Corrientes 1540"), dos_turnos)
    assert not cita_esta_en(Cita(turno=0, texto="Corrientes 1540"), dos_turnos)


@pytest.mark.parametrize(
    ("cita", "turno", "vale"),
    [
        ("Cañada", "Estoy en Cañada de Gómez", True),
        ("Canada", "Estoy en Cañada de Gómez", False),
        ("Nuñez", "Barrio de Núñez", True),
        ("Nunez", "Barrio de Núñez", False),
        ("Güemes", "calle guemes al 300", True),
        ("Łódź", "Embajada en Łódź 12", True),
    ],
)
def test_las_citas_respetan_la_enie_y_las_letras_que_no_son_ascii(cita, turno, vale):
    assert cita_esta_en(Cita(turno=0, texto=cita), [Turno(texto=turno)]) is vale


def test_la_cita_de_una_respuesta_en_la_carta_tambien_se_verifica(sugerencia_completa):
    carta = {
        **sugerencia_completa,
        "prioridad": {"origen": "operador", "valor": "P1"},
        "llamada_id": "abc",
        "derivada_en": "2026-11-22T03:00:00Z",
    }
    carta["checklist"][1]["cita"] = {"turno": 0, "texto": "no hay nadie adentro"}
    sugerencia = Sugerencia.model_validate(sugerencia_completa).model_dump(mode="json")
    sugerencia["checklist"][1]["cita"] = {"turno": 0, "texto": "se prendió fuego"}

    with pytest.raises(ValidationError, match="La cita no aparece"):
        Llamada.model_validate(llamada(sugerencia, estado="derivada", carta=carta))


def test_una_carta_de_otra_llamada_no_es_valida(sugerencia_completa):
    carta = {
        **sugerencia_completa,
        "prioridad": {"origen": "operador", "valor": "P1"},
        "llamada_id": "otra",
        "derivada_en": "2026-11-22T03:00:00Z",
    }

    with pytest.raises(ValidationError, match="otra llamada"):
        Llamada.model_validate(llamada(sugerencia_completa, estado="derivada", carta=carta))


def test_un_dato_ya_armado_no_se_puede_modificar(sugerencia_completa):
    sugerencia = Sugerencia.model_validate(sugerencia_completa)

    with pytest.raises(ValidationError, match="frozen"):
        sugerencia.ubicacion.esquinas[1].fuente = "intuición"


def test_un_dato_alterado_por_fuera_no_pasa_como_parte_de_otro(sugerencia_completa):
    sugerencia = Sugerencia.model_validate(sugerencia_completa)
    alterada = sugerencia.ubicacion.calle.model_copy(update={"cita": None})

    with pytest.raises(ValidationError):
        Ubicacion(calle=alterada, altura=sugerencia.ubicacion.altura, esquinas=[])
