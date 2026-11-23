import csv
import json
import subprocess
import sys
from importlib import resources
from math import cos, hypot, radians
from pathlib import Path

import pytest
from conftest import DATOS_EMPAQUETADOS, TURNOS
from fastapi.testclient import TestClient

from copiloto import callejero, mapa, ubicacion
from copiloto.esquemas import CuadraDelPlano, Turno, valor_de
from copiloto.main import crear_app

CORRIENTES = {"calle": "Av. Corrientes", "altura": 1540, "esquinas": []}


def _distancia_al_punto(cuadra: CuadraDelPlano) -> float:
    """Metros entre el punto del plano, que es el origen, y el lugar más cercano de la cuadra."""
    dx, dy = cuadra.x2 - cuadra.x1, cuadra.y2 - cuadra.y1
    largo_al_cuadrado = dx**2 + dy**2
    fraccion = -(cuadra.x1 * dx + cuadra.y1 * dy) / largo_al_cuadrado if largo_al_cuadrado else 0
    fraccion = max(0, min(1, fraccion))
    return hypot(cuadra.x1 + fraccion * dx, cuadra.y1 + fraccion * dy)


def test_los_extremos_tienen_coordenadas_dentro_de_la_ciudad():
    with DATOS_EMPAQUETADOS.joinpath("callejero_nodos.csv").open(encoding="utf-8") as archivo:
        nodos = list(csv.DictReader(archivo))
    ids = [int(nodo["nodo"]) for nodo in nodos]
    assert ids == sorted(set(ids))
    assert all(-58.54 <= float(nodo["lon"]) <= -58.33 for nodo in nodos)
    assert all(-34.71 <= float(nodo["lat"]) <= -34.52 for nodo in nodos)

    with DATOS_EMPAQUETADOS.joinpath("callejero_caba.csv").open(encoding="utf-8") as archivo:
        extremos = {
            int(tramo[campo])
            for tramo in csv.DictReader(archivo)
            for campo in ("nodo_ini", "nodo_fin")
        }
    assert extremos == set(ids)


def test_plano_de_corrientes_ubica_la_altura_y_muestra_las_entrecalles():
    plano = mapa.plano("Av. Corrientes", 1540, [])

    assert plano is not None
    assert plano.exacto
    assert plano.radio_m == 250
    principales = [cuadra for cuadra in plano.cuadras if cuadra.principal]
    assert min(_distancia_al_punto(cuadra) for cuadra in principales) < 1

    cj = callejero.cargar()
    cruces = [cj.nombre_para_mostrar(nombre) for nombre in ("PARANA", "MONTEVIDEO")]
    assert set(cruces) <= {cuadra.nombre for cuadra in plano.cuadras}
    assert plano.leyenda == f"Av. Corrientes 1540, entre {cruces[0]} y {cruces[1]} · San Nicolas"
    # Una cuadra larga puede pasar cerca del punto sin tener un extremo dentro del radio.
    for cuadra in plano.cuadras:
        assert _distancia_al_punto(cuadra) <= plano.radio_m + 0.1


@pytest.mark.parametrize("altura", [None, 99_999])
def test_el_plano_por_esquina_usa_un_extremo_compartido(altura):
    plano = mapa.plano("Av. Córdoba", altura, ["Av. Corrientes", "Gascón"])

    assert plano is not None
    assert not plano.exacto
    cj = callejero.cargar()
    for nombre in ("CORDOBA AV.", "GASCON"):
        visible = cj.nombre_para_mostrar(nombre)
        assert visible in plano.leyenda
        assert any(
            min(hypot(cuadra.x1, cuadra.y1), hypot(cuadra.x2, cuadra.y2)) < 1
            for cuadra in plano.cuadras
            if cuadra.nombre == visible
        )


@pytest.mark.parametrize(
    ("calle", "altura", "esquinas"),
    [
        ("Av. Corrientes", 99_999, []),
        ("Av. Corrientes", None, []),
        ("Av. Calle Inventada", 1540, []),
        # Dos calles se llaman así y las dos tienen esa altura.
        ("Peron", 1500, []),
        ("Av. Corrientes", None, ["Córdoba"]),
    ],
)
def test_no_hay_plano_si_no_se_puede_ubicar(calle, altura, esquinas):
    assert mapa.plano(calle, altura, esquinas) is None


def test_mayusculas_y_acentos_no_cambian_el_plano():
    plano = mapa.plano("Av. Córdoba", None, ["Gascón"])
    assert plano is not None
    assert plano == mapa.plano("AV CORDOBA", None, ["GASCON"])


def test_la_altura_mas_alta_cae_mas_cerca_del_fin_de_la_misma_cuadra():
    def distancias_a_los_extremos(altura):
        plano = mapa.plano("Av. Corrientes", altura, [])
        assert plano is not None
        cuadra = next(
            cuadra
            for cuadra in plano.cuadras
            if cuadra.principal and cuadra.x1 * cuadra.x2 + cuadra.y1 * cuadra.y2 < 0
        )
        return hypot(cuadra.x1, cuadra.y1), hypot(cuadra.x2, cuadra.y2)

    inicio_bajo, fin_bajo = distancias_a_los_extremos(1520)
    inicio_alto, fin_alto = distancias_a_los_extremos(1580)
    assert inicio_bajo < inicio_alto
    assert fin_alto < fin_bajo


def test_la_api_devuelve_el_plano_solo_por_post(cliente):
    respuesta = cliente.post("/api/mapa", json=CORRIENTES)

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo.keys() == {"radio_m", "exacto", "leyenda", "cuadras"}
    assert cuerpo["radio_m"] == 250
    assert cuerpo["exacto"] is True
    assert "Av. Corrientes 1540" in cuerpo["leyenda"]
    assert cuerpo["cuadras"]
    for cuadra in cuerpo["cuadras"]:
        assert cuadra.keys() == {"nombre", "x1", "y1", "x2", "y2", "principal"}
        assert isinstance(cuadra["nombre"], str)
        assert isinstance(cuadra["principal"], bool)
        assert all(isinstance(cuadra[eje], float) for eje in ("x1", "y1", "x2", "y2"))
    assert cliente.get("/api/mapa", params={"calle": CORRIENTES["calle"]}).status_code in (404, 405)


def test_la_api_devuelve_404_si_no_hay_plano(cliente):
    respuesta = cliente.post("/api/mapa", json={**CORRIENTES, "altura": 99_999})

    assert respuesta.status_code == 404
    assert isinstance(respuesta.json()["detail"], str)


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("de_mas", True),
        ("altura", 100_000),
        ("altura", "1540"),
        ("calle", " "),
        ("calle", "a" * 201),
        ("esquinas", ["Parana", "Montevideo", "Uruguay"]),
    ],
)
def test_la_api_valida_el_pedido_de_plano(cliente, campo, valor):
    respuesta = cliente.post("/api/mapa", json={**CORRIENTES, campo: valor})

    assert respuesta.status_code == 422
    assert respuesta.json()["detail"][0]["loc"] == ["body", campo]


def test_el_arranque_y_el_alta_no_cargan_los_nodos(configuracion, monkeypatch):
    def fallar_si_se_carga():
        pytest.fail("El alta de una llamada no necesita las coordenadas del plano.")

    monkeypatch.setattr(mapa, "_cargar_mapa", fallar_si_se_carga)
    with TestClient(crear_app(configuracion)) as cliente:
        assert cliente.post("/api/llamadas", json={"turnos": TURNOS}).status_code == 201


def test_el_reductor_conserva_los_tramos_y_puede_escribir_los_nodos(tmp_path):
    herramienta = Path(__file__).resolve().parents[1] / "herramientas" / "reducir_callejero.py"
    oficial = tmp_path / "oficial.csv"
    reducido = tmp_path / "reducido.csv"
    con_nodos = tmp_path / "reducido_con_nodos.csv"
    nodos = tmp_path / "nodos.csv"
    columnas = (
        "nomoficial,nom_mapa,tipo_c,alt_izqini,alt_izqfin,alt_derini,alt_derfin,"
        "barrio_par,barrio_imp,com_par,com_impar"
    )
    primera = "UNA,UNA,CALLE,2,100,1,99,Flores,Flores,7,7"
    segunda = "OTRA,OTRA,CALLE,2,100,1,99,Flores,Flores,7,7"
    oficial.write_text(
        f"{columnas},geometry\n"
        f'{primera},"LINESTRING (-58.4000004 -34.6000004, -58.4015 -34.6015, -58.402 -34.602)"\n'
        f'{segunda},"LINESTRING (-58.402007 -34.602007, -58.403 -34.603)"\n',
        encoding="utf-8-sig",
    )

    subprocess.run([sys.executable, herramienta, oficial, reducido], check=True)
    assert not nodos.exists()
    subprocess.run([sys.executable, herramienta, oficial, con_nodos, "--nodos", nodos], check=True)

    assert (
        reducido.read_bytes()
        == f"{columnas},nodo_ini,nodo_fin\n{primera},0,1\n{segunda},1,2\n".encode()
    )
    assert con_nodos.read_bytes() == reducido.read_bytes()
    assert nodos.read_bytes() == (
        b"nodo,lon,lat\n0,-58.400000,-34.600000\n1,-58.402000,-34.602000\n2,-58.403000,-34.603000\n"
    )


@pytest.mark.parametrize(
    "calle, altura, principal",
    [
        # Hay otras dos calles Pueyrredón, y una calle y una avenida Honduras.
        ("Av. Pueyrredon", 1200, "Av. Pueyrredon"),
        ("Pueyrredon", 1200, "Av. Pueyrredon"),
        ("Honduras", 4850, "Honduras"),
    ],
)
def test_el_nombre_que_muestra_el_panel_alcanza_para_elegir_la_calle(calle, altura, principal):
    plano = mapa.plano(calle, altura, [])

    assert plano is not None
    assert {cuadra.nombre for cuadra in plano.cuadras if cuadra.principal} == {principal}


def test_una_esquina_que_no_se_reconoce_no_impide_ubicar_por_la_altura():
    assert mapa.plano("Av. Corrientes", 1540, ["Calle Que No Existe"]) == mapa.plano(
        "Av. Corrientes", 1540, []
    )


def test_en_una_esquina_la_leyenda_no_nombra_entrecalles():
    cj = callejero.cargar()
    assert len(cj.entrecalles("WARNES AV.", 1400)) > 2

    plano = mapa.plano("Av. Warnes", 1400, [])

    assert plano is not None
    assert plano.leyenda.startswith("Av. Warnes 1400 · ")
    assert "entre" not in plano.leyenda


@pytest.mark.parametrize(
    "calle, altura, esquinas",
    [
        ("Av. Corrientes", 1540, []),
        ("Av. Gral. Paz", 10000, []),
        ("Av. Cordoba", None, ["Gascon"]),
    ],
)
def test_el_plano_trae_todas_las_cuadras_que_pasan_cerca(calle, altura, esquinas):
    """La grilla no puede perder cuadras: se compara contra recorrer todo el callejero."""
    plano = mapa.plano(calle, altura, esquinas)
    assert plano is not None
    cj = callejero.cargar()
    nodos, _ = mapa._cargar_mapa()
    todos = [tramo for tramos in cj.tramos.values() for tramo in tramos]

    class TodoElCallejero(dict):
        def get(self, _celda, _defecto=()):
            return todos

    lugar = mapa._ubicar(calle, altura, esquinas)
    assert lugar is not None

    completo = mapa._cuadras_cercanas(cj, lugar.nombre, lugar.punto, nodos, TodoElCallejero())

    assert sorted(plano.cuadras, key=repr) == sorted(completo, key=repr)


def test_una_cuadra_larga_que_cruza_el_plano_se_dibuja_aunque_sus_extremos_queden_lejos():
    assert mapa._distancia_al_origen(-400, 10, 400, 10) == 10
    assert mapa._distancia_al_origen(300, 0, 400, 0) == 300
    assert mapa._distancia_al_origen(5, 5, 5, 5) == pytest.approx(7.07, abs=0.01)
    lejos = ((-58.4000, -34.6000), (-58.3900, -34.6000))
    assert len(mapa._celdas_que_cruza(*lejos)) >= 4


def test_si_la_altura_no_existe_el_plano_muestra_la_esquina_y_lo_dice():
    plano = mapa.plano("Av. Corrientes", 9999, ["Montevideo"])

    assert plano is not None
    assert not plano.exacto
    assert plano.leyenda == (
        "Av. Corrientes y Montevideo · San Nicolas. La altura 9999 no figura en esa calle."
    )
    assert mapa.plano("Av. Corrientes", None, ["Montevideo"]).leyenda == (
        "Av. Corrientes y Montevideo · San Nicolas"
    )


def test_un_nombre_de_calle_y_de_avenida_se_decide_por_donde_existe_la_altura():
    # «Rivadavia» es una calle y también una avenida: la altura 5000 sólo está en la avenida.
    plano = mapa.plano("Rivadavia", 5000, [])

    assert plano is not None
    assert plano.leyenda.startswith("Av. Rivadavia 5000")


def test_el_plano_ubica_la_calle_igual_que_la_lectura_de_la_llamada():
    for frase in ("Es en Paz 1234.", "Estoy en Santa Fe 3200.", "En Rivadavia 5000 hay humo."):
        leida = ubicacion.interpretar([Turno(hablante="llamante", texto=frase)]).ubicacion
        calle, altura = valor_de(leida.calle), valor_de(leida.altura)
        assert calle is not None and altura is not None

        plano = mapa.plano(calle, altura, [])

        assert plano is not None
        assert plano.leyenda.startswith(f"{calle} {altura}")


def _llamadas_de_la_medicion() -> list[str]:
    archivo = resources.files("copiloto").joinpath("datos", "dataset_challenge_soflex.csv")
    with archivo.open("r", encoding="utf-8-sig", newline="") as abierto:
        dataset = [fila["transcripcion_cruda"] for fila in csv.DictReader(abierto)]
    nuevas = json.loads(
        Path(__file__).with_name("datos").joinpath("llamadas_nuevas.json").read_text()
    )
    return dataset + [llamada["texto"] for llamada in nuevas]


def test_toda_direccion_que_lee_el_servicio_tiene_plano():
    """En las 62 llamadas de la medición: 53 traen calle y altura o esquina, y las 53 se dibujan."""
    con_lugar = con_plano = 0
    for texto in _llamadas_de_la_medicion():
        leida = ubicacion.interpretar([Turno(texto=texto)]).ubicacion
        calle, altura = valor_de(leida.calle), valor_de(leida.altura)
        esquinas = [esquina.valor for esquina in leida.esquinas]
        if calle is None or (altura is None and not esquinas):
            continue
        con_lugar += 1
        plano = mapa.plano(calle, altura, esquinas)
        if plano is not None:
            con_plano += 1
            # Dibujar otra calle sería peor que no dibujar: la leyenda nombra la que se leyó.
            assert plano.leyenda.startswith(calle), (calle, plano.leyenda)

    assert (con_lugar, con_plano) == (53, 53)


def test_el_punto_queda_cerca_del_que_da_el_servicio_de_direcciones_de_la_ciudad():
    """Contra 13 direcciones geocodificadas por USIG: el punto queda a menos de 20 m.

    El punto se interpola sobre la recta de la cuadra, así que no es exacto: alcanza para ver en
    qué cuadra cae la dirección.
    """
    referencia = json.loads(
        Path(__file__).with_name("datos").joinpath("puntos_de_referencia.json").read_text()
    )
    distancias = []
    for punto in referencia["puntos"]:
        lugar = mapa._ubicar(punto["calle"], punto["altura"], [])
        assert lugar is not None, punto
        lon, lat = lugar.punto
        distancias.append(
            hypot(
                (punto["lon"] - lon) * cos(radians(lat)) * 111_320,
                (punto["lat"] - lat) * 110_540,
            )
        )

    assert len(distancias) == 13
    assert max(distancias) < 20
    assert sorted(distancias)[6] < 15
