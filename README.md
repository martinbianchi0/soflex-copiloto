# Copiloto para Operadores de Sala

Prototipo que asiste al operador de una sala de emergencias: lee la transcripción de una llamada, propone ubicación, tipo de hecho y prioridad, y el operador revisa, ajusta y deriva la Carta de Llamada.

**Estado:** funciona el modo `mock`, que interpreta la llamada con reglas, sin red ni modelo. Propone la ubicación contrastada con el callejero de la Ciudad, con la cita de lo que dijo el llamante y avisos cuando la dirección no cierra. Si la llamada es una de las 30 del dataset, propone además el tipo, el subtipo, la prioridad y las preguntas del protocolo que el relato ya responde. Para un texto nuevo propone la categoría por palabras clave y el resto lo completa el operador. Todavía no hay un modo con modelo: `LLM_PROVIDER` acepta sólo `mock`.

## Cómo levantarlo

```bash
docker compose up --build
```

El panel queda en <http://localhost:8000>. Hace falta Docker con Compose 2.24 o más nuevo. No hace falta `.env`: sin configuración corre en modo `mock`, que no usa red ni claves. Las variables que se pueden cambiar están en `.env.example`.

El estado de las llamadas se guarda en un volumen de Docker: una llamada que quedó a medias sigue ahí después de `docker compose down` y de volver a levantar.

## Cómo está armado

- `backend/`: la API (FastAPI) y el recorrido de la llamada (LangGraph, con el estado en SQLite).
- `frontend/`: el panel (React, Vite y TypeScript). Se compila y lo sirve el mismo backend.
- `backend/src/copiloto/datos/`: el dataset provisto. De ahí sale el catálogo de protocolos: preguntas e instrucciones de pre-arribo por subtipo de hecho. Su contenido no está validado por una autoridad médica ni operativa.
- `backend/src/copiloto/ubicacion.py` y `callejero.py`: la lectura de la dirección y su contraste con el callejero.
- `backend/src/copiloto/criterio.py`: el criterio de prioridad P1 a P4, que el panel muestra junto a la prioridad.
- `DECISIONS.md`: qué se eligió y por qué.

## Datos de terceros

`backend/src/copiloto/datos/callejero_caba.csv` es una versión reducida del [Callejero de la Ciudad de Buenos Aires](https://data.buenosaires.gob.ar/dataset/calles), publicado por el Gobierno de la Ciudad en BA Data con licencia [CC BY 2.5 AR](https://creativecommons.org/licenses/by/2.5/ar/). Se usó el archivo `callejero.csv` descargado el 20/11/2026. Se quitaron la geometría y las columnas que no se usan; se descartaron los tramos sin nombre oficial y los de tipos que no sirven para dar una dirección; y a cada tramo se le agregó un número de nodo por extremo, agrupando los extremos que quedan a unos 3 m. La reducción se regenera con `backend/herramientas/reducir_callejero.py`.

## Desarrollo

```bash
cd backend && uv run pytest          # tests del backend
cd backend && uv run uvicorn copiloto.main:app --reload
cd frontend && pnpm install && pnpm dev   # panel con recarga, apuntando a la API local
```

Fuera de Docker la configuración también sale de variables de entorno. Para usar un `.env`: `uv run --env-file ../.env uvicorn copiloto.main:app`.
