import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from copiloto.duplicados import Lugar, UbicacionesRecientes, coinciden
from copiloto.esquemas import Ajustes, Categoria, PosibleDuplicado, Turno
from copiloto.llamadas import LlamadaInexistente, Llamadas

AHORA = datetime(2026, 11, 22, 12, tzinfo=UTC)
CHOQUE = Turno(texto="Hay un choque en Av. Corrientes 1540.")


@pytest.mark.parametrize(
    "primera, segunda, coincide",
    [
        (Lugar("Gaona", 2920, ()), Lugar("Gaona", 2950, ()), True),
        (Lugar("Gaona", 2920, ()), Lugar("Gaona", 3020, ()), True),
        (Lugar("Gaona", 2920, ()), Lugar("Gaona", 3070, ()), False),
        (Lugar("Córdoba", 3900, ("Gascón",)), Lugar("Córdoba", None, ("Gascón",)), True),
        (Lugar("Córdoba", 3900, ("Gascón",)), Lugar("Córdoba", None, ("Medrano",)), False),
        (Lugar("Córdoba", None, ("Gascón",)), Lugar("Gascón", None, ("Córdoba",)), True),
        (Lugar("Córdoba", None, ()), Lugar("Córdoba", 3900, ("Gascón",)), False),
        (Lugar("Córdoba", None, ()), Lugar("Córdoba", None, ()), False),
        (Lugar("Gaona", 2920, ("Gascón",)), Lugar("Córdoba", 2920, ("Gascón",)), False),
        (Lugar("Av. CÓRDOBA", None, ("GASCÓN",)), Lugar("av cordoba", None, ("gascon",)), True),
        # Dos cuadras seguidas comparten una esquina del callejero, pero están lejos.
        (
            Lugar("Av. Corrientes", 1502, ("Parana", "Montevideo")),
            Lugar("Av. Corrientes", 1698, ("Montevideo", "Rodriguez Peña")),
            False,
        ),
        (
            Lugar("Av. Corrientes", 1502, ("Parana", "Montevideo")),
            Lugar("Av. Corrientes", None, ("Montevideo",)),
            True,
        ),
    ],
)
def test_coincidencia_de_lugares(primera, segunda, coincide):
    assert coinciden(primera, segunda) is coincide
    assert coinciden(segunda, primera) is coincide


@pytest.mark.parametrize(
    "lugar, texto",
    [
        (Lugar("Av. Gaona", 2920, ("Terrada", "Condarco")), "Av. Gaona 2920"),
        (Lugar("Av. Córdoba", None, ("Gascón",)), "Av. Córdoba y Gascón"),
        (Lugar("Av. Córdoba", None, ("Gascón", "Medrano")), "Av. Córdoba entre Gascón y Medrano"),
    ],
)
def test_como_se_muestra_un_lugar(lugar, texto):
    assert lugar.mostrar() == texto


@pytest.fixture
def servicio(tmp_path):
    class Reloj:
        ahora = AHORA

        def __call__(self):
            return self.ahora

    reloj = Reloj()
    llamadas = Llamadas(tmp_path / "llamadas.sqlite", reloj=reloj)
    try:
        yield llamadas, reloj
    finally:
        llamadas.cerrar()


@pytest.mark.parametrize("minutos, coinciden", [(5, True), (30, True), (40, False)])
def test_la_ventana_corre_en_los_dos_sentidos(servicio, minutos, coinciden):
    llamadas, reloj = servicio
    primera = llamadas.iniciar([CHOQUE]).llamada_id
    reloj.ahora += timedelta(minutes=minutos)
    segunda = llamadas.iniciar([CHOQUE]).llamada_id

    assert llamadas.consultar_duplicados(primera)[1] == (
        [
            PosibleDuplicado(
                llamada_id=segunda,
                recibida_en=reloj.ahora,
                ubicacion="Av. Corrientes 1540",
                categoria="ACCIDENTE_VIAL",
                derivada=False,
            )
        ]
        if coinciden
        else []
    )
    _, posibles = llamadas.consultar_duplicados(segunda)
    assert [posible.llamada_id for posible in posibles] == ([primera] if coinciden else [])


def test_una_llamada_sola_no_se_ve_a_si_misma(servicio):
    llamadas, _ = servicio
    llamada = llamadas.iniciar([CHOQUE])

    assert llamadas.consultar_duplicados(llamada.llamada_id) == (AHORA, [])


def test_devuelve_hasta_cinco_coincidencias_de_mas_nueva_a_mas_vieja(servicio):
    llamadas, reloj = servicio
    ids = []
    for minutos in range(7):
        reloj.ahora = AHORA + timedelta(minutes=minutos)
        ids.append(llamadas.iniciar([CHOQUE]).llamada_id)
    reloj.ahora += timedelta(minutes=1)
    llamadas.iniciar([Turno(texto="Hay un choque en Av. Gaona 2920.")])

    _, posibles = llamadas.consultar_duplicados(ids[0])

    assert [posible.llamada_id for posible in posibles] == ids[:1:-1]


def test_al_sumar_la_altura_coincide_con_la_hora_original(servicio):
    llamadas, reloj = servicio
    primera = llamadas.iniciar(
        [Turno(texto="Hay un choque en Av. Corrientes.", hablante="llamante")]
    ).llamada_id
    reloj.ahora += timedelta(minutes=5)
    segunda = llamadas.iniciar([CHOQUE]).llamada_id
    assert llamadas.consultar_duplicados(segunda)[1] == []

    reloj.ahora += timedelta(minutes=40)
    llamadas.sumar_turno(primera, Turno(texto="¿A qué altura?", hablante="operador"))
    llamadas.sumar_turno(primera, Turno(texto="Al 1540.", hablante="llamante"))

    _, posibles = llamadas.consultar_duplicados(segunda)
    assert [(posible.llamada_id, posible.recibida_en) for posible in posibles] == [(primera, AHORA)]


def test_la_llamada_sin_calle_conserva_la_hora_al_reiniciar(tmp_path):
    ruta = tmp_path / "llamadas.sqlite"
    antes = Llamadas(ruta, reloj=lambda: AHORA)
    try:
        llamada = antes.iniciar([Turno(texto="Hay un choque.")])
        assert antes.consultar_duplicados(llamada.llamada_id) == (None, [])
    finally:
        antes.cerrar()

    despues = Llamadas(ruta, reloj=lambda: AHORA + timedelta(minutes=5))
    try:
        otra = despues.iniciar([CHOQUE])
        despues.sumar_turno(llamada.llamada_id, Turno(texto="En Av. Corrientes 1540."))
        _, posibles = despues.consultar_duplicados(otra.llamada_id)
        assert [(posible.llamada_id, posible.recibida_en) for posible in posibles] == [
            (llamada.llamada_id, AHORA)
        ]
    finally:
        despues.cerrar()


def test_el_analisis_terminado_actualiza_la_categoria_del_aviso(tmp_path):
    def modelo(_sistema, _usuario, _vence):
        return '{"categoria":"DEFENSA_CIVIL","subtipo":null,"prioridad":"P2"}'

    llamadas = Llamadas(tmp_path / "llamadas.sqlite", modelo, reloj=lambda: AHORA)
    try:
        primera = llamadas.iniciar([CHOQUE])
        segunda = llamadas.iniciar([CHOQUE])
        assert primera.estado == "analizando"
        (_, [posible]) = llamadas.consultar_duplicados(segunda.llamada_id)
        assert posible.categoria == Categoria.ACCIDENTE_VIAL

        assert llamadas.completar_analisis(primera.llamada_id).estado == "esperando_operador"

        (_, [posible]) = llamadas.consultar_duplicados(segunda.llamada_id)
        assert posible.categoria == Categoria.DEFENSA_CIVIL
        assert posible.recibida_en == AHORA
    finally:
        llamadas.cerrar()


def test_al_derivar_se_usa_la_ubicacion_y_la_categoria_de_la_carta(servicio):
    llamadas, reloj = servicio
    primera = llamadas.iniciar([CHOQUE]).llamada_id
    reloj.ahora += timedelta(minutes=5)
    segunda = llamadas.iniciar([CHOQUE]).llamada_id
    ajustes = Ajustes.model_validate(
        {
            "ubicacion": {"calle": "Av. Corrientes", "altura": 1560, "esquinas": []},
            "tipo_hecho": {"categoria": "DEFENSA_CIVIL", "subtipo": None},
            "prioridad": "P2",
        }
    )

    llamadas.derivar(primera, ajustes)

    _, posibles = llamadas.consultar_duplicados(segunda)
    assert [posible.model_dump(mode="json") for posible in posibles] == [
        {
            "llamada_id": primera,
            "recibida_en": "2026-11-22T12:00:00Z",
            "ubicacion": "Av. Corrientes 1560",
            "categoria": "DEFENSA_CIVIL",
            "derivada": True,
        }
    ]


def test_una_llamada_inexistente_no_se_puede_consultar(servicio):
    llamadas, _ = servicio
    with pytest.raises(LlamadaInexistente):
        llamadas.consultar_duplicados("no-existe")


def test_una_base_sin_el_indice_sigue_leyendo_sus_llamadas(tmp_path):
    ruta = tmp_path / "llamadas.sqlite"
    antes = Llamadas(ruta, reloj=lambda: AHORA)
    try:
        guardada = antes.iniciar([CHOQUE])
    finally:
        antes.cerrar()
    conexion = sqlite3.connect(ruta)
    try:
        with conexion:
            conexion.execute("DROP TABLE ubicaciones_recientes")
    finally:
        conexion.close()

    despues = Llamadas(ruta, reloj=lambda: AHORA)
    try:
        assert despues.consultar(guardada.llamada_id) == guardada
        despues.iniciar([CHOQUE])
        assert despues.consultar_duplicados(guardada.llamada_id) == (None, [])
    finally:
        despues.cerrar()


def test_un_error_al_escribir_el_indice_no_impide_iniciar(tmp_path, servicio, caplog):
    llamadas, _ = servicio
    conexion = sqlite3.connect(tmp_path / "llamadas.sqlite")
    try:
        with conexion:
            conexion.execute("""
                CREATE TRIGGER falla_indice BEFORE INSERT ON ubicaciones_recientes
                BEGIN SELECT RAISE(ABORT, 'falla simulada'); END
            """)
    finally:
        conexion.close()

    llamada = llamadas.iniciar([CHOQUE])

    assert llamada.estado == "esperando_operador"
    assert llamadas.consultar(llamada.llamada_id) == llamada
    assert "falla simulada" in caplog.text


def test_la_api_devuelve_los_duplicados_sin_cambiar_el_json_de_la_llamada(cliente):
    entrada = {"turnos": [CHOQUE.model_dump(mode="json")]}
    primera = cliente.post("/api/llamadas", json=entrada).json()
    ruta = f"/api/llamadas/{primera['llamada_id']}"
    antes = cliente.get(ruta).json()

    segunda = cliente.post("/api/llamadas", json=entrada).json()
    respuesta = cliente.get(f"{ruta}/duplicados")

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    (posible,) = cuerpo["posibles"]
    hora_primera = datetime.fromisoformat(cuerpo["recibida_en"])
    hora_segunda = datetime.fromisoformat(posible["recibida_en"])
    assert hora_primera.utcoffset() == hora_segunda.utcoffset() == timedelta(0)
    assert hora_primera <= hora_segunda
    assert cuerpo == {
        "llamada_id": primera["llamada_id"],
        "recibida_en": cuerpo["recibida_en"],
        "posibles": [
            {
                "llamada_id": segunda["llamada_id"],
                "recibida_en": posible["recibida_en"],
                "ubicacion": "Av. Corrientes 1540",
                "categoria": "ACCIDENTE_VIAL",
                "derivada": False,
            }
        ],
    }
    assert cliente.get(ruta).json() == antes


def test_la_api_devuelve_404_al_buscar_duplicados_de_una_llamada_inexistente(cliente):
    assert cliente.get("/api/llamadas/no-existe/duplicados").status_code == 404


def test_una_base_sin_ninguna_tabla_del_indice_arranca_y_vuelve_a_indexar(tmp_path):
    ruta = tmp_path / "llamadas.sqlite"
    antes = Llamadas(ruta, reloj=lambda: AHORA)
    try:
        guardada = antes.iniciar([CHOQUE])
    finally:
        antes.cerrar()
    conexion = sqlite3.connect(ruta)
    try:
        with conexion:
            conexion.execute("DROP TABLE ubicaciones_recientes")
            conexion.execute("DROP TABLE recepciones_llamadas")
    finally:
        conexion.close()

    despues = Llamadas(ruta, reloj=lambda: AHORA)
    try:
        assert despues.consultar(guardada.llamada_id) == guardada
        primera = despues.iniciar([CHOQUE]).llamada_id
        segunda = despues.iniciar([CHOQUE]).llamada_id
        assert despues.consultar_duplicados(guardada.llamada_id) == (None, [])
        _, posibles = despues.consultar_duplicados(segunda)
        assert [posible.llamada_id for posible in posibles] == [primera]
    finally:
        despues.cerrar()


def test_un_error_cualquiera_del_indice_no_hace_fallar_a_la_llamada(servicio, monkeypatch, caplog):
    llamadas, _ = servicio

    def falla(*_argumentos, **_opciones):
        raise TypeError("falla simulada")

    monkeypatch.setattr(UbicacionesRecientes, "_actualizar_ubicacion", falla)

    llamada = llamadas.iniciar([CHOQUE])
    con_turno = llamadas.sumar_turno(llamada.llamada_id, Turno(texto="Hay un herido."))
    derivada = llamadas.derivar(llamada.llamada_id, Ajustes.model_validate({"prioridad": "P2"}))

    assert len(con_turno.turnos) == 2
    assert derivada.estado == "derivada"
    assert llamadas.consultar_duplicados(llamada.llamada_id) == (None, [])
    assert caplog.text.count("falla simulada") >= 3


def test_una_fila_mal_guardada_no_deja_sin_aviso_a_las_demas(tmp_path, servicio, caplog):
    llamadas, reloj = servicio
    primera = llamadas.iniciar([CHOQUE]).llamada_id
    rota = llamadas.iniciar([CHOQUE]).llamada_id
    reloj.ahora += timedelta(minutes=1)
    tercera = llamadas.iniciar([CHOQUE]).llamada_id
    conexion = sqlite3.connect(tmp_path / "llamadas.sqlite")
    try:
        with conexion:
            conexion.execute(
                "UPDATE ubicaciones_recientes SET categoria = 'OTRA' WHERE llamada_id = ?", (rota,)
            )
    finally:
        conexion.close()

    _, posibles = llamadas.consultar_duplicados(tercera)

    assert [posible.llamada_id for posible in posibles] == [primera]
    assert rota in caplog.text


def test_sin_la_tabla_del_indice_la_consulta_no_trae_avisos_y_la_llamada_sigue(
    tmp_path, servicio, caplog
):
    llamadas, _ = servicio
    llamada = llamadas.iniciar([CHOQUE])
    conexion = sqlite3.connect(tmp_path / "llamadas.sqlite")
    try:
        with conexion:
            conexion.execute("DROP TABLE ubicaciones_recientes")
    finally:
        conexion.close()

    assert llamadas.consultar_duplicados(llamada.llamada_id) == (None, [])
    assert llamadas.sumar_turno(llamada.llamada_id, Turno(texto="Hay un herido.")).turnos
    assert "No se pudo consultar el índice" in caplog.text


def test_al_derivar_con_otra_calle_deja_de_coincidir_con_la_anterior(servicio):
    llamadas, reloj = servicio
    primera = llamadas.iniciar([CHOQUE]).llamada_id
    reloj.ahora += timedelta(minutes=5)
    segunda = llamadas.iniciar([CHOQUE]).llamada_id
    tercera = llamadas.iniciar([Turno(texto="Hay un choque en Av. Gaona 2920.")]).llamada_id
    ajustes = Ajustes.model_validate(
        {
            "ubicacion": {"calle": "Av. Gaona", "altura": 2950, "esquinas": []},
            "tipo_hecho": {"categoria": "ACCIDENTE_VIAL", "subtipo": None},
            "prioridad": "P2",
        }
    )

    llamadas.derivar(primera, ajustes)

    assert llamadas.consultar_duplicados(segunda)[1] == []
    _, posibles = llamadas.consultar_duplicados(tercera)
    assert [(posible.llamada_id, posible.ubicacion) for posible in posibles] == [
        (primera, "Av. Gaona 2950")
    ]


def test_completar_el_analisis_dos_veces_deja_el_mismo_aviso(tmp_path):
    def modelo(_sistema, _usuario, _vence):
        return '{"categoria":"DEFENSA_CIVIL","subtipo":null,"prioridad":"P2"}'

    llamadas = Llamadas(tmp_path / "llamadas.sqlite", modelo, reloj=lambda: AHORA)
    try:
        primera = llamadas.iniciar([CHOQUE]).llamada_id
        segunda = llamadas.iniciar([CHOQUE]).llamada_id
        llamadas.completar_analisis(primera)
        una_vez = llamadas.consultar_duplicados(segunda)

        llamadas.completar_analisis(primera)

        assert llamadas.consultar_duplicados(segunda) == una_vez
    finally:
        llamadas.cerrar()
