import type { DetalleValidacion } from './api'

const nombresCampos: Record<string, string> = {
  ajustes: 'Ajustes',
  ubicacion: 'Ubicación',
  calle: 'Calle',
  altura: 'Altura',
  esquinas: 'Esquinas',
  tipo_hecho: 'Tipo de hecho',
  categoria: 'Tipo de hecho',
  subtipo: 'Subtipo',
  prioridad: 'Prioridad',
  checklist: 'Preguntas del protocolo',
  turnos: 'Turnos',
  texto: 'Texto de la transcripción',
  llamada_id: 'Identificador de la llamada',
}

export function nombrarCampo(loc: DetalleValidacion['loc']) {
  const ruta = loc[0] === 'body' ? loc.slice(1) : loc
  const campo = ruta.findLast((parte) => typeof parte === 'string')
  if (campo && Object.hasOwn(nombresCampos, campo)) return nombresCampos[campo]
  return ruta.join('.') || 'Solicitud'
}

export function campoSugerencia({ loc }: DetalleValidacion) {
  if (loc.includes('checklist')) return 'checklist'
  if (loc.includes('esquinas')) return 'esquinas'
  const campo = loc.findLast((parte) => typeof parte === 'string')
  switch (campo) {
    case 'ubicacion': return 'calle'
    case 'categoria': return 'tipo_hecho'
    case 'calle':
    case 'altura':
    case 'tipo_hecho':
    case 'subtipo':
    case 'prioridad': return campo
  }
}
