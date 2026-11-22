# Decisiones

Qué se eligió, por qué y qué se dejó afuera.

## Base del servicio

- **Python 3.13 con FastAPI, y las dependencias con uv.** `uv.lock` se versiona: cualquier máquina instala exactamente las mismas versiones.
- **La configuración sale sólo de variables de entorno.** `.env` no se versiona; `.env.example` documenta las variables que se pueden cambiar. Sin `.env`, el servicio levanta en modo `mock`, que no necesita red ni claves.
- **Un valor inválido corta el arranque.** `LLM_PROVIDER` se valida al iniciar: un proveedor mal escrito falla en el momento, no en la primera llamada.

## Orquestación

- **El recorrido de una llamada es un grafo de LangGraph con tres nodos:** analizar, esperar al operador y derivar. La espera es un `interrupt`: el grafo se detiene, guarda su estado y sigue cuando el operador confirma.
- **El estado de cada llamada se guarda en SQLite después de cada nodo.** Una llamada que quedó esperando al operador se puede derivar aunque el servicio se haya reiniciado.
- **La lógica no depende del grafo.** Los nodos sólo llaman a funciones de `flujo.py`, que no importa LangGraph: se prueban solas y el orquestador se puede cambiar sin tocarlas.
- **El nodo de la espera no hace nada más que esperar.** Al retomar, LangGraph lo corre de nuevo desde el principio. Por eso la Carta de Llamada se arma en un nodo aparte, que sólo se repite si el servicio se corta antes de guardarla.
- **Una llamada se deriva una sola vez.** Un segundo intento se rechaza y la carta ya derivada no cambia. Lo garantiza un candado dentro del proceso, y el servicio corre con un solo proceso: para escalar a varios haría falta un bloqueo en la base.
- **Cada nodo se guarda en disco antes de que empiece el siguiente.** Si el servicio se corta después de que el operador confirmó, la carta se termina de armar con esos ajustes la próxima vez que se consulta la llamada.

## API

- **Tres operaciones:** iniciar una llamada (`POST /api/llamadas`), consultarla (`GET /api/llamadas/{id}`) y derivarla (`POST /api/llamadas/{id}/derivar`). La llamada entra como una lista de turnos.
- **Lo que entra se valida antes de tocar el flujo.** Los esquemas rechazan campos desconocidos, textos vacíos y prioridades fuera de P1–P4. Un ajuste inválido devuelve 422 y la llamada sigue esperando al operador.
- **El operador manda sólo lo que cambia.** Lo que no manda queda como lo sugirió el sistema, y la carta registra qué campos ajustó. La ubicación es la excepción: se manda entera y reemplaza a la sugerida, para que no quede una dirección armada con partes de dos.
- **Los errores dicen qué pasó:** 404 si la llamada no existe y 409 si ya no está esperando al operador.
