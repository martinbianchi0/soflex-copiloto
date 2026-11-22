import { describe, expect, test } from 'vitest'
import { respuestas } from './pruebas/respuestas'
import { ubicarRotulos } from './rotulosDelPlano'

const { cuadras, radio_m } = respuestas.plano
const tamanos = [[382, 204], [446, 185]] as const

function dibujar(ancho: number, alto: number, tramos = cuadras) {
  const escala = Math.max(ancho, alto) / (2 * radio_m)
  return { escala, rotulos: ubicarRotulos(tramos, escala, ancho, alto, 100 * escala) }
}

function cuadraHorizontal(nombre: string, norte: number, desde = -100, hasta = 100) {
  const cuadra = cuadras.find((tramo) => tramo.nombre === nombre)
  if (!cuadra) throw new Error(`Falta la cuadra de ${nombre}`)
  return Object.assign(structuredClone(cuadra), { x1: desde, y1: norte, x2: hasta, y2: norte })
}

describe('Los rótulos del plano de Av. Corrientes 1540', () => {
  test('en 382 × 204 se rotulan las calles vecinas que entran, en orden', () => {
    const { rotulos } = dibujar(382, 204)
    expect(rotulos.map(({ nombre }) => nombre)).toEqual([
      'Av. Corrientes', 'Parana', 'Montevideo', 'Lavalle', 'Sarmiento', 'Av. Uruguay', 'Uruguay',
    ])
  })

  test('en 446 × 185 se rotulan las calles vecinas que entran, en orden', () => {
    const { rotulos } = dibujar(446, 185)
    expect(rotulos.map(({ nombre }) => nombre)).toEqual([
      'Av. Corrientes', 'Parana', 'Montevideo', 'Av. Uruguay', 'Uruguay', 'Rodriguez Peña',
    ])
  })

  test('una calle con varias cuadras recibe a lo sumo un rótulo', () => {
    const { rotulos } = dibujar(382, 204)
    const nombres = rotulos.map(({ nombre }) => nombre)
    expect(new Set(nombres).size).toBe(nombres.length)
  })

  test.each(tamanos)('ningún rótulo queda cabeza abajo en %i × %i', (ancho, alto) => {
    const { rotulos } = dibujar(ancho, alto)
    expect(rotulos.every(({ angulo }) => angulo >= -90 && angulo <= 90)).toBe(true)
  })

  test.each(tamanos)('todos los rótulos quedan dentro del dibujo en %i × %i', (ancho, alto) => {
    const { escala, rotulos } = dibujar(ancho, alto)
    expect(rotulos.every(({ x, y }) => Math.abs(x) * escala <= ancho / 2 && Math.abs(y) * escala <= alto / 2)).toBe(true)
  })

})

describe('Qué calles reciben rótulo', () => {
  test('la calle pedida queda primera y marcada como principal aunque otra esté más cerca', () => {
    const cercana = cuadraHorizontal('Parana', 40)
    const principal = cuadraHorizontal('Av. Corrientes', -80)
    const { rotulos } = dibujar(382, 204, [cercana, principal])
    expect(rotulos.map(({ nombre, principal }) => ({ nombre, principal }))).toEqual([
      { nombre: 'Av. Corrientes', principal: true }, { nombre: 'Parana', principal: false },
    ])
  })

  test('una cuadra al norte queda arriba del centro del dibujo', () => {
    const { rotulos } = dibujar(382, 204, [cuadraHorizontal('Parana', 40)])
    expect(rotulos.map(({ y }) => y)).toEqual([-40])
  })

  test('una cuadra que pasa entera a 200 m al norte no recibe rótulo', () => {
    expect(dibujar(382, 204, [cuadraHorizontal('Parana', 200)]).rotulos).toEqual([])
  })

  test('entre dos calles paralelas separadas por 5 m se rotula sólo la más cercana', () => {
    const lejana = cuadraHorizontal('Montevideo', 45, -15, 15)
    const cercana = cuadraHorizontal('Parana', 40, -15, 15)
    const { rotulos } = dibujar(382, 204, [lejana, cercana])
    expect(rotulos.map(({ nombre }) => nombre)).toEqual(['Parana'])
  })

  test('en un dibujo de 40 × 30 no entra ningún rótulo', () => {
    expect(dibujar(40, 30).rotulos).toEqual([])
  })

  test('sin cuadras no hay rótulos', () => {
    expect(dibujar(382, 204, []).rotulos).toEqual([])
  })

  test('el rótulo de una calle que pasa por el punto se corre para no taparlo', () => {
    // Centrado quedaría sobre el punto: va al 30 % de la cuadra, 40 m al oeste.
    const { rotulos } = dibujar(382, 204, [cuadraHorizontal('Parana', 0)])
    expect(rotulos.map(({ x }) => x)).toEqual([-40])
  })

  test('el rótulo de una calle que pasa al lado del punto queda centrado', () => {
    const { rotulos } = dibujar(382, 204, [cuadraHorizontal('Parana', 40)])
    expect(rotulos.map(({ x }) => x)).toEqual([0])
  })
})
