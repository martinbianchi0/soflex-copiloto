export const prioridades = ['P1', 'P2', 'P3', 'P4'] as const

export type Prioridad = (typeof prioridades)[number]

export type Ubicacion = {
  calle: string
  altura: number | null
  esquinas: string[]
}

export type Sugerencia = {
  ubicacion: Ubicacion
  tipo_hecho: string
  prioridad: Prioridad
}

export type Ajustes = Partial<Sugerencia>

export type Carta = Sugerencia & {
  llamada_id: string
  ajustado_por_operador: (keyof Sugerencia)[]
}

export type Llamada = {
  llamada_id: string
  turnos: { texto: string }[]
} & (
  | { estado: 'en_proceso'; sugerencia: Sugerencia | null; carta: null }
  | { estado: 'esperando_operador'; sugerencia: Sugerencia; carta: null }
  | { estado: 'derivada'; sugerencia: Sugerencia; carta: Carta }
)

export type Salud = { status: string; llm_provider: string }
export type DetalleValidacion = { loc: (string | number)[]; msg: string }

export class ErrorApi extends Error {
  estado: number
  detalle?: string | DetalleValidacion[]

  constructor(estado: number, detalle?: string | DetalleValidacion[]) {
    super(typeof detalle === 'string' ? detalle : `HTTP ${estado}`)
    this.estado = estado
    this.detalle = detalle
  }
}

async function pedir<Respuesta>(ruta: string, senal: AbortSignal, datos?: object): Promise<Respuesta> {
  const respuesta = await fetch(`/api${ruta}`, datos ? {
    signal: senal,
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(datos),
  } : { signal: senal })

  if (!respuesta.ok) {
    const cuerpo = await respuesta.json().catch(() => null) as { detail?: ErrorApi['detalle'] } | null
    throw new ErrorApi(respuesta.status, cuerpo?.detail)
  }

  return respuesta.json()
}

export function consultarSalud(senal: AbortSignal) {
  return pedir<Salud>('/health', senal)
}

export function crearLlamada(texto: string, senal: AbortSignal) {
  return pedir<Llamada>('/llamadas', senal, { turnos: [{ texto }] })
}

export function consultarLlamada(identificador: string, senal: AbortSignal) {
  return pedir<Llamada>(`/llamadas/${encodeURIComponent(identificador)}`, senal)
}

export function derivarLlamada(identificador: string, ajustes: Ajustes, senal: AbortSignal) {
  return pedir<Llamada>(`/llamadas/${encodeURIComponent(identificador)}/derivar`, senal, { ajustes })
}
