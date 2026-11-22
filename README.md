# Copiloto para Operadores de Sala

Prototipo que asiste al operador de una sala de emergencias: lee la transcripción de una llamada, propone ubicación, tipo de hecho y prioridad, y el operador revisa, ajusta y deriva la Carta de Llamada.

**Estado:** el análisis todavía no interpreta el texto. Deja la ubicación y la prioridad como faltantes y el tipo de hecho como "sin determinar", y lo completa el operador. Todavía no hay intérprete por reglas ni con modelo. Al elegir el subtipo del hecho, el panel muestra las preguntas del protocolo y las instrucciones de pre-arribo de ese subtipo.

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
- `backend/src/copiloto/criterio.py`: el criterio de prioridad P1 a P4, que el panel muestra junto a la prioridad.
- `DECISIONS.md`: qué se eligió y por qué.

## Desarrollo

```bash
cd backend && uv run pytest          # tests del backend
cd backend && uv run uvicorn copiloto.main:app --reload
cd frontend && pnpm install && pnpm dev   # panel con recarga, apuntando a la API local
```

Fuera de Docker la configuración también sale de variables de entorno. Para usar un `.env`: `uv run --env-file ../.env uvicorn copiloto.main:app`.
