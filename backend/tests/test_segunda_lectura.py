import hashlib
import json
from pathlib import Path

from copiloto import segunda_lectura, ubicacion
from copiloto.esquemas import Turno
from copiloto.turnos import separar_hablantes

CASOS = Path(__file__).parent / "datos" / "direcciones_dificiles.json"


def test_texto_del_sistema():
    """El pedido con el que se midió evaluacion/direccion-modelo.json.

    Si cambia, hay que volver a medir.
    """
    huella = hashlib.sha256(segunda_lectura.SISTEMA_CON_DATOS.encode("utf-8")).hexdigest()
    assert huella == "301b0bfa22aeb387f233aee5952bd081f294221286d30e9ec32450705cd86cc2"


def test_pedido_completo_para_una_llamada():
    casos = json.loads(CASOS.read_text(encoding="utf-8"))
    texto = next(caso["texto"] for caso in casos if caso["id"] == "D02")
    turnos = separar_hablantes([Turno(texto=texto)])
    assert (
        segunda_lectura.pedido(turnos, ubicacion.interpretar(turnos))
        == """Transcripción:
Operador: nueve once dónde es la emergencia Llamante: en gurruchaga 1236 mandá bomberos por favor no perdón es aráoz 1236 entre masón y cabrera se prendió fuego el toldo del patio ya salimos por delante pero el humo está entrando al departamento de arriba y no sabemos si hay alguien

Lo que leyeron las reglas: calle: Gurruchaga; altura: 1236; esquinas: Jose A. Cabrera.
Avisos de las reglas:
- Se mencionaron Gurruchaga 1236 y Araoz 1236. Confirmá con el llamante cuál es la dirección.
- Confirmá si «masón» cruza Gurruchaga.
- La altura 1236 no coincide con Jose A. Cabrera. Leele la dirección de vuelta al llamante.

Datos del callejero:
- La cuadra de Gurruchaga 1236 queda entre Av. Cordoba y Cnel. Niceto Vega.
- Gurruchaga cruza Jose A. Cabrera a la altura 1399-1402."""
    )
