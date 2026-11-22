// @vitest-environment jsdom
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, test } from 'vitest'
import App from './App'
import './pruebas/dom'
import { respuestas } from './pruebas/respuestas'
import { contestar, contestacionPendiente, simularServicio } from './pruebas/servicio'

const { llamadaPorTurnos, llamadaPorTurnosConAltura } = respuestas
const identificador = llamadaPorTurnos.llamada_id
const sumaDeTurno = `POST /api/llamadas/${identificador}/turnos`

function abrirLlamada() {
  const servicio = simularServicio()
  servicio.responder('GET /api/health', respuestas.salud)
  servicio.responder('GET /api/catalogo', respuestas.catalogo)
  servicio.responder('GET /api/ejemplos', respuestas.ejemplos)
  servicio.responder('POST /api/mapa', respuestas.plano)
  servicio.responder(`GET /api/llamadas/${identificador}`, llamadaPorTurnos)
  // Variante sin duplicados para la llamada por turnos.
  const duplicados = structuredClone(respuestas.duplicadosSinOtra)
  duplicados.llamada_id = identificador
  servicio.responder(`GET /api/llamadas/${identificador}/duplicados`, duplicados)
  window.history.replaceState(null, '', `/?llamada=${identificador}`)
  render(<App />)
  return servicio
}

function campoAltura() {
  return screen.getByRole<HTMLInputElement>('textbox', { name: 'Altura (opcional)' })
}

function campoPrioridad() {
  return screen.getByRole<HTMLSelectElement>('combobox', { name: 'Prioridad' })
}

function textoDelTurno() {
  return screen.getByRole<HTMLTextAreaElement>('textbox', { name: /Texto del turno/ })
}

describe('Sumar lo que se dijo después', () => {
  const intercambio = 'Operador: ¿A qué altura? Llamante: Al 2100.'

  test('Sumar a la llamada envía el turno y completa la altura y las entrecalles', async () => {
    const servicio = abrirLlamada()
    servicio.responder(sumaDeTurno, llamadaPorTurnosConAltura)
    const operador = userEvent.setup()

    await screen.findByRole('group', { name: 'Sugerencia' })
    expect(campoAltura().value).toBe('')
    await operador.type(textoDelTurno(), intercambio)
    await operador.click(screen.getByRole('button', { name: 'Sumar a la llamada' }))

    expect(servicio.pedidosA(sumaDeTurno).map(({ cuerpo }) => cuerpo))
      .toEqual([{ turno: { texto: intercambio, hablante: null } }])
    await screen.findByText('Se sumó un turno. Sugerencia actualizada.')
    expect(campoAltura().value).toBe('2100')
    expect(screen.getByRole<HTMLInputElement>('textbox', { name: 'Primera esquina (opcional)' }).value).toBe('Sarandi')
    expect(screen.getByRole<HTMLInputElement>('textbox', { name: 'Segunda esquina (opcional)' }).value).toBe('Rincon')
  })

  test('Sumar un turno conserva la prioridad elegida por el operador', async () => {
    const servicio = abrirLlamada()
    servicio.responder(sumaDeTurno, llamadaPorTurnosConAltura)
    const operador = userEvent.setup()

    await operador.selectOptions(await screen.findByRole('combobox', { name: 'Prioridad' }), 'P2')
    await operador.type(textoDelTurno(), intercambio)
    await operador.click(screen.getByRole('button', { name: 'Sumar a la llamada' }))

    await screen.findByText('Se sumó un turno. Sugerencia actualizada.')
    expect(campoPrioridad().value).toBe('P2')
  })

  test('Sumar un turno conserva toda la ubicación corregida y muestra la nueva dirección sugerida', async () => {
    const servicio = abrirLlamada()
    servicio.responder(sumaDeTurno, llamadaPorTurnosConAltura)
    const operador = userEvent.setup()

    const calle = await screen.findByRole<HTMLInputElement>('textbox', { name: 'Calle' })
    await operador.clear(calle)
    await operador.type(calle, 'Av. Independencia')
    await operador.type(textoDelTurno(), intercambio)
    await operador.click(screen.getByRole('button', { name: 'Sumar a la llamada' }))

    expect(await screen.findByRole('textbox', {
      name: 'Calle', description: /El análisis ahora sugiere otra dirección: Av\. San Juan 2100\./,
    })).toBe(calle)
    expect(calle.value).toBe('Av. Independencia')
    expect(campoAltura().value).toBe('')
    expect(screen.getByRole<HTMLInputElement>('textbox', { name: 'Primera esquina (opcional)' }).value).toBe('')
    expect(screen.getByRole<HTMLInputElement>('textbox', { name: 'Segunda esquina (opcional)' }).value).toBe('')
  })

  test('Ctrl+Enter en el texto del turno lo suma con el hablante elegido y no deriva', async () => {
    const servicio = abrirLlamada()
    const pedidoDerivar = `POST /api/llamadas/${llamadaPorTurnos.llamada_id}/derivar`
    servicio.responder(sumaDeTurno, () => contestacionPendiente().promesa)
    servicio.responder(pedidoDerivar, () => contestacionPendiente().promesa)
    const operador = userEvent.setup()

    await operador.selectOptions(await screen.findByRole('combobox', { name: 'Prioridad' }), 'P2')
    await operador.selectOptions(screen.getByRole('combobox', { name: 'Quién habla' }), 'Operador')
    await operador.type(textoDelTurno(), '¿A qué altura?')
    await operador.keyboard('{Control>}{Enter}{/Control}')

    expect(servicio.pedidosA(sumaDeTurno).map(({ cuerpo }) => cuerpo))
      .toEqual([{ turno: { texto: '¿A qué altura?', hablante: 'operador' } }])
    expect(servicio.pedidosA(pedidoDerivar)).toEqual([])
  })

  test('Un turno vacío no se puede sumar ni con Ctrl+Enter', async () => {
    const servicio = abrirLlamada()
    servicio.responder(sumaDeTurno, () => contestacionPendiente().promesa)
    const operador = userEvent.setup()

    await operador.click(await screen.findByRole('textbox', { name: 'Texto del turno' }))
    await operador.keyboard('{Control>}{Enter}{/Control}')
    const sumar = screen.getByRole<HTMLButtonElement>('button', { name: 'Sumar a la llamada' })
    expect(sumar.disabled).toBe(true)
    await operador.click(sumar)

    expect(servicio.pedidosA(sumaDeTurno)).toEqual([])
  })

  test('Si falla la suma se conserva el turno y se puede volver a enviar', async () => {
    const servicio = abrirLlamada()
    servicio.responder(sumaDeTurno, async () => { throw new TypeError('Falló la conexión') })
    const operador = userEvent.setup()

    await screen.findByRole('group', { name: 'Sugerencia' })
    await operador.type(textoDelTurno(), intercambio)
    await operador.click(screen.getByRole('button', { name: 'Sumar a la llamada' }))

    expect((await screen.findByRole('alert')).textContent).toBe('No se pudo conectar con el servicio.')
    expect(textoDelTurno().value).toBe(intercambio)

    servicio.responder(sumaDeTurno, llamadaPorTurnosConAltura)
    await operador.click(screen.getByRole('button', { name: 'Sumar a la llamada' }))

    await screen.findByText('Se sumó un turno. Sugerencia actualizada.')
    expect(servicio.pedidosA(sumaDeTurno).map(({ cuerpo }) => cuerpo)).toEqual([
      { turno: { texto: intercambio, hablante: null } },
      { turno: { texto: intercambio, hablante: null } },
    ])
    expect(textoDelTurno().value).toBe('')
    expect(screen.queryByRole('alert')).toBeNull()
  })

  // Cuando llega el turno, el panel devuelve el foco al texto del turno aunque se haya movido.
  test.fails('Al llegar la sugerencia actualizada se conserva el foco donde lo dejó el operador', async () => {
    const servicio = abrirLlamada()
    const pendiente = contestacionPendiente()
    servicio.responder(sumaDeTurno, () => pendiente.promesa)
    const operador = userEvent.setup()

    await screen.findByRole('group', { name: 'Sugerencia' })
    await operador.type(textoDelTurno(), intercambio)
    await operador.click(screen.getByRole('button', { name: 'Sumar a la llamada' }))
    const transcripcion = screen.getByRole('region', { name: 'Transcripción de la llamada' })
    await operador.click(transcripcion)
    expect(document.activeElement).toBe(transcripcion)

    await act(async () => pendiente.entregar(contestar(llamadaPorTurnosConAltura)))

    expect(screen.getByText('Se sumó un turno. Sugerencia actualizada.')).toBeTruthy()
    expect(document.activeElement).toBe(transcripcion)
  })
})
