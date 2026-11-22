# Copiloto para Operadores de Sala

Prototipo que asiste al operador de una sala de emergencias: lee la transcripción de una llamada, propone ubicación, tipo de hecho y prioridad, y el operador revisa, ajusta y deriva la Carta de Llamada.

**Estado:** funcionan los dos modos. En `mock`, sin red ni modelo, las reglas proponen la ubicación contrastada con el callejero de la Ciudad, con la cita de lo que dijo el llamante y avisos cuando la dirección no cierra; para un texto nuevo proponen además la categoría por palabras clave, y si la llamada es una de las 30 del dataset, su tipo, su subtipo, su prioridad y las preguntas del protocolo que el relato ya responde. Con un modelo local, la ubicación sigue saliendo de las reglas y el modelo propone el tipo de hecho, la prioridad con la cita que la justifica y las preguntas ya respondidas. En los dos modos el operador revisa, marca el protocolo y deriva la carta, que lleva lo que quedó sin confirmar con el llamante. El panel trae llamadas de ejemplo para cargar.

## Cómo levantarlo

```bash
docker compose up --build
```

El panel queda en <http://localhost:8000>. Hace falta Docker con Compose 2.24 o más nuevo. No hace falta `.env`: sin configuración corre en modo `mock`, que no usa red ni claves. Las variables que se pueden cambiar están en `.env.example`.

El estado de las llamadas se guarda en un volumen de Docker: una llamada que quedó a medias sigue ahí después de `docker compose down` y de volver a levantar.

## Con un modelo local (opcional)

Por defecto corre en modo `mock`. Para que un modelo proponga el tipo de hecho, la prioridad y las preguntas del protocolo que el llamante ya respondió:

1. Instalar [Ollama](https://ollama.com) en la máquina (0.30 o más nuevo) y bajar el modelo, de 3,3 GB:
   ```bash
   ollama pull qwen3.5:4b-q4_K_M
   ```
2. Crear un `.env` junto a `docker-compose.yml` con `LLM_PROVIDER=ollama` (las demás variables están en `.env.example`).
3. Levantar con `docker compose up --build`. El encabezado del panel muestra el modo y el modelo.

Ollama corre en la máquina y no en el contenedor, para usar la aceleración del equipo; el contenedor lo alcanza en `host.docker.internal:11434`. En Linux, Ollama escucha sólo en `127.0.0.1` y el contenedor no lo alcanza: hay que hacerlo escuchar también en la interfaz de Docker (por ejemplo, `OLLAMA_HOST=0.0.0.0`, con un firewall que no lo exponga a la red, porque la API de Ollama no pide autenticación). En Linux no se probó.

La ubicación la siguen leyendo las reglas y aparece al instante; lo que propone el modelo llega unos segundos después. Si el modelo no responde, el panel lo avisa, con el motivo, y muestra la sugerencia de las reglas.

## Cuánto acierta

Medido con `backend/herramientas/evaluar.py`, que pasa cada llamada por el mismo camino que el panel. Una corrida, en una Mac M5 con 16 GB y Ollama 0.40.16. El detalle por llamada está en `evaluacion/`, y la lectura de estos números, en `DECISIONS.md`.

| | Reglas (`mock`), 32 nuevas | Modelo, 32 nuevas | Modelo, 30 del dataset |
|---|---|---|---|
| Categoría correcta | 23 (8 sin determinar, 1 mal) | 30 | 29 |
| Prioridad igual a la esperada | no propone | 26 (31 admisibles) | 21 |
| Prioridad menos urgente que lo admisible | — | 0 | 2 |
| Prioridad más urgente que lo admisible | — | 1 | 7 |
| Llamadas P1 detectadas | — | 9 de 9 | 12 de 14 |
| Subtipo correcto | — | — | 26 (4 sin subtipo, 0 equivocados) |
| Subtipo propuesto sin que el catálogo tenga uno | — | 4 | — |
| Preguntas del protocolo ya respondidas | — | — | detecta 4 de las 7 anotadas; marca otras 15 |
| Tiempo por llamada (mediana y percentil 95) | menos de 0,1 s | 5,2 y 10,0 s | 7,2 y 11,5 s |

Las 30 llamadas del dataset son las mismas con las que se escribieron el criterio de prioridad y el catálogo: sus números son un techo. Las otras 32 son sintéticas y no son del dataset: son pocas, y no reemplazan una medición con llamadas reales. En modo `mock`, las 30 del dataset se reconocen por su texto y traen su ficha, así que ahí no hay nada que medir. La ubicación sale siempre de las reglas: reconoce la calle en 27 de las 28 llamadas nuevas que nombran una (`backend/tests/test_medicion.py`).

```bash
cd backend && uv run python herramientas/evaluar.py --proveedor ollama --salida ../evaluacion/modelo.json
```

## Cómo está armado

- `backend/`: la API (FastAPI) y el recorrido de la llamada (LangGraph, con el estado en SQLite).
- `frontend/`: el panel (React, Vite y TypeScript). Se compila y lo sirve el mismo backend.
- `backend/src/copiloto/datos/`: el dataset provisto, con 30 llamadas sintéticas. De ahí sale el catálogo de protocolos: preguntas e instrucciones de pre-arribo por subtipo de hecho. Su contenido no está validado por una autoridad médica ni operativa.
- `backend/src/copiloto/ubicacion.py` y `callejero.py`: la lectura de la dirección y su contraste con el callejero.
- `backend/src/copiloto/interprete.py` y `modelo.py`: los pedidos al modelo local y la verificación de lo que devuelve.
- `backend/herramientas/evaluar.py` y `evaluacion/`: la medición de lo que propone el servicio y su detalle por llamada.
- `backend/src/copiloto/criterio.py`: el criterio de prioridad P1 a P4, que el panel muestra junto a la prioridad.
- `DECISIONS.md`: qué se eligió y por qué.

## Datos de terceros

`backend/src/copiloto/datos/callejero_caba.csv` es una versión reducida del [Callejero de la Ciudad de Buenos Aires](https://data.buenosaires.gob.ar/dataset/calles), publicado por el Gobierno de la Ciudad en BA Data con licencia [CC BY 2.5 AR](https://creativecommons.org/licenses/by/2.5/ar/). Se usó el archivo `callejero.csv` descargado el 20/11/2026. Se quitaron la geometría y las columnas que no se usan; se descartaron los tramos sin nombre oficial y los de tipos que no sirven para dar una dirección; y a cada tramo se le agregó un número de nodo por extremo, agrupando los extremos que quedan a unos 3 m. La reducción se regenera con `backend/herramientas/reducir_callejero.py`.

## Desarrollo

```bash
cd backend && uv run pytest          # tests del backend
cd backend && uv run ruff check . && uv run mypy src   # estilo y tipos
cd backend && uv run uvicorn copiloto.main:app --reload
cd frontend && pnpm install && pnpm dev   # panel con recarga, apuntando a la API local
```

Fuera de Docker la configuración también sale de variables de entorno. Para usar un `.env`: `uv run --env-file ../.env uvicorn copiloto.main:app`.
