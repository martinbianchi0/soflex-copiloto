import json
from pathlib import Path

import pytest

from copiloto import dataset, dictados, flujo
from copiloto.esquemas import Aviso, Cita, DatoDictado, Turno
from copiloto.turnos import separar_hablantes

NUEVAS = json.loads(
    Path(__file__).with_name("datos").joinpath("llamadas_nuevas.json").read_text(encoding="utf-8")
)
TRANSCRIPCIONES = [
    *(pytest.param(texto, id=protocolo.id) for protocolo, texto in dataset.transcripciones()),
    *(pytest.param(caso["texto"], id=caso["id"]) for caso in NUEVAS),
]


@pytest.mark.parametrize(
    ("anuncio", "literal", "valor"),
    [
        ("patente ", "ZA 345 BD", "ZA 345 BD"),
        ("la PÁTENTE es ", "za345bd", "ZA 345 BD"),
        ("dominio: ", "aBc-123", "ABC 123"),
        ("patente ", "ABC123", "ABC 123"),
        ("chapa patente ", "a.123.bCd", "A 123 BCD"),
        ("patente ", "a123bcd", "A 123 BCD"),
        ("patente ", "a 123 bcd", "A 123 BCD"),
        ("la patente era del ", "123 ABC", "123 ABC"),
        ("dominio ", "123abc", "123 ABC"),
        ("la patente del otro auto era ", "zA - 345.Bd", "ZA 345 BD"),
        ("patente ", "abc 123", "ABC 123"),
        # Escritas en mayúsculas, las letras son de la patente aunque formen una palabra.
        ("patente ", "AB 123 DE", "AB 123 DE"),
        ("la patente es ", "LA 456 NO", "LA 456 NO"),
        ("patente ", "DEL 123", "DEL 123"),
    ],
)
def test_patentes_validas(anuncio, literal, valor):
    turnos = [Turno(texto=f"Choque y fuga, {anuncio}{literal}. Se escapó.")]

    assert dictados.buscar(turnos) == (
        [DatoDictado(tipo="patente", valor=valor, cita=Cita(turno=0, texto=literal))],
        [],
    )


@pytest.mark.parametrize(
    "literal",
    ["AB 12 CD", "ABC 12", "AB 123 CDE", "ABCD 123", "ABC 123 DEF", "AB123CD1", "AB 123"],
)
def test_patentes_incompletas_o_ambiguas(literal):
    assert dictados.buscar([Turno(texto=f"patente {literal}")]) == (
        [],
        [
            Aviso(
                codigo="dictado_incompleto",
                mensaje=f"La patente dictada («{literal}») no tiene un formato válido. "
                "Pedí que la repitan.",
            )
        ],
    )


@pytest.mark.parametrize(
    ("anuncio", "literal", "valor"),
    [
        ("teléfono: ", "1110000142", "1110000142"),
        ("mi celular es ", "11 1000-0142", "1110000142"),
        ("MI NÚMERO ", "1001 0142", "10010142"),
        ("contacto al ", "(011) 1001-0142", "01110010142"),
        ("llamame al ", "+54 9 11 1000-0142", "5491110000142"),
        ("llámenme al ", "54 9 11 1000.0142", "5491110000142"),
        ("me pueden llamar al ", "15-1000-0142", "1510000142"),
        ("me llaman al ", "011-15 1000-0142", "0111510000142"),
        ("teléfono: ", "(0291) 15 100-0142", "0291151000142"),
        ("mi número es el ", "11 1000-0142", "1110000142"),
        ("mi teléfono es el ", "1001-0142", "10010142"),
        ("mi teléfono fijo es ", "1001-0142", "10010142"),
        ("le anoto el teléfono del vecino: ", "11 1000-0142", "1110000142"),
        ("el celular de mi marido es ", "15 1000 0142", "1510000142"),
        # De otro país se guarda como se dictó.
        ("mi celular es ", "+34 612 345 678", "34612345678"),
        # Un número de la Ciudad que empieza con 54 no trae el código del país.
        ("mi teléfono es ", "5411-2233", "54112233"),
        ("celular ", "54 11 1000-0142", "541110000142"),
    ],
)
def test_telefonos_validos(anuncio, literal, valor):
    turnos = [Turno(texto=f"Si se corta, {anuncio}{literal}. Gracias.")]

    assert dictados.buscar(turnos) == (
        [DatoDictado(tipo="telefono", valor=valor, cita=Cita(turno=0, texto=literal))],
        [],
    )


@pytest.mark.parametrize("literal", ["1000 014", "11-1000", "+54 9 11 1000-014"])
def test_telefonos_incompletos(literal):
    assert dictados.buscar([Turno(texto=f"mi celular es {literal}")]) == (
        [],
        [
            Aviso(
                codigo="dictado_incompleto",
                mensaje=f"El teléfono dictado («{literal}») no parece completo. Pedí que lo repitan.",
            )
        ],
    )


@pytest.mark.parametrize(
    "texto",
    [
        "No le vi la patente",
        "Sin patente",
        "La patente no la llegué a ver",
        "Una chapa de 6 metros",
        "Le robaron el celular a mi hijo de 16 años",
        "No tengo teléfono",
        "Me quedé sin celular",
        "En Corrientes 1540 dejé anotado AB 123 CD y 11 1000-0142",
        "Operador: ¿me repite la patente AB 123 CD?",
        "Patente AB 123 CD. Operador: Hola. Llamante: Me chocaron.",
        "Llamante: La patente era Operador: ¿Me escucha? Llamante: AB 123 CD",
        "La patente del otro auto que estaba en la esquina era AB 123 CD",
        "No le vi la patente. Hay 2 autos más.",
        # Un número corto no es un teléfono de contacto dictado.
        "Llamé al teléfono 911 y no atendían",
        "Ya llamamos al celular 107",
        "Mi celular es un 5G",
        # Un número suelto después de «patente» puede ser cualquier cosa.
        "La patente es 1234",
        "Patente: 2 tipos se bajaron, ni la vi",
        "Patente: 23 hs, esa fue la hora",
        "La patente eran 32 años",
        "Patente no tenía, eran 2 tipos",
        # Nombrarlo para decir que no se tiene no es anunciarlo.
        "No vi la patente: Paz 1234 es donde chocó",
        "No me acuerdo la patente, AB 123 CD creo",
        # Un documento no es un teléfono.
        "Mi número es 12345678, el DNI",
        "Mi número de documento es 12345678",
    ],
)
def test_sin_dictado_no_hay_datos_ni_avisos(texto):
    assert dictados.buscar([Turno(texto=texto)]) == ([], [])


@pytest.mark.parametrize(
    ("pedido", "respuesta", "esperado"),
    [
        ("¿Me repite la patente?", "AB 123 CD.", [("patente", "AB 123 CD", "AB 123 CD")]),
        ("¿Me dice el dominio?", "Sí, era abc 123, creo.", [("patente", "ABC 123", "abc 123")]),
        (
            "¿A qué teléfono lo llamamos?",
            "Al 11 1000-0142.",
            [("telefono", "1110000142", "11 1000-0142")],
        ),
        ("¿Tiene un celular?", "Sí, 15 1000 0142.", [("telefono", "1510000142", "15 1000 0142")]),
        (
            "¿Me da la patente y un teléfono?",
            "ZA 345 BD, y mi celular es 1001-0142.",
            [("patente", "ZA 345 BD", "ZA 345 BD"), ("telefono", "10010142", "1001-0142")],
        ),
        # Si la respuesta no empieza con el dato, o no llega a ser uno entero, no se toma nada.
        ("¿Vio la patente? ¿Cuántos autos eran?", "No, eran 3 autos.", []),
        ("¿Vio la patente?", "No la llegué a ver, fue a las 22 30.", []),
        ("¿Tiene un teléfono? ¿Qué edad tiene la señora?", "82.", []),
        (
            "¿Qué patente y qué teléfono tiene?",
            "ABC 123 y 11 1000-0142.",
            [("patente", "ABC 123", "ABC 123"), ("telefono", "1110000142", "11 1000-0142")],
        ),
        # Sin que el operador lo pida, lo dicho sin anunciar no cuenta.
        ("¿Hay heridos?", "AB 123 CD.", []),
        # Nombrar el dato sin preguntar por él no es pedirlo.
        ("No se preocupe por la patente.", "Paz 123, ahí fue el choque.", []),
        # Con dos preguntas no se sabe a cuál contesta.
        ("¿Vio la patente? ¿Qué móvil es?", "123 PFA.", []),
    ],
)
def test_lo_que_pide_el_operador_se_lee_al_empezar_la_respuesta(pedido, respuesta, esperado):
    turnos = [
        Turno(texto="Me chocaron y se fue.", hablante="llamante"),
        Turno(texto=pedido, hablante="operador"),
        Turno(texto=respuesta, hablante="llamante"),
    ]

    assert dictados.buscar(turnos) == (
        [
            DatoDictado(tipo=tipo, valor=valor, cita=Cita(turno=2, texto=literal))
            for tipo, valor, literal in esperado
        ],
        [],
    )


def test_un_dato_entero_dictado_despues_resuelve_el_aviso():
    turnos = [
        Turno(texto="La patente era AB 12 CD. Mi celular es 1000 014.", hablante="llamante"),
        Turno(texto="¿Me repite la patente?", hablante="operador"),
        Turno(texto="AB 123 CD.", hablante="llamante"),
    ]

    datos, avisos = dictados.buscar(turnos)

    assert [dato.valor for dato in datos] == ["AB 123 CD"]
    # El teléfono sigue sin repetirse: su aviso queda.
    assert [aviso.mensaje for aviso in avisos] == [
        "El teléfono dictado («1000 014») no parece completo. Pedí que lo repitan."
    ]


def test_un_dato_a_medias_dictado_despues_de_uno_entero_se_avisa():
    turnos = [Turno(texto="Patente AB 123 CD. No, perdón, patente AB 12 CD.", hablante="llamante")]

    datos, avisos = dictados.buscar(turnos)

    assert [dato.valor for dato in datos] == ["AB 123 CD"]
    assert len(avisos) == 1


def test_lo_pedido_que_llega_a_medias_tambien_se_avisa():
    turnos = [
        Turno(texto="Me chocaron y se fue.", hablante="llamante"),
        Turno(texto="¿Me repite la patente?", hablante="operador"),
        Turno(texto="AB 12 CD.", hablante="llamante"),
    ]

    assert dictados.buscar(turnos) == (
        [],
        [
            Aviso(
                codigo="dictado_incompleto",
                mensaje="La patente dictada («AB 12 CD») no tiene un formato válido. "
                "Pedí que la repitan.",
            )
        ],
    )


def test_el_telefono_termina_donde_termina_la_oracion():
    turnos = [Turno(texto="Mi celular es 11 1000-0142. 25 de Mayo 500, ahí chocó.")]

    assert dictados.buscar(turnos) == (
        [
            DatoDictado(
                tipo="telefono", valor="1110000142", cita=Cita(turno=0, texto="11 1000-0142")
            )
        ],
        [],
    )


def test_la_patente_termina_donde_termina_la_oracion():
    datos, avisos = dictados.buscar([Turno(texto="Patente ABC 123. DNI 12345678.")])

    assert [dato.valor for dato in datos] == ["ABC 123"]
    assert avisos == []


def test_un_dato_que_no_entra_no_resuelve_el_aviso():
    turnos = [
        *(Turno(texto=f"Patente AC {numero} BD") for numero in range(100, 110)),
        Turno(texto="Mi teléfono es 1000 014."),
        Turno(texto="Mi teléfono es 11 1000-0142."),
    ]

    datos, avisos = dictados.buscar(turnos)

    assert len(datos) == 10
    assert len(avisos) == 1


def test_los_datos_repetidos_conservan_la_primera_cita():
    turnos = [
        Turno(texto="Operador: Patente AB 123 CD. Llamante: Patente ab-123-cd, celular 1001-0142."),
        Turno(texto="Patente AB123CD, teléfono 10010142.", hablante="llamante"),
    ]

    assert dictados.buscar(turnos) == (
        [
            DatoDictado(tipo="patente", valor="AB 123 CD", cita=Cita(turno=0, texto="ab-123-cd")),
            DatoDictado(tipo="telefono", valor="10010142", cita=Cita(turno=0, texto="1001-0142")),
        ],
        [],
    )


def test_se_conservan_los_primeros_diez_datos():
    turnos = [Turno(texto=f"Patente AC {numero} BD") for numero in range(100, 111)]

    datos, avisos = dictados.buscar(turnos)

    assert [dato.cita.turno for dato in datos] == list(range(10))
    assert avisos == []


@pytest.mark.parametrize("texto", TRANSCRIPCIONES)
def test_agregar_los_dictados_no_cambia_la_ubicacion(texto):
    turnos = separar_hablantes([Turno(texto=texto)])
    nuevo = Turno(texto="Llamante: La patente es ZA 345 BD y mi celular es 11 1000-0142.")

    assert dictados.buscar([Turno(texto=texto)]) == ([], [])
    assert dictados.buscar(turnos) == ([], [])
    inicial = flujo.analizar(turnos)
    ampliada = flujo.analizar([*turnos, nuevo])
    assert ampliada.ubicacion == inicial.ubicacion
    assert [dato.valor for dato in ampliada.datos_dictados] == ["ZA 345 BD", "1110000142"]


@pytest.mark.parametrize(
    "turnos",
    [
        [Turno(texto="Mi celular es 11 1000-0142. 25 de Mayo 500, ahí chocó.")],
        [Turno(texto="No vi la patente: Paz 1234 es donde chocó.")],
        [Turno(texto="Chocaron en Córdoba y Gascón. Patente PAZ 123.")],
        [Turno(texto="Patente PAZ 123. Chocaron en Corrientes 1540 casi Montevideo.")],
        [
            Turno(texto="Fue en Corrientes.", hablante="llamante"),
            Turno(texto="No se preocupe por la patente.", hablante="operador"),
            Turno(texto="Paz 123, ahí fue el choque.", hablante="llamante"),
        ],
        [
            Turno(texto="Fue en La Pampa.", hablante="llamante"),
            Turno(texto="¿Me pasa el teléfono?", hablante="operador"),
            Turno(texto="La… 11 1000-0142, Pampa 1500.", hablante="llamante"),
        ],
    ],
)
def test_la_direccion_se_lee_igual_haya_o_no_dictados(turnos, monkeypatch):
    con_dictados = flujo.analizar(turnos)
    monkeypatch.setattr(dictados, "buscar", lambda turnos: ([], []))
    sin_dictados = flujo.analizar(turnos)

    assert con_dictados.ubicacion == sin_dictados.ubicacion
    assert [aviso for aviso in con_dictados.avisos if aviso.codigo != "dictado_incompleto"] == (
        sin_dictados.avisos
    )
