import csv
import io
from collections import Counter
from importlib import resources

import pytest
from pydantic import ValidationError

from copiloto import catalogo
from copiloto.catalogo import CatalogoInvalido, SubtipoInvalido
from copiloto.criterio import Criterio
from copiloto.esquemas import Categoria

CSV = (
    resources.files("copiloto").joinpath("datos", catalogo.ARCHIVO).read_text(encoding="utf-8-sig")
)
FILAS = list(csv.DictReader(CSV.splitlines()))


def test_el_catalogo_trae_un_protocolo_por_cada_fila_del_dataset():
    protocolos = catalogo.cargar().protocolos

    assert [p.id for p in protocolos] == [f"SFX-{n:03d}" for n in range(1, 31)]
    assert [p.nombre for p in protocolos] == [fila["subcategoria"] for fila in FILAS]
    assert Counter(p.categoria.value for p in protocolos) == {
        "INCENDIO_RESCATE": 8,
        "EMERGENCIA_MEDICA": 6,
        "ACCIDENTE_VIAL": 5,
        "DEFENSA_CIVIL": 5,
        "SERVICIOS_PUBLICOS": 4,
        "CONVIVENCIA_SEGURIDAD": 2,
    }


def test_los_textos_son_los_del_dataset_letra_por_letra():
    for protocolo, fila in zip(catalogo.cargar().protocolos, FILAS, strict=True):
        preguntas = fila["preguntas_protocolo_mandatorias"].split(" | ")
        assert [q.texto for q in protocolo.preguntas] == preguntas
        assert [q.id for q in protocolo.preguntas] == [f"{protocolo.id}-Q{n}" for n in (1, 2, 3)]
        assert [(i.id, i.texto) for i in protocolo.instrucciones] == [
            (f"{protocolo.id}-I1", fila["instrucciones_prearribo"])
        ]


def test_una_aclaracion_entre_parentesis_es_parte_de_la_pregunta():
    pregunta = catalogo.cargar().protocolos[25].preguntas[2]

    assert pregunta.texto == "¿Se le colocó algún objeto en la boca? (NO colocar)"


def test_el_catalogo_se_lee_una_sola_vez():
    assert catalogo.cargar() is catalogo.cargar()


def test_buscar_el_protocolo_de_un_subtipo():
    cat = catalogo.cargar()

    assert cat.protocolo(Categoria.ACCIDENTE_VIAL, "SFX-005").nombre.startswith("Colisión")
    assert cat.protocolo(Categoria.ACCIDENTE_VIAL, None) is None
    assert cat.protocolo(Categoria.NO_DETERMINADA, None) is None
    with pytest.raises(SubtipoInvalido, match="otra categoría"):
        cat.protocolo(Categoria.INCENDIO_RESCATE, "SFX-005")
    with pytest.raises(SubtipoInvalido, match="no está"):
        cat.protocolo(Categoria.ACCIDENTE_VIAL, "SFX-031")


def con(**cambios: str) -> str:
    """El CSV con su primera fila cambiada."""
    filas = [{**FILAS[0], **cambios}, *FILAS[1:]]
    salida = io.StringIO()
    escritor = csv.DictWriter(salida, fieldnames=list(FILAS[0]))
    escritor.writeheader()
    escritor.writerows(filas)
    return salida.getvalue()


def test_el_csv_tal_cual_y_reescrito_dan_el_mismo_catalogo():
    assert catalogo.leer(con()) == catalogo.cargar()


@pytest.mark.parametrize(
    ("cambios", "mensaje"),
    [
        ({"categoria": "INCENDIOS"}, "SFX-REC-2026-001"),
        ({"categoria": "NO_DETERMINADA"}, "categoría reconocida"),
        ({"subcategoria": "  "}, "SFX-REC-2026-001"),
        ({"instrucciones_prearribo": ""}, "SFX-REC-2026-001"),
        ({"preguntas_protocolo_mandatorias": ""}, "SFX-REC-2026-001"),
        ({"preguntas_protocolo_mandatorias": "¿Hay humo? |  | ¿Hay fuego?"}, "SFX-REC-2026-001"),
        ({"id_registro": "REC-1"}, "REC-1"),
        ({"id_registro": "SFX-REC-2026-002"}, "repetido"),
        ({"subcategoria": FILAS[1]["subcategoria"]}, "repetido"),
    ],
)
def test_un_csv_que_no_sirve_no_arma_un_catalogo(cambios, mensaje):
    with pytest.raises(CatalogoInvalido, match=mensaje):
        catalogo.leer(con(**cambios))


def test_un_csv_sin_una_columna_o_vacio_no_arma_un_catalogo():
    sin_columna = "\n".join(linea.split(",", 1)[1] for linea in con().splitlines())

    with pytest.raises(CatalogoInvalido, match="id_registro"):
        catalogo.leer(sin_columna)
    with pytest.raises(CatalogoInvalido):
        catalogo.leer("")
    with pytest.raises(CatalogoInvalido):
        catalogo.leer(con().splitlines()[0])


def test_una_fila_con_celdas_de_menos_o_de_mas_no_arma_un_catalogo():
    lineas = con().splitlines()

    with pytest.raises(CatalogoInvalido, match="SFX-REC-2026-030 no tiene las mismas columnas"):
        catalogo.leer("\n".join([*lineas[:-1], "SFX-REC-2026-030,2026-10-14T08:15:22"]))
    with pytest.raises(CatalogoInvalido, match="SFX-REC-2026-030 no tiene las mismas columnas"):
        catalogo.leer("\n".join([*lineas[:-1], lineas[-1] + ",de más"]))


def test_una_columna_repetida_no_pisa_en_silencio_a_la_original():
    lineas = con().splitlines()
    repetida = [
        lineas[0] + ",instrucciones_prearribo",
        *(linea + ",Otro texto" for linea in lineas[1:]),
    ]

    with pytest.raises(CatalogoInvalido, match="columnas repetidas"):
        catalogo.leer("\n".join(repetida))


def test_unas_comillas_sin_cerrar_no_arman_un_catalogo():
    with pytest.raises(CatalogoInvalido, match="no se puede leer"):
        catalogo.leer(con() + 'SFX-REC-2026-031,"sin cerrar')


def test_un_salto_de_linea_dentro_de_un_texto_se_conserva_tal_cual():
    con_salto = catalogo.leer(con(instrucciones_prearribo="No reingresar.\r\nEsperar afuera."))

    assert con_salto.protocolos[0].instrucciones[0].texto == "No reingresar.\r\nEsperar afuera."


# ---------- El criterio de prioridad ----------


def test_el_catalogo_trae_el_criterio_con_los_cuatro_niveles_en_orden():
    criterio = catalogo.cargar().criterio

    assert [nivel.id.value for nivel in criterio.niveles] == ["P1", "P2", "P3", "P4"]
    assert all(nivel.nombre and nivel.definicion and nivel.senales for nivel in criterio.niveles)
    assert "Una sola señal de P1 alcanza" in criterio.reglas[0]


def test_un_criterio_sin_un_nivel_o_desordenado_no_es_valido():
    niveles = catalogo.cargar().criterio.model_dump()["niveles"]

    for mal in (niveles[:3], niveles[::-1], [*niveles, niveles[0]]):
        with pytest.raises(ValidationError, match="en ese orden"):
            Criterio(niveles=mal, reglas=["x"])
