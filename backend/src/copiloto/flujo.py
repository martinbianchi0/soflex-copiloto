"""La lógica del flujo de una llamada, en funciones comunes. Acá no se importa el grafo."""

from copy import deepcopy

# La misma respuesta para cualquier llamada, hasta que exista el intérprete.
SUGERENCIA_FIJA = {
    "ubicacion": {"calle": "Av. Corrientes", "altura": 1540, "esquinas": ["Montevideo"]},
    "tipo_hecho": "Incendio en comercio gastronómico",
    "prioridad": "P1",
}


def analizar(turnos: list[dict]) -> dict:
    """Devuelve una sugerencia fija de ejemplo, igual para cualquier llamada."""
    return deepcopy(SUGERENCIA_FIJA)


def derivar(llamada_id: str, sugerencia: dict, ajustes: dict) -> dict:
    """Arma la Carta de Llamada: lo sugerido, con lo que el operador cambió por encima."""
    cambiados = [campo for campo, valor in ajustes.items() if valor != sugerencia.get(campo)]
    return {
        "llamada_id": llamada_id,
        **sugerencia,
        **ajustes,
        "ajustado_por_operador": sorted(cambiados),
    }
