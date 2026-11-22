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

## El catálogo de protocolos

- **Las preguntas y las instrucciones salen de un catálogo, no se redactan.** El sistema elige un protocolo por su identificador y muestra su texto tal cual. Una instrucción de pre-arribo mal redactada puede hacer daño: si en "no retirar el casco" de un motociclista se pierde el "no", la instrucción se invierte. Por eso el servicio nunca escribe una.
- **El catálogo se arma del dataset provisto, al arrancar.** Cada fila da un protocolo: el subtipo de hecho, sus tres preguntas obligatorias y su instrucción de pre-arribo. Son 30, uno por subtipo, repartidos en las 6 categorías. Si el archivo no tiene la forma esperada (columnas que faltan o se repiten, filas con celdas de más o de menos, un registro repetido o incompleto), el servicio no arranca.
- **Los identificadores salen del número de registro del dataset** (`SFX-REC-2026-005` da el protocolo `SFX-005`, sus preguntas `SFX-005-Q1` a `Q3` y su instrucción `SFX-005-I1`). Así cada texto que ve el operador se puede rastrear hasta su fila.
- **El protocolo son las preguntas obligatorias.** El dataset trae otras dos columnas de preguntas (las respondidas en el relato y las pendientes), pero describen esa llamada puntual: algunas nombran sus calles o sus detalles, y de las 90 obligatorias sólo 1 aparece también ahí. No son un protocolo reutilizable; sirven de referencia para medir qué preguntas detecta el sistema como respondidas.
- **El tipo de hecho tiene dos niveles: categoría y subtipo.** La categoría siempre está; el subtipo es opcional y es el que trae el protocolo. Un subtipo de otra categoría se rechaza.
- **Sin subtipo no se muestra el protocolo de un subtipo parecido.** El dataset no trae protocolos por categoría: mientras el hecho no tenga subtipo, la carta sale sin checklist ni instrucciones, y lo deja a la vista.
- **El checklist y las instrucciones son siempre los del subtipo, con el texto del catálogo.** Los arma el servicio a partir del identificador, tanto en la sugerencia (antes de guardarla) como en la carta. Un subtipo sugerido que el catálogo no respalda se descarta. Si el operador cambia el subtipo, del anterior no se arrastra nada: ni las respuestas ni sus citas.
- **El contenido no está validado por una autoridad médica ni operativa.** Viene del dataset provisto. En un sistema real, el catálogo lo aprueba y lo versiona quien es responsable del protocolo.

## El criterio de prioridad

- **La prioridad sigue las etiquetas del dataset.** El criterio P1 a P4 se escribió para que cada una de las 30 llamadas provistas caiga en el nivel que trae el dataset. Se comprobó leyendo cada llamada, no con un intérprete.
- **P2 no es "poco grave": es "estable por ahora".** En cuatro llamadas hay una señal fuerte de riesgo y el dataset marca P2: un ascensor trabado con una embarazada, cables de media tensión cortados, conductores sobre los techos en un anegamiento y una fractura expuesta que sangra. El criterio las deja en P2, porque hay personas afectadas pero estables o un peligro que todavía no alcanzó a nadie. La alternativa, subir a P1 ante cualquier señal fuerte, coincidía con el dataset en 26 de 30 (leyendo las 30 llamadas una por una).
- **Lo que sube un P2 a P1 son las respuestas a las preguntas del protocolo:** si el sangrado es a chorros, si alguien encerrado se descompensa. Por eso el checklist y la prioridad se leen juntos.
- **Una sola señal de P1 alcanza, y ante la duda va el nivel más urgente.** Un golpe de alta energía (atropello, choque de moto, vuelco) es P1 aunque la persona esté consciente: así lo marca el dataset.
- **P4 está definido aunque el dataset no trae ninguno:** lo que no es una emergencia y puede esperar. Así la escala cubre también los pedidos que pueden esperar, sin mezclarlos con las emergencias.
- **El criterio es un dato del servicio, no un comentario.** Viaja con el catálogo y el panel lo muestra junto a la prioridad. Es el mismo texto que va a recibir cualquier intérprete que proponga una: el operador y el sistema leen la misma regla.
- **La prioridad es siempre una propuesta.** La confirma el operador, y sin ella no se puede derivar.
- **No está validado por una autoridad operativa.** En un sistema real el criterio lo define y lo versiona quien es responsable del protocolo.

## API

- **Cuatro operaciones:** leer el catálogo y el criterio de prioridad (`GET /api/catalogo`), iniciar una llamada (`POST /api/llamadas`), consultarla (`GET /api/llamadas/{id}`) y derivarla (`POST /api/llamadas/{id}/derivar`). La llamada entra como una lista de turnos.
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
- **`.env` es opcional y no entra a la imagen.** `docker-compose.yml` lo lee si existe y `.dockerignore` lo deja fuera del contexto de construcción.
