import pytest

from copiloto.callejero import Candidato, cargar, normalizar


def test_el_callejero_trae_todas_las_calles_y_tramos():
    tramos = cargar().tramos

    assert len(tramos) == 2450
    assert sum(len(calle) for calle in tramos.values()) == 30801


def test_el_callejero_se_carga_una_sola_vez():
    assert cargar() is cargar()


@pytest.mark.parametrize(
    ("consulta", "esperados"),
    [
        ("Av. Corrientes", [Candidato("CORRIENTES AV.", 98, "exacto")]),
        (
            "Lacroze",
            [
                Candidato("LACROZE, FEDERICO", 94, "apellido"),
                Candidato("LACROZE, FEDERICO AV.", 94, "apellido"),
            ],
        ),
        ("Corientes", [Candidato("CORRIENTES AV.", 94, "fonetico")]),
        ("Corrientos", [Candidato("CORRIENTES AV.", 80, "difuso")]),
    ],
    ids=["exacta", "apellido", "fonetica", "difusa"],
)
def test_buscar_candidatos(consulta, esperados):
    assert cargar().candidatos(normalizar(consulta)) == esperados


@pytest.mark.parametrize(
    "consulta",
    [
        "Pasaje",
        "Pje.",
        "Calle",
        "Avda.",
        "Avenida",
        "Boulevard",
        "Bv.",
        "Autopista",
        "Au.",
        "Diagonal",
        "Diag.",
        "Puente",
        "Pte.",
        "Plz.",
        "Parque",
        "Parq.",
        "Barrio",
        "Estación",
        "Est.",
    ],
)
def test_un_generico_solo_no_produce_coincidencias_parciales(consulta):
    assert cargar().candidatos(normalizar(consulta)) == []


def test_plaza_puede_ser_el_nombre_exacto_de_una_calle():
    assert Candidato("PLAZA", 98, "exacto") in cargar().candidatos("PLAZA")


def test_entrecalles_de_corrientes_a_la_altura_1540():
    assert cargar().entrecalles("CORRIENTES AV.", 1540) == ["PARANA", "MONTEVIDEO"]


@pytest.mark.parametrize(
    ("oficial", "visible"),
    [
        ("CORRIENTES AV.", "Av. Corrientes"),
        ("SCALABRINI ORTIZ, RAUL AV.", "Av. Raul Scalabrini Ortiz"),
        ("DEL LIBERTADOR AV.", "Av. del Libertador"),
        ("LOPE DE VEGA AV.", "Av. Lope de Vega"),
        ("MUÑECAS", "Muñecas"),
        ("PARANA", "Parana"),
    ],
)
def test_nombre_para_mostrar(oficial, visible):
    assert cargar().nombre_para_mostrar(oficial) == visible
