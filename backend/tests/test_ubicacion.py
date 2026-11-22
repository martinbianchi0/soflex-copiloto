import json
from pathlib import Path

import pytest

from copiloto.callejero import cargar
from copiloto.esquemas import Cita, Turno, cita_esta_en
from copiloto.ubicacion import interpretar

REFERENCIA = json.loads(
    (Path(__file__).parent / "datos" / "ubicaciones_de_referencia.json").read_text(encoding="utf-8")
)


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


def test_altura_en_palabras_conserva_la_frase_literal():
    turnos = [Turno(texto="Av. Corrientes, mil quinientos cuarenta")]
    altura = interpretar(turnos).ubicacion.altura

    assert (altura.origen, altura.valor) == ("dicho", 1540)
    assert altura.cita == Cita(turno=0, texto="mil quinientos cuarenta")
    assert cita_esta_en(altura.cita, turnos)


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
    assert ubicacion.altura.cita == Cita(turno=3, texto="1540")
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
    assert ubicacion.altura.cita == Cita(turno=0, texto="mil quinientos cuarenta")
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
