export const prioridades = ['P1', 'P2', 'P3', 'P4'] as const

export type Prioridad = (typeof prioridades)[number]

export const nombresTiposHecho = {
  INCENDIO_RESCATE: 'Incendio o rescate',
  EMERGENCIA_MEDICA: 'Emergencia médica',
  ACCIDENTE_VIAL: 'Accidente vial',
  DEFENSA_CIVIL: 'Defensa civil',
  SERVICIOS_PUBLICOS: 'Servicios públicos',
  CONVIVENCIA_SEGURIDAD: 'Convivencia y seguridad',
  NO_DETERMINADA: 'Sin determinar',
}

export type TipoHecho = keyof typeof nombresTiposHecho
export type Cita = { turno: number; texto: string }

export type Dato<Valor> =
  | { origen: 'dicho'; valor: Valor; cita: Cita }
  | { origen: 'inferido'; valor: Valor; fuente: 'callejero' | 'reglas' | 'modelo' | 'dataset' }
  | { origen: 'operador'; valor: Valor | null }
  | { origen: 'falta' }

export function valorDato<Valor>(dato: Dato<Valor>): Valor | null {
  return dato.origen === 'falta' ? null : dato.valor
}

export function textoOrigen(dato: Dato<unknown>): string {
  if (dato.origen === 'inferido') return dato.fuente === 'dataset' ? 'ficha del dataset' : `inferido · ${dato.fuente}`
  if (dato.origen === 'operador') return 'del operador'
  return dato.origen
}

export type Ubicacion = {
  calle: Dato<string>
  altura: Dato<number>
  esquinas: Dato<string>[]
}

type UbicacionAjustada = {
  calle: string
  altura: number | null
  esquinas: string[]
}

type Pregunta = { id: string; pregunta: string; respondida: boolean; cita: Cita | null }
type TextoProtocolo = { id: string; texto: string }

export type Protocolo = {
  id: string
  categoria: Exclude<TipoHecho, 'NO_DETERMINADA'>
  nombre: string
  preguntas: TextoProtocolo[]
  instrucciones: TextoProtocolo[]
}

export type Nivel = { id: Prioridad; nombre: string; definicion: string; senales: string[] }
export type Criterio = { niveles: Nivel[]; reglas: string[] }

export type Catalogo = { protocolos: Protocolo[]; criterio: Criterio }

export type Aviso = {
  codigo: 'sin_calle' | 'falta_altura' | 'calle_ambigua' | 'direccion_no_cierra' | 'cruce_sin_confirmar' | 'dato_descartado'
  mensaje: string
}

type Ficha = {
  ubicacion: Ubicacion
  tipo_hecho: Dato<TipoHecho>
  subtipo: Dato<string>
  prioridad: Dato<Prioridad>
  checklist: Pregunta[]
  instrucciones: TextoProtocolo[]
}

export type Sugerencia = Ficha & { avisos: Aviso[] }

export type Ajustes = {
  ubicacion?: UbicacionAjustada
  tipo_hecho?: { categoria: TipoHecho; subtipo: string | null }
  prioridad?: Prioridad
}

export type Carta = Ficha & {
  llamada_id: string
  derivada_en: string
}

export type Llamada = {
  llamada_id: string
  turnos: { texto: string; hablante: 'operador' | 'llamante' | null }[]
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

export function consultarCatalogo(senal: AbortSignal) {
  return pedir<Catalogo>('/catalogo', senal)
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
