import type { Prioridad } from './api'

export default function PrioridadEtiqueta({ prioridad, nombre }: { prioridad: Prioridad; nombre?: string }) {
  return <span className={`prioridad prioridad-${prioridad.toLowerCase()}`}>{prioridad}{nombre && ` · ${nombre}`}</span>
}
