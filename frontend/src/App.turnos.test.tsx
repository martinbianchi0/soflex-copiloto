// @vitest-environment jsdom
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, test } from 'vitest'
import App from './App'
import './pruebas/dom'
import { respuestas } from './pruebas/respuestas'
import { contestar, contestacionPendiente, simularServicio } from './pruebas/servicio'

const { llamadaPorTurnos, llamadaPorTurnosConAltura, llamadaDelDataset } = respuestas
const identificador = llamadaPorTurnos.llamada_id
const sumaDeTurno = `POST /api/llamadas/${identificador}/turnos`

function abrirLlamada(llamada = llamadaPorTurnos) {
  const identificador = llamada.llamada_id
  const servicio = simularServicio()
  servicio.responder('GET /api/health', respuestas.salud)
  servicio.responder('GET /api/catalogo', respuestas.catalogo)
  servicio.responder('GET /api/ejemplos', respuestas.ejemplos)
  servicio.responder('POST /api/mapa', respuestas.plano)
  servicio.responder(`GET /api/llamadas/${identificador}`, llamada)
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

  test('Después de sumar un turno con el botón, el foco vuelve al texto para seguir sumando', async () => {
    const servicio = abrirLlamada()
    servicio.responder(sumaDeTurno, llamadaPorTurnosConAltura)
    const operador = userEvent.setup()

    await screen.findByRole('group', { name: 'Sugerencia' })
    await operador.type(textoDelTurno(), intercambio)
    await operador.click(screen.getByRole('button', { name: 'Sumar a la llamada' }))

    await screen.findByText('Se sumó un turno. Sugerencia actualizada.')
    await waitFor(() => expect(document.activeElement).toBe(textoDelTurno()))
  })

  test('Al llegar la sugerencia actualizada se conserva el foco donde lo dejó el operador', async () => {
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

describe('Dirección alternativa del modelo', () => {
  const { llamadaConAviso } = respuestas
  const direccion = { calle: 'Aráoz', altura: 1236, esquinas: ['José A. Cabrera'] }
  const ruta = `POST /api/llamadas/${llamadaConAviso.llamada_id}`
  const derivacion = `${ruta}/derivar`
  const nombreBoton = 'Usar esta dirección'
  const mensaje = 'El modelo leyó otra dirección: Aráoz 1236, esquina José A. Cabrera. Confirmala con el llamante antes de usarla.'

  function conAlternativa() {
    const llamada = structuredClone(llamadaConAviso)
    if (!llamada.sugerencia) throw new Error('La llamada guardada no trae sugerencia')
    llamada.sugerencia.direccion_alternativa = direccion
    llamada.sugerencia.prioridad = { origen: 'inferido', valor: 'P2', fuente: 'modelo' }
    return { llamada, sugerencia: llamada.sugerencia }
  }

  function camposDeUbicacion() {
    return [
      screen.getByRole<HTMLInputElement>('textbox', { name: 'Calle' }),
      campoAltura(),
      screen.getByRole<HTMLInputElement>('textbox', { name: 'Primera esquina (opcional)' }),
      screen.getByRole<HTMLInputElement>('textbox', { name: 'Segunda esquina (opcional)' }),
    ]
  }

  test('Anuncia la alternativa y Enter en el botón carga la ubicación sin derivar', async () => {
    const servicio = abrirLlamada(conAlternativa().llamada)
    servicio.responder(derivacion, () => contestacionPendiente().promesa)
    const operador = userEvent.setup()
    const usar = await screen.findByRole('button', { name: nombreBoton })
    const derivar = screen.getByRole<HTMLButtonElement>('button', { name: 'Derivar Carta de Llamada' })
    expect(derivar.disabled).toBe(false)
    expect(usar.previousElementSibling?.textContent).toBe(mensaje)
    expect((await screen.findByText(mensaje)).closest('[aria-live="polite"]')).toBeTruthy()

    const [calle, altura, esquina, otraEsquina] = camposDeUbicacion()
    await operador.click(calle)
    await operador.tab({ shift: true })
    expect(document.activeElement).toBe(usar)
    await operador.keyboard('{Enter}')
    expect(document.activeElement).toBe(calle)
    expect(servicio.pedidosA(derivacion)).toEqual([])
    expect([calle.value, altura.value, esquina.value, otraEsquina.value])
      .toEqual(['Aráoz', '1236', 'José A. Cabrera', ''])
    for (const campo of [calle, altura, esquina]) {
      expect(campo.getAttribute('aria-describedby')).toContain(`${campo.id}-origen`)
      expect(document.getElementById(`${campo.id}-origen`)?.textContent).toBe('del operador')
    }
    expect(screen.queryByRole('button', { name: nombreBoton })).toBeNull()
    await waitFor(() => expect(servicio.pedidosA('POST /api/mapa').at(-1)?.cuerpo).toEqual(direccion))

    await operador.click(derivar)
    expect(servicio.pedidosA(derivacion).map(({ cuerpo }) => cuerpo))
      .toEqual([{ ajustes: { ubicacion: direccion } }])
  })

  test('Sin alternativa no aparece el bloque', async () => {
    abrirLlamada(llamadaConAviso)
    await screen.findByRole('group', { name: 'Sugerencia' })
    expect(screen.queryByRole('button', { name: nombreBoton })).toBeNull()
    expect(screen.queryByText(/El modelo leyó otra dirección/)).toBeNull()
  })

  test('El bloque se oculta cuando la dirección ya coincide con el formulario', async () => {
    const { llamada, sugerencia } = conAlternativa()
    sugerencia.ubicacion = {
      calle: { origen: 'inferido', valor: 'Araoz', fuente: 'callejero' },
      altura: { origen: 'inferido', valor: direccion.altura, fuente: 'callejero' },
      esquinas: [{ origen: 'inferido', valor: 'Jose A Cabrera', fuente: 'callejero' }],
    }
    abrirLlamada(llamada)
    await screen.findByRole('group', { name: 'Sugerencia' })
    expect(screen.queryByRole('button', { name: nombreBoton })).toBeNull()
    expect(screen.queryByText(/El modelo leyó otra dirección/)).toBeNull()
  })

  test('La dirección usada se conserva entera al sumar un turno', async () => {
    const { llamada } = conAlternativa()
    const nueva = structuredClone(llamadaPorTurnosConAltura)
    const turno = { texto: 'Ya salieron todos.', hablante: null }
    nueva.llamada_id = llamada.llamada_id
    nueva.turnos = [...llamada.turnos, turno]
    const servicio = abrirLlamada(llamada)
    servicio.responder(`${ruta}/turnos`, nueva)
    const operador = userEvent.setup()
    await operador.click(await screen.findByRole('button', { name: nombreBoton }))
    await operador.type(textoDelTurno(), turno.texto)
    await operador.click(screen.getByRole('button', { name: 'Sumar a la llamada' }))

    await screen.findByText('Se sumó un turno. Sugerencia actualizada.')
    expect(camposDeUbicacion().map(({ value }) => value)).toEqual(['Aráoz', '1236', 'José A. Cabrera', ''])
  })
})

describe('El protocolo cuando llega otra sugerencia', () => {
  const sumaAlDataset = `POST /api/llamadas/${llamadaDelDataset.llamada_id}/turnos`
  const [, preguntaGas] = respuestas.catalogo.protocolos[0].preguntas
  // En modo mock la ficha de una llamada del dataset no cambia: la sugerencia con otro subtipo,
  // como la que puede dar el modelo al sumar un turno, se arma acá.
  const conOtroSubtipo = structuredClone(llamadaDelDataset)
  if (conOtroSubtipo.sugerencia) {
    conOtroSubtipo.sugerencia.subtipo = { origen: 'inferido', valor: 'SFX-002', fuente: 'modelo' }
    conOtroSubtipo.sugerencia.checklist = []
  }

  async function sumarUnTurno(operador: ReturnType<typeof userEvent.setup>) {
    await operador.type(textoDelTurno(), 'Llamante: Es el contenedor de la vereda.')
    await operador.click(screen.getByRole('button', { name: 'Sumar a la llamada' }))
    await screen.findByText('Se sumó un turno. Sugerencia actualizada.')
  }

  function campoSubtipo() {
    return screen.getByRole<HTMLSelectElement>('combobox', { name: 'Subtipo (opcional)' })
  }

  test('Con una pregunta marcada, el subtipo no cambia aunque se sugiera otro', async () => {
    const servicio = abrirLlamada(llamadaDelDataset)
    servicio.responder(sumaAlDataset, conOtroSubtipo)
    const operador = userEvent.setup()

    await operador.click(await screen.findByRole('checkbox', { name: preguntaGas.texto, checked: false }))
    await sumarUnTurno(operador)

    expect(campoSubtipo().value).toBe('SFX-001')
    expect(screen.getByRole('checkbox', { name: preguntaGas.texto, checked: true })).toBeTruthy()
  })

  test('Una pregunta tildada y vuelta a destildar no fija el subtipo', async () => {
    const servicio = abrirLlamada(llamadaDelDataset)
    servicio.responder(sumaAlDataset, conOtroSubtipo)
    const operador = userEvent.setup()

    const pregunta = await screen.findByRole('checkbox', { name: preguntaGas.texto, checked: false })
    await operador.click(pregunta)
    await operador.click(pregunta)
    await sumarUnTurno(operador)

    expect(campoSubtipo().value).toBe('SFX-002')
  })
})
