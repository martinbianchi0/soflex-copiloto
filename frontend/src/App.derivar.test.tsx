// @vitest-environment jsdom
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, test } from 'vitest'
import App from './App'
import './pruebas/dom'
import { respuestas } from './pruebas/respuestas'
import { contestacionPendiente, contestar, simularServicio } from './pruebas/servicio'

const {
  llamadaDelDataset, llamadaDelDatasetDerivada, llamadaDelDatasetConTurnoTrasDerivar,
  llamadaDelDatasetActualizada, llamadaDelDatasetTerminada, llamadaSinDatos,
  llamadaPorTurnosDerivada, historialTerminada,
} = respuestas
const protocoloIncendio = respuestas.catalogo.protocolos.find(({ id }) => id === 'SFX-001')!
const [preguntaAtrapados, preguntaGas] = protocoloIncendio.preguntas
const [instruccionIncendio] = protocoloIncendio.instrucciones
const ruta = `/api/llamadas/${llamadaDelDataset.llamada_id}`
const consulta = `GET ${ruta}`
const derivacion = `POST ${ruta}/derivar`
const actualizacion = `POST ${ruta}/actualizaciones`
const terminacion = `POST ${ruta}/terminar`
const historial = `GET ${ruta}/historial`
const derivadaAlDia = /^Carta derivada a las \d{2}:\d{2}\. Está al día\.$/
const actualizadaAlDia = /^Carta derivada a las \d{2}:\d{2}, actualizada a las \d{2}:\d{2}\. Está al día\.$/

function abrirLlamada(llamada = llamadaDelDataset) {
  const servicio = simularServicio()
  servicio.responder('GET /api/health', respuestas.salud)
  servicio.responder('GET /api/catalogo', respuestas.catalogo)
  servicio.responder('GET /api/ejemplos', respuestas.ejemplos)
  servicio.responder('POST /api/mapa', respuestas.plano)
  const { llamada_id: identificador } = llamada
  servicio.responder(`GET /api/llamadas/${identificador}`, llamada)
  if (llamada.estado === 'terminada') {
    servicio.responder(historial, historialTerminada)
  } else {
    const duplicados = structuredClone(respuestas.duplicadosSinOtra)
    duplicados.llamada_id = identificador
    servicio.responder(`GET /api/llamadas/${identificador}/duplicados`, duplicados)
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

function botonActualizar() {
  return screen.getByRole<HTMLButtonElement>('button', { name: 'Actualizar carta' })
}

function cartaAlDia(descripcion = /Está al día\.$/) {
  return screen.findByRole<HTMLButtonElement>('button', { name: 'Actualizar carta', description: descripcion })
}

function campoAltura() {
  return screen.getByRole<HTMLInputElement>('textbox', { name: 'Altura (opcional)' })
}

function campoPrioridad() {
  return screen.getByRole<HTMLSelectElement>('combobox', { name: 'Prioridad' })
}

function anuncio(texto: string) {
  return screen.findByText(texto, { selector: '[aria-live="polite"] span' })
}

const AVISO_YA_DERIVADA = 'La llamada ya estaba derivada. Lo que tenés en pantalla sigue acá: si hay cambios, actualizá la carta.'

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

  test('Después de derivar sigue el formulario y la carta figura al día', async () => {
    const servicio = abrirLlamada()
    servicio.responder(derivacion, llamadaDelDatasetDerivada)
    const operador = userEvent.setup()

    await screen.findByRole('group', { name: 'Sugerencia' })
    await operador.click(botonDerivar())

    await anuncio('Carta derivada. La llamada sigue abierta: podés seguir con el protocolo.')
    expect(screen.getByRole('group', { name: 'Sugerencia' })).toBeTruthy()
    expect(screen.getByRole('region', { name: 'Protocolo' })).toBeTruthy()
    expect((await cartaAlDia(derivadaAlDia)).disabled).toBe(true)
    expect(screen.getByRole<HTMLButtonElement>('button', { name: 'Terminar llamada' }).disabled).toBe(false)
    expect(screen.getByRole('button', { name: 'Nueva llamada' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Derivar Carta de Llamada' })).toBeNull()
    expect(screen.queryByRole('heading', { name: 'Carta de Llamada' })).toBeNull()
    expect(screen.queryByRole('region', { name: 'Historial' })).toBeNull()
    expect(servicio.pedidosA(historial)).toEqual([])
    // El botón quedó deshabilitado mientras se mandaba: el foco pasa a la línea que dice si la carta
    // está al día, no se pierde.
    expect(document.activeElement?.textContent).toMatch(/^Carta derivada a las \d\d:\d\d\. Está al día\.$/)
  })

  test('Si la carta sale con avisos, los anuncia y deja abierta la llamada', async () => {
    // El primer intercambio y la carta de la derivación temprana tienen identificadores distintos.
    const llamada = structuredClone(respuestas.llamadaPorTurnos)
    llamada.llamada_id = llamadaPorTurnosDerivada.llamada_id
    const servicio = abrirLlamada(llamada)
    const pedido = `POST /api/llamadas/${llamada.llamada_id}/derivar`
    servicio.responder(pedido, llamadaPorTurnosDerivada)
    const operador = userEvent.setup()

    await operador.selectOptions(await screen.findByRole('combobox', { name: 'Prioridad' }), 'P1')
    await operador.click(botonDerivar())

    await anuncio('Carta derivada. Hay avisos sin confirmar. La llamada sigue abierta: podés seguir con el protocolo.')
    expect(servicio.pedidosA(pedido).map(({ cuerpo }) => cuerpo)).toEqual([{ ajustes: { prioridad: 'P1' } }])
    expect(botonActualizar().disabled).toBe(true)
  })

  test('Un 409 al derivar vuelve a consultar la llamada y conserva lo que el operador tenía en pantalla', async () => {
    const servicio = abrirLlamada()
    const respuestaDeConsulta = contestacionPendiente()
    servicio.responder(derivacion, respuestas.errorYaDerivada, 409)
    const operador = userEvent.setup()

    await operador.selectOptions(await screen.findByRole('combobox', { name: 'Prioridad' }), 'P3')
    servicio.responder(consulta, () => respuestaDeConsulta.promesa)
    await operador.click(botonDerivar())

    await waitFor(() => expect(servicio.pedidosA(consulta)).toHaveLength(2))
    await act(async () => respuestaDeConsulta.entregar(contestar(llamadaDelDatasetActualizada)))
    await screen.findByText(AVISO_YA_DERIVADA)
    expect(screen.getByRole('group', { name: 'Sugerencia' })).toBeTruthy()
    expect(screen.queryByRole('heading', { name: 'Carta de Llamada' })).toBeNull()
    // La carta guardada tiene P2; la P3 que eligió el operador sigue, para mandarla si corresponde.
    expect(campoPrioridad().value).toBe('P3')
    expect(screen.getByText('Hay cambios que la carta no tiene.')).toBeTruthy()
    expect(botonActualizar().disabled).toBe(false)
  })

  test('Un 409 con una consulta rápida da lo mismo', async () => {
    const servicio = abrirLlamada()
    servicio.responder(derivacion, respuestas.errorYaDerivada, 409)
    const operador = userEvent.setup()

    await operador.selectOptions(await screen.findByRole('combobox', { name: 'Prioridad' }), 'P3')
    servicio.responder(consulta, llamadaDelDatasetActualizada)
    await act(async () => { await operador.click(botonDerivar()) })

    await screen.findByText(AVISO_YA_DERIVADA)
    expect(campoPrioridad().value).toBe('P3')
    expect(botonActualizar().disabled).toBe(false)
  })

  test('Nueva llamada vuelve al comienzo y quita el identificador de la URL', async () => {
    abrirLlamada(llamadaDelDatasetDerivada)
    const operador = userEvent.setup()

    await screen.findByRole('button', { name: 'Actualizar carta' })
    await operador.click(screen.getByRole('button', { name: 'Nueva llamada' }))

    const transcripcion = screen.getByRole<HTMLTextAreaElement>('textbox', { name: 'Transcripción de la llamada' })
    expect(transcripcion.value).toBe('')
    expect(transcripcion.disabled).toBe(false)
    expect(screen.queryByRole('group', { name: 'Sugerencia' })).toBeNull()
    expect(window.location.search).toBe('')
  })
})

describe('Actualizar la carta', () => {
  test('Cambiar la prioridad deja la carta pendiente hasta que se manda la actualización', async () => {
    const servicio = abrirLlamada(llamadaDelDatasetConTurnoTrasDerivar)
    servicio.responder(actualizacion, llamadaDelDatasetActualizada)
    const operador = userEvent.setup()
    await cartaAlDia()

    await operador.selectOptions(campoPrioridad(), 'P2')

    expect(screen.getByText('Hay cambios que la carta no tiene.')).toBeTruthy()
    expect(botonActualizar().disabled).toBe(false)
    expect(servicio.pedidosA(actualizacion)).toEqual([])
    await operador.click(botonActualizar())

    await anuncio('Carta actualizada.')
    expect(servicio.pedidosA(actualizacion).map(({ cuerpo }) => cuerpo)).toEqual([{ ajustes: { prioridad: 'P2' } }])
    expect((await cartaAlDia(actualizadaAlDia)).disabled).toBe(true)
  })

  test('Volver a la prioridad de la carta la deja al día sin mandar una actualización', async () => {
    const servicio = abrirLlamada(llamadaDelDatasetActualizada)
    const operador = userEvent.setup()
    await cartaAlDia()

    await operador.selectOptions(campoPrioridad(), 'P3')
    expect(screen.getByText('Hay cambios que la carta no tiene.')).toBeTruthy()
    expect(botonActualizar().disabled).toBe(false)
    await operador.selectOptions(campoPrioridad(), 'P2')

    expect((await cartaAlDia()).disabled).toBe(true)
    expect(servicio.pedidosA(actualizacion)).toEqual([])
  })

  test('Si el servicio devuelve la misma carta, queda al día y se anuncia que no cambió', async () => {
    // El panel todavía tiene un estado pendiente, pero al actualizar ya corresponde la misma carta.
    const pendiente = structuredClone(llamadaDelDatasetActualizada)
    pendiente.carta_al_dia = false
    const servicio = abrirLlamada(pendiente)
    servicio.responder(actualizacion, llamadaDelDatasetActualizada)
    const operador = userEvent.setup()

    await screen.findByText('Hay cambios que la carta no tiene.')
    await operador.click(botonActualizar())

    await anuncio('La carta ya tenía todo: no cambió.')
    expect(servicio.pedidosA(actualizacion).map(({ cuerpo }) => cuerpo)).toEqual([{ ajustes: { prioridad: 'P2' } }])
    expect((await cartaAlDia()).disabled).toBe(true)
  })

  test('Ctrl+Enter manda todos los ajustes, incluidos los que la carta ya tenía', async () => {
    const servicio = abrirLlamada(llamadaDelDatasetActualizada)
    servicio.responder(actualizacion, () => contestacionPendiente().promesa)
    const operador = userEvent.setup()
    await cartaAlDia()

    await operador.clear(campoAltura())
    await operador.type(campoAltura(), '1550')
    await operador.keyboard('{Control>}{Enter}{/Control}')

    expect(servicio.pedidosA(actualizacion).map(({ cuerpo }) => cuerpo)).toEqual([{
      ajustes: {
        prioridad: 'P2',
        ubicacion: { calle: 'Av. Corrientes', altura: 1550, esquinas: ['Montevideo', 'Parana'] },
      },
    }])
  })

  test('Ctrl+Enter con la carta al día no manda ningún pedido', async () => {
    const servicio = abrirLlamada(llamadaDelDatasetActualizada)
    const operador = userEvent.setup()
    await cartaAlDia()
    await operador.click(campoPrioridad())
    const cantidadDePedidos = servicio.pedidos.length

    await operador.keyboard('{Control>}{Enter}{/Control}')

    expect(servicio.pedidos).toHaveLength(cantidadDePedidos)
    expect(botonActualizar().disabled).toBe(true)
  })

  test('Un 409 al actualizar muestra la carta si la llamada ya estaba terminada', async () => {
    const servicio = abrirLlamada(llamadaDelDatasetConTurnoTrasDerivar)
    const conflicto = structuredClone(respuestas.errorYaDerivada)
    conflicto.detail = 'La llamada no está esperando al operador.'
    servicio.responder(actualizacion, conflicto, 409)
    servicio.responder(historial, historialTerminada)
    const operador = userEvent.setup()

    await operador.selectOptions(await screen.findByRole('combobox', { name: 'Prioridad' }), 'P2')
    servicio.responder(consulta, llamadaDelDatasetTerminada)
    await operador.click(botonActualizar())

    await screen.findByRole('heading', { name: 'Carta de Llamada' })
    expect(screen.getByText('La llamada ya estaba terminada.')).toBeTruthy()
    expect(screen.queryByRole('group', { name: 'Sugerencia' })).toBeNull()
    expect(servicio.pedidosA(actualizacion)).toHaveLength(1)
    expect(servicio.pedidosA(consulta)).toHaveLength(2)
  })
})

describe('Abrir una llamada con carta', () => {
  test.each([
    { llamada: llamadaDelDatasetActualizada, prioridad: 'P2', descripcion: actualizadaAlDia },
    { llamada: llamadaPorTurnosDerivada, prioridad: 'P1', descripcion: derivadaAlDia },
  ])('Al abrir por URL se restaura $prioridad como elección del operador y la carta figura al día', async ({
    llamada, prioridad, descripcion,
  }) => {
    abrirLlamada(llamada)

    const campo = await screen.findByRole<HTMLSelectElement>('combobox', { name: 'Prioridad', description: /^del operador\b/ })
    expect(campo.value).toBe(prioridad)
    expect((await cartaAlDia(descripcion)).disabled).toBe(true)
  })

  test('La llamada terminada muestra los datos para despacho y la última actualización', async () => {
    abrirLlamada(llamadaDelDatasetTerminada)

    const titulo = await screen.findByRole('heading', { name: 'Carta de Llamada' })
    await waitFor(() => expect(document.activeElement).toBe(titulo))
    expect(screen.queryByRole('group', { name: 'Sugerencia' })).toBeNull()
    for (const dato of [
      'Av. Corrientes', '1540', 'Montevideo', 'Parana', 'Incendio o rescate', protocoloIncendio.nombre,
      'P2 · Urgente, sin riesgo de vida inmediato',
    ]) {
      expect(screen.getByText(dato)).toBeTruthy()
    }
    const ultimaActualizacion = screen.getByText('Última actualización')
    expect(ultimaActualizacion.nextElementSibling?.querySelector('time')?.dateTime)
      .toBe(llamadaDelDatasetTerminada.carta?.actualizada_en)
    expect(screen.getByRole('heading', { name: 'Preguntas del protocolo' })).toBeTruthy()
    for (const { texto } of protocoloIncendio.preguntas) {
      expect(screen.getByText(texto)).toBeTruthy()
    }
    expect(screen.getByText('Respondida · Turno 2 «adentro quedó el cocinero»')).toBeTruthy()
    const instrucciones = within(screen.getByRole('region', { name: 'Instrucciones de pre-arribo del protocolo' }))
    expect(instrucciones.getByText(instruccionIncendio.texto)).toBeTruthy()
  })
})

describe('Terminar la llamada', () => {
  test('Con la carta al día sólo pide terminar y entonces muestra el historial', async () => {
    const servicio = abrirLlamada(llamadaDelDatasetActualizada)
    servicio.responder(terminacion, llamadaDelDatasetTerminada)
    servicio.responder(historial, historialTerminada)
    const operador = userEvent.setup()
    const terminar = await screen.findByRole('button', { name: 'Terminar llamada' })
    expect(servicio.pedidosA(historial)).toEqual([])
    expect(screen.queryByRole('region', { name: 'Historial' })).toBeNull()

    await operador.click(terminar)

    await anuncio('Llamada terminada.')
    expect(servicio.pedidosA(terminacion).map(({ cuerpo }) => cuerpo)).toEqual([undefined])
    expect(servicio.pedidosA(actualizacion)).toEqual([])
    const region = within(await screen.findByRole('region', { name: 'Historial' }))
    expect(await region.findByRole('table', { name: 'Qué cambió el operador' })).toBeTruthy()
    expect(servicio.pedidosA(historial)).toHaveLength(1)
    const eventos = region.getAllByRole('listitem')
    expect(eventos.map(({ textContent }) => textContent))
      .toEqual(historialTerminada.eventos.map(({ detalle }) => expect.stringContaining(detalle)))
    expect(region.getByText('0 s')).toBeTruthy()
  })

  test('Con cambios pendientes espera que se actualice la carta antes de terminar', async () => {
    const servicio = abrirLlamada(llamadaDelDatasetConTurnoTrasDerivar)
    const respuestaDeActualizacion = contestacionPendiente()
    servicio.responder(actualizacion, () => respuestaDeActualizacion.promesa)
    servicio.responder(terminacion, llamadaDelDatasetTerminada)
    servicio.responder(historial, historialTerminada)
    const operador = userEvent.setup()

    await operador.selectOptions(await screen.findByRole('combobox', { name: 'Prioridad' }), 'P2')
    await operador.click(screen.getByRole('button', { name: 'Actualizar y terminar' }))

    expect(servicio.pedidosA(actualizacion).map(({ cuerpo }) => cuerpo)).toEqual([{ ajustes: { prioridad: 'P2' } }])
    expect(servicio.pedidosA(terminacion)).toEqual([])
    await act(async () => respuestaDeActualizacion.entregar(contestar(llamadaDelDatasetActualizada)))

    await anuncio('Carta actualizada. Llamada terminada.')
    expect(servicio.pedidosA(terminacion).map(({ cuerpo }) => cuerpo)).toEqual([undefined])
    expect(screen.getByRole('heading', { name: 'Carta de Llamada' })).toBeTruthy()
  })

  test('Si la actualización da 422, deja los errores a la vista y la llamada abierta', async () => {
    const servicio = abrirLlamada(llamadaDelDatasetConTurnoTrasDerivar)
    servicio.responder(actualizacion, respuestas.errorFaltaLoMinimo, 422)
    const operador = userEvent.setup()

    await operador.selectOptions(await screen.findByRole('combobox', { name: 'Prioridad' }), 'P2')
    await operador.click(screen.getByRole('button', { name: 'Actualizar y terminar' }))

    await screen.findByText('Revisá los campos marcados.')
    expect(servicio.pedidosA(actualizacion)).toHaveLength(1)
    expect(servicio.pedidosA(terminacion)).toEqual([])
    expect(screen.getByRole('textbox', { name: 'Calle', description: /Hace falta para derivar\./ })).toBeTruthy()
    expect(screen.getByRole('combobox', { name: 'Prioridad', description: /Hace falta para derivar\./ })).toBeTruthy()
    expect(campoPrioridad().value).toBe('P2')
    expect(botonActualizar().disabled).toBe(false)
    expect(screen.queryByRole('heading', { name: 'Carta de Llamada' })).toBeNull()
  })
})
