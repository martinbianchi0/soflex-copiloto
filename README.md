# Copiloto para Operadores de Sala

Prototipo que asiste al operador de una sala de emergencias: lee la transcripción de una llamada, propone ubicación, tipo de hecho y prioridad, y el operador revisa, ajusta y deriva la Carta de Llamada.

**Estado:** funcionan los dos modos. En `mock`, sin red ni modelo, las reglas proponen la ubicación contrastada con el callejero de la Ciudad, con la cita de lo que dijo el llamante y avisos cuando la dirección no cierra; para un texto nuevo proponen además la categoría por palabras clave, y si la llamada es una de las 30 del dataset, su tipo, su subtipo, su prioridad y las preguntas del protocolo que el relato ya responde. Con un modelo local, la ubicación sigue saliendo de las reglas y el modelo propone el tipo de hecho, la prioridad con la cita que la justifica y posibles respuestas a las preguntas del protocolo, que el operador confirma; y cuando las reglas avisan que la dirección no cierra, el modelo la lee de nuevo y el panel ofrece la que propone si el callejero la confirma. En los dos modos el operador revisa, marca el protocolo, suma lo que el llamante dice después (la sugerencia se actualiza sin pisar lo que ya corrigió) y deriva la carta. Si el llamante dicta una patente o un teléfono, también van a la carta, y si los dicta a medias el panel avisa para pedir que los repita. Si en la media hora anterior o posterior entró otra llamada del mismo lugar, el panel lo avisa. Debajo de la dirección hay un plano chico de la cuadra, dibujado con el callejero y sin red, que sigue lo que el operador corrige. La carta lleva los avisos sobre la dirección que quedaron sin resolver y el historial de la llamada: qué propuso el sistema, cuándo, y qué cambió el operador. El panel trae llamadas de ejemplo para cargar.

## Cómo levantarlo

```bash
docker compose up --build
```

El panel queda en <http://localhost:8000>. Hace falta Docker con Compose 2.24 o más nuevo. No hace falta `.env`: sin configuración corre en modo `mock`, que no usa red ni claves. Las variables que se pueden cambiar están en `.env.example`.

Para probarlo: en "Cargar un ejemplo", elegir *Choque con moto · la llamada llega de a un intercambio*, tildar "Reproducir de a un intercambio" y apretar "Analizar llamada". La llamada llega de a poco: la altura aparece cuando el operador la pregunta. Mientras tanto se puede corregir la sugerencia, elegir el subtipo para marcar su protocolo y derivar; lo que el operador cambia no se pisa.

Al corregir la calle, la altura o una esquina de la sugerencia, el plano de abajo se actualiza: muestra dónde cae la dirección y qué calles la cruzan.

Analizar dos veces el mismo ejemplo muestra, en la segunda, el aviso "Otra llamada del mismo lugar": las dos tienen la misma dirección y entraron con poca diferencia.

El estado de las llamadas se guarda en un volumen de Docker: una llamada que quedó a medias sigue ahí después de `docker compose down` y de volver a levantar.

## Con un modelo local (opcional)

Por defecto corre en modo `mock`. Para que un modelo proponga el tipo de hecho, la prioridad y posibles respuestas a las preguntas del protocolo:

1. Instalar [Ollama](https://ollama.com) en la máquina (0.30 o más nuevo) y bajar el modelo, de 3,3 GB:
   ```bash
   ollama pull qwen3.5:4b-q4_K_M
   ```
2. Crear un `.env` junto a `docker-compose.yml` con `LLM_PROVIDER=ollama` (las demás variables están en `.env.example`).
3. Levantar con `docker compose up --build`. El encabezado del panel muestra el modo y el modelo.

El modelo no viene con el repositorio: lo baja Ollama, y se distribuye con licencia Apache 2.0 (`ollama show qwen3.5:4b-q4_K_M --license`).

Ollama corre en la máquina y no en el contenedor, para usar la aceleración del equipo; el contenedor lo alcanza en `host.docker.internal:11434`. En Linux, Ollama escucha sólo en `127.0.0.1` y el contenedor no lo alcanza: hay que hacerlo escuchar también en la interfaz de Docker (por ejemplo, `OLLAMA_HOST=0.0.0.0`, con un firewall que no lo exponga a la red, porque la API de Ollama no pide autenticación). En Linux no se probó.

La ubicación la siguen leyendo las reglas y aparece al instante; lo que propone el modelo llega unos segundos después. Si el modelo no responde, el panel lo avisa, con el motivo, y muestra la sugerencia de las reglas. Si lo que falla es sólo la confirmación del subtipo, quedan el tipo y la prioridad del modelo, sin subtipo y con un aviso.

Cuando las reglas avisan que la dirección no cierra, el modelo la lee de nuevo. Para probarlo: cargar el ejemplo *Auto con humo · el llamante se corrige al dar la dirección* y analizar. Las reglas se quedan con la primera altura que dijo el llamante y avisan que no cierra con la esquina; arriba de la sugerencia aparece "El modelo leyó otra dirección", con la altura corregida y el botón "Usar esta dirección". Usarla es una corrección del operador: la carta lleva lo que cambió con ese origen.

## Trazas de cada llamada (opcional)

Para revisar qué se le pidió al modelo en una llamada, qué contestó y cuánto tardó, el servicio puede mandar trazas a un [Langfuse](https://langfuse.com) propio. Está apagado por defecto: sin las dos claves, el servicio no importa la librería ni abre ninguna conexión.

1. Tener un Langfuse corriendo (se levanta aparte, con el `docker compose` de su documentación) y un proyecto con su par de claves.
2. En el `.env`: `LANGFUSE_PUBLIC_KEY` y `LANGFUSE_SECRET_KEY`. Por defecto apunta al de la misma máquina, en el puerto 3000; se cambia con `LANGFUSE_BASE_URL`.
3. Levantar con `docker compose up --build`.

Cada llamada queda como una sesión, con una traza por operación (el alta, cada turno sumado, el análisis del modelo y la derivación) y, dentro del análisis, cada pedido al modelo con su entrada, su salida y su duración.

Las trazas llevan el texto de la llamada y lo que entra y sale de cada paso: la sugerencia, los datos dictados y la carta. Por eso se piensa para un Langfuse propio, y este repositorio no levanta uno.

## Cuánto acierta

Medido con `backend/herramientas/evaluar.py`, que pasa cada llamada por el mismo camino que el panel. Corridas repetidas dieron las mismas propuestas en las 62 llamadas (el pedido va con temperatura 0 y semilla fija), en una Mac M5 con 16 GB y Ollama 0.40.16. Los tiempos son los de la corrida guardada, hecha con el equipo a batería y en modo de bajo consumo. Cambian mucho con el estado del equipo: otras tres corridas de las mismas 62 llamadas, con el equipo enchufado, dieron medianas de entre 5 y 15 segundos (la más rápida, antes de sumar la segunda lectura de la dirección), con las mismas propuestas de tipo, prioridad y protocolo. El detalle por llamada está en `evaluacion/`, y la lectura de estos números, en `DECISIONS.md`.

| | Reglas (`mock`), 32 nuevas | Modelo, 32 nuevas | Modelo, 30 del dataset |
|---|---|---|---|
| Categoría correcta | 23 (8 sin determinar, 1 mal) | 30 | 29 |
| Prioridad igual a la esperada | no propone | 26 (31 admisibles) | 21 |
| Prioridad menos urgente que lo admisible | — | 0 | 2 |
| Prioridad más urgente que lo admisible | — | 1 | 7 |
| Llamadas P1 detectadas | — | 9 de 9 | 12 de 14 |
| Subtipo correcto | — | — | 26 (4 sin subtipo, 0 equivocados) |
| Subtipo propuesto sin que el catálogo tenga uno | — | 4 | — |
| Preguntas del protocolo: posibles respuestas | — | — | señala 4 de las 7 anotadas, y otras 15 |
| Tiempo por llamada (mediana y percentil 95) | menos de 0,1 s | 7,7 y 13,9 s | 11,6 y 18,2 s |

Las 30 llamadas del dataset son las mismas con las que se escribieron el criterio de prioridad y el catálogo: sus números son optimistas. Las otras 32 son sintéticas y no son del dataset: son pocas, y no reemplazan una medición con llamadas reales. En modo `mock`, las 30 del dataset se reconocen por su texto y traen su ficha, así que ahí el tipo y la prioridad no se miden. La ubicación que se sugiere sale siempre de las reglas: reconoce la calle en 27 de las 28 llamadas nuevas que nombran una (`backend/tests/test_medicion.py`). En 16 de las 62 las reglas dan un aviso sobre la dirección y el análisis suma el pedido de la segunda lectura, que ofreció otra dirección en 2.

```bash
(cd backend && uv run python herramientas/evaluar.py --proveedor ollama --salida ../evaluacion/modelo.json)
```

### La segunda lectura de la dirección

`backend/herramientas/evaluar_direccion.py` pasa 48 llamadas sintéticas con direcciones difíciles (`backend/tests/datos/direcciones_dificiles.json`: el llamante se corrige, dice la altura en palabras, nombra dos direcciones, se contradice) por el mismo camino que el panel. En 29 las reglas dan un aviso de los que piden la segunda lectura (detalle en `evaluacion/direccion-modelo.json`):

| | Modelo, 29 llamadas con aviso |
|---|---|
| No había otra dirección que proponer (las reglas ya tenían la dicha, o lo dicho no alcanza para dar una): el modelo no propuso ninguna | 16 de 16 |
| Las reglas no la tenían: el modelo propuso la calle y la altura dichas | 7 de 13 |
| Las reglas no la tenían: el modelo propuso otra cosa | 1 de 13 (la calle y las esquinas dichas, sin la altura) |
| Las reglas no la tenían: el modelo no propuso nada | 5 de 13 |
| Tiempo que agrega el pedido (mediana y percentil 95) | 4,9 y 7,3 s |
| Tiempo del análisis completo con aviso (mediana y percentil 95) | 11,7 y 17,1 s (sin aviso, 6,6 s de mediana) |

Son pocas llamadas y sintéticas: con una corrección menos, la segunda lectura no habría alcanzado el mínimo que se fijó para sumarla (corregir la mitad). La lectura está en `DECISIONS.md`.

```bash
(cd backend && uv run python herramientas/evaluar_direccion.py --proveedor ollama --salida ../evaluacion/direccion-modelo.json)
```

### A medida que llega la llamada

`backend/herramientas/evaluar_turnos.py` pasa 14 guiones de 3 a 5 intercambios (49 en total, en `backend/tests/datos/guiones.json`) por el camino que usa el panel al sumar un turno, y después de cada intercambio compara lo propuesto con lo que hasta ahí se dijo (detalle en `evaluacion/turnos-reglas.json` y `evaluacion/turnos-modelo.json`):

| | Reglas (`mock`), 49 intercambios | Modelo, 49 intercambios |
|---|---|---|
| Calle y altura iguales a lo dicho hasta ahí (o el cruce, si no se dijo altura) | 49 | 49 |
| Guiones en los que la dirección queda completa cuando se termina de decir | 14 de 14 | 14 de 14 |
| Categoría correcta | 29 (11 sin determinar, 6 mal; en 3 todavía no se podía saber y no propuso ninguna) | 46 (ninguna mal; en 3 todavía no se podía saber y no propuso ninguna) |
| Subtipo correcto | no propone | 39 (ninguno equivocado; en 8 todavía no se podía saber y no propuso ninguno; en 2 lo propuso antes de que se pudiera saber) |
| Respuestas ya dadas que señala como posibles, contando cada pregunta en cada intercambio en que el subtipo es el esperado | — | 46 de 49, y 7 que no se habían respondido |
| Tiempo por intercambio (mediana y percentil 95) | menos de 0,1 s | 12,3 y 15,7 s |

Cada intercambio vuelve a analizar la llamada entera, así que tarda más a medida que la llamada crece: 9,3 segundos de mediana en el primero y 15,5 del cuarto en adelante (en las mismas condiciones que la corrida de arriba).

```bash
(cd backend && uv run python herramientas/evaluar_turnos.py --proveedor mock --salida ../evaluacion/turnos-reglas.json)
(cd backend && uv run python herramientas/evaluar_turnos.py --proveedor ollama --salida ../evaluacion/turnos-modelo.json)
```

## Supuestos

- **La llamada llega como texto**, en una lista de turnos con quién habla si se sabe. No hay audio ni reconocimiento de voz.
- **Las llamadas son de la Ciudad de Buenos Aires.** Toda dirección se lee contra su callejero: una calle de otro lugar que se llama igual que una porteña se toma por la porteña. El operador tiene la cita al lado y la corrige.
- **El operador no despacha.** Revisa, completa y deriva la Carta de Llamada; el despacho es de otro sistema.
- **Todo lo que propone el sistema es una sugerencia.** El operador revisa la ubicación, el tipo, la prioridad y las preguntas respondidas, y al derivar los da por buenos; la carta dice de dónde salió cada dato.
- **El catálogo tiene los 30 protocolos del dataset provisto, uno por subtipo.** Un hecho que no está ahí queda con su categoría y sin protocolo. Su contenido no está validado por una autoridad médica ni operativa.
- **Un puesto, un proceso.** No hay usuarios ni permisos, y la garantía de que una llamada se deriva una sola vez vale con un solo proceso del servicio.

## Qué haría con más tiempo

- **Medir con llamadas reales.** Todo lo medido son llamadas sintéticas (las 62 de la primera tabla, 48 con direcciones difíciles y 14 guiones), con un modelo y en una máquina. Faltan transcripciones de reconocimiento de voz, con ruido, interrupciones y varios turnos, y repetir la medición con otros modelos.
- **Un piso para la prioridad.** El modelo dejó en P2 dos llamadas P1 del dataset. Señales de riesgo de vida detectadas por reglas podrían subir la propuesta sin depender del modelo; hay que validarlas con casos reales para no subir todo.
- **Que la segunda lectura de la dirección no demore el resto.** Hoy es un pedido más, detrás de los otros, y el formulario espera a todos: con aviso, el análisis pasa de unos 7 segundos a unos 12. Podría llegar aparte, después de mostrar el tipo y la prioridad.
- **Que el modelo consulte el callejero por su cuenta.** Hoy recibe los datos del callejero en el pedido. En una prueba exploratoria, de una corrida, dejarlo hacer hasta tres consultas corrigió más direcciones, pero tardó unos 16 segundos por llamada.
- **Protocolos para lo que el catálogo no cubre**, definidos por quien tiene la autoridad para hacerlo.
- **Patentes y teléfonos como llegan de un reconocimiento de voz:** deletreados o con los números en palabras. Hoy se leen escritos con letras y cifras.
- **Entrada en vivo.** Hoy el operador escribe cada turno, o se reproduce un ejemplo. La API ya recibe los turnos de a uno; falta conectarle un transcriptor que los mande a medida que se habla.
- **Que el aviso de otra llamada del mismo lugar compare por distancia.** Hoy compara calle, altura y esquinas, y una calle que el operador escribió con otro nombre no coincide.
- **Coordenadas en la carta, además de calle y altura**, y contraste con el servicio de direcciones de la Ciudad cuando hay red. Hoy el punto del plano se interpola sobre la cuadra y no se guarda.
- **Tests del panel en un navegador real.** Los que hay corren sobre un DOM simulado, con la API simulada a partir de respuestas reales del servicio: prueban qué pide y qué muestra el panel, no la disposición ni los estilos.
- **Probarlo con un lector de pantalla y en Linux.** Los anuncios y el foco están pensados para un lector de pantalla, pero no se probaron con uno, y el modo con modelo no se probó en Linux.

## Cómo está armado

- `backend/`: la API (FastAPI) y el recorrido de la llamada (LangGraph, con el estado en SQLite).
- `frontend/`: el panel (React, Vite y TypeScript). Se compila y lo sirve el mismo backend.
- `backend/src/copiloto/datos/`: el dataset provisto, con 30 llamadas sintéticas. De ahí sale el catálogo de protocolos: preguntas e instrucciones de pre-arribo por subtipo de hecho. Su contenido no está validado por una autoridad médica ni operativa.
- `backend/src/copiloto/ubicacion.py` y `callejero.py`: la lectura de la dirección y su contraste con el callejero.
- `backend/src/copiloto/dictados.py`: la patente y el teléfono que dicta el llamante.
- `backend/src/copiloto/duplicados.py`: el aviso de otra llamada reciente del mismo lugar.
- `backend/src/copiloto/mapa.py`: el plano de la cuadra para confirmar la dirección.
- `backend/src/copiloto/interprete.py` y `modelo.py`: los pedidos al modelo local y la verificación de lo que devuelve.
- `backend/src/copiloto/trazas.py`: las trazas opcionales en Langfuse.
- `backend/src/copiloto/segunda_lectura.py`: la dirección que propone el modelo cuando las reglas avisan, comprobada contra el callejero.
- `backend/herramientas/evaluar.py`, `evaluar_turnos.py`, `evaluar_direccion.py` y `evaluacion/`: las mediciones de lo que propone el servicio y su detalle por llamada.
- `backend/herramientas/capturar_respuestas.py` y `frontend/src/pruebas/respuestas/`: respuestas reales del servicio, que usan los tests del panel.
- `backend/src/copiloto/criterio.py`: el criterio de prioridad P1 a P4, que el panel muestra junto a la prioridad.
- `DECISIONS.md`: qué se eligió y por qué.

## Datos de terceros

`backend/src/copiloto/datos/callejero_caba.csv` es una versión reducida del [Callejero de la Ciudad de Buenos Aires](https://data.buenosaires.gob.ar/dataset/calles), publicado por el Gobierno de la Ciudad en BA Data con licencia [CC BY 2.5 AR](https://creativecommons.org/licenses/by/2.5/ar/). Se usó el archivo `callejero.csv` descargado el 20/11/2026. Se quitaron la geometría y las columnas que no se usan; se descartaron los tramos sin nombre oficial y los de tipos que no sirven para dar una dirección; y a cada tramo se le agregó un número de nodo por extremo, agrupando los extremos que quedan a unos 3 m. La reducción se regenera con `backend/herramientas/reducir_callejero.py`. `callejero_nodos.csv`, en la misma carpeta, sale del mismo archivo y de la misma corrida (opción `--nodos`): de la geometría conserva sólo la longitud y la latitud de cada nodo, la del primer extremo de su grupo, con seis decimales.

`backend/tests/datos/puntos_de_referencia.json` trae 13 direcciones con la coordenada que devolvió el normalizador de direcciones de [USIG](https://usig.buenosaires.gob.ar/apis/) (Gobierno de la Ciudad), consultado el 22/11/2026. Se usan sólo en un test, para comprobar el punto del plano; el test no consulta el servicio.

## Desarrollo

```bash
(cd backend && uv run pytest)                               # tests del backend
(cd backend && uv run ruff check . && uv run mypy src)      # estilo y tipos
(cd backend && uv run uvicorn copiloto.main:app --reload)   # la API, en el puerto 8000
(cd frontend && pnpm install && pnpm dev)                   # en otra terminal: el panel con recarga, apuntando a esa API
(cd frontend && pnpm test && pnpm lint)                     # tests y estilo del panel
```

Fuera de Docker la configuración también sale de variables de entorno. Para usar el `.env` de la raíz: `(cd backend && uv run --env-file ../.env uvicorn copiloto.main:app)`.
