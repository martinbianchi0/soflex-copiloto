import { describe, expect, test } from 'vitest'
import { oraciones } from './oraciones'
import { respuestas } from './pruebas/respuestas'

const instrucciones = respuestas.catalogo.protocolos.flatMap((protocolo) => protocolo.instrucciones)

describe('Las oraciones de una instrucción', () => {
  test('el catálogo trae instrucciones para probar', () => {
    expect(instrucciones.length).toBeGreaterThanOrEqual(30)
  })

  test.each(instrucciones)('$id: unidas con un espacio dan el texto del catálogo, letra por letra', ({ texto }) => {
    expect(oraciones(texto).join(' ')).toBe(texto)
  })

  test('cada oración queda en su renglón', () => {
    expect(oraciones('NO ARROJAR AGUA COMÚN. El agua puede reaccionar violentamente con el litio. Evacuar el local.'))
      .toEqual(['NO ARROJAR AGUA COMÚN.', 'El agua puede reaccionar violentamente con el litio.', 'Evacuar el local.'])
  })

  test('un punto dentro de un número o antes de una minúscula no corta', () => {
    expect(oraciones('Elevarle las piernas 30.5 cm. Aflojarle la ropa (aprox. dos dedos).'))
      .toEqual(['Elevarle las piernas 30.5 cm.', 'Aflojarle la ropa (aprox. dos dedos).'])
  })

  test('una oración que abre con signo de pregunta o de exclamación también se separa', () => {
    expect(oraciones('No lo mueva. ¿Respira? ¡Aléjese!')).toEqual(['No lo mueva.', '¿Respira?', '¡Aléjese!'])
  })

  test('un texto de una sola oración queda entero', () => {
    expect(oraciones('No aproximarse al borde del cráter.')).toEqual(['No aproximarse al borde del cráter.'])
  })
})
