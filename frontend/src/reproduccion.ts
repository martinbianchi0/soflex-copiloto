import type { Turno } from './api'

const marcas = { operador: 'Operador: ', llamante: 'Llamante: ' }

export function separarIntercambios(turnos: Turno[]): string[] {
  const intercambios: string[] = []
  let tramos: string[] = []
  for (const { texto, hablante } of turnos) {
    tramos.push(hablante ? marcas[hablante] + texto : texto)
    if (hablante === 'llamante') {
      intercambios.push(tramos.join(' '))
      tramos = []
    }
  }
  if (tramos.length) intercambios.push(tramos.join(' '))
  return intercambios
}

export function calcularPausa(intercambio: string): number {
  return Math.min(6_000, 2_000 + 40 * Array.from(intercambio).length)
}
