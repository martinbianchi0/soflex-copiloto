// @vitest-environment jsdom
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, test } from 'vitest'
import App from './App'
import './pruebas/dom'
import { respuestas } from './pruebas/respuestas'
import { contestacionPendiente, simularServicio } from './pruebas/servicio'

const { llamadaDelDataset, llamadaDelDatasetDerivada, llamadaSinDatos } = respuestas
const protocoloIncendio = respuestas.catalogo.protocolos.find(({ id }) => id === 'SFX-001')!
const [preguntaAtrapados, preguntaGas] = protocoloIncendio.preguntas
const [instruccionIncendio] = protocoloIncendio.instrucciones
const derivacion = `POST /api/llamadas/${llamadaDelDataset.llamada_id}/derivar`
const historial = `GET /api/llamadas/${llamadaDelDataset.llamada_id}/historial`

function abrirLlamada(llamada = llamadaDelDataset) {
  const servicio = simularServicio()
  servicio.responder('GET /api/health', respuestas.salud)
  servicio.responder('GET /api/catalogo', respuestas.catalogo)
  servicio.responder('GET /api/ejemplos', respuestas.ejemplos)
  servicio.responder('POST /api/mapa', respuestas.plano)
  const { llamada_id: identificador } = llamada
  servicio.responder(`GET /api/llamadas/${identificador}`, llamada)
  if (llamada.estado === 'derivada') {
    servicio.responder(historial, respuestas.historialDerivada)
  } else if (llamada === llamadaSinDatos) {
    // Variante sin duplicados para la llamada sin datos.
    const duplicados = structuredClone(respuestas.duplicadosSinOtra)
    duplicados.llamada_id = identificador
    servicio.responder(`GET /api/llamadas/${identificador}/duplicados`, duplicados)
  } else {
    servicio.responder(`GET /api/llamadas/${identificador}/duplicados`, respuestas.duplicadosSinOtra)
  }
  window.history.replaceState(null, '', `/?llamada=${identificador}`)
  render(<App />)
  return servicio
}

const citaPosible = { turno: 1, texto: 'la campana de la cocina' }

function conPosibleRespuesta() {
  // Variante: lo que propone el modelo llega pendiente y con su cita. El modo `mock` no lo produce.
  const llamada = structuredClone(llamadaDelDataset)
  if (!llamada.sugerencia) throw new Error('La llamada guardada no trae sugerencia')
  llamada.sugerencia.checklist[1].cita = citaPosible
  return llamada
}

function dejarDerivacionPendiente(servicio: ReturnType<typeof simularServicio>) {
  servicio.responder(derivacion, () => contestacionPendiente().promesa)
}

function botonDerivar() {
  return screen.getByRole<HTMLButtonElement>('button', { name: 'Derivar Carta de Llamada' })
}

function campoAltura() {
  return screen.getByRole<HTMLInputElement>('textbox', { name: 'Altura (opcional)' })
}

function campoPrioridad() {
  return screen.getByRole<HTMLSelectElement>('combobox', { name: 'Prioridad' })
}

describe('Derivar', () => {
  test.each([
    { nombre: 'un campo de texto', rol: 'textbox', etiqueta: 'Calle' },
    { nombre: 'un desplegable', rol: 'combobox', etiqueta: 'Prioridad' },
  ])('Enter sobre $nombre no deriva la carta', async ({ rol, etiqueta }) => {
    const servicio = abrirLlamada()
    dejarDerivacionPendiente(servicio)
    const operador = userEvent.setup()
    const campo = await screen.findByRole(rol, { name: etiqueta })

    await operador.click(campo)
    expect(document.activeElement).toBe(campo)
    await operador.keyboard('{Enter}')

    expect(servicio.pedidosA(derivacion)).toEqual([])
  })

  test.each([
    { rol: 'textbox', etiqueta: 'Calle' },
    { rol: 'combobox', etiqueta: 'Prioridad' },
  ])('Ctrl+Enter desde $etiqueta deriva la carta', async ({ rol, etiqueta }) => {
    const servicio = abrirLlamada()
    dejarDerivacionPendiente(servicio)
    const operador = userEvent.setup()

    await operador.click(await screen.findByRole(rol, { name: etiqueta }))
    await operador.keyboard('{Control>}{Enter}{/Control}')

    expect(servicio.pedidosA(derivacion)).toHaveLength(1)
  })

  test('El botón deriva la sugerencia intacta con ajustes vacíos', async () => {
    const servicio = abrirLlamada()
    dejarDerivacionPendiente(servicio)
    const operador = userEvent.setup()

    await screen.findByRole('group', { name: 'Sugerencia' })
    await operador.click(botonDerivar())

    expect(servicio.pedidosA(derivacion).map(({ cuerpo }) => cuerpo)).toEqual([{ ajustes: {} }])
  })

  test('Si se cambia la prioridad se manda sólo la prioridad', async () => {
    const servicio = abrirLlamada()
    dejarDerivacionPendiente(servicio)
    const operador = userEvent.setup()

    await operador.selectOptions(await screen.findByRole('combobox', { name: 'Prioridad' }), 'P2')
    await operador.click(botonDerivar())

    expect(servicio.pedidosA(derivacion).map(({ cuerpo }) => cuerpo)).toEqual([{ ajustes: { prioridad: 'P2' } }])
  })

  test('Si se cambia la altura se manda la ubicación entera', async () => {
    const servicio = abrirLlamada()
    dejarDerivacionPendiente(servicio)
    const operador = userEvent.setup()

    await screen.findByRole('group', { name: 'Sugerencia' })
    await operador.clear(campoAltura())
    await operador.type(campoAltura(), '1550')
    await operador.click(botonDerivar())

    expect(servicio.pedidosA(derivacion).map(({ cuerpo }) => cuerpo)).toEqual([{
      ajustes: { ubicacion: { calle: 'Av. Corrientes', altura: 1550, esquinas: ['Montevideo', 'Parana'] } },
    }])
  })

  test('La derivación manda las preguntas marcadas y desmarcadas sin cita', async () => {
    const servicio = abrirLlamada()
    dejarDerivacionPendiente(servicio)
    const operador = userEvent.setup()

    await operador.click(await screen.findByRole('checkbox', { name: preguntaAtrapados.texto, checked: true }))
    await operador.click(screen.getByRole('checkbox', { name: preguntaGas.texto, checked: false }))
    await operador.click(botonDerivar())

    expect(servicio.pedidosA(derivacion).map(({ cuerpo }) => cuerpo)).toEqual([{
      ajustes: { checklist: [
        { id: preguntaAtrapados.id, respondida: false, cita: null },
        { id: preguntaGas.id, respondida: true, cita: null },
      ] },
    }])
  })

  test('Una pregunta que vuelve a su marca original no se manda como ajuste', async () => {
    const servicio = abrirLlamada()
    dejarDerivacionPendiente(servicio)
    const operador = userEvent.setup()

    const pregunta = await screen.findByRole('checkbox', { name: preguntaGas.texto, checked: false })
    await operador.click(pregunta)
    await operador.click(pregunta)
    await operador.click(botonDerivar())

    expect(servicio.pedidosA(derivacion).map(({ cuerpo }) => cuerpo)).toEqual([{ ajustes: {} }])
  })

  test('Confirmar una posible respuesta la manda con la cita que el operador tuvo a la vista', async () => {
    const servicio = abrirLlamada(conPosibleRespuesta())
    dejarDerivacionPendiente(servicio)
    const operador = userEvent.setup()

    await operador.click(await screen.findByRole('checkbox', { name: preguntaGas.texto, checked: false }))
    await operador.click(botonDerivar())

    expect(servicio.pedidosA(derivacion).map(({ cuerpo }) => cuerpo)).toEqual([{
      ajustes: { checklist: [{ id: preguntaGas.id, respondida: true, cita: citaPosible }] },
    }])
  })

  test('Una posible respuesta confirmada y vuelta a destildar sigue siendo una posible respuesta', async () => {
    const servicio = abrirLlamada(conPosibleRespuesta())
    dejarDerivacionPendiente(servicio)
    const operador = userEvent.setup()

    const pregunta = await screen.findByRole('checkbox', { name: preguntaGas.texto, checked: false })
    await operador.click(pregunta)
    await operador.click(pregunta)
    await operador.click(botonDerivar())

    expect(screen.getByText(/Posible respuesta/)).toBeTruthy()
    expect(servicio.pedidosA(derivacion).map(({ cuerpo }) => cuerpo)).toEqual([{ ajustes: {} }])
  })

  test('Una altura inválida impide derivar y recibe el foco con su error', async () => {
    const servicio = abrirLlamada()
    dejarDerivacionPendiente(servicio)
    const operador = userEvent.setup()

    await screen.findByRole('group', { name: 'Sugerencia' })
    const altura = campoAltura()
    await operador.clear(altura)
    await operador.type(altura, '15a')
    await operador.click(botonDerivar())

    expect(servicio.pedidosA(derivacion)).toEqual([])
    expect(altura.getAttribute('aria-invalid')).toBe('true')
    expect(screen.getByRole('textbox', {
      name: 'Altura (opcional)', description: /Ingresá un número entero entre 1 y 99999\./,
    })).toBe(altura)
    expect(document.activeElement).toBe(altura)
  })

  test('La validación local marca Calle y Prioridad vacías antes de enviar', async () => {
    const servicio = abrirLlamada(llamadaSinDatos)
    const pedido = `POST /api/llamadas/${llamadaSinDatos.llamada_id}/derivar`
    servicio.responder(pedido, respuestas.errorFaltaLoMinimo, 422)
    const operador = userEvent.setup()

    await screen.findByRole('group', { name: 'Sugerencia' })
    await operador.click(botonDerivar())

    expect(servicio.pedidosA(pedido)).toEqual([])
    expect(screen.getByRole('textbox', { name: 'Calle', description: /Ingresá una calle\./ })).toBeTruthy()
    expect(screen.getByRole('combobox', { name: 'Prioridad', description: /Elegí una prioridad\./ })).toBeTruthy()
  })

  test('Un 422 de derivación marca Calle y Prioridad y deja abierta la llamada', async () => {
    const servicio = abrirLlamada(llamadaSinDatos)
    const pedido = `POST /api/llamadas/${llamadaSinDatos.llamada_id}/derivar`
    servicio.responder(pedido, respuestas.errorFaltaLoMinimo, 422)
    const operador = userEvent.setup()

    // Los datos se completan para que el pedido pase la validación local y llegue al 422 simulado.
    const calle = await screen.findByRole<HTMLInputElement>('textbox', { name: 'Calle' })
    await operador.type(calle, 'Av. Corrientes')
    await operador.selectOptions(campoPrioridad(), 'P2')
    await operador.click(botonDerivar())

    await screen.findByText('Revisá los campos marcados.')
    expect(servicio.pedidosA(pedido)).toHaveLength(1)
    expect(screen.getByRole('textbox', { name: 'Calle', description: /Hace falta para derivar\./ })).toBe(calle)
    const prioridad = campoPrioridad()
    expect(screen.getByRole('combobox', { name: 'Prioridad', description: /Hace falta para derivar\./ })).toBe(prioridad)
    expect(calle.getAttribute('aria-invalid')).toBe('true')
    expect(prioridad.getAttribute('aria-invalid')).toBe('true')
    expect(botonDerivar().disabled).toBe(false)
    expect(screen.queryByRole('heading', { name: 'Carta de Llamada' })).toBeNull()
    expect(new URLSearchParams(window.location.search).get('llamada')).toBe(llamadaSinDatos.llamada_id)
  })

  test('La carta reemplaza el formulario y muestra los datos para despacho', async () => {
    const servicio = abrirLlamada()
    servicio.responder(derivacion, llamadaDelDatasetDerivada)
    servicio.responder(historial, respuestas.historialDerivada)
    const operador = userEvent.setup()

    await screen.findByRole('group', { name: 'Sugerencia' })
    await operador.click(botonDerivar())

    const titulo = await screen.findByRole('heading', { name: 'Carta de Llamada' })
    await waitFor(() => expect(document.activeElement).toBe(titulo))
    expect(screen.queryByRole('group', { name: 'Sugerencia' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Derivar Carta de Llamada' })).toBeNull()
    for (const dato of ['Av. Corrientes', '1540', 'Montevideo', 'Parana', 'Incendio o rescate', protocoloIncendio.nombre, 'P1 · Riesgo de vida ahora']) {
      expect(screen.getByText(dato)).toBeTruthy()
    }
    expect(screen.getByRole('heading', { name: 'Preguntas del protocolo' })).toBeTruthy()
    for (const { texto } of protocoloIncendio.preguntas) {
      expect(screen.getByText(texto)).toBeTruthy()
    }
    expect(screen.getByText('Respondida · Turno 2 «adentro quedó el cocinero»')).toBeTruthy()
    const instrucciones = within(screen.getByRole('region', { name: 'Instrucciones de pre-arribo del protocolo' }))
    expect(instrucciones.getByText(instruccionIncendio.texto)).toBeTruthy()
  })

  test('El historial se pide y se muestra después de derivar', async () => {
    const servicio = abrirLlamada()
    servicio.responder(derivacion, llamadaDelDatasetDerivada)
    servicio.responder(historial, respuestas.historialDerivada)
    const operador = userEvent.setup()

    await screen.findByRole('group', { name: 'Sugerencia' })
    expect(servicio.pedidosA(historial)).toEqual([])
    expect(screen.queryByRole('region', { name: 'Historial' })).toBeNull()
    await operador.click(botonDerivar())

    const region = within(await screen.findByRole('region', { name: 'Historial' }))
    expect(await region.findByText('El operador derivó la sugerencia sin cambios.')).toBeTruthy()
    expect(servicio.pedidosA(historial)).toHaveLength(1)
    const eventos = region.getAllByRole('listitem')
    expect(eventos.map(({ textContent }) => textContent))
      .toEqual(respuestas.historialDerivada.eventos.map(({ detalle }) => expect.stringContaining(detalle)))
    expect(region.getByText('0 s')).toBeTruthy()
  })

  test('Un 409 al derivar vuelve a consultar la llamada y muestra la carta', async () => {
    const servicio = abrirLlamada()
    servicio.responder(derivacion, respuestas.errorYaDerivada, 409)
    servicio.responder(historial, respuestas.historialDerivada)
    const consulta = `GET /api/llamadas/${llamadaDelDataset.llamada_id}`
    const operador = userEvent.setup()

    await screen.findByRole('group', { name: 'Sugerencia' })
    servicio.responder(consulta, llamadaDelDatasetDerivada)
    await operador.click(botonDerivar())

    expect(await screen.findByRole('heading', { name: 'Carta de Llamada' })).toBeTruthy()
    expect(screen.getByText('La llamada ya estaba derivada.')).toBeTruthy()
    expect(servicio.pedidosA(consulta)).toHaveLength(2)
  })

  test('Nueva llamada vuelve al comienzo y quita el identificador de la URL', async () => {
    abrirLlamada(llamadaDelDatasetDerivada)
    const operador = userEvent.setup()

    await screen.findByRole('heading', { name: 'Carta de Llamada' })
    await operador.click(screen.getByRole('button', { name: 'Nueva llamada' }))

    const transcripcion = screen.getByRole<HTMLTextAreaElement>('textbox', { name: 'Transcripción de la llamada' })
    expect(transcripcion.value).toBe('')
    expect(transcripcion.disabled).toBe(false)
    expect(screen.queryByRole('heading', { name: 'Carta de Llamada' })).toBeNull()
    expect(window.location.search).toBe('')
  })
})
