// @vitest-environment jsdom
import { render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'
import type { PosibleDuplicado } from './api'
import AvisoDuplicados from './AvisoDuplicados'
import './pruebas/dom'
import { respuestas } from './pruebas/respuestas'

const { recibida_en: recibidaEn, posibles } = respuestas.duplicadosConOtra
if (!recibidaEn) throw new Error('Falta la hora de la llamada')
const momento = Date.parse(recibidaEn)

function otraLlamadaEn(diferencia: number) {
  // Variante de la hora de entrada de la otra llamada.
  const otra = structuredClone(posibles[0])
  otra.recibida_en = new Date(momento + diferencia * 1000).toISOString()
  return otra
}

function otraLlamadaCon(cambios: Partial<Pick<PosibleDuplicado, 'categoria' | 'derivada'>>) {
  // Variante de una llamada que todavía no se derivó o cuya categoría no se determinó.
  return Object.assign(structuredClone(posibles[0]), cambios)
}

test('El aviso muestra el lugar de la otra llamada y el nombre de su categoría', () => {
  render(<AvisoDuplicados recibidaEn={recibidaEn} posibles={posibles} />)

  expect(screen.getByRole('listitem').textContent).toContain('Av. Corrientes 1540 (Incendio o rescate)')
})

test.each([
  [-180, '3 min antes que esta'],
  [120, '2 min después que esta'],
  [59, 'casi al mismo tiempo que esta'],
])('Con %i segundos de diferencia dice «%s»', (diferencia, texto) => {
  render(<AvisoDuplicados recibidaEn={recibidaEn} posibles={[otraLlamadaEn(diferencia)]} />)

  expect(screen.getByRole('listitem').textContent).toContain(`, ${texto}.`)
})

test('El aviso dice «Ya se derivó.» si la otra llamada ya se derivó', () => {
  render(<AvisoDuplicados recibidaEn={recibidaEn} posibles={posibles} />)

  expect(screen.getByRole('listitem').textContent).toContain('Ya se derivó.')
})

test('El aviso omite la derivación si la otra llamada sigue abierta', () => {
  render(<AvisoDuplicados recibidaEn={recibidaEn} posibles={[otraLlamadaCon({ derivada: false })]} />)

  expect(screen.getByRole('listitem').textContent).not.toContain('Ya se derivó.')
})

test('El aviso omite una categoría sin determinar', () => {
  render(<AvisoDuplicados recibidaEn={recibidaEn} posibles={[otraLlamadaCon({ categoria: 'NO_DETERMINADA' })]} />)

  expect(screen.getByRole('listitem').textContent).toContain('Av. Corrientes 1540, casi al mismo tiempo')
})

test('El enlace abre el identificador de la otra llamada en otra pestaña', () => {
  render(<AvisoDuplicados recibidaEn={recibidaEn} posibles={posibles} />)

  const enlace = screen.getByRole('link', { name: 'Abrir' })
  expect(enlace.getAttribute('href')).toBe(`?llamada=${posibles[0].llamada_id}`)
  expect(enlace.getAttribute('target')).toBe('_blank')
})
