// @vitest-environment jsdom
import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test } from 'vitest'
import App from './App'
import './pruebas/dom'
import { respuestas } from './pruebas/respuestas'
import llamadaConModelo from './pruebas/respuestas/llamada-con-modelo-analizando.json'
import llamadaEnMock from './pruebas/respuestas/llamada-en-mock-con-modelo-disponible.json'
import saludConModelo from './pruebas/respuestas/salud-con-modelo.json'
import { contestar, contestacionPendiente, simularServicio } from './pruebas/servicio'

const alta = 'POST /api/llamadas'
const salud = 'GET /api/health'
const etiquetaMock = 'mock (sólo reglas)'
const etiquetaOllama = `ollama · ${saludConModelo.modelo}`
const ayuda = 'El modo se elige antes de analizar. Una llamada abierta sigue con el suyo.'
const ejemploSocavon = respuestas.ejemplos.find(({ id }) => id === 'SFX-013')!

function prepararServicio() {
  const servicio = simularServicio()
  servicio.responder(salud, saludConModelo)
  servicio.responder('GET /api/catalogo', respuestas.catalogo)
  servicio.responder('GET /api/ejemplos', respuestas.ejemplos)
  servicio.responder('POST /api/mapa', respuestas.plano)
  return servicio
}

function responderDuplicados(servicio: ReturnType<typeof simularServicio>, llamadaId: string) {
  servicio.responder(`GET /api/llamadas/${llamadaId}/duplicados`, { ...respuestas.duplicadosSinOtra, llamada_id: llamadaId })
}

function comprobarRadios(proveedor: 'mock' | 'ollama', bloqueados: boolean) {
  const radios = screen.getAllByRole<HTMLInputElement>('radio')
  expect(radios.map((radio) => [radio.value, radio.checked, radio.matches(':disabled')])).toEqual([
    ['mock', proveedor === 'mock', bloqueados],
    ['ollama', proveedor === 'ollama', bloqueados],
  ])
}

test('Con un solo modo se muestra Modo: mock y el alta se envía sin proveedor', async () => {
  const servicio = prepararServicio()
  servicio.responder(salud, respuestas.salud)
  servicio.responder(alta, respuestas.llamadaDelDataset, 201)
  responderDuplicados(servicio, respuestas.llamadaDelDataset.llamada_id)
  const operador = userEvent.setup()
  render(<App />)

  const modo = await screen.findByText('Modo: mock')
  expect(modo.getAttribute('title')).toBe('El modo se elige al levantar el servicio.')
  expect(screen.queryAllByRole('radio')).toEqual([])

  const ejemplo = respuestas.ejemplos.find(({ id }) => id === 'SFX-001')!
  await operador.selectOptions(await screen.findByLabelText('Cargar un ejemplo'), ejemplo.id)
  await operador.click(screen.getByRole('button', { name: 'Analizar llamada' }))

  await screen.findByRole('group', { name: 'Sugerencia' })
  expect(servicio.pedidosA(alta).map(({ cuerpo }) => cuerpo)).toEqual([{ turnos: [{ texto: ejemplo.texto }] }])
})

test('Con dos modos aparecen los radios en orden y ollama queda marcado por defecto', async () => {
  prepararServicio()
  render(<App />)

  const selector = await screen.findByRole('group', { name: 'Modo', description: ayuda })
  expect(selector.getAttribute('title')).toBe(ayuda)
  const radios = within(selector)
  expect(radios.getAllByRole('radio')).toEqual([
    radios.getByRole('radio', { name: etiquetaMock, checked: false }),
    radios.getByRole('radio', { name: etiquetaOllama, checked: true }),
  ])
  expect(radios.getAllByRole<HTMLInputElement>('radio').map(({ name }) => name)).toEqual(['modo', 'modo'])
  comprobarRadios('ollama', false)
})

test('Elegir mock envía ese proveedor, abre la sugerencia y lo conserva para una nueva llamada', async () => {
  const servicio = prepararServicio()
  servicio.responder(alta, llamadaEnMock, 201)
  responderDuplicados(servicio, llamadaEnMock.llamada_id)
  const operador = userEvent.setup()
  render(<App />)

  await operador.click(await screen.findByRole('radio', { name: etiquetaMock }))
  await operador.selectOptions(await screen.findByLabelText('Cargar un ejemplo'), ejemploSocavon.id)
  await operador.click(screen.getByRole('button', { name: 'Analizar llamada' }))

  await screen.findByRole('group', { name: 'Sugerencia' })
  expect(servicio.pedidosA(alta).map(({ cuerpo }) => cuerpo))
    .toEqual([{ turnos: [{ texto: ejemploSocavon.texto }], proveedor: 'mock' }])
  expect(servicio.pedidosA(`POST /api/llamadas/${llamadaEnMock.llamada_id}/analisis`)).toEqual([])
  comprobarRadios('mock', true)

  await operador.click(screen.getByRole('button', { name: 'Nueva llamada' }))
  comprobarRadios('mock', false)
})

test('El alta por defecto envía ollama, pide el análisis y bloquea el modo durante los pedidos', async () => {
  const servicio = prepararServicio()
  const altaPendiente = contestacionPendiente()
  const analisisPendiente = contestacionPendiente()
  const analisis = `POST /api/llamadas/${llamadaConModelo.llamada_id}/analisis`
  servicio.responder(alta, () => altaPendiente.promesa)
  servicio.responder(analisis, () => analisisPendiente.promesa)
  responderDuplicados(servicio, llamadaConModelo.llamada_id)
  const operador = userEvent.setup()
  render(<App />)

  await screen.findByRole('radio', { name: etiquetaOllama, checked: true })
  await operador.selectOptions(await screen.findByLabelText('Cargar un ejemplo'), ejemploSocavon.id)
  await operador.click(screen.getByRole('button', { name: 'Analizar llamada' }))

  expect(servicio.pedidosA(alta).map(({ cuerpo }) => cuerpo))
    .toEqual([{ turnos: [{ texto: ejemploSocavon.texto }], proveedor: 'ollama' }])
  comprobarRadios('ollama', true)

  await act(async () => altaPendiente.entregar(contestar(llamadaConModelo, 201)))
  expect(servicio.pedidosA(analisis)).toHaveLength(1)
  expect(screen.getByText(/El modelo está leyendo la llamada/)).toBeTruthy()
  comprobarRadios('ollama', true)

  await act(async () => analisisPendiente.entregar(contestar({ ...llamadaConModelo, estado: 'esperando_operador' })))
  expect(screen.queryByText(/El modelo está leyendo la llamada/)).toBeNull()
  expect(screen.getByRole('group', { name: 'Sugerencia' })).toBeTruthy()
  comprobarRadios('ollama', true)
})

test.each([
  { estado: 'abierta', llamada: llamadaEnMock, rol: 'group', nombre: 'Sugerencia' },
  { estado: 'ya derivada', llamada: respuestas.llamadaDelDatasetDerivada, rol: 'heading', nombre: 'Carta de Llamada' },
])('Abrir por URL una llamada mock $estado marca mock aunque el servicio arranque en ollama', async ({ llamada, rol, nombre }) => {
  const servicio = prepararServicio()
  const pendiente = contestacionPendiente()
  const ruta = `/api/llamadas/${llamada.llamada_id}`
  servicio.responder(salud, () => pendiente.promesa)
  servicio.responder(`GET ${ruta}`, llamada)
  if (llamada.estado === 'derivada') servicio.responder(`GET ${ruta}/historial`, respuestas.historialDerivada)
  else responderDuplicados(servicio, llamada.llamada_id)
  window.history.replaceState(null, '', `/?llamada=${llamada.llamada_id}`)
  const operador = userEvent.setup()
  render(<App />)

  await screen.findByRole(rol, { name: nombre })
  expect(screen.getByText('Modo: consultando…')).toBeTruthy()
  await act(async () => pendiente.entregar(contestar(saludConModelo)))
  comprobarRadios('mock', true)

  await operador.click(screen.getByRole('button', { name: 'Nueva llamada' }))
  comprobarRadios('mock', false)
})

test('Reproducir de a un intercambio envía el modo elegido en el alta', async () => {
  const servicio = prepararServicio()
  servicio.responder(alta, () => contestacionPendiente().promesa)
  const operador = userEvent.setup()
  render(<App />)

  await operador.click(await screen.findByRole('radio', { name: etiquetaMock }))
  await operador.selectOptions(await screen.findByLabelText('Cargar un ejemplo'), 'nueva-5')
  await operador.click(screen.getByRole('checkbox', { name: 'Reproducir de a un intercambio' }))
  await operador.click(screen.getByRole('button', { name: 'Analizar llamada' }))

  const texto = 'Operador: 911, ¿cuál es su emergencia? Llamante: Chocaron un auto y una moto en Av. San Juan, el de la moto quedó tirado en la calle.'
  expect(servicio.pedidosA(alta).map(({ cuerpo }) => cuerpo)).toEqual([{ turnos: [{ texto }], proveedor: 'mock' }])
})

test('Consultar la salud bloquea el panel y si falla se muestra Modo: no disponible sin radios', async () => {
  const servicio = prepararServicio()
  const pendiente = contestacionPendiente()
  servicio.responder(salud, () => pendiente.promesa)
  render(<App />)

  await screen.findByLabelText('Cargar un ejemplo')
  const transcripcion = screen.getByRole<HTMLTextAreaElement>('textbox', { name: 'Transcripción de la llamada' })
  expect(screen.getByText('Modo: consultando…')).toBeTruthy()
  expect(screen.queryAllByRole('radio')).toEqual([])
  expect(transcripcion.disabled).toBe(true)

  await act(async () => pendiente.entregar(contestar({}, 503)))
  expect(screen.getByText('Modo: no disponible')).toBeTruthy()
  expect(screen.getByText('No se pudo conectar con el servicio.')).toBeTruthy()
  expect(screen.queryAllByRole('radio')).toEqual([])
  expect(transcripcion.disabled).toBe(false)
})
