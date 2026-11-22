import pytest
from conftest import FILAS_DATASET, TEXTO_SIN_DATOS

from copiloto.esquemas import Categoria, Turno
from copiloto.tipo import por_palabras_clave, puntajes


def test_las_reglas_aciertan_al_menos_veintisiete_categorias_del_dataset():
    aciertos = 0
    for subtipo, fila in FILAS_DATASET.items():
        categoria = por_palabras_clave([Turno(texto=fila["transcripcion_cruda"])])
        esperada = fila["categoria"]
        assert categoria in (esperada, Categoria.NO_DETERMINADA), subtipo
        aciertos += categoria == esperada

    assert aciertos >= 27


def test_sin_palabras_clave_no_se_determina_la_categoria():
    turnos = [Turno(texto=TEXTO_SIN_DATOS)]

    assert por_palabras_clave(turnos) == Categoria.NO_DETERMINADA
    assert not any(puntajes(turnos).values())


def test_un_empate_no_determina_la_categoria():
    turnos = [Turno(texto="Escuché un choque. Necesito una ambulancia.")]

    detalle = puntajes(turnos)

    assert detalle[Categoria.ACCIDENTE_VIAL] == detalle[Categoria.EMERGENCIA_MEDICA] > 0
    assert por_palabras_clave(turnos) == Categoria.NO_DETERMINADA


def test_motores_no_cuenta_como_moto():
    motores = [Turno(texto="Escucho motores.")]
    moto = [Turno(texto="Escucho una moto.")]

    assert puntajes(motores)[Categoria.ACCIDENTE_VIAL] == 0
    assert por_palabras_clave(motores) == Categoria.NO_DETERMINADA
    assert puntajes(moto)[Categoria.ACCIDENTE_VIAL] > 0
    assert por_palabras_clave(moto) == Categoria.ACCIDENTE_VIAL


def test_las_palabras_clave_del_operador_no_suman():
    llamante = Turno(hablante="llamante", texto="Hubo un choque.")
    operador = Turno(hablante="operador", texto="¿Hay fuego, humo o llamas? ¿Llamó a bomberos?")

    assert puntajes([operador, llamante]) == puntajes([llamante])
    assert por_palabras_clave([operador, llamante]) == Categoria.ACCIDENTE_VIAL


def test_las_mayusculas_y_las_tildes_no_cambian_el_puntaje_ni_la_categoria():
    texto = [Turno(texto="Se apagó el semáforo.")]
    variante = [Turno(texto="SE APAGO EL SEMAFORO.")]

    assert puntajes(texto) == puntajes(variante)
    assert por_palabras_clave(texto) == por_palabras_clave(variante) == Categoria.SERVICIOS_PUBLICOS


@pytest.mark.parametrize(
    "relato",
    [
        "Llamaste a mi papá",
        "Gaspar tiene dolor de pecho",
        "Dolor en la parte posterior de la cabeza",
        "Estaba armando un mueble",
        "Vivo en el barrio de Flores",
    ],
)
def test_una_palabra_clave_no_cuenta_dentro_de_otra_palabra(relato):
    assert por_palabras_clave([Turno(texto=relato)]) == Categoria.NO_DETERMINADA


def test_una_raiz_vale_con_cualquier_terminacion():
    assert por_palabras_clave([Turno(texto="Se inundó toda la cuadra")]) == Categoria.DEFENSA_CIVIL
    assert por_palabras_clave([Turno(texto="La calle está inundada")]) == Categoria.DEFENSA_CIVIL
