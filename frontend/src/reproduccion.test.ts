import { describe, expect, test } from 'vitest'
import type { Turno } from './api'
import { respuestas } from './pruebas/respuestas'
import { calcularPausa, separarIntercambios } from './reproduccion'

const ejemplo = respuestas.ejemplos.find(({ id }) => id === 'nueva-5')
if (!ejemplo) throw new Error('Falta el ejemplo nueva-5')

const primerIntercambio = 'Operador: 911, ¿cuál es su emergencia? Llamante: Chocaron un auto y una moto en Av. San Juan, el de la moto quedó tirado en la calle.'

function sinHablante(turno: Turno) {
  const variante = structuredClone(turno)
  variante.hablante = null
  return variante
}

describe('Los intercambios de la llamada', () => {
  test('cada pregunta del operador se reúne con la respuesta del llamante, con sus marcas', () => {
    expect(separarIntercambios(ejemplo.turnos)).toEqual([
      primerIntercambio,
      'Operador: ¿A qué altura? Llamante: Al 2100.',
      'Operador: ¿El motociclista respira? ¿Le responde? Llamante: Sí, respira y me contesta, pero dice que le duele mucho la pierna.',
      'Operador: No le saquen el casco. ¿Lo tiene puesto? Llamante: Sí, lo tiene puesto, no se lo tocamos.',
      'Operador: ¿Ve nafta o aceite en el asfalto? Llamante: Sí, hay una mancha de nafta debajo de la moto.',
    ])
  })

  test('un turno sin hablante se agrega al intercambio sin marca', () => {
    const [pregunta, respuesta] = ejemplo.turnos
    expect(separarIntercambios([sinHablante(pregunta), respuesta])).toEqual([
      '911, ¿cuál es su emergencia? Llamante: Chocaron un auto y una moto en Av. San Juan, el de la moto quedó tirado en la calle.',
    ])
  })

  test('la última pregunta sin respuesta queda como un intercambio propio', () => {
    expect(separarIntercambios(ejemplo.turnos.slice(0, 3))).toEqual([
      primerIntercambio, 'Operador: ¿A qué altura?',
    ])
  })

  test('una llamada sin turnos no tiene intercambios', () => {
    expect(separarIntercambios([])).toEqual([])
  })

  test('dos turnos seguidos del llamante quedan en intercambios distintos', () => {
    expect(separarIntercambios([ejemplo.turnos[1], ejemplo.turnos[3]])).toEqual([
      'Llamante: Chocaron un auto y una moto en Av. San Juan, el de la moto quedó tirado en la calle.',
      'Llamante: Al 2100.',
    ])
  })
})

describe('La pausa entre intercambios', () => {
  test('la pausa de un texto vacío es de dos segundos', () => {
    expect(calcularPausa('')).toBe(2_000)
  })

  test('la pausa suma cuarenta milisegundos por cada carácter', () => {
    expect(calcularPausa(ejemplo.turnos[3].texto)).toBe(2_320)
  })

  test('la pausa de un texto largo tiene un tope de seis segundos', () => {
    expect(calcularPausa(ejemplo.texto)).toBe(6_000)
  })

  test('un emoji suma cuarenta milisegundos como cualquier otro carácter', () => {
    expect(calcularPausa('🚒')).toBe(2_040)
  })
})
