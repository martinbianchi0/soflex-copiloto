// @vitest-environment jsdom
/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, onTestFinished, test, vi } from 'vitest'
import MiniMapa from './MiniMapa'
import './pruebas/dom'
import { respuestas } from './pruebas/respuestas'
import { contestacionPendiente, contestar, simularServicio } from './pruebas/servicio'

const rutaPlano = 'POST /api/mapa'
const direccion = { calle: 'Av. Corrientes', altura: '1540', esquinas: ['Montevideo', ''] } satisfies React.ComponentProps<typeof MiniMapa>

function simularPlano(cuerpo: unknown = respuestas.plano, estado = 200) {
  const servicio = simularServicio()
  servicio.responder(rutaPlano, cuerpo, estado)
  // La verificación de la ayuda no corre si se registra desde el cuerpo del test.
  onTestFinished(() => { expect(servicio.pedidos).toEqual(servicio.pedidosA(rutaPlano)) })
  return servicio
}

function avanzar(ms: number) {
  return act(async () => { await vi.advanceTimersByTimeAsync(ms) })
}

function planoDeOtraAltura() {
  // Variante de otra altura en la misma cuadra, para distinguir cuál respuesta quedó.
  const plano = structuredClone(respuestas.plano)
  plano.leyenda = plano.leyenda.replace('1540', '1542')
  return plano
}

function planoPorEsquina() {
  // Variante de un plano ubicado por la esquina.
  const plano = structuredClone(respuestas.plano)
  plano.exacto = false
  return plano
}

beforeEach(() => { vi.useFakeTimers() })

test('Pide el plano con la altura numérica y sólo las esquinas escritas, y muestra su leyenda', async () => {
  const servicio = simularPlano()
  render(<MiniMapa {...direccion} esquinas={['Montevideo', '  ']} />)
  await avanzar(400)

  expect(servicio.pedidosA(rutaPlano).map(({ cuerpo }) => cuerpo)).toEqual([
    { calle: 'Av. Corrientes', altura: 1540, esquinas: ['Montevideo'] },
  ])
  expect(screen.getByText(respuestas.plano.leyenda)).toBeTruthy()
  expect(screen.getByRole('img', { name: respuestas.plano.leyenda })).toBeTruthy()
})

test('Tres cambios seguidos hacen un solo pedido 400 ms después del último', async () => {
  const servicio = simularPlano()
  const { rerender } = render(<MiniMapa {...direccion} altura="1" />)

  await avanzar(100)
  rerender(<MiniMapa {...direccion} altura="15" />)
  await avanzar(100)
  rerender(<MiniMapa {...direccion} altura="154" />)
  await avanzar(100)
  rerender(<MiniMapa {...direccion} />)
  await avanzar(399)
  expect(servicio.pedidosA(rutaPlano)).toHaveLength(0)

  await avanzar(1)
  expect(servicio.pedidosA(rutaPlano).map(({ cuerpo }) => cuerpo)).toEqual([
    { calle: 'Av. Corrientes', altura: 1540, esquinas: ['Montevideo'] },
  ])
})

test('Una respuesta tardía no reemplaza el plano de la dirección nueva', async () => {
  const anterior = contestacionPendiente()
  const nuevo = planoDeOtraAltura()
  const servicio = simularPlano(() => anterior.promesa)
  const { rerender } = render(<MiniMapa {...direccion} />)
  await avanzar(400)
  expect(servicio.pedidosA(rutaPlano)).toHaveLength(1)

  servicio.responder(rutaPlano, nuevo)
  rerender(<MiniMapa {...direccion} altura="1542" />)
  await avanzar(400)
  expect(screen.getByRole('img', { name: nuevo.leyenda })).toBeTruthy()

  await act(async () => { anterior.entregar(contestar(respuestas.plano)) })
  expect(screen.getByRole('img', { name: nuevo.leyenda })).toBeTruthy()
  expect(screen.queryByText(respuestas.plano.leyenda)).toBeNull()
})

test('Muestra «Buscando plano…» hasta que contesta el servicio', async () => {
  const pendiente = contestacionPendiente()
  simularPlano(() => pendiente.promesa)
  render(<MiniMapa {...direccion} />)
  expect(screen.getByText('Buscando plano…')).toBeTruthy()

  await avanzar(400)
  expect(screen.getByText('Buscando plano…')).toBeTruthy()
  await act(async () => { pendiente.entregar(contestar(respuestas.plano)) })
  expect(screen.queryByText('Buscando plano…')).toBeNull()
})

test.each([
  { caso: 'la calle está vacía', calle: ' ', altura: '1540', esquina: 'Montevideo',
    mensaje: 'Sin plano: falta la calle.' },
  { caso: 'faltan tanto la altura como la esquina', calle: 'Av. Corrientes', altura: '', esquina: '',
    mensaje: 'Sin plano: falta la altura o una esquina.' },
  { caso: 'la altura es inválida aunque haya esquina', calle: 'Av. Corrientes', altura: '15A', esquina: 'Montevideo',
    mensaje: 'Sin plano: falta la altura o una esquina.' },
])('Muestra por qué falta el plano y no lo pide si $caso', async ({ calle, altura, esquina, mensaje }) => {
  const servicio = simularServicio()
  render(<MiniMapa calle={calle} altura={altura} esquinas={[esquina, '']} />)
  await avanzar(400)

  expect(screen.getByText(mensaje)).toBeTruthy()
  expect(servicio.pedidos).toHaveLength(0)
})

test.each([
  [404, 'Sin plano: esa dirección no se pudo ubicar en el callejero.'],
  [500, 'Sin plano: no se pudo consultar.'],
])('Muestra el mensaje del plano correspondiente al error %i', async (estado, mensaje) => {
  simularPlano(respuestas.errorSinPlano, estado)
  render(<MiniMapa {...direccion} />)
  await avanzar(400)

  expect(screen.getByText(mensaje)).toBeTruthy()
})

test('Con una esquina sola pide el plano con altura nula', async () => {
  const servicio = simularPlano(planoPorEsquina())
  render(<MiniMapa {...direccion} altura="" />)
  await avanzar(400)

  expect(servicio.pedidosA(rutaPlano).map(({ cuerpo }) => cuerpo)).toEqual([
    { calle: 'Av. Corrientes', altura: null, esquinas: ['Montevideo'] },
  ])
})

test.each([
  { ubicacion: 'exacta', plano: respuestas.plano, conRelleno: true },
  { ubicacion: 'por la esquina', plano: planoPorEsquina(), conRelleno: false },
])('El relleno del punto corresponde a una ubicación $ubicacion', async ({ plano, conRelleno }) => {
  simularPlano(plano)
  // El dibujo usa los estilos del panel para distinguir el punto exacto del aproximado.
  const estilos = readFileSync('src/index.css', 'utf8')
  render(<><style>{estilos}</style><MiniMapa {...direccion} altura={plano.exacto ? '1540' : ''} /></>)
  await avanzar(400)

  const punto = screen.getByRole('img', { name: plano.leyenda }).querySelector('circle')
  if (!punto) throw new Error('Falta el punto del plano')
  const relleno = getComputedStyle(punto).getPropertyValue('fill')
  expect(relleno).toBeTruthy()
  expect(relleno !== 'none').toBe(conRelleno)
})

test('Al tabular se salta el plano y el dibujo no puede tomar el foco', async () => {
  simularPlano()
  render(<><button>Antes</button><MiniMapa {...direccion} /><button>Después</button></>)
  await avanzar(400)
  vi.useRealTimers()
  const usuario = userEvent.setup()

  await usuario.tab()
  expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Antes' }))
  await usuario.tab()
  expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Después' }))
  const plano = screen.getByRole('figure')
  expect(plano.matches('[tabindex]')).toBe(false)
  expect(plano.querySelector('[tabindex]')).toBeNull()
})

test('El plano no anuncia la búsqueda ni el dibujo en una región viva', async () => {
  simularPlano()
  const { container } = render(<MiniMapa {...direccion} />)

  const regionesVivas = '[aria-live], [role~="alert"], [role~="status"], [role~="log"], [role~="marquee"], [role~="timer"]'
  expect(container.querySelector(regionesVivas)).toBeNull()
  await avanzar(400)
  expect(container.querySelector(regionesVivas)).toBeNull()
})
