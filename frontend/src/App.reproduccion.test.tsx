// @vitest-environment jsdom
import { act, configure, getConfig, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, onTestFinished, test, vi } from 'vitest'
import type { Llamada } from './api'
import App from './App'
import './pruebas/dom'
import { respuestas } from './pruebas/respuestas'
import { contestacionPendiente, contestar, simularServicio } from './pruebas/servicio'

const id = respuestas.llamadaPorTurnos.llamada_id
const ruta = `/api/llamadas/${id}`
const rutaAlta = 'POST /api/llamadas'
const rutaTurnos = `POST ${ruta}/turnos`
const etiquetaReproduccion = 'Reproducir de a un intercambio'
const envolverAccion = getConfig().asyncWrapper
const primerIntercambio = 'Operador: 911, ¿cuál es su emergencia? Llamante: Chocaron un auto y una moto en Av. San Juan, el de la moto quedó tirado en la calle.'
const siguientesIntercambios = [
  { texto: 'Operador: ¿A qué altura? Llamante: Al 2100.', pausa: 3_720 },
  { texto: 'Operador: ¿El motociclista respira? ¿Le responde? Llamante: Sí, respira y me contesta, pero dice que le duele mucho la pierna.', pausa: 6_000 },
  { texto: 'Operador: No le saquen el casco. ¿Lo tiene puesto? Llamante: Sí, lo tiene puesto, no se lo tocamos.', pausa: 5_960 },
  { texto: 'Operador: ¿Ve nafta o aceite en el asfalto? Llamante: Sí, hay una mancha de nafta debajo de la moto.', pausa: 6_000 },
]

function duplicadosSinOtraParaElEjemplo() {
  // Variante sin coincidencias para el identificador del ejemplo reproducido.
  const duplicados = structuredClone(respuestas.duplicadosSinOtra)
  duplicados.llamada_id = id
  return duplicados
}

function llamadaDelEjemploDerivada(): Llamada {
  // Variante del segundo intercambio con la carta y la prioridad que eligió el operador.
  const llamada = structuredClone(respuestas.llamadaPorTurnosConAltura)
  const derivada = structuredClone(respuestas.llamadaDelDatasetDerivada)
  if (llamada.estado !== 'esperando_operador' || derivada.estado !== 'derivada') {
    throw new Error('Falta la sugerencia del ejemplo o la carta derivada')
  }
  return {
    ...llamada,
    estado: 'derivada',
    carta: {
      ...llamada.sugerencia,
      llamada_id: id,
      derivada_en: derivada.carta.derivada_en,
      prioridad: { origen: 'operador', valor: 'P2' },
    },
  }
}

function historialDelEjemplo() {
  // Variante del historial con el identificador del ejemplo reproducido.
  const historial = structuredClone(respuestas.historialDerivada)
  historial.llamada_id = id
  return historial
}

function intercambioConAnalisisPendiente(): Llamada {
  // Variante del segundo intercambio mientras todavía lo analiza el modelo.
  const llamada = structuredClone(respuestas.llamadaPorTurnosConAltura)
  if (llamada.estado !== 'esperando_operador') throw new Error('Falta la sugerencia del segundo intercambio')
  return { ...llamada, estado: 'analizando' }
}

function avanzar(ms: number) {
  return act(async () => { await vi.advanceTimersByTimeAsync(ms) })
}

async function abrirPanel() {
  const servicio = simularServicio()
  const responder = vi.spyOn(servicio, 'responder')
  // La verificación de la ayuda no corre si se registra desde el cuerpo del test.
  onTestFinished(() => {
    const rutasSimuladas = new Set(responder.mock.calls.map(([clave]) => clave))
    const sinRespuesta = servicio.pedidos.map(({ metodo, ruta }) => `${metodo} ${ruta}`)
      .filter((clave) => !rutasSimuladas.has(clave))
    expect(sinRespuesta).toEqual([])
  })
  servicio.responder('GET /api/health', respuestas.salud)
  servicio.responder('GET /api/catalogo', respuestas.catalogo)
  servicio.responder('GET /api/ejemplos', respuestas.ejemplos)
  servicio.responder(rutaAlta, respuestas.llamadaPorTurnos, 201)
  servicio.responder(rutaTurnos, respuestas.llamadaPorTurnosConAltura)
  servicio.responder(`GET ${ruta}/duplicados`, duplicadosSinOtraParaElEjemplo())
  servicio.responder('POST /api/mapa', respuestas.errorSinPlano, 404)
  await act(async () => { render(<App />) })
  const usuario = userEvent.setup({ advanceTimers: (ms) => { vi.advanceTimersByTime(ms) } })
  return { servicio, usuario }
}

async function elegirEjemplo(usuario: ReturnType<typeof userEvent.setup>, idEjemplo: string) {
  await act(async () => { await usuario.selectOptions(screen.getByLabelText('Cargar un ejemplo'), idEjemplo) })
}

async function reproducirEjemplo(usuario: ReturnType<typeof userEvent.setup>) {
  await elegirEjemplo(usuario, 'nueva-5')
  await act(async () => { await usuario.click(screen.getByRole('checkbox', { name: etiquetaReproduccion })) })
  await act(async () => { await usuario.click(screen.getByRole('button', { name: 'Analizar llamada' })) })
}

beforeEach(() => {
  vi.useFakeTimers()
  // Cada interacción se espera en act, sin el temporizador adicional del envoltorio habitual.
  configure({ asyncWrapper: async (accion) => accion() })
})
afterEach(() => { configure({ asyncWrapper: envolverAccion }) })

test('La casilla para reproducir aparece sólo si el ejemplo tiene más de un intercambio', async () => {
  const { usuario } = await abrirPanel()
  expect(screen.queryByRole('checkbox', { name: etiquetaReproduccion })).toBeNull()

  await elegirEjemplo(usuario, 'nueva-5')
  expect(screen.getByRole('checkbox', { name: etiquetaReproduccion })).toBeTruthy()

  await elegirEjemplo(usuario, 'nueva-1')
  expect(screen.queryByRole('checkbox', { name: etiquetaReproduccion })).toBeNull()
})

test('Al analizar con la casilla tildada da de alta sólo el primer intercambio', async () => {
  const { servicio, usuario } = await abrirPanel()
  await reproducirEjemplo(usuario)

  expect(servicio.pedidosA(rutaAlta).map(({ cuerpo }) => cuerpo)).toEqual([
    { turnos: [{ texto: primerIntercambio }] },
  ])
  expect(servicio.pedidosA(rutaTurnos)).toHaveLength(0)
})

test('Suma cada intercambio por orden después de su pausa y termina al llegar al último', async () => {
  const { servicio, usuario } = await abrirPanel()
  await reproducirEjemplo(usuario)

  for (const [indice, { texto, pausa }] of siguientesIntercambios.entries()) {
    await avanzar(pausa - 1)
    expect(servicio.pedidosA(rutaTurnos)).toHaveLength(indice)
    await avanzar(1)
    const pedidos = servicio.pedidosA(rutaTurnos)
    expect(pedidos).toHaveLength(indice + 1)
    expect(pedidos[indice].cuerpo).toEqual({ turno: { texto, hablante: null } })
  }

  expect(screen.getByText('La llamada terminó.', { selector: 'p' })).toBeTruthy()
  expect(screen.queryByRole('button', { name: 'Detener' })).toBeNull()
  await avanzar(6_000)
  expect(servicio.pedidosA(rutaTurnos)).toHaveLength(siguientesIntercambios.length)
})

test('Durante el análisis de un intercambio espera al modelo antes de iniciar la pausa del siguiente', async () => {
  const { servicio, usuario } = await abrirPanel()
  const analisis = contestacionPendiente()
  servicio.responder(rutaTurnos, intercambioConAnalisisPendiente())
  servicio.responder(`POST ${ruta}/analisis`, () => analisis.promesa)
  await reproducirEjemplo(usuario)

  await avanzar(siguientesIntercambios[0].pausa)
  expect(servicio.pedidosA(`POST ${ruta}/analisis`)).toHaveLength(1)
  await avanzar(6_000)
  expect(servicio.pedidosA(rutaTurnos)).toHaveLength(1)

  servicio.responder(rutaTurnos, respuestas.llamadaPorTurnosConAltura)
  await act(async () => { analisis.entregar(contestar(respuestas.llamadaPorTurnosConAltura)) })
  await avanzar(siguientesIntercambios[1].pausa - 1)
  expect(servicio.pedidosA(rutaTurnos)).toHaveLength(1)
  await avanzar(1)
  expect(servicio.pedidosA(rutaTurnos)).toHaveLength(2)
})

test('Al pulsar Detener, no suma más intercambios', async () => {
  const { servicio, usuario } = await abrirPanel()
  await reproducirEjemplo(usuario)
  await avanzar(siguientesIntercambios[0].pausa)

  await act(async () => { await usuario.click(screen.getByRole('button', { name: 'Detener' })) })
  expect(screen.getByText('Reproducción detenida.')).toBeTruthy()
  await avanzar(24_000)
  expect(servicio.pedidosA(rutaTurnos)).toHaveLength(1)
})

test('Si deriva durante una pausa, aparece la carta y termina la reproducción', async () => {
  const { servicio, usuario } = await abrirPanel()
  servicio.responder(`POST ${ruta}/derivar`, llamadaDelEjemploDerivada())
  servicio.responder(`GET ${ruta}/historial`, historialDelEjemplo())
  await reproducirEjemplo(usuario)
  await avanzar(siguientesIntercambios[0].pausa)

  await act(async () => { await usuario.selectOptions(screen.getByRole('combobox', { name: 'Prioridad' }), 'P2') })
  await act(async () => { await usuario.click(screen.getByRole('button', { name: 'Derivar Carta de Llamada' })) })

  expect(screen.getByRole('heading', { name: 'Carta de Llamada' })).toBeTruthy()
  expect(screen.queryAllByText(/^Reproduciendo la llamada:/)).toHaveLength(0)
  await avanzar(24_000)
  expect(servicio.pedidosA(rutaTurnos)).toHaveLength(1)
})

test('Si falla un pedido de un intercambio, muestra el error y deja de sumar', async () => {
  const { servicio, usuario } = await abrirPanel()
  servicio.responder(rutaTurnos, respuestas.errorYaDerivada, 409)
  await reproducirEjemplo(usuario)
  await avanzar(siguientesIntercambios[0].pausa)

  expect(screen.getByRole('alert').textContent).toBe(respuestas.errorYaDerivada.detail)
  expect(screen.queryByRole('button', { name: 'Detener' })).toBeNull()
  await avanzar(24_000)
  expect(servicio.pedidosA(rutaTurnos)).toHaveLength(1)
})
