from datetime import UTC, datetime

import pytest
from conftest import FILAS_DATASET, TEXTO, TEXTO_SIN_DATOS, TURNOS

from copiloto import catalogo, flujo, ubicacion
from copiloto.catalogo import SubtipoInvalido
from copiloto.esquemas import (
    Ajustes,
    Categoria,
    Cita,
    Falta,
    Inferido,
    Prioridad,
    Sugerencia,
    Turno,
)

AHORA = datetime(2026, 11, 22, 3, 0, tzinfo=UTC)
COMPLETA = {"calle": "Av. Corrientes", "altura": 1540, "esquinas": ["Montevideo", "Paraná"]}
TEXTO_NUEVO = "Chocaron dos autos en Av. Corrientes."


def derivar(sugerencia: dict, ajustes: dict) -> dict:
    carta = flujo.derivar(
        "abc", Sugerencia.model_validate(sugerencia), Ajustes.model_validate(ajustes), AHORA
    )
    return carta.model_dump(mode="json")


def test_analizar_no_afirma_nada_que_no_haya_leido():
    sugerencia = flujo.analizar([Turno(texto=TEXTO_SIN_DATOS)])

    assert sugerencia.faltantes() == ["calle", "prioridad"]
    assert sugerencia.tipo_hecho == Inferido[Categoria](
        valor=Categoria.NO_DETERMINADA, fuente="reglas"
    )
    assert sugerencia.ubicacion.calle == sugerencia.ubicacion.altura == Falta()
    assert sugerencia.subtipo == sugerencia.prioridad == Falta()
    assert sugerencia.ubicacion.esquinas == sugerencia.checklist == sugerencia.citas() == []


def test_analizar_una_llamada_del_dataset_sugiere_su_protocolo_y_cita_sus_respuestas():
    turnos = [
        Turno(hablante="operador", texto="911 emergencias, ¿dónde es su urgencia?"),
        Turno(hablante="llamante", texto=TEXTO),
    ]

    sugerencia = flujo.analizar(turnos)

    assert sugerencia.ubicacion.calle.valor == "Av. Corrientes"
    assert sugerencia.ubicacion.calle.cita == Cita(turno=1, texto="Av. Corrientes")
    assert sugerencia.ubicacion.altura.valor == 1540
    assert sugerencia.ubicacion.altura.cita == Cita(turno=1, texto="1540")
    assert sugerencia.tipo_hecho == Inferido[Categoria](
        valor=Categoria.INCENDIO_RESCATE, fuente="dataset"
    )
    assert sugerencia.subtipo.model_dump() == {
        "origen": "inferido",
        "valor": "SFX-001",
        "fuente": "dataset",
    }
    assert sugerencia.prioridad.model_dump(mode="json") == {
        "origen": "inferido",
        "valor": "P1",
        "fuente": "dataset",
    }
    esperado = pendientes("SFX-001")
    esperado[0].update(respondida=True, cita={"turno": 1, "texto": "adentro quedó el cocinero"})
    assert [item.model_dump() for item in sugerencia.checklist] == esperado


def test_analizar_un_texto_nuevo_sugiere_la_ubicacion_y_solo_la_categoria():
    turnos = [
        Turno(hablante="operador", texto="¿Hay un incendio, llamas y humo en Av. San Juan 800?"),
        Turno(hablante="llamante", texto=TEXTO_NUEVO),
    ]

    sugerencia = flujo.analizar(turnos)

    assert sugerencia.ubicacion.calle.valor == "Av. Corrientes"
    assert sugerencia.ubicacion.calle.cita == Cita(turno=1, texto="Av. Corrientes")
    assert sugerencia.ubicacion.altura == Falta()
    assert sugerencia.ubicacion.esquinas == []
    assert [aviso.codigo for aviso in sugerencia.avisos] == ["falta_altura"]
    assert sugerencia.tipo_hecho == Inferido[Categoria](
        valor=Categoria.ACCIDENTE_VIAL, fuente="reglas"
    )
    assert sugerencia.subtipo == sugerencia.prioridad == Falta()
    assert sugerencia.checklist == sugerencia.instrucciones == []


@pytest.mark.parametrize(
    "texto",
    [
        pytest.param(fila["transcripcion_cruda"], id=subtipo)
        for subtipo, fila in FILAS_DATASET.items()
    ]
    + [pytest.param(TEXTO_NUEVO, id="texto_nuevo"), pytest.param(TEXTO_SIN_DATOS, id="sin_datos")],
)
def test_analizar_no_produce_datos_con_origen_operador(texto):
    sugerencia = flujo.analizar([Turno(texto=texto)])

    assert all(dato.origen != "operador" for dato in sugerencia.datos().values())


def test_se_descarta_cada_dato_sin_cita_respaldada_y_se_avisa(sugerencia_completa):
    cita_falsa = {"turno": 0, "texto": "Alguien vio una sirena azul."}
    ubicacion = sugerencia_completa["ubicacion"]
    respuesta = sugerencia_completa["checklist"][0]
    for dato in (ubicacion["calle"], ubicacion["altura"], ubicacion["esquinas"][0], respuesta):
        dato["cita"] = cita_falsa
    for campo, valor in (("tipo_hecho", "INCENDIO_RESCATE"), ("prioridad", "P1")):
        sugerencia_completa[campo] = {"origen": "dicho", "valor": valor, "cita": cita_falsa}
    sugerencia = Sugerencia.model_validate(sugerencia_completa)

    revisada = flujo.quitar_lo_que_nadie_dijo(sugerencia, [Turno(**turno) for turno in TURNOS])

    assert revisada.ubicacion.calle == revisada.ubicacion.altura == revisada.prioridad == Falta()
    assert revisada.ubicacion.esquinas == sugerencia.ubicacion.esquinas[1:]
    assert revisada.tipo_hecho == Inferido[Categoria](
        valor=Categoria.NO_DETERMINADA, fuente="reglas"
    )
    assert revisada.subtipo == sugerencia.subtipo
    assert revisada.checklist[0].model_dump() == {**respuesta, "respondida": False, "cita": None}
    assert revisada.checklist[1:] == sugerencia.checklist[1:]
    assert [aviso.codigo for aviso in revisada.avisos] == ["dato_descartado"] * 6
    for campo in ("calle", "altura", "esquina", "tipo de hecho", "prioridad", "respuesta"):
        assert sum(campo in aviso.mensaje for aviso in revisada.avisos) == 1


def test_si_todas_las_citas_estan_respaldadas_se_conserva_la_sugerencia(sugerencia_completa):
    sugerencia = Sugerencia.model_validate(sugerencia_completa)
    turnos = [Turno(**turno) for turno in TURNOS]

    assert flujo.quitar_lo_que_nadie_dijo(sugerencia, turnos) == sugerencia


def test_de_un_inferido_se_quita_solo_la_cita_que_no_verifica(sugerencia_completa):
    cita = Cita(turno=0, texto="Explotó una garrafa")
    sugerencia_completa["prioridad"] = Inferido[Prioridad](
        valor=Prioridad.P1, fuente="modelo", cita=cita
    )
    sugerencia = Sugerencia.model_validate(sugerencia_completa)

    revisada = flujo.quitar_lo_que_nadie_dijo(sugerencia, [Turno(**turno) for turno in TURNOS])

    assert cita in sugerencia.citas()
    assert cita not in revisada.citas()
    assert revisada.prioridad == Inferido[Prioridad](valor=Prioridad.P1, fuente="modelo")
    assert revisada.avisos == sugerencia.avisos


def test_lo_que_el_operador_no_toca_conserva_su_origen_y_su_cita(sugerencia_completa):
    carta = derivar(sugerencia_completa, {"prioridad": "P1"})

    assert carta["ubicacion"] == sugerencia_completa["ubicacion"]
    assert carta["tipo_hecho"] == sugerencia_completa["tipo_hecho"]
    assert carta["subtipo"] == sugerencia_completa["subtipo"]
    assert carta["checklist"] == sugerencia_completa["checklist"]
    assert carta["instrucciones"] == sugerencia_completa["instrucciones"]
    assert carta["prioridad"] == {"origen": "operador", "valor": "P1"}
    assert carta["llamada_id"] == "abc"
    assert carta["derivada_en"] == "2026-11-22T03:00:00Z"


def test_lo_que_el_operador_cambia_pasa_a_ser_suyo_y_el_resto_no(sugerencia_completa):
    ubicacion = {**COMPLETA, "altura": 1548, "esquinas": ["Montevideo", "Uruguay"]}

    carta = derivar(sugerencia_completa, {"prioridad": "P2", "ubicacion": ubicacion})

    sugerida = sugerencia_completa["ubicacion"]
    assert carta["ubicacion"]["calle"] == sugerida["calle"]
    assert carta["ubicacion"]["altura"] == {"origen": "operador", "valor": 1548}
    assert carta["ubicacion"]["esquinas"] == [
        sugerida["esquinas"][0],
        {"origen": "operador", "valor": "Uruguay"},
    ]


def test_reescribir_lo_mismo_con_otras_mayusculas_o_tildes_no_es_un_cambio(sugerencia_completa):
    ubicacion = {"calle": " av corrientes ", "altura": 1540, "esquinas": ["PARANA", "montevideo"]}

    carta = derivar(sugerencia_completa, {"prioridad": "P1", "ubicacion": ubicacion})

    sugerida = sugerencia_completa["ubicacion"]
    assert carta["ubicacion"]["calle"] == sugerida["calle"]
    assert carta["ubicacion"]["altura"] == sugerida["altura"]
    assert carta["ubicacion"]["esquinas"] == [sugerida["esquinas"][1], sugerida["esquinas"][0]]


def test_vaciar_lo_sugerido_queda_como_decision_del_operador_no_como_falta(sugerencia_completa):
    ubicacion = {"calle": "Av. Corrientes", "altura": None, "esquinas": []}

    carta = derivar(sugerencia_completa, {"prioridad": "P1", "ubicacion": ubicacion})

    assert carta["ubicacion"]["altura"] == {"origen": "operador", "valor": None}
    assert carta["ubicacion"]["esquinas"] == []


def test_lo_que_faltaba_y_el_operador_no_completa_sigue_faltando(sugerencia_completa):
    sugerencia_completa["ubicacion"]["altura"] = {"origen": "falta"}
    ubicacion = {"calle": "Av. Corrientes", "altura": None, "esquinas": ["Montevideo", "Paraná"]}

    carta = derivar(sugerencia_completa, {"prioridad": "P1", "ubicacion": ubicacion})

    assert carta["ubicacion"]["altura"] == {"origen": "falta"}


def test_elegir_el_mismo_tipo_que_se_sugirio_no_lo_vuelve_del_operador(sugerencia_completa):
    mismo = {"categoria": "INCENDIO_RESCATE", "subtipo": "SFX-001"}

    carta = derivar(sugerencia_completa, {"prioridad": "P1", "tipo_hecho": mismo})

    assert carta["tipo_hecho"] == sugerencia_completa["tipo_hecho"]
    assert carta["subtipo"] == sugerencia_completa["subtipo"]
    assert carta["checklist"] == sugerencia_completa["checklist"]


def test_sin_los_datos_obligatorios_no_hay_carta(sugerencia_completa):
    with pytest.raises(flujo.FaltanDatos) as error:
        derivar(sugerencia_completa, {})
    assert error.value.campos == ["prioridad"]

    sin_nada = flujo.analizar([Turno(texto=TEXTO_SIN_DATOS)]).model_dump(mode="json")
    with pytest.raises(flujo.FaltanDatos) as error:
        derivar(sin_nada, {"tipo_hecho": {"categoria": "ACCIDENTE_VIAL", "subtipo": None}})
    assert error.value.campos == ["calle", "prioridad"]


def test_confirmar_sin_cambios_una_sugerencia_completa_la_deja_tal_cual(sugerencia_completa):
    sugerencia_completa["prioridad"] = {"origen": "inferido", "valor": "P1", "fuente": "reglas"}

    carta = derivar(sugerencia_completa, {})

    assert carta == {
        **sugerencia_completa,
        "llamada_id": "abc",
        "derivada_en": carta["derivada_en"],
    }


def test_corregir_una_enie_es_un_cambio(sugerencia_completa):
    sugerencia_completa["ubicacion"]["calle"]["valor"] = "Cañada"
    ubicacion = {"calle": "Canada", "altura": 1540, "esquinas": []}

    carta = derivar(sugerencia_completa, {"prioridad": "P1", "ubicacion": ubicacion})

    assert carta["ubicacion"]["calle"] == {"origen": "operador", "valor": "Canada"}


@pytest.mark.parametrize(
    ("ubicacion", "conserva_avisos"),
    [
        pytest.param(None, True, id="sin_ajuste_de_ubicacion"),
        pytest.param(COMPLETA, True, id="misma_ubicacion"),
        pytest.param({**COMPLETA, "calle": "Av. Córdoba"}, False, id="otra_calle"),
        pytest.param({**COMPLETA, "altura": 1548}, False, id="otra_altura"),
        pytest.param({**COMPLETA, "esquinas": ["Montevideo", "Uruguay"]}, False, id="otra_esquina"),
    ],
)
def test_la_carta_lleva_los_avisos_de_ubicacion_si_esta_queda_igual(
    sugerencia_completa, ubicacion, conserva_avisos
):
    avisos_de_ubicacion = [
        {"codigo": "direccion_no_cierra", "mensaje": "La altura no coincide con la esquina."},
        {"codigo": "cruce_sin_confirmar", "mensaje": "Confirmar si la esquina es Montevideo."},
    ]
    sugerencia_completa["avisos"] = [
        avisos_de_ubicacion[0],
        {"codigo": "dato_descartado", "mensaje": "Se descartó la respuesta a una pregunta."},
        avisos_de_ubicacion[1],
    ]
    ajustes = {"prioridad": "P1"}
    if ubicacion is not None:
        ajustes["ubicacion"] = ubicacion

    carta = derivar(sugerencia_completa, ajustes)

    assert carta["avisos"] == (avisos_de_ubicacion if conserva_avisos else [])


# ---------- El subtipo, el checklist y las instrucciones ----------


def protocolo(subtipo: str) -> dict:
    return next(
        p for p in catalogo.cargar().model_dump(mode="json")["protocolos"] if p["id"] == subtipo
    )


def pendientes(subtipo: str) -> list[dict]:
    return [
        {
            "id": q["id"],
            "pregunta": q["texto"],
            "respondida": False,
            "cita": None,
            "del_operador": False,
        }
        for q in protocolo(subtipo)["preguntas"]
    ]


@pytest.mark.parametrize(
    ("marcas", "cambios"),
    [
        pytest.param([{"id": "SFX-001-Q1", "respondida": True}], {}, id="confirmar_q1"),
        pytest.param([{"id": "SFX-001-Q1", "respondida": False}], {0: False}, id="desmarcar_q1"),
        pytest.param([{"id": "SFX-001-Q2", "respondida": True}], {1: True}, id="marcar_q2"),
        pytest.param(
            [{"id": "SFX-001-Q2", "respondida": True}, {"id": "SFX-001-Q1", "respondida": False}],
            {0: False, 1: True},
            id="marcar_y_desmarcar",
        ),
    ],
)
def test_al_derivar_se_aplican_los_cambios_del_operador_al_checklist(
    sugerencia_completa, marcas, cambios
):
    carta = derivar(sugerencia_completa, {"prioridad": "P1", "checklist": marcas})

    esperado = [pregunta.copy() for pregunta in sugerencia_completa["checklist"]]
    for indice, respondida in cambios.items():
        esperado[indice].update(respondida=respondida, cita=None, del_operador=True)
    assert carta["checklist"] == esperado


def test_si_el_operador_cambia_el_subtipo_puede_marcar_una_pregunta_del_nuevo(sugerencia_completa):
    elegido = {"categoria": "INCENDIO_RESCATE", "subtipo": "SFX-002"}
    marcas = [{"id": "SFX-002-Q1", "respondida": True}]

    carta = derivar(
        sugerencia_completa, {"prioridad": "P1", "tipo_hecho": elegido, "checklist": marcas}
    )

    esperado = pendientes("SFX-002")
    esperado[0].update(respondida=True, del_operador=True)
    assert carta["subtipo"] == {"origen": "operador", "valor": "SFX-002"}
    assert carta["checklist"] == esperado


def test_la_cita_de_una_marca_se_copia_del_turno_indicado(sugerencia_completa):
    turnos = [
        Turno(texto="No hay gas.", hablante="llamante"),
        Turno(texto="Operador: No hay gas. Llamante: No, hay gas.", hablante=None),
    ]
    ajustes = Ajustes.model_validate(
        {
            "prioridad": "P1",
            "checklist": [
                {
                    "id": "SFX-001-Q2",
                    "respondida": True,
                    "cita": {"turno": 1, "texto": "No hay gas"},
                }
            ],
        }
    )

    carta = flujo.derivar(
        "abc", Sugerencia.model_validate(sugerencia_completa), ajustes, AHORA, turnos=turnos
    )

    assert carta.checklist[1].cita == Cita(turno=1, texto="No, hay gas")


@pytest.mark.parametrize(
    ("tipo", "pregunta"),
    [
        pytest.param(None, "SFX-002-Q1", id="de_otro_protocolo"),
        pytest.param(
            {"categoria": "INCENDIO_RESCATE", "subtipo": "SFX-002"},
            "SFX-001-Q1",
            id="del_protocolo_anterior",
        ),
        pytest.param(
            {"categoria": "INCENDIO_RESCATE", "subtipo": None},
            "SFX-001-Q1",
            id="sin_subtipo",
        ),
    ],
)
def test_no_se_puede_marcar_una_pregunta_ajena_al_protocolo_de_la_carta(
    sugerencia_completa, tipo, pregunta
):
    ajustes = {"prioridad": "P1", "checklist": [{"id": pregunta, "respondida": True}]}
    if tipo is not None:
        ajustes["tipo_hecho"] = tipo

    with pytest.raises(flujo.MarcaInvalida) as error:
        derivar(sugerencia_completa, ajustes)

    assert error.value.preguntas == [pregunta]


def test_si_el_operador_elige_el_subtipo_la_carta_lleva_su_protocolo_textual():
    sin_nada = flujo.analizar([Turno(texto=TEXTO_SIN_DATOS)]).model_dump(mode="json")
    ajustes = {
        "prioridad": "P1",
        "ubicacion": {"calle": "Av. Rivadavia", "altura": None, "esquinas": []},
        "tipo_hecho": {"categoria": "INCENDIO_RESCATE", "subtipo": "SFX-025"},
    }

    carta = derivar(sin_nada, ajustes)

    assert carta["tipo_hecho"] == {"origen": "operador", "valor": "INCENDIO_RESCATE"}
    assert carta["subtipo"] == {"origen": "operador", "valor": "SFX-025"}
    assert carta["checklist"] == pendientes("SFX-025")
    assert carta["instrucciones"] == [
        {
            "id": "SFX-025-I1",
            "texto": "NO ARROJAR AGUA COMÚN. El agua puede reaccionar violentamente con el litio. "
            "Evacuar el local inmediatamente y cerrar la persiana para frenar la dispersión del "
            "humo fluorado.",
        }
    ]


def test_si_el_operador_cambia_el_subtipo_no_se_arrastra_nada_del_anterior(sugerencia_completa):
    otro = {"categoria": "INCENDIO_RESCATE", "subtipo": "SFX-002"}

    carta = derivar(sugerencia_completa, {"prioridad": "P3", "tipo_hecho": otro})

    assert carta["tipo_hecho"] == sugerencia_completa["tipo_hecho"]
    assert carta["subtipo"] == {"origen": "operador", "valor": "SFX-002"}
    assert carta["checklist"] == pendientes("SFX-002")
    assert carta["instrucciones"] == protocolo("SFX-002")["instrucciones"]


def test_si_el_operador_cambia_la_categoria_y_no_elige_subtipo_la_carta_queda_sin_protocolo(
    sugerencia_completa,
):
    otra = {"categoria": "ACCIDENTE_VIAL", "subtipo": None}

    carta = derivar(sugerencia_completa, {"prioridad": "P2", "tipo_hecho": otra})

    assert carta["tipo_hecho"] == {"origen": "operador", "valor": "ACCIDENTE_VIAL"}
    assert carta["subtipo"] == {"origen": "operador", "valor": None}
    assert carta["checklist"] == []
    assert carta["instrucciones"] == []


@pytest.mark.parametrize(
    "tipo",
    [
        {"categoria": "ACCIDENTE_VIAL", "subtipo": "SFX-001"},
        {"categoria": "INCENDIO_RESCATE", "subtipo": "SFX-999"},
        {"categoria": "NO_DETERMINADA", "subtipo": "SFX-001"},
    ],
)
def test_un_subtipo_que_no_existe_o_es_de_otra_categoria_no_se_acepta(sugerencia_completa, tipo):
    with pytest.raises(SubtipoInvalido):
        derivar(sugerencia_completa, {"prioridad": "P1", "tipo_hecho": tipo})


def test_los_textos_de_la_carta_salen_del_catalogo_y_no_de_la_sugerencia(sugerencia_completa):
    sugerencia_completa["checklist"].append(
        {"id": "inventada", "pregunta": "¿De qué color es el humo?", "respondida": False}
    )
    sugerencia_completa["instrucciones"] = [
        {"id": "inventada", "texto": "Apagar el fuego con agua."}
    ]

    carta = derivar(sugerencia_completa, {"prioridad": "P1"})

    respondida = {**pendientes("SFX-001")[0], "respondida": True}
    respondida["cita"] = {"turno": 0, "texto": "adentro quedó el cocinero"}
    assert carta["checklist"] == [respondida, *pendientes("SFX-001")[1:]]
    assert carta["instrucciones"] == protocolo("SFX-001")["instrucciones"]


def test_una_respuesta_no_se_conserva_si_la_pregunta_no_es_la_del_catalogo(sugerencia_completa):
    sugerencia_completa["checklist"][0]["pregunta"] = "¿Hay alguien adentro, más o menos?"

    carta = derivar(sugerencia_completa, {"prioridad": "P1"})

    assert carta["checklist"] == pendientes("SFX-001")


def test_una_cita_no_pasa_a_la_pregunta_de_otro_subtipo(sugerencia_completa):
    # La sugerencia es del subtipo 002 pero trae, por error, una respuesta con el identificador de
    # una pregunta del 001. Si el operador elige el 001, esa cita no puede quedar como su respuesta.
    sugerencia_completa["subtipo"]["valor"] = "SFX-002"
    sugerencia_completa["checklist"] = [
        {
            "id": "SFX-001-Q1",
            "pregunta": "¿Hay personas atrapadas en el interior?",
            "respondida": True,
            "cita": {"turno": 0, "texto": "se prendió fuego la campana"},
        }
    ]
    elegido = {"categoria": "INCENDIO_RESCATE", "subtipo": "SFX-001"}

    carta = derivar(sugerencia_completa, {"prioridad": "P1", "tipo_hecho": elegido})

    assert carta["checklist"] == pendientes("SFX-001")


def test_un_identificador_de_subtipo_se_compara_exacto(sugerencia_completa):
    sugerencia_completa["subtipo"]["valor"] = "sfx-001"
    sugerencia_completa["checklist"] = []
    corregido = {"categoria": "INCENDIO_RESCATE", "subtipo": "SFX-001"}

    carta = derivar(sugerencia_completa, {"prioridad": "P1", "tipo_hecho": corregido})

    assert carta["subtipo"] == {"origen": "operador", "valor": "SFX-001"}
    assert carta["checklist"] == pendientes("SFX-001")


# ---------- La sugerencia se ajusta al catálogo antes de guardarse ----------


def ajustar(sugerencia: dict) -> dict:
    ajustada = flujo.ajustar_al_catalogo(Sugerencia.model_validate(sugerencia))
    return ajustada.model_dump(mode="json")


def test_una_sugerencia_que_ya_sigue_al_catalogo_no_cambia(sugerencia_completa):
    assert ajustar(sugerencia_completa) == sugerencia_completa


def test_de_una_sugerencia_se_quita_lo_que_no_es_del_catalogo(sugerencia_completa):
    sugerencia_completa["checklist"] = [
        {"id": "inventada", "pregunta": "¿De qué color es el humo?", "respondida": False}
    ]
    sugerencia_completa["instrucciones"] = [
        {"id": "inventada", "texto": "Apagar el fuego con agua."}
    ]

    ajustada = ajustar(sugerencia_completa)

    assert ajustada["checklist"] == pendientes("SFX-001")
    assert ajustada["instrucciones"] == protocolo("SFX-001")["instrucciones"]


@pytest.mark.parametrize(
    ("categoria", "subtipo"),
    [("INCENDIO_RESCATE", "SFX-999"), ("ACCIDENTE_VIAL", "SFX-001"), ("NO_DETERMINADA", "SFX-001")],
)
def test_un_subtipo_sugerido_que_el_catalogo_no_respalda_queda_como_faltante(
    sugerencia_completa, categoria, subtipo
):
    sugerencia_completa["tipo_hecho"]["valor"] = categoria
    sugerencia_completa["subtipo"]["valor"] = subtipo

    ajustada = ajustar(sugerencia_completa)

    assert ajustada["subtipo"] == {"origen": "falta"}
    assert ajustada["checklist"] == []
    assert ajustada["instrucciones"] == []
    assert ajustada["ubicacion"] == sugerencia_completa["ubicacion"]
    (aviso,) = ajustada["avisos"]
    assert aviso["codigo"] == "dato_descartado"
    assert "subtipo" in aviso["mensaje"]


def test_lo_que_dice_el_operador_no_se_interpreta_con_las_marcas_en_mayusculas():
    turnos = [
        Turno(texto="OPERADOR: Hay un incendio en Av. Corrientes 1540. LLAMANTE: Hola, hola.")
    ]

    sugerencia = flujo.analizar(turnos)

    assert sugerencia.ubicacion.calle.origen == "falta"
    assert sugerencia.ubicacion.altura.origen == "falta"
    assert sugerencia.tipo_hecho.valor == "NO_DETERMINADA"


def test_una_cita_que_solo_esta_en_lo_que_dijo_el_operador_no_respalda_nada():
    turnos = [
        Turno(hablante="operador", texto="¿Es en Av. Corrientes 1540?"),
        Turno(hablante="llamante", texto="No sé, estoy perdido."),
    ]
    calle = {
        "origen": "dicho",
        "valor": "Av. Corrientes",
        "cita": {"turno": 0, "texto": "Corrientes"},
    }
    sugerencia = Sugerencia.model_validate(
        {
            "ubicacion": {"calle": calle, "altura": {"origen": "falta"}, "esquinas": []},
            "tipo_hecho": {"origen": "inferido", "valor": "NO_DETERMINADA", "fuente": "reglas"},
            "prioridad": {"origen": "falta"},
        }
    )

    filtrada = flujo.quitar_lo_que_nadie_dijo(sugerencia, turnos)

    assert filtrada.ubicacion.calle.origen == "falta"
    assert [aviso.codigo for aviso in filtrada.avisos] == ["dato_descartado"]


def test_la_respuesta_anotada_se_cita_en_el_turno_del_llamante_aunque_el_operador_la_repita():
    turnos = [
        Turno(hablante="operador", texto="¿Me dice que adentro quedó el cocinero?"),
        Turno(hablante="llamante", texto=TEXTO),
    ]

    sugerencia = flujo.analizar(turnos)

    respondidas = [item for item in sugerencia.checklist if item.respondida]
    assert [item.cita.turno for item in respondidas] == [1]


def test_lo_que_esta_antes_de_la_primera_marca_no_es_evidencia():
    turnos = [Turno(texto="Incendio en Av. Corrientes 1540. Llamante: Hola, ¿me escuchan?")]

    sugerencia = flujo.analizar(turnos)

    assert sugerencia.ubicacion.calle.origen == "falta"
    assert sugerencia.tipo_hecho.valor == "NO_DETERMINADA"


BILLINGHURST = "Hay un ascensor trabado en Billinghurst 1845."


def _con_entrecalles() -> dict:
    sugerencia = flujo.analizar([Turno(texto=BILLINGHURST)]).model_dump()
    assert [e["fuente"] for e in sugerencia["ubicacion"]["esquinas"]] == ["callejero"] * 2
    return sugerencia


def _ajustes(sugerencia: dict, **cambios: object) -> dict:
    ubicacion = sugerencia["ubicacion"]
    actual = {
        "calle": ubicacion["calle"]["valor"],
        "altura": ubicacion["altura"]["valor"],
        "esquinas": [esquina["valor"] for esquina in ubicacion["esquinas"]],
    }
    return {"ubicacion": {**actual, **cambios}, "prioridad": "P2"}


def test_derivar_conserva_las_entrecalles_si_la_altura_nueva_es_de_la_misma_cuadra():
    sugerencia = _con_entrecalles()

    carta = derivar(sugerencia, _ajustes(sugerencia, altura=1850))

    assert carta["ubicacion"]["altura"] == {"origen": "operador", "valor": 1850}
    assert carta["ubicacion"]["esquinas"] == sugerencia["ubicacion"]["esquinas"]
    assert carta["avisos"] == []


@pytest.mark.parametrize(
    "cambios",
    [
        {"altura": 300},
        {"altura": None},
        {"calle": "Av. Rivadavia"},
        {"calle": "Una calle que no existe"},
    ],
    ids=["otra cuadra", "sin altura", "otra calle", "calle desconocida"],
)
def test_derivar_quita_las_entrecalles_del_callejero_si_son_de_otra_direccion(cambios: dict):
    sugerencia = _con_entrecalles()

    carta = derivar(sugerencia, _ajustes(sugerencia, **cambios))

    assert carta["ubicacion"]["esquinas"] == []
    assert [aviso["codigo"] for aviso in carta["avisos"]] == ["cruce_sin_confirmar"]


def test_derivar_no_quita_las_esquinas_que_dijo_el_llamante_ni_las_del_operador():
    sugerencia = flujo.analizar(
        [Turno(texto="Chocaron en Billinghurst 1845, esquina Arenales.")]
    ).model_dump()
    dicha = sugerencia["ubicacion"]["esquinas"][0]
    assert dicha["origen"] == "dicho"

    ajustes = _ajustes(sugerencia, altura=300, esquinas=[dicha["valor"], "Lavalle"])
    carta = derivar(sugerencia, ajustes)

    assert carta["ubicacion"]["esquinas"] == [dicha, {"origen": "operador", "valor": "Lavalle"}]


def test_las_entrecalles_sugeridas_se_vuelven_a_encontrar_con_la_calle_como_se_muestra():
    comprobadas = 0
    for fila in FILAS_DATASET.values():
        lugar = flujo.analizar([Turno(texto=fila["transcripcion_cruda"])]).ubicacion
        inferidas = {esquina.valor for esquina in lugar.esquinas if isinstance(esquina, Inferido)}
        if inferidas:
            comprobadas += 1
            assert inferidas <= set(ubicacion.entrecalles_de(lugar.calle.valor, lugar.altura.valor))

    assert comprobadas == 12


def test_lo_que_se_dice_despues_del_relato_no_cambia_la_ficha_y_la_sugerencia_lo_avisa():
    relato = [Turno(texto=TEXTO)]
    ampliada = [*relato, Turno(hablante="llamante", texto="Ya salieron todos, no quedó nadie.")]

    sola, con_mas = flujo.analizar(relato), flujo.analizar(ampliada)

    assert [aviso.codigo for aviso in sola.avisos] == []
    assert [aviso.codigo for aviso in con_mas.avisos] == ["ficha_sin_actualizar"]
    assert con_mas.model_dump(exclude={"avisos"}) == sola.model_dump(exclude={"avisos"})


def test_una_respuesta_anotada_repetida_despues_no_cambia_el_checklist_de_la_ficha():
    fragmento = "adentro quedó el cocinero"
    relato = [
        Turno(hablante="operador", texto=f"¿Dijo que {fragmento}?"),
        Turno(hablante="llamante", texto=TEXTO.replace(fragmento, "adentro  quedó el cocinero")),
    ]
    ampliada = [*relato, Turno(hablante="llamante", texto=fragmento)]

    sola, con_mas = flujo.analizar(relato), flujo.analizar(ampliada)

    assert sola.subtipo == con_mas.subtipo
    assert [aviso.codigo for aviso in con_mas.avisos] == ["ficha_sin_actualizar"]
    assert con_mas.checklist == sola.checklist


def test_el_aviso_de_la_ficha_no_viaja_a_la_carta():
    turnos = [Turno(texto=TEXTO), Turno(hablante="llamante", texto="Apúrense.")]
    sugerencia = flujo.analizar(turnos)

    carta = flujo.derivar("llamada-1", sugerencia, Ajustes(), datetime.now(UTC), turnos=turnos)

    assert carta.avisos == []
