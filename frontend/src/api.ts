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
export type DictadoQuitado = { tipo: 'patente' | 'telefono'; valor: string }
export type DatoDictado = DictadoQuitado & { cita: Cita }

export function idDictado({ tipo, valor }: DictadoQuitado) {
  return `dictado-${tipo}-${encodeURIComponent(valor)}`
}

export type Dato<Valor> =
  | { origen: 'dicho'; valor: Valor; cita: Cita }
  | { origen: 'inferido'; valor: Valor; fuente: 'callejero' | 'reglas' | 'modelo' | 'dataset'; cita?: Cita | null }
  | { origen: 'operador'; valor: Valor | null }
  | { origen: 'falta' }

export function valorDato<Valor>(dato: Dato<Valor>): Valor | null {
  return dato.origen === 'falta' ? null : dato.valor
}

export function citaDato(dato: Dato<unknown>) {
  return dato.origen === 'dicho' || dato.origen === 'inferido' ? dato.cita : undefined
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

export type Pregunta = { id: string; pregunta: string; respondida: boolean; cita: Cita | null; del_operador: boolean }
type TextoProtocolo = { id: string; texto: string }

export type Ejemplo = { id: string; titulo: string; origen: 'dataset' | 'nueva'; texto: string; turnos: Turno[] }

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
  codigo: 'sin_calle' | 'falta_altura' | 'calle_ambigua' | 'direccion_no_cierra' | 'cruce_sin_confirmar' | 'ficha_sin_actualizar' | 'prioridad_cambiada' | 'dato_descartado' | 'modelo_no_disponible' | 'dictado_incompleto'
  mensaje: string
}

type Ficha = {
  ubicacion: Ubicacion
  tipo_hecho: Dato<TipoHecho>
  subtipo: Dato<string>
  prioridad: Dato<Prioridad>
  checklist: Pregunta[]
  instrucciones: TextoProtocolo[]
  avisos: Aviso[]
  datos_dictados: DatoDictado[]
}

export type DireccionAlternativa = UbicacionAjustada

export type Sugerencia = Ficha & { direccion_alternativa: DireccionAlternativa | null }

export type MarcaChecklist = Pick<Pregunta, 'id' | 'respondida'> & { cita: Cita | null }

export type Ajustes = {
  ubicacion?: UbicacionAjustada
  tipo_hecho?: { categoria: TipoHecho; subtipo: string | null }
  prioridad?: Prioridad
  checklist?: MarcaChecklist[]
  dictados_quitados?: DictadoQuitado[]
}

export type Carta = Ficha & {
  llamada_id: string
  derivada_en: string
}

type EventoHistorial = {
  tipo: 'recibida' | 'sugerencia_reglas' | 'sugerencia_modelo' | 'turno_agregado' | 'ajustes_operador' | 'derivada'
  cuando: string
  detalle: string
}

export type ValorCambio = Dato<string | number> | Dato<string>[] | { respondida: boolean; propuesta: boolean }

export type Historial = {
  llamada_id: string
  eventos: EventoHistorial[]
  cambios: { campo: string; sugerido: ValorCambio; final: ValorCambio }[]
}

export type Turno = { texto: string; hablante: 'operador' | 'llamante' | null }
export type Proveedor = 'mock' | 'ollama'

export type Llamada = {
  llamada_id: string
  turnos: Turno[]
  proveedor: Proveedor
} & (
  | { estado: 'en_proceso'; sugerencia: Sugerencia | null; carta: null }
  | { estado: 'analizando'; sugerencia: Sugerencia; carta: null }
  | { estado: 'esperando_operador'; sugerencia: Sugerencia; carta: null }
  | { estado: 'derivada'; sugerencia: Sugerencia; carta: Carta }
)

export type PosibleDuplicado = {
  llamada_id: string
  recibida_en: string
  ubicacion: string
  categoria: TipoHecho
  derivada: boolean
}

export type Duplicados = { llamada_id: string; recibida_en: string | null; posibles: PosibleDuplicado[] }

export type PedidoDePlano = {
  calle: string
  altura: number | null
  esquinas: string[]
}

export type CuadraDelPlano = {
  nombre: string
  x1: number
  y1: number
  x2: number
  y2: number
  principal: boolean
}

export type Plano = { radio_m: number; exacto: boolean; leyenda: string; cuadras: CuadraDelPlano[] }

export type Salud = { status: string; llm_provider: Proveedor; modelo: string | null; proveedores: Proveedor[] }
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

async function pedir<Respuesta>(ruta: string, senal: AbortSignal, opciones?: RequestInit): Promise<Respuesta> {
  const respuesta = await fetch(`/api${ruta}`, { ...opciones, signal: senal })

  if (!respuesta.ok) {
    const cuerpo = await respuesta.json().catch(() => null) as { detail?: ErrorApi['detalle'] } | null
    throw new ErrorApi(respuesta.status, cuerpo?.detail)
  }

  return respuesta.json()
}

function enviar<Respuesta>(ruta: string, senal: AbortSignal, datos: object) {
  return pedir<Respuesta>(ruta, senal, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(datos),
  })
}

export function consultarSalud(senal: AbortSignal) {
  return pedir<Salud>('/health', senal)
}

export function consultarCatalogo(senal: AbortSignal) {
  return pedir<Catalogo>('/catalogo', senal)
}

export function consultarEjemplos(senal: AbortSignal) {
  return pedir<Ejemplo[]>('/ejemplos', senal)
}

export function consultarPlano(pedido: PedidoDePlano, senal: AbortSignal) {
  return enviar<Plano>('/mapa', senal, pedido)
}

export function crearLlamada(texto: string, senal: AbortSignal, proveedor?: Proveedor) {
  return enviar<Llamada>('/llamadas', senal, { turnos: [{ texto }], proveedor })
}

export function consultarLlamada(identificador: string, senal: AbortSignal) {
  return pedir<Llamada>(`/llamadas/${encodeURIComponent(identificador)}`, senal)
}

export function consultarDuplicados(identificador: string, senal: AbortSignal) {
  return pedir<Duplicados>(`/llamadas/${encodeURIComponent(identificador)}/duplicados`, senal, { cache: 'no-store' })
}

export function consultarHistorial(identificador: string, senal: AbortSignal) {
  return pedir<Historial>(`/llamadas/${encodeURIComponent(identificador)}/historial`, senal)
}

export function analizarLlamada(identificador: string, senal: AbortSignal) {
  return pedir<Llamada>(`/llamadas/${encodeURIComponent(identificador)}/analisis`, senal, { method: 'POST' })
}

export function sumarTurno(identificador: string, turno: Turno, senal: AbortSignal) {
  return enviar<Llamada>(`/llamadas/${encodeURIComponent(identificador)}/turnos`, senal, { turno })
}

export function derivarLlamada(identificador: string, ajustes: Ajustes, senal: AbortSignal) {
  return enviar<Llamada>(`/llamadas/${encodeURIComponent(identificador)}/derivar`, senal, { ajustes })
}
