"""Lo que la API acepta. Un pedido que no cumple el esquema se rechaza antes de llegar al flujo."""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Texto = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
TextoDeTurno = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20_000)
]


class Esquema(BaseModel):
    # Un campo que no existe es un error del cliente, no algo para ignorar en silencio.
    model_config = ConfigDict(extra="forbid")


class Turno(Esquema):
    texto: TextoDeTurno


class NuevaLlamada(Esquema):
    turnos: list[Turno] = Field(min_length=1, max_length=500)


class Ubicacion(Esquema):
    """Se manda entera: reemplaza a la sugerida, no se mezcla con ella."""

    calle: Texto
    # Sin altura se manda `null`. Tiene que ser un entero de verdad: ni "1540" ni 1540.0.
    altura: int | None = Field(ge=1, le=99_999, strict=True)
    esquinas: list[Texto] = Field(max_length=2)

    @model_validator(mode="after")
    def calle_y_esquinas_distintas(self) -> Self:
        nombres = [nombre.casefold() for nombre in (self.calle, *self.esquinas)]
        if len(set(nombres)) != len(nombres):
            raise ValueError("La calle y las esquinas tienen que ser distintas entre sí.")
        return self


class Ajustes(Esquema):
    """Lo que el operador cambia de la sugerencia. Lo que no manda queda como estaba."""

    ubicacion: Ubicacion | None = None
    tipo_hecho: Texto | None = None
    prioridad: Literal["P1", "P2", "P3", "P4"] | None = None

    @model_validator(mode="after")
    def sin_campos_vacios(self) -> Self:
        # Omitir un campo y mandarlo en `null` no son lo mismo: lo segundo es un pedido mal armado.
        vacios = sorted(campo for campo in self.model_fields_set if getattr(self, campo) is None)
        if vacios:
            raise ValueError(f"Para dejar un campo como está, no lo mandes: {', '.join(vacios)}.")
        return self

    def cambios(self) -> dict:
        return self.model_dump(exclude_unset=True)


class Derivacion(Esquema):
    ajustes: Ajustes = Field(default_factory=Ajustes)
