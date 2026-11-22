from copiloto import flujo

TURNOS = [{"texto": "Se prendió fuego la cocina de la pizzería de Corrientes 1540."}]


def test_analizar_propone_ubicacion_tipo_y_prioridad():
    sugerencia = flujo.analizar(TURNOS)

    assert set(sugerencia) == {"ubicacion", "tipo_hecho", "prioridad"}


def test_analizar_no_comparte_la_sugerencia_entre_llamadas():
    flujo.analizar(TURNOS)["ubicacion"]["calle"] = "Otra calle"

    assert flujo.analizar(TURNOS)["ubicacion"]["calle"] == "Av. Corrientes"


def test_derivar_sin_ajustes_deja_la_sugerencia_tal_cual():
    sugerencia = flujo.analizar(TURNOS)

    carta = flujo.derivar("abc", sugerencia, {})

    assert carta == {"llamada_id": "abc", **sugerencia, "ajustado_por_operador": []}


def test_derivar_pone_los_ajustes_por_encima_y_dice_cuales_cambiaron():
    sugerencia = flujo.analizar(TURNOS)

    carta = flujo.derivar(
        "abc", sugerencia, {"prioridad": "P2", "tipo_hecho": sugerencia["tipo_hecho"]}
    )

    assert carta["prioridad"] == "P2"
    assert carta["ubicacion"] == sugerencia["ubicacion"]
    assert carta["ajustado_por_operador"] == ["prioridad"]
