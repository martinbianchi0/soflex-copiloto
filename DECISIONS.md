# Decisiones

Qué se eligió, por qué y qué se dejó afuera.

## Base del servicio

- **Python 3.13 con FastAPI, y las dependencias con uv.** `uv.lock` se versiona: la imagen y cualquier máquina instalan exactamente las mismas versiones.
- **La configuración sale sólo de variables de entorno.** `.env` no se versiona; `.env.example` documenta las variables que se pueden cambiar. Sin `.env`, el servicio levanta en modo `mock`, que no necesita red ni claves.
- **Un valor inválido corta el arranque.** `LLM_PROVIDER` se valida al iniciar: un proveedor mal escrito falla en el momento, no en la primera llamada.

## Orquestación

- **El recorrido de una llamada es un grafo de LangGraph con tres nodos:** analizar, esperar al operador y derivar. La espera es un `interrupt`: el grafo se detiene, guarda su estado y sigue cuando el operador confirma.
- **El estado de cada llamada se guarda en SQLite después de cada nodo.** Una llamada que quedó esperando al operador se puede derivar aunque el servicio se haya reiniciado.
- **La lógica no depende del grafo.** Los nodos sólo llaman a funciones de `flujo.py`, que no importa LangGraph: se prueban solas y el orquestador se puede cambiar sin tocarlas.
- **El nodo de la espera no hace nada más que esperar.** Al retomar, LangGraph lo corre de nuevo desde el principio. Por eso la Carta de Llamada se arma en un nodo aparte, que sólo se repite si el servicio se corta antes de guardarla.
- **Una llamada se deriva una sola vez.** Un segundo intento se rechaza y la carta ya derivada no cambia. Lo garantiza un candado dentro del proceso, y el servicio corre con un solo proceso: para escalar a varios haría falta un bloqueo en la base.
- **Cada nodo se guarda en disco antes de que empiece el siguiente.** Si el servicio se corta después de que el operador confirmó, la carta se termina de armar con esos ajustes la próxima vez que se consulta la llamada.

## Los datos y su origen

- **Cada dato dice de dónde salió.** Hay cuatro orígenes y cada uno tiene su forma: *dicho* (el valor y la cita textual de la llamada), *inferido* (el valor y quién lo completó: el callejero, las reglas o el modelo), *del operador* y *falta*. Un dato "dicho" sin su cita, o uno que "falta" con un valor, no se pueden construir: el esquema no los admite.
- **El sistema no afirma lo que no leyó.** Un dato sin respaldo queda como *falta* y lo completa el operador; no se rellena con un valor probable.
- **Las citas se verifican contra la llamada.** Una cita vale si sus palabras aparecen enteras y de corrido en el turno que indica, sin distinguir mayúsculas, acentos ni puntuación. Una sugerencia con una cita que no está en la llamada no se guarda, y una llamada así no es válida al leerla de la base. La verificación dice que la cita existe, no que respalde el valor: por eso el panel muestra la cita al lado de cada dato.
- **El tipo de hecho nunca falta.** Si lo dicho no alcanza para reconocerlo, vale "sin determinar", que es un tipo con el que se puede derivar.
- **Para derivar hacen falta la calle, el tipo de hecho y la prioridad.** Lo demás puede faltar: la carta lo muestra como faltante, no lo esconde.
- **Lo que el operador no cambia conserva su origen y su cita; lo que cambia pasa a ser suyo.** Volver a escribir lo mismo con otras mayúsculas o acentos no es un cambio. Vaciar un dato sugerido queda registrado como una decisión del operador, que no es lo mismo que un dato que nadie dijo.
- **Lo guardado se valida al leerlo.** El grafo guarda datos planos y cada nodo los valida al entrar: de la base no sale una llamada que rompa sus propias reglas. Una llamada guardada con un formato anterior se informa como ilegible: en un prototipo no hay migración de datos.

## API

- **Tres operaciones:** iniciar una llamada (`POST /api/llamadas`), consultarla (`GET /api/llamadas/{id}`) y derivarla (`POST /api/llamadas/{id}/derivar`). La llamada entra como una lista de turnos.
- **Lo que entra se valida antes de tocar el flujo.** Los esquemas rechazan campos desconocidos, textos vacíos y prioridades fuera de P1–P4. La regla que depende de la sugerencia (lo mínimo para derivar) también se comprueba antes de retomar el grafo. En los dos casos la respuesta es 422 y la llamada sigue esperando al operador.
- **El operador manda sólo lo que cambia, con los valores a secas.** Lo que no manda queda como lo sugirió el sistema. La ubicación se manda entera, y el servicio compara cada parte con la sugerida para decidir qué conserva su origen y qué pasa a ser del operador.
- **Los errores dicen qué pasó:** 404 si la llamada no existe y 409 si ya no está esperando al operador.

## Panel

- **React, Vite y TypeScript, compilado a archivos estáticos que sirve el mismo backend.** Un solo contenedor y un solo puerto, sin CORS.
- **El panel se sirve en `/` y la API es una aplicación aparte montada en `/api`.** Todo lo que empieza con `/api` lo contesta la API, también sus errores: un 404 o un 405 de la API nunca devuelve la página del panel.
- **El identificador de la llamada vive en la URL (`?llamada=…`).** Recargar la página o reiniciar el servicio no pierde una llamada a medias: el panel la vuelve a pedir.
- **El panel manda sólo lo que el operador cambió.** Lo demás queda como lo sugirió el sistema.
- **Sin librería de componentes ni de rutas.** Son tres vistas; el formulario usa los controles del navegador con sus etiquetas, y los avisos se anuncian en una región `aria-live`.

## Empaquetado

- **Una imagen en tres etapas:** Node compila el panel, uv instala el backend y la imagen final lleva sólo Python, el entorno y el panel. Ni Node ni uv quedan en lo que corre.
- **El servicio corre con un usuario sin privilegios**, y la imagen declara su propio chequeo de salud sobre `/api/health`.
- **El estado de las llamadas vive en un volumen.** `docker compose down` y `docker compose up --build` no lo borran.
- **`.env` es opcional y no entra a la imagen.** `compose.yaml` lo lee si existe y `.dockerignore` lo deja fuera del contexto de construcción.
