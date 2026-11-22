import pytest

from copiloto.esquemas import Turno
from copiloto.turnos import dicho_por_el_llamante, separar_hablantes, tramos_del_llamante


@pytest.mark.parametrize(
    ("operador", "llamante"),
    [("Operador", "Llamante"), ("OPERADOR", "LLAMANTE"), ("operador", "llamante")],
    ids=["inicial_mayuscula", "mayusculas", "minusculas"],
)
def test_las_marcas_separan_lo_que_dijo_cada_hablante(operador, llamante):
    texto = f"{operador}: ¿Dónde está? {llamante}: Estoy acá. {operador}: Entendido."

    assert separar_hablantes([Turno(texto=texto)]) == [
        Turno(hablante="operador", texto="¿Dónde está?"),
        Turno(hablante="llamante", texto="Estoy acá."),
        Turno(hablante="operador", texto="Entendido."),
    ]


def test_un_turno_sin_marcas_queda_como_llego():
    turnos = [Turno(texto="Hola. Escuché unos gritos.")]

    assert separar_hablantes(turnos) == turnos


def test_un_turno_con_hablante_no_se_vuelve_a_partir():
    turnos = [Turno(hablante="llamante", texto="Leí en el aviso: Operador: espere en línea.")]

    assert separar_hablantes(turnos) == turnos


def test_un_turno_con_texto_antes_de_la_primera_marca_se_guarda_entero():
    # Ese texto no es de nadie: partir el turno sería atribuírselo a alguien.
    turnos = [Turno(texto="Se escucha un timbre. Operador: Buen día. Llamante: Hola.")]

    assert separar_hablantes(turnos) == turnos
    assert tramos_del_llamante(turnos[0]) == ["Hola."]


def test_un_trozo_que_solo_tiene_puntuacion_se_conserva():
    turnos = [Turno(texto="Operador: ¿Me escucha? Llamante: …?! Operador: ¿Hola?")]

    assert separar_hablantes(turnos) == [
        Turno(hablante="operador", texto="¿Me escucha?"),
        Turno(hablante="llamante", texto="…?!"),
        Turno(hablante="operador", texto="¿Hola?"),
    ]


def test_cooperador_no_es_una_marca_de_hablante():
    turnos = [Turno(texto="Llamante: Dijo el cooperador: espere acá.")]

    assert separar_hablantes(turnos) == [
        Turno(hablante="llamante", texto="Dijo el cooperador: espere acá.")
    ]


def test_si_hay_mas_de_quinientos_trozos_se_conserva_el_original():
    turnos = [Turno(texto="Llamante: Hola. " * 501)]

    assert separar_hablantes(turnos) == turnos


def test_quinientos_trozos_se_pueden_separar():
    turnos = [Turno(texto="Llamante: Hola. " * 500)]

    assert separar_hablantes(turnos) == [Turno(hablante="llamante", texto="Hola.")] * 500


def test_si_solo_hay_marcas_se_conserva_el_original():
    turnos = [Turno(texto="Operador: Llamante: Operador:")]

    assert separar_hablantes(turnos) == turnos


def test_separar_dos_veces_da_los_mismos_turnos():
    turnos = [
        Turno(texto="Hola. Operador: Buen día. Llamante: Escuché unos gritos."),
        Turno(hablante="llamante", texto="Volví a escuchar: Operador: buen día."),
    ]

    separados = separar_hablantes(turnos)

    assert separar_hablantes(separados) == separados


def test_dicho_por_el_llamante_junta_todo_lo_que_no_dijo_el_operador():
    turnos = [
        Turno(texto="Hay fuego. Operador: ¿Qué pasó? Llamante: Escuché unos gritos."),
        Turno(hablante="operador", texto="¿Y ahora?"),
        Turno(hablante="llamante", texto="Ahora hay silencio."),
        Turno(texto="Eso es todo."),
    ]

    # "Hay fuego." está antes de la primera marca: no se sabe quién lo dijo y no cuenta.
    esperado = "Escuché unos gritos. Ahora hay silencio. Eso es todo."
    assert dicho_por_el_llamante(turnos) == esperado
