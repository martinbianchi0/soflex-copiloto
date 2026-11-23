// @vitest-environment jsdom
import { act, configure, getConfig, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, onTestFinished, test, vi } from 'vitest'
import type { Llamada } from './api'
import App from './App'
import './pruebas/dom'
import { respuestas } from './pruebas/respuestas'
import { simularServicio } from './pruebas/servicio'

const id = respuestas.llamadaRepetida.llamada_id
const ruta = `/api/llamadas/${id}`
const rutaDuplicados = `GET ${ruta}/duplicados`
const tituloAviso = 'Otra llamada del mismo lugar'
const envolverAccion = getConfig().asyncWrapper

function duplicadosSinOtraParaEstaLlamada() {
  // Variante sin coincidencias para el identificador de la llamada abierta.
  const duplicados = structuredClone(respuestas.duplicadosSinOtra)
  duplicados.llamada_id = id
  return duplicados
}

function llamadaRepetidaDerivada() {
  // Variante de la derivación de la misma transcripción, con el identificador de la repetida.
  const llamada = structuredClone(respuestas.llamadaDelDatasetDerivada)
  if (llamada.estado !== 'esperando_operador' || !llamada.carta) throw new Error('Falta la carta derivada')
  return { ...llamada, llamada_id: id, carta: { ...llamada.carta, llamada_id: id } }
}

function historialDeLaRepetida() {
  // Variante del historial con el identificador de la llamada repetida.
  const historial = structuredClone(respuestas.historialTerminada)
  historial.llamada_id = id
  return historial
}

function avanzar(ms: number) {
  return act(async () => { await vi.advanceTimersByTimeAsync(ms) })
}

function simularPanel() {
  const servicio = simularServicio()
  const responder = vi.spyOn(servicio, 'responder')
  // La verificación de la ayuda no corre si se registra desde el cuerpo del test.
  onTestFinished(() => {
    const rutasSimuladas = new Set(responder.mock.calls.map(([clave]) => clave))
    const sinRespuesta = servicio.pedidos.map(({ metodo, ruta }) => `${metodo} ${ruta}`)
      .filter((clave) => !rutasSimuladas.has(clave))
    expect(sinRespuesta).toEqual([])
  })
  return servicio
}

async function abrirLlamada(servicio: ReturnType<typeof simularServicio>) {
  servicio.responder('GET /api/health', respuestas.salud)
  servicio.responder('GET /api/catalogo', respuestas.catalogo)
  servicio.responder('GET /api/ejemplos', respuestas.ejemplos)
  servicio.responder(`GET ${ruta}`, respuestas.llamadaRepetida)
  servicio.responder('POST /api/mapa', respuestas.plano)
  window.history.replaceState(null, '', `?llamada=${id}`)
  await act(async () => { render(<App />) })
}

beforeEach(() => { vi.useFakeTimers() })
afterEach(() => { configure({ asyncWrapper: envolverAccion }) })

test('Al abrir la llamada pide sus duplicados y muestra el aviso antes de los campos de la sugerencia', async () => {
  const servicio = simularPanel()
  servicio.responder(rutaDuplicados, respuestas.duplicadosConOtra)
  await abrirLlamada(servicio)

  expect(servicio.pedidosA(rutaDuplicados)).toHaveLength(1)
  const sugerencia = within(screen.getByRole('group', { name: 'Sugerencia' }))
  const aviso = sugerencia.getByRole('region', { name: tituloAviso })
  const calle = sugerencia.getByRole('textbox', { name: 'Calle' })
  expect(aviso.compareDocumentPosition(calle)).toBe(Node.DOCUMENT_POSITION_FOLLOWING)
})

test('Sin otras llamadas en el mismo lugar no muestra el aviso', async () => {
  const servicio = simularPanel()
  servicio.responder(rutaDuplicados, duplicadosSinOtraParaEstaLlamada())
  await abrirLlamada(servicio)

  expect(servicio.pedidosA(rutaDuplicados)).toHaveLength(1)
  expect(screen.queryByRole('region', { name: tituloAviso })).toBeNull()
})

test('Cada 15 segundos vuelve a preguntar y muestra la otra llamada que acaba de aparecer', async () => {
  const servicio = simularPanel()
  servicio.responder(rutaDuplicados, duplicadosSinOtraParaEstaLlamada())
  await abrirLlamada(servicio)
  expect(screen.queryByRole('region', { name: tituloAviso })).toBeNull()

  servicio.responder(rutaDuplicados, respuestas.duplicadosConOtra)
  await avanzar(14_999)
  expect(servicio.pedidosA(rutaDuplicados)).toHaveLength(1)
  await avanzar(1)
  expect(servicio.pedidosA(rutaDuplicados)).toHaveLength(2)
  const aviso = screen.getByRole('region', { name: tituloAviso })
  expect(within(aviso).getByRole('listitem').textContent).toContain('Av. Corrientes 1540')

  await avanzar(14_999)
  expect(servicio.pedidosA(rutaDuplicados)).toHaveLength(2)
  await avanzar(1)
  expect(servicio.pedidosA(rutaDuplicados)).toHaveLength(3)
})

test('Si falla el refresco conserva el aviso que ya mostraba', async () => {
  const servicio = simularPanel()
  servicio.responder(rutaDuplicados, respuestas.duplicadosConOtra)
  await abrirLlamada(servicio)
  const aviso = screen.getByRole('region', { name: tituloAviso })
  const contenido = within(aviso).getByRole('listitem').textContent

  servicio.responder(rutaDuplicados, respuestas.errorLlamadaInexistente, 404)
  await avanzar(15_000)
  expect(servicio.pedidosA(rutaDuplicados)).toHaveLength(2)
  expect(within(screen.getByRole('region', { name: tituloAviso })).getByRole('listitem').textContent).toBe(contenido)
})

test('El aviso y las consultas de duplicados siguen al derivar y cesan al terminar', async () => {
  const servicio = simularPanel()
  const derivada = llamadaRepetidaDerivada()
  const terminada: Llamada = { ...derivada, estado: 'terminada', carta_al_dia: null }
  servicio.responder(rutaDuplicados, respuestas.duplicadosConOtra)
  servicio.responder(`POST ${ruta}/derivar`, derivada)
  servicio.responder(`POST ${ruta}/terminar`, terminada)
  servicio.responder(`GET ${ruta}/historial`, historialDeLaRepetida())
  await abrirLlamada(servicio)
  expect(screen.getByRole('region', { name: tituloAviso })).toBeTruthy()

  // La espera de 0 ms del envoltorio habitual no avanza con este reloj.
  configure({ asyncWrapper: async (accion) => accion() })
  const usuario = userEvent.setup({ advanceTimers: (ms) => { vi.advanceTimersByTime(ms) } })
  await act(async () => { await usuario.click(screen.getByRole('button', { name: 'Derivar Carta de Llamada' })) })

  expect(screen.getByRole('region', { name: tituloAviso })).toBeTruthy()
  const consultasAlDerivar = servicio.pedidosA(rutaDuplicados).length
  await avanzar(15_000)
  expect(servicio.pedidosA(rutaDuplicados)).toHaveLength(consultasAlDerivar + 1)

  await act(async () => { await usuario.click(screen.getByRole('button', { name: 'Terminar llamada' })) })
  expect(screen.getByRole('heading', { name: 'Carta de Llamada' })).toBeTruthy()
  expect(screen.queryByRole('region', { name: tituloAviso })).toBeNull()
  await avanzar(30_000)
  expect(servicio.pedidosA(rutaDuplicados)).toHaveLength(consultasAlDerivar + 1)
})
