"""Ubicaciones de otras llamadas recibidas cerca en el tiempo."""

import json
import logging
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from copiloto.esquemas import Categoria, Llamada, PosibleDuplicado, texto_plano, valor_de

VENTANA_DE_COINCIDENCIA = timedelta(minutes=30)
TOLERANCIA_DE_ALTURA = 100
MAXIMO_DE_COINCIDENCIAS = 5

_registro = logging.getLogger(__name__)


@dataclass(frozen=True)
class Lugar:
    calle: str
    altura: int | None
    esquinas: tuple[str, ...]

    def mostrar(self) -> str:
        if self.altura is not None:
            return f"{self.calle} {self.altura}"
        if len(self.esquinas) == 2:
            return f"{self.calle} entre {self.esquinas[0]} y {self.esquinas[1]}"
        return " y ".join((self.calle, *self.esquinas))


def coinciden(primero: Lugar, segundo: Lugar) -> bool:
    calle_primera, calle_segunda = texto_plano(primero.calle), texto_plano(segundo.calle)
    esquinas_primera = {texto_plano(esquina) for esquina in primero.esquinas}
    esquinas_segunda = {texto_plano(esquina) for esquina in segundo.esquinas}
    if calle_primera != calle_segunda:
        return calle_primera in esquinas_segunda and calle_segunda in esquinas_primera
    return bool(esquinas_primera & esquinas_segunda) or (
        primero.altura is not None
        and segundo.altura is not None
        and abs(primero.altura - segundo.altura) <= TOLERANCIA_DE_ALTURA
    )


def iso_utc(fecha: datetime) -> str:
    return fecha.astimezone(UTC).isoformat(timespec="microseconds")


class UbicacionesRecientes:
    def __init__(self, ruta: Path) -> None:
        self._conexion = sqlite3.connect(ruta, check_same_thread=False)
        self._candado = threading.Lock()
        with self._conexion:
            # La hora se guarda también cuando el llamante todavía no dio la calle.
            self._conexion.execute("""
                CREATE TABLE IF NOT EXISTS recepciones_llamadas (
                    llamada_id TEXT PRIMARY KEY,
                    recibida_en TEXT NOT NULL
                )
            """)
            self._conexion.execute("""
                CREATE TABLE IF NOT EXISTS ubicaciones_recientes (
                    llamada_id TEXT PRIMARY KEY,
                    recibida_en TEXT NOT NULL,
                    calle TEXT NOT NULL,
                    altura INTEGER,
                    esquinas TEXT NOT NULL,
                    categoria TEXT NOT NULL,
                    derivada INTEGER NOT NULL
                )
            """)
            self._conexion.execute("""
                CREATE INDEX IF NOT EXISTS ubicaciones_por_recepcion
                ON ubicaciones_recientes (recibida_en, llamada_id)
            """)

    def cerrar(self) -> None:
        with self._candado:
            self._conexion.close()

    def actualizar(self, llamada: Llamada, recibida_en: datetime | None = None) -> None:
        llamada_id = llamada.llamada_id
        try:
            with self._candado:
                if recibida_en is not None:
                    with self._conexion:
                        self._conexion.execute(
                            "INSERT INTO recepciones_llamadas VALUES (?, ?) ON CONFLICT DO NOTHING",
                            (llamada_id, iso_utc(recibida_en)),
                        )
                with self._conexion:
                    self._actualizar_ubicacion(llamada)
        except sqlite3.Error:
            _registro.exception("No se pudo actualizar el índice de la llamada %s.", llamada_id)

    def _actualizar_ubicacion(self, llamada: Llamada) -> None:
        ficha = llamada.carta if llamada.carta is not None else llamada.sugerencia
        calle = valor_de(ficha.ubicacion.calle) if ficha is not None else None
        if ficha is None or calle is None:
            self._conexion.execute(
                "DELETE FROM ubicaciones_recientes WHERE llamada_id = ?", (llamada.llamada_id,)
            )
            return

        esquinas = [valor_de(esquina) for esquina in ficha.ubicacion.esquinas]
        self._conexion.execute(
            """
            INSERT INTO ubicaciones_recientes
                (llamada_id, recibida_en, calle, altura, esquinas, categoria, derivada)
            SELECT llamada_id, recibida_en, ?, ?, ?, ?, ?
            FROM recepciones_llamadas WHERE llamada_id = ?
            ON CONFLICT (llamada_id) DO UPDATE SET
                calle = excluded.calle, altura = excluded.altura, esquinas = excluded.esquinas,
                categoria = excluded.categoria, derivada = excluded.derivada
            """,
            (
                calle,
                valor_de(ficha.ubicacion.altura),
                json.dumps(esquinas, ensure_ascii=False),
                valor_de(ficha.tipo_hecho) or Categoria.NO_DETERMINADA,
                int(llamada.carta is not None),
                llamada.llamada_id,
            ),
        )

    def consultar(self, llamada_id: str) -> tuple[datetime | None, list[PosibleDuplicado]]:
        with self._candado:
            fila = self._conexion.execute(
                "SELECT recibida_en, calle, altura, esquinas FROM ubicaciones_recientes "
                "WHERE llamada_id = ?",
                (llamada_id,),
            ).fetchone()
            if fila is None:
                return None, []
            recibida, calle, altura, esquinas = fila
            recibida_en = datetime.fromisoformat(recibida)
            lugar = Lugar(calle, altura, tuple(json.loads(esquinas)))
            posibles = self._buscar(llamada_id, recibida_en, lugar)
        return recibida_en, posibles

    def _buscar(
        self, llamada_id: str, recibida_en: datetime, lugar: Lugar
    ) -> list[PosibleDuplicado]:
        posibles: list[PosibleDuplicado] = []
        filas = self._conexion.execute(
            """
            SELECT llamada_id, recibida_en, calle, altura, esquinas, categoria, derivada
            FROM ubicaciones_recientes
            WHERE recibida_en BETWEEN ? AND ? AND llamada_id != ?
            ORDER BY recibida_en DESC, llamada_id DESC
            """,
            (
                iso_utc(recibida_en - VENTANA_DE_COINCIDENCIA),
                iso_utc(recibida_en + VENTANA_DE_COINCIDENCIA),
                llamada_id,
            ),
        )
        try:
            for otro_id, fecha, calle, altura, esquinas, categoria, derivada in filas:
                otro = Lugar(calle, altura, tuple(json.loads(esquinas)))
                if coinciden(lugar, otro):
                    posibles.append(
                        PosibleDuplicado(
                            llamada_id=otro_id,
                            recibida_en=datetime.fromisoformat(fecha),
                            ubicacion=otro.mostrar(),
                            categoria=Categoria(categoria),
                            derivada=bool(derivada),
                        )
                    )
                    if len(posibles) == MAXIMO_DE_COINCIDENCIAS:
                        break
        finally:
            filas.close()
        return posibles
