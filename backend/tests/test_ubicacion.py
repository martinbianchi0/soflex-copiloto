from time import perf_counter

import pytest
from conftest import REFERENCIA

from copiloto.callejero import cargar
from copiloto.esquemas import Cita, Turno, cita_esta_en
from copiloto.ubicacion import interpretar


def _codigos(resultado):
    return [aviso.codigo for aviso in resultado.avisos]


@pytest.mark.parametrize("caso", REFERENCIA, ids=[caso["id"] for caso in REFERENCIA])
def test_la_lectura_de_las_direcciones_de_referencia_no_cambia(caso):
    """Instantánea de lo que leen las reglas en estas llamadas, con sus errores conocidos.

    Detecta cambios en la lectura; no mide aciertos.
    """
    turnos = [Turno(texto=caso["texto"])]
    resultado = interpretar(turnos)
    ubicacion = resultado.ubicacion
    publicado = cargar().nombre_para_mostrar
    esperado = caso["esperado"]

    assert resultado.calle_oficial == esperado["calle"]
    assert getattr(ubicacion.altura, "valor", None) == esperado["altura"]
    assert [esquina.valor for esquina in ubicacion.esquinas if esquina.origen == "dicho"] == [
        publicado(nombre) for nombre in esperado["cruces_dichos"]
    ]
    assert _codigos(resultado).count("direccion_no_cierra") == sum(
        aviso.startswith("CONFLICTO:") for aviso in esperado["avisos"]
    )
    for dato in (ubicacion.calle, ubicacion.altura, *ubicacion.esquinas):
        if dato.origen == "dicho":
            assert dato.cita.texto in turnos[dato.cita.turno].texto
            assert cita_esta_en(dato.cita, turnos)


def test_corrientes_1540_casi_montevideo():
    resultado = interpretar([Turno(texto="Av. Corrientes 1540 casi Montevideo")])
    ubicacion = resultado.ubicacion

    assert (ubicacion.calle.origen, ubicacion.calle.valor) == ("dicho", "Av. Corrientes")
    assert ubicacion.calle.cita == Cita(turno=0, texto="Av. Corrientes")
    assert (ubicacion.altura.origen, ubicacion.altura.valor) == ("dicho", 1540)
    assert ubicacion.altura.cita == Cita(turno=0, texto="1540")
    dicha, inferida = ubicacion.esquinas
    assert (dicha.origen, dicha.valor) == ("dicho", "Montevideo")
    assert dicha.cita == Cita(turno=0, texto="Montevideo")
    assert (inferida.origen, inferida.valor, inferida.fuente) == ("inferido", "Parana", "callejero")
    assert not resultado.avisos


def test_esquina_de_san_juan_y_entre_rios_sin_altura():
    resultado = interpretar([Turno(texto="Av. San Juan y Entre Ríos")])
    ubicacion = resultado.ubicacion

    assert ubicacion.calle.valor == "Av. San Juan"
    assert ubicacion.altura.origen == "falta"
    (esquina,) = ubicacion.esquinas
    assert (esquina.origen, esquina.valor) == ("dicho", "Av. Entre Rios")
    assert esquina.cita == Cita(turno=0, texto="Entre Ríos")
    assert not resultado.avisos


def test_entre_rios_puede_ser_la_calle_principal_de_una_esquina():
    resultado = interpretar([Turno(texto="Entre Ríos y San Juan")])

    assert resultado.ubicacion.calle.valor == "Av. Entre Rios"
    assert resultado.ubicacion.esquinas[0].valor == "Av. San Juan"


def test_altura_en_palabras_conserva_la_frase_literal():
    turnos = [Turno(texto="Av. Corrientes, mil quinientos cuarenta")]
    altura = interpretar(turnos).ubicacion.altura

    assert (altura.origen, altura.valor) == ("dicho", 1540)
    assert altura.cita == Cita(turno=0, texto="mil quinientos cuarenta")
    assert cita_esta_en(altura.cita, turnos)


@pytest.mark.parametrize("numero", ["1540", "1.540"])
def test_altura_en_cifras_conserva_la_cita_literal(numero):
    turnos = [Turno(texto=f"Av. Corrientes {numero}")]
    resultado = interpretar(turnos)
    altura = resultado.ubicacion.altura

    assert (altura.origen, altura.valor) == ("dicho", 1540)
    assert altura.cita == Cita(turno=0, texto=numero)
    assert cita_esta_en(altura.cita, turnos)
    assert not resultado.avisos


@pytest.mark.parametrize(
    "detalle",
    ["19:30", "19:30:15", "8.º piso", "8º", "8°", "8vo"]
    + [
        f", 19 {unidad}"
        for unidad in (
            "personas",
            "vecinos",
            "chicos",
            "nenes",
            "años",
            "minutos",
            "horas",
            "metros",
            "cuadras",
            "pisos",
            "autos",
            "motos",
            "tipos",
            "hombres",
            "mujeres",
            "pibes",
        )
    ],
)
def test_una_hora_un_ordinal_o_una_cantidad_no_son_altura(detalle):
    resultado = interpretar([Turno(texto=f"Av. Corrientes {detalle}")])

    assert resultado.ubicacion.calle.valor == "Av. Corrientes"
    assert resultado.ubicacion.altura.origen == "falta"
    assert _codigos(resultado) == ["falta_altura"]


def test_el_piso_despues_de_una_pausa_no_invalida_la_altura():
    resultado = interpretar([Turno(texto="Av. Corrientes 1540, piso 4.")])

    assert resultado.ubicacion.altura.valor == 1540
    assert not resultado.avisos


def test_una_altura_fuera_de_rango_se_conserva_y_se_avisa():
    resultado = interpretar([Turno(texto="Av. Corrientes 9000")])
    ubicacion = resultado.ubicacion

    assert ubicacion.calle.valor == "Av. Corrientes"
    assert (ubicacion.altura.origen, ubicacion.altura.valor) == ("dicho", 9000)
    assert ubicacion.altura.cita == Cita(turno=0, texto="9000")
    assert ubicacion.esquinas == []
    (aviso,) = resultado.avisos
    assert aviso.codigo == "direccion_no_cierra"
    assert aviso.mensaje == (
        "La altura 9000 no existe en Av. Corrientes. Leele la dirección de vuelta al llamante."
    )


def test_entre_calles_homonimas_elige_la_que_tiene_la_altura():
    resultado = interpretar([Turno(texto="Lacroze 3050")])

    assert resultado.calle_oficial == "LACROZE, FEDERICO AV."
    assert resultado.ubicacion.altura.valor == 3050
    assert not resultado.avisos


@pytest.mark.parametrize(
    ("texto", "otra_direccion"),
    [
        ("No es Corrientes 1540, es Rivadavia 6300", "Av. Rivadavia 6300"),
        ("Corrientes 1540, Corrientes 1550", "Av. Corrientes 1550"),
        (
            "Llamante: Corrientes 1540. Operador: ¿Seguro? Llamante: Rivadavia 6300",
            "Av. Rivadavia 6300",
        ),
    ],
)
def test_dos_direcciones_distintas_piden_confirmacion(texto, otra_direccion):
    resultado = interpretar([Turno(texto=texto)])

    assert resultado.ubicacion.calle.valor == "Av. Corrientes"
    assert resultado.ubicacion.altura.valor == 1540
    (aviso,) = resultado.avisos
    assert aviso.codigo == "direccion_no_cierra"
    assert "Av. Corrientes 1540" in aviso.mensaje
    assert otra_direccion in aviso.mensaje
    assert "Confirmá con el llamante" in aviso.mensaje


def test_repetir_la_misma_direccion_no_es_un_conflicto():
    resultado = interpretar([Turno(texto="Corrientes 1540. Repito, Av. Corrientes 1.540.")])

    assert resultado.ubicacion.altura.valor == 1540
    assert not resultado.avisos


def test_caso_002_el_conflicto_impide_inferir_esquinas():
    caso = next(caso for caso in REFERENCIA if caso["id"] == "002")
    resultado = interpretar([Turno(texto=caso["texto"])])

    assert "direccion_no_cierra" in _codigos(resultado)
    assert [(esquina.origen, esquina.valor) for esquina in resultado.ubicacion.esquinas] == [
        ("dicho", "Vera"),
        ("dicho", "Juan Ramirez de Velasco"),
    ]


def test_un_texto_sin_calle_devuelve_faltantes():
    resultado = interpretar([Turno(texto="Veo humo por la ventana de enfrente.")])

    assert resultado.calle_oficial is None
    assert resultado.ubicacion.calle.origen == resultado.ubicacion.altura.origen == "falta"
    assert resultado.ubicacion.esquinas == []
    assert _codigos(resultado) == ["sin_calle"]


def test_sin_altura_ni_esquina_pide_confirmarla():
    resultado = interpretar([Turno(texto="Estamos en Av. Corrientes.")])

    assert _codigos(resultado) == ["falta_altura"]


def test_el_tipo_de_via_solo_no_es_una_calle():
    resultado = interpretar([Turno(texto="Calle Pasaje")])

    assert resultado.ubicacion.calle.origen == "falta"
    assert _codigos(resultado) == ["sin_calle"]


def test_calle_ambigua_muestra_la_alternativa_del_callejero():
    resultado = interpretar([Turno(texto="Mitre 700")])

    (aviso,) = resultado.avisos
    assert aviso.codigo == "calle_ambigua"
    assert "Emilio Mitre" in aviso.mensaje


@pytest.mark.parametrize("cruce", ["Yerbal", "Xyloprax"], ids=["no_cruza", "no_figura"])
def test_cruce_sin_confirmar(cruce):
    resultado = interpretar([Turno(texto=f"Av. Corrientes 1540, casi {cruce}.")])

    (aviso,) = resultado.avisos
    assert aviso.codigo == "cruce_sin_confirmar"
    assert cruce in aviso.mensaje
    assert all(esquina.origen == "inferido" for esquina in resultado.ubicacion.esquinas)


def test_ignora_al_operador_y_conserva_los_indices_de_los_turnos():
    turnos = [
        Turno(hablante="operador", texto="Av. Corrientes 911, ¿dónde es la emergencia?"),
        Turno(hablante="llamante", texto="En Av. Corrientes"),
        Turno(hablante="operador", texto="107, indique con qué calle"),
        Turno(hablante="llamante", texto="1540 casi Montevideo"),
    ]
    ubicacion = interpretar(turnos).ubicacion

    assert ubicacion.calle.cita == Cita(turno=1, texto="Av. Corrientes")
    assert ubicacion.altura.origen == "falta"
    assert ubicacion.esquinas[0].cita == Cita(turno=3, texto="Montevideo")


def test_marcas_de_hablante_en_turno_sin_etiqueta():
    turnos = [
        Turno(
            texto="Operador: Av. Corrientes 911. Llamante: Av. Corrientes, Operador: 107. "
            "Llamante: mil quinientos cuarenta casi Montevideo."
        )
    ]
    ubicacion = interpretar(turnos).ubicacion

    assert ubicacion.calle.cita == Cita(turno=0, texto="Av. Corrientes")
    assert ubicacion.altura.origen == "falta"
    assert ubicacion.esquinas[0].cita == Cita(turno=0, texto="Montevideo")


def test_la_cita_no_puede_saltar_un_fragmento_del_operador():
    turnos = [
        Turno(
            texto="Llamante: Av. Corrientes mil Operador: ¿A qué altura? Llamante: quinientos cuarenta."
        )
    ]
    ubicacion = interpretar(turnos).ubicacion

    assert ubicacion.calle.valor == "Av. Corrientes"
    assert ubicacion.altura.origen == "falta"


@pytest.mark.parametrize(
    "turnos",
    [
        [Turno(texto="Llamante: Corrientes. Operador: ¿Qué edad tiene? Llamante: 82")],
        [Turno(texto="Llamante: 1540. Operador: ¿Dónde? Llamante: Corrientes")],
        [Turno(texto="Corrientes.", hablante="llamante"), Turno(texto="82", hablante="llamante")],
    ],
    ids=["en_otro_tramo", "antes_de_la_calle", "en_otro_turno"],
)
def test_calle_y_altura_tienen_que_estar_en_el_mismo_tramo(turnos):
    resultado = interpretar(turnos)

    assert resultado.ubicacion.calle.valor == "Av. Corrientes"
    assert resultado.ubicacion.altura.origen == "falta"
    assert _codigos(resultado) == ["falta_altura"]


def test_la_altura_del_mismo_tramo_se_conserva():
    texto = "Llamante: Corrientes al 1540. Operador: ¿Qué edad tiene? Llamante: 82"
    resultado = interpretar([Turno(texto=texto)])

    assert resultado.ubicacion.calle.valor == "Av. Corrientes"
    assert resultado.ubicacion.altura.valor == 1540
    assert resultado.ubicacion.altura.cita == Cita(turno=0, texto="1540")
    assert not resultado.avisos


@pytest.mark.parametrize(
    "texto",
    [
        "Llamante: Corrientes y Operador: ¿Con qué calle? Llamante: Montevideo.",
        "Llamante: Av. Corrientes y Operador: ¿Con qué calle? Llamante: Montevideo.",
        "Llamante: Av. Corrientes. Operador: ¿Con qué calle? Llamante: Y Montevideo.",
        (
            "Llamante: Av. Corrientes. Operador: ¿Con qué calle? Llamante: Esquina "
            "Operador: ¿Cuál? Llamante: Montevideo."
        ),
    ],
)
def test_un_cruce_no_se_compone_con_palabras_de_tramos_distintos(texto):
    resultado = interpretar([Turno(texto=texto)])

    assert resultado.ubicacion.calle.valor == "Av. Corrientes"
    assert resultado.ubicacion.esquinas == []
    assert _codigos(resultado) == ["falta_altura"]


@pytest.mark.parametrize(
    ("frase", "esperadas"),
    [
        ("casi Montevideo", ["Montevideo"]),
        ("esquina Montevideo", ["Montevideo"]),
        ("entre Paraná y Montevideo", ["Paraná", "Montevideo"]),
    ],
)
def test_los_cruces_marcados_en_otro_tramo_siguen_valiendo(frase, esperadas):
    turnos = [Turno(texto=f"Llamante: Corrientes. Operador: ¿Con qué calle? Llamante: {frase}")]
    resultado = interpretar(turnos)

    assert resultado.ubicacion.calle.valor == "Av. Corrientes"
    assert resultado.ubicacion.altura.origen == "falta"
    assert [esquina.cita for esquina in resultado.ubicacion.esquinas] == [
        Cita(turno=0, texto=esquina) for esquina in esperadas
    ]
    assert not resultado.avisos


@pytest.mark.parametrize("hablante", [None, "llamante"])
def test_el_prefijo_sin_marca_no_es_evidencia(hablante):
    turnos = [
        Turno(
            hablante=hablante,
            texto="Av. Corrientes 1540. Operador: ¿Dónde es? Llamante: Necesito ayuda.",
        )
    ]
    resultado = interpretar(turnos)

    assert resultado.ubicacion.calle.origen == "falta"
    assert resultado.ubicacion.altura.origen == "falta"
    assert _codigos(resultado) == ["sin_calle"]


def test_una_cita_conserva_los_acentos_descompuestos():
    turnos = [Turno(texto="Av. San Juan y Entre Ri\u0301os")]
    esquina = interpretar(turnos).ubicacion.esquinas[0]

    assert esquina.cita == Cita(turno=0, texto="Entre Ri\u0301os")
    assert cita_esta_en(esquina.cita, turnos)


@pytest.mark.parametrize(
    "turnos",
    [
        [],
        [Turno(texto="1" * 20_000)],
        [Turno(texto="X" * 20_000)],
        [Turno(texto="¿?!_-…")],
        [Turno(texto="Calle 911")],
        [Turno(hablante="operador", texto="Av. Corrientes 1540")],
    ],
    ids=["vacio", "digitos", "texto_largo", "signos", "calle_sin_nombre", "solo_operador"],
)
def test_entradas_sin_una_direccion_interpretable(turnos):
    resultado = interpretar(turnos)

    assert resultado.calle_oficial is None
    assert resultado.ubicacion.calle.origen == resultado.ubicacion.altura.origen == "falta"
    assert resultado.ubicacion.esquinas == []
    assert _codigos(resultado) == ["sin_calle"]


@pytest.mark.parametrize(
    "turnos",
    [
        [Turno(texto="Corrientes 1540 " + "casi Uruguay " * 900)],
        [Turno(texto=("qxjxzx y " * 2300)[:20_000])] * 2,
        [Turno(texto="a" * 20_000)] * 2,
        [Turno(texto="0" * 19_999 + "9")] * 2,
        [Turno(texto="Av. " * 5000)] * 2 + [Turno(texto="Av. " * 2000)],
        [Turno.model_construct(texto="Av. " * 12_000)],
    ],
    ids=["casi_uruguay", "qxjxzx_y", "letras", "ceros", "avenidas", "avenidas_en_un_turno"],
)
def test_entradas_largas_se_interpretan_en_menos_de_un_segundo(turnos):
    cargar()
    inicio = perf_counter()
    interpretar(turnos)
    assert perf_counter() - inicio < 1


def test_perdon_no_es_la_avenida_peron():
    leida = interpretar([Turno(texto="Perdón, al 3200")])

    assert leida.ubicacion.calle.origen == "falta"
    assert [aviso.codigo for aviso in leida.avisos] == ["sin_calle"]


def test_con_dos_direcciones_en_el_relato_no_se_infieren_entrecalles():
    leida = interpretar([Turno(texto="No es Corrientes 1540, es Rivadavia 6300")])

    assert leida.ubicacion.esquinas == []
    assert [aviso.codigo for aviso in leida.avisos] == ["direccion_no_cierra"]
