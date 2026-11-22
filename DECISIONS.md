# Decisiones

Qué se eligió, por qué y qué se dejó afuera.

## Base del servicio

- **Python 3.13 con FastAPI, y las dependencias con uv.** Para comparar nombres de calles se usa `rapidfuzz`. `uv.lock` se versiona: la imagen y cualquier máquina instalan exactamente las mismas versiones.
- **Tipos estrictos en el backend.** `mypy` en modo estricto, con el complemento de Pydantic, sobre `src/` (los tests quedan fuera). Las pocas excepciones son por firmas de librerías que no contemplan este uso, y cada una dice cuál.
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

- **Cada dato dice de dónde salió.** Hay cuatro orígenes y cada uno tiene su forma: *dicho* (el valor y la cita textual de la llamada), *inferido* (el valor y quién lo completó: el callejero, las reglas, el modelo o la ficha del dataset), *del operador* y *falta*. Un dato "dicho" sin su cita, o uno que "falta" con un valor, no se pueden construir: el esquema no los admite.
- **El sistema no afirma lo que no leyó.** Un dato sin respaldo queda como *falta* y lo completa el operador; no se rellena con un valor probable. Tampoco da por respondida una pregunta del protocolo sin la cita de dónde se respondió.
- **Las citas se verifican contra la llamada.** Una cita vale si sus palabras aparecen enteras y de corrido en el turno que indica, sin distinguir mayúsculas, acentos ni puntuación. Un dato cuya cita no está en lo que dijo el llamante se descarta antes de guardar: queda como *falta*, la sugerencia lo avisa y la llamada sigue su curso. Una llamada guardada con una cita que no está en su turno no es válida al leerla de la base. La verificación dice que la cita existe, no que respalde el valor: por eso el panel muestra la cita, con su turno, al lado de cada dato.
- **El tipo de hecho nunca falta.** Si lo dicho no alcanza para reconocerlo, vale "sin determinar", que es un tipo con el que se puede derivar.
- **Para derivar hacen falta la calle, el tipo de hecho y la prioridad.** Lo demás puede faltar: la carta lo muestra como faltante, no lo esconde.
- **Lo que el operador no cambia conserva su origen y su cita; lo que cambia pasa a ser suyo.** Volver a escribir lo mismo con otras mayúsculas o acentos no es un cambio. Vaciar un dato sugerido queda registrado como una decisión del operador, que no es lo mismo que un dato que nadie dijo.
- **Lo guardado se valida al leerlo.** El grafo guarda datos planos y cada nodo los valida al entrar: de la base no sale una llamada que rompa sus propias reglas. Una llamada guardada con un formato anterior se informa como ilegible: en un prototipo no hay migración de datos.

## El catálogo de protocolos

- **Las preguntas y las instrucciones salen de un catálogo, no se redactan.** El sistema elige un protocolo por su identificador y muestra su texto tal cual. Una instrucción de pre-arribo mal redactada puede hacer daño: si al reescribir "BAJO NINGUNA CIRCUNSTANCIA retire el casco del motociclista" se pierde la negación, la instrucción se invierte. Por eso el servicio nunca escribe una.
- **El catálogo se arma del dataset provisto, al arrancar.** Cada fila da un protocolo: el subtipo de hecho, sus tres preguntas obligatorias y su instrucción de pre-arribo. Son 30, uno por subtipo, repartidos en las 6 categorías. Si el archivo no tiene la forma esperada (columnas que faltan o se repiten, filas con celdas de más o de menos, un registro repetido o incompleto), el servicio no arranca.
- **Los identificadores salen del número de registro del dataset** (`SFX-REC-2026-005` da el protocolo `SFX-005`, sus preguntas `SFX-005-Q1` a `Q3` y su instrucción `SFX-005-I1`). Así cada texto que ve el operador se puede rastrear hasta su fila.
- **El protocolo son las preguntas obligatorias.** El dataset trae otras dos columnas de preguntas (las respondidas en el relato y las pendientes), pero describen esa llamada puntual: algunas nombran sus calles o sus detalles, y de las 90 obligatorias sólo 1 aparece también ahí. No son un protocolo reutilizable y, como casi no nombran las obligatorias, tampoco sirven para medir cuáles responde el relato.
- **El tipo de hecho tiene dos niveles: categoría y subtipo.** La categoría siempre está; el subtipo es opcional y es el que trae el protocolo. Un subtipo de otra categoría se rechaza.
- **Sin subtipo no se muestra el protocolo de un subtipo parecido.** El dataset no trae protocolos por categoría: mientras el hecho no tenga subtipo, la carta sale sin checklist ni instrucciones, y lo deja a la vista.
- **El checklist y las instrucciones son siempre los del subtipo, con el texto del catálogo.** Los arma el servicio a partir del identificador, tanto en la sugerencia (antes de guardarla) como en la carta. Un subtipo sugerido que el catálogo no respalda se descarta, y la sugerencia lo avisa. Si el operador cambia el subtipo, del anterior no se arrastra nada: ni las respuestas ni sus citas.
- **El contenido no está validado por una autoridad médica ni operativa.** Viene del dataset provisto, que es sintético. En un sistema real, el catálogo lo aprueba y lo versiona quien es responsable del protocolo.

## El criterio de prioridad

- **La prioridad sigue las etiquetas del dataset.** El criterio P1 a P4 se escribió para que cada una de las 30 llamadas provistas caiga en el nivel que trae el dataset. Se comprobó leyendo cada llamada, no con un intérprete.
- **P2 no es "poco grave": es "estable por ahora".** En cuatro llamadas hay una señal fuerte de riesgo y el dataset marca P2: un ascensor trabado con una embarazada, cables de media tensión cortados, conductores sobre los techos en un anegamiento y una fractura expuesta que sangra. El criterio las deja en P2, porque hay personas afectadas pero estables o un peligro que todavía no alcanzó a nadie. La alternativa, subir a P1 ante cualquier señal fuerte, coincidía con el dataset en 26 de 30 (leyendo las 30 llamadas una por una).
- **Lo que sube un P2 a P1 son las respuestas a las preguntas del protocolo:** si el sangrado es a chorros, si alguien encerrado se descompensa. Por eso el checklist y la prioridad se leen juntos.
- **Una sola señal de P1 alcanza, y ante la duda va el nivel más urgente.** Un golpe de alta energía (atropello, choque de moto, vuelco) es P1 aunque la persona esté consciente: así lo marca el dataset.
- **P4 está definido aunque el dataset no trae ninguno:** lo que no es una emergencia y puede esperar. Así la escala cubre también los pedidos que pueden esperar, sin mezclarlos con las emergencias.
- **El criterio es un dato del servicio, no un comentario.** Viaja con el catálogo y el panel lo muestra junto a la prioridad. Es el mismo texto que va a recibir cualquier intérprete que proponga una: el operador y el sistema leen la misma regla.
- **La prioridad es siempre una propuesta.** La confirma el operador, y sin ella no se puede derivar.
- **No está validado por una autoridad operativa.** En un sistema real el criterio lo define y lo versiona quien es responsable del protocolo.

## El intérprete por reglas

- **El modo `mock` interpreta con reglas: no devuelve una respuesta fija.** No usa red ni ningún modelo, y para el mismo texto da siempre lo mismo. Lee cualquier llamada, no sólo las del dataset.
- **Sólo cuenta lo que dijo el llamante.** Una transcripción que llega como un solo texto con las marcas "Operador:" y "Llamante:" se parte en turnos antes de guardarla. Lo que dice el operador no es evidencia de lo que pasó: no se cita ni se interpreta. Lo que está antes de la primera marca no se sabe quién lo dijo, y tampoco cuenta. Sin ninguna marca, todo el texto se toma como del llamante.
- **La ubicación sale del texto y se contrasta con el callejero oficial de la Ciudad.** La calle se busca por su nombre, por una parte del nombre ("Velasco" por "Juan Ramírez de Velasco"), por cómo suena ("Escalabrini") y por parecido de escritura. La altura se lee en cifras o en palabras. Los cruces se leen de lo dicho ("casi", "esquina", "entre … y …"). Cada uno lleva su cita. Las entrecalles que nadie dijo y que el callejero da para esa altura salen como *inferido · callejero*.
- **Una calle y su altura tienen que estar en el mismo tramo del llamante.** Un número dicho en otro turno puede ser una edad o la respuesta a otra pregunta: no se junta con la calle, y el intérprete pide la altura. Tampoco son alturas una hora ("19:30"), un piso ("8.º") ni una cantidad ("19 vecinos"); "1.540" sí es 1540.
- **Una palabra común no nombra una calle.** "Pasaje" o "avenida" solas no alcanzan ("Plaza" vale sólo porque es el nombre exacto de una calle), y "perdón" no es "Perón".
- **Una altura redonda es una cuadra, no una puerta.** "Al 800" puede ser el 800 exacto, que cierra la cuadra del 700, o la cuadra del 800 al 899, que es como se dice en la calle. Para un número redondo se consideran las dos.
- **Cuando lo dicho no cierra, el intérprete avisa y no corrige.** Si la altura y los cruces no pueden ser el mismo lugar, deja los dos datos como se dijeron, no agrega entrecalles y le pide al operador que lea la dirección de vuelta. En el dataset pasa con "Scalabrini Ortiz al 800, entre Vera y Velasco": esas dos calles limitan la cuadra del 400. Lo mismo si la altura no existe en esa calle o si el relato trae dos direcciones distintas ("no es Corrientes 1540, es Rivadavia 6300"): no elige por el llamante. También avisa cuando no encuentra una calle, cuando faltan la altura y la esquina, cuando el nombre corresponde a dos calles y cuando el callejero no confirma un cruce. Los avisos no bloquean la derivación.
- **Cuánto acierta la ubicación.** Sobre las 30 llamadas del dataset, con las que se escribieron las reglas, reconoce la calle en 29 (la que falta es una estación de subte, no una dirección) y lee las 17 alturas que el llamante dice; el dataset trae una más, que nadie dijo, y no la propone. Sobre 32 llamadas sintéticas que no son del dataset (típicas, casos límite y texto con ruido de transcripción): de las 28 que nombran una calle de la Ciudad acierta 27; de las 4 que no nombran ninguna, en 3 no propone nada; y acierta 19 de las 22 alturas dichas. Calle y altura quedan bien a la vez en 28 de las 32, y en las otras 4 hay un aviso a la vista. Lo que no resuelve: una autocorrección ("al 2300, no, al 3200"), una altura dicha de a pares ("treinta y dos cincuenta"), un nombre muy deformado y una dirección de fuera de la Ciudad, que puede coincidir con una calle porteña del mismo nombre. Son pocas y sintéticas: el número es optimista y no reemplaza una medición con llamadas reales. Los números salen de `backend/tests/test_medicion.py`.
- **Los nombres de las calles se muestran como están en el callejero, sin tildes** ("Av. Raul Scalabrini Ortiz").
- **Si la llamada es una de las 30 del dataset, el tipo, el subtipo y la prioridad salen de su fila.** Se la reconoce sólo si el llamante dice exactamente lo mismo, letra por letra: con otra puntuación, con otras mayúsculas o con una frase de más ya es un texto nuevo. El origen de esos datos es *ficha del dataset*: es una búsqueda, no una interpretación, y no dice nada de cuánto acierta el sistema.
- **La ubicación no sale de la fila del dataset, ni siquiera para esas 30 llamadas.** Sale siempre de lo que dijo el llamante y del callejero. Las columnas de ubicación del dataset mezclan lo dicho con datos agregados (en 22 de las 30 traen una entrecalle que nadie nombró) y no siempre coinciden con el callejero oficial: de los 17 casos con altura, las entrecalles coinciden en 7. Por eso, para la misma llamada, las esquinas que propone el sistema pueden no ser las del dataset. Copiarlas sería afirmar algo que no se dijo ni se pudo verificar.
- **Qué preguntas del protocolo ya responde cada relato está anotado, con criterio estricto.** Son 7 de las 90, cada una con el fragmento del relato que la responde, en `datos/respuestas_anotadas.json`. Una pregunta cuenta como respondida sólo si el relato da justo lo que pregunta: "tiene casco puesto" responde si se le retiró el casco; "asfalto mojado" no responde si hay agua sobre la vereda. Dar por respondida una pregunta que sigue abierta hace que el operador no la haga; dejar pendiente una ya respondida le cuesta unos segundos. Las columnas del dataset que describen lo respondido no se pueden usar para esto, porque no nombran las preguntas obligatorias.
- **Para un texto nuevo, las reglas proponen sólo la categoría.** Cuentan palabras clave; si ninguna categoría gana con claridad, queda "sin determinar". El subtipo, la prioridad y las respuestas al protocolo necesitan entender el relato: quedan como *falta* y los completa el operador. Una prioridad sacada de contar palabras sería una afirmación sin respaldo en el dato más delicado de la carta.
- **Cuánto acierta la categoría.** Las palabras se eligieron mirando las 30 llamadas del dataset: 27 quedan bien y 3 "sin determinar". Sobre las 32 llamadas nuevas: 23 bien, 8 "sin determinar" y 1 equivocada, una consulta que dice "no me robaron" y queda como convivencia y seguridad. Las reglas cuentan palabras enteras y no entienden una negación ni algo que ya pasó. Como son pocas y sintéticas, el número es optimista.
- **No hay protocolo genérico por categoría.** El dataset trae protocolos por subtipo. Mostrar las preguntas de un subtipo parecido, o redactar unas generales, sería poner delante del operador instrucciones que nadie aprobó para ese caso.

## La revisión del operador

- **El operador marca y desmarca las preguntas del protocolo.** Una pregunta que marca queda como respondida *por el operador* y sin cita: la respuesta la escuchó él, no la leyó el sistema. Si desmarca una que el sistema daba por respondida, queda pendiente y su cita no viaja a la carta. Confirmar lo que el sistema ya había detectado no cambia nada: la respuesta conserva su cita.
- **La carta distingue quién respondió cada pregunta.** Respondida con cita, respondida por el operador, pendiente o desmarcada por el operador: el despachador ve qué se sabe y por quién.
- **La carta lleva los avisos que quedaron sin resolver.** Si el operador deriva sin cambiar la ubicación, los avisos sobre la dirección viajan en la carta como "quedó sin confirmar con el llamante". Si la cambia, esos avisos ya no describen lo que va en la carta y no se copian. Los avisos de datos que el sistema descartó son para el operador y no van a la carta.
- **Hay llamadas de ejemplo para cargar desde el panel:** las 30 del dataset y 4 sintéticas que el servicio no conoce, que muestran lo que hace el modo `mock` con un texto nuevo: una calle dicha como suena y con la altura en palabras, un nombre que corresponde a dos calles y sin altura, una altura que no cierra con la esquina y un reclamo que no es una emergencia.

## API

- **Cinco operaciones:** leer el catálogo y el criterio de prioridad (`GET /api/catalogo`), leer las llamadas de ejemplo (`GET /api/ejemplos`), iniciar una llamada (`POST /api/llamadas`), consultarla (`GET /api/llamadas/{id}`) y derivarla (`POST /api/llamadas/{id}/derivar`). La llamada entra como una lista de turnos, cada uno con quién habla si se sabe.
- **Lo que entra se valida antes de tocar el flujo.** Los esquemas rechazan campos desconocidos, textos vacíos y prioridades fuera de P1–P4. Una llamada puede tener hasta 500 turnos y 50.000 caracteres en total, unas cinco veces una llamada de diez minutos: el tope acota lo que tarda el análisis. La regla que depende de la sugerencia (lo mínimo para derivar) también se comprueba antes de retomar el grafo. En todos los casos la respuesta es 422 y la llamada sigue esperando al operador.
- **El operador manda sólo lo que cambia, con los valores a secas.** Lo que no manda queda como lo sugirió el sistema. La ubicación se manda entera, y el servicio compara cada parte con la sugerida para decidir qué conserva su origen y qué pasa a ser del operador. Del checklist se mandan sólo las preguntas cuya marca cambió; una marca sobre una pregunta que no es del protocolo de la carta se rechaza con 422.
- **Los errores dicen qué pasó:** 404 si la llamada no existe y 409 si ya no está esperando al operador.

## Panel

- **React, Vite y TypeScript, compilado a archivos estáticos que sirve el mismo backend.** Un solo contenedor y un solo puerto, sin CORS.
- **El panel se sirve en `/` y la API es una aplicación aparte montada en `/api`.** Todo lo que empieza con `/api` lo contesta la API, también sus errores: un 404 o un 405 de la API nunca devuelve la página del panel.
- **El identificador de la llamada vive en la URL (`?llamada=…`).** Recargar la página o reiniciar el servicio no pierde una llamada a medias: el panel la vuelve a pedir.
- **El panel manda sólo lo que el operador cambió.** Lo demás queda como lo sugirió el sistema.
- **La transcripción se muestra por turnos, con quién habla, y con cada cita resaltada dentro del texto.** Es la evidencia que respalda cada dato: al enfocar un campo o una pregunta, su cita se destaca en la transcripción.
- **Los avisos del análisis van arriba de la sugerencia y no bloquean la derivación.** Piden confirmar algo con el llamante; decidir sigue siendo del operador. Los que quedan sin resolver se ven también en la carta.
- **El origen que se ve junto a un campo sigue lo que hace el operador.** Al cambiar un valor, la etiqueta pasa a "del operador" y su cita se oculta; si vuelve al valor sugerido, vuelven la etiqueta y la cita.
- **El checklist se marca con casillas, y cada una dice quién la marcó:** la cita del sistema, o "marcada por vos" y "desmarcada por vos".
- **Las instrucciones de pre-arribo van arriba del checklist, con letra más grande:** son lo que el operador lee en voz alta.
- **Sin librería de componentes ni de rutas.** Son tres vistas; el formulario usa los controles del navegador con sus etiquetas, y los avisos se anuncian en una región `aria-live`.

## Empaquetado

- **Una imagen en tres etapas:** Node compila el panel, uv instala el backend y la imagen final lleva sólo Python, el entorno y el panel. Ni Node ni uv quedan en lo que corre.
- **El servicio corre con un usuario sin privilegios**, y la imagen declara su propio chequeo de salud sobre `/api/health`.
- **El estado de las llamadas vive en un volumen.** `docker compose down` y `docker compose up --build` no lo borran.
- **`.env` es opcional y no entra a la imagen.** `docker-compose.yml` lo lee si existe y `.dockerignore` lo deja fuera del contexto de construcción.
