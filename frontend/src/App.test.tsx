// @vitest-environment jsdom
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, test } from 'vitest'
import App from './App'
import './pruebas/dom'
import { respuestas } from './pruebas/respuestas'
import { contestar, contestacionPendiente, simularServicio } from './pruebas/servicio'

const { llamadaConAviso, llamadaDelDataset, llamadaSinDatos } = respuestas
const ejemploIncendio = respuestas.ejemplos.find(({ id }) => id === 'SFX-001')!
const protocoloIncendio = respuestas.catalogo.protocolos.find(({ id }) => id === 'SFX-001')!
const [preguntaAtrapados, preguntaGas] = protocoloIncendio.preguntas
const [instruccionIncendio] = protocoloIncendio.instrucciones
const alta = 'POST /api/llamadas'
const derivacion = `POST /api/llamadas/${llamadaDelDataset.llamada_id}/derivar`

function prepararServicio() {
  const servicio = simularServicio()
  servicio.responder('GET /api/health', respuestas.salud)
  servicio.responder('GET /api/catalogo', respuestas.catalogo)
  servicio.responder('GET /api/ejemplos', respuestas.ejemplos)
  servicio.responder('POST /api/mapa', respuestas.plano)
  return servicio
}

function duplicadosSinOtraDe(identificador: string) {
  if (identificador === respuestas.duplicadosSinOtra.llamada_id) return respuestas.duplicadosSinOtra
  // Variante sin duplicados para los otros identificadores guardados.
  const duplicados = structuredClone(respuestas.duplicadosSinOtra)
  duplicados.llamada_id = identificador
  return duplicados
}

function responderDuplicados(servicio: ReturnType<typeof simularServicio>, identificador: string) {
  servicio.responder(`GET /api/llamadas/${identificador}/duplicados`, duplicadosSinOtraDe(identificador))
}

function altaMientrasAnaliza() {
  // Variante del alta que devuelve el servicio con modelo antes de completar el análisis.
  return { ...structuredClone(llamadaDelDataset), estado: 'analizando' }
}

function abrirLlamada(llamada = llamadaDelDataset) {
  const servicio = prepararServicio()
  const { llamada_id: identificador } = llamada
  servicio.responder(`GET /api/llamadas/${identificador}`, llamada)
  responderDuplicados(servicio, identificador)
  window.history.replaceState(null, '', `/?llamada=${identificador}`)
  render(<App />)
  return servicio
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

describe('Entrar y analizar', () => {
  test('El panel muestra en qué modo corre el servicio', async () => {
    prepararServicio()
    render(<App />)

    expect(await screen.findByText('Modo: mock')).toBeTruthy()
  })

  test('Elegir un ejemplo carga su transcripción', async () => {
    prepararServicio()
    const operador = userEvent.setup()
    render(<App />)

    await operador.selectOptions(await screen.findByLabelText('Cargar un ejemplo'), `${ejemploIncendio.id} · ${ejemploIncendio.titulo}`)

    expect(screen.getByRole<HTMLTextAreaElement>('textbox', { name: 'Transcripción de la llamada' }).value)
      .toBe(ejemploIncendio.texto)
  })

  test('Analizar el ejemplo envía la transcripción y abre la sugerencia del servicio', async () => {
    const servicio = prepararServicio()
    servicio.responder(alta, llamadaDelDataset, 201)
    responderDuplicados(servicio, llamadaDelDataset.llamada_id)
    const operador = userEvent.setup()
    render(<App />)

    await operador.selectOptions(await screen.findByLabelText('Cargar un ejemplo'), ejemploIncendio.id)
    await operador.click(screen.getByRole('button', { name: 'Analizar llamada' }))

    await screen.findByRole('group', { name: 'Sugerencia' })
    expect(servicio.pedidosA(alta).map(({ cuerpo }) => cuerpo)).toEqual([{ turnos: [{ texto: ejemploIncendio.texto }] }])
    expect(screen.getByRole<HTMLInputElement>('textbox', { name: 'Calle' }).value).toBe('Av. Corrientes')
    expect(campoAltura().value).toBe('1540')
    expect(screen.getByRole<HTMLInputElement>('textbox', { name: 'Primera esquina (opcional)' }).value).toBe('Montevideo')
    expect(screen.getByRole<HTMLInputElement>('textbox', { name: 'Segunda esquina (opcional)' }).value).toBe('Parana')
    expect(screen.getByRole<HTMLOptionElement>('option', { name: 'Incendio o rescate', selected: true }).value).toBe('INCENDIO_RESCATE')
    expect(screen.getByRole<HTMLOptionElement>('option', { name: protocoloIncendio.nombre, selected: true }).value).toBe('SFX-001')
    expect(campoPrioridad().value).toBe('P1')
    expect(new URLSearchParams(window.location.search).get('llamada')).toBe(llamadaDelDataset.llamada_id)
  })

  test('Ctrl+Enter en la transcripción analiza la llamada', async () => {
    const servicio = prepararServicio()
    servicio.responder(alta, llamadaSinDatos, 201)
    responderDuplicados(servicio, llamadaSinDatos.llamada_id)
    const operador = userEvent.setup()
    render(<App />)

    const transcripcion = await screen.findByRole('textbox', { name: 'Transcripción de la llamada', description: '' })
    await operador.type(transcripcion, 'Hola, ¿me escuchan?')
    await operador.keyboard('{Control>}{Enter}{/Control}')

    expect(servicio.pedidosA(alta).map(({ cuerpo }) => cuerpo)).toEqual([{ turnos: [{ texto: 'Hola, ¿me escuchan?' }] }])
    expect(await screen.findByRole('group', { name: 'Sugerencia' })).toBeTruthy()
  })

  test('Enter solo en la transcripción agrega un renglón', async () => {
    const servicio = prepararServicio()
    servicio.responder(alta, () => contestacionPendiente().promesa)
    const operador = userEvent.setup()
    render(<App />)

    const transcripcion = await screen.findByRole<HTMLTextAreaElement>('textbox', { name: 'Transcripción de la llamada', description: '' })
    await operador.type(transcripcion, 'Hola{Enter}¿Me escuchan?')

    expect(servicio.pedidosA(alta)).toEqual([])
    expect(transcripcion.value).toBe('Hola\n¿Me escuchan?')
  })

  test('Al abrir una URL con llamada se consulta y muestra esa llamada', async () => {
    const servicio = abrirLlamada()

    expect((await screen.findByRole<HTMLInputElement>('textbox', { name: 'Calle' })).value).toBe('Av. Corrientes')
    expect(servicio.pedidosA(`GET /api/llamadas/${llamadaDelDataset.llamada_id}`)).toHaveLength(1)
    const transcripcion = within(screen.getByRole('region', { name: 'Transcripción de la llamada' }))
    expect(transcripcion.getByText('911 emergencias, ¿dónde es su urgencia?')).toBeTruthy()
  })

  test('Una llamada inexistente se avisa y deja empezar otra', async () => {
    const servicio = prepararServicio()
    servicio.responder('GET /api/llamadas/inexistente', respuestas.errorLlamadaInexistente, 404)
    window.history.replaceState(null, '', '/?llamada=inexistente')
    const operador = userEvent.setup()
    render(<App />)

    expect(await screen.findByText('No existe esa llamada.')).toBeTruthy()
    await operador.click(screen.getByRole('button', { name: 'Nueva llamada' }))

    expect(screen.getByRole<HTMLTextAreaElement>('textbox', { name: 'Transcripción de la llamada' }).disabled).toBe(false)
    expect(window.location.search).toBe('')
  })

  test('Si falla la conexión al analizar se conserva lo escrito', async () => {
    const servicio = prepararServicio()
    servicio.responder(alta, async () => { throw new TypeError('Falló la conexión') })
    const operador = userEvent.setup()
    render(<App />)

    const transcripcion = await screen.findByRole<HTMLTextAreaElement>('textbox', { name: 'Transcripción de la llamada', description: '' })
    await operador.type(transcripcion, 'Hola, ¿me escuchan?')
    await operador.click(screen.getByRole('button', { name: 'Analizar llamada' }))

    expect(await screen.findByText('No se pudo conectar con el servicio.')).toBeTruthy()
    expect(transcripcion.value).toBe('Hola, ¿me escuchan?')
  })
})

describe('La sugerencia', () => {
  test.each([
    { campo: 'Calle', llamada: llamadaSinDatos },
    { campo: 'Prioridad', llamada: llamadaConAviso },
  ])('Al quedar lista la sugerencia el foco va a $campo, el primer dato faltante', async ({ campo, llamada }) => {
    abrirLlamada(llamada)

    const faltante = await screen.findByLabelText(campo)
    await waitFor(() => expect(document.activeElement).toBe(faltante))
  })

  test('Si la sugerencia está completa el foco queda en la transcripción', async () => {
    abrirLlamada()

    const transcripcion = await screen.findByRole('region', { name: 'Transcripción de la llamada' })
    await waitFor(() => expect(document.activeElement).toBe(transcripcion))
  })

  test('El aviso de dirección que no cierra aparece arriba de los campos de la sugerencia', async () => {
    abrirLlamada(llamadaConAviso)

    const sugerencia = within(await screen.findByRole('group', { name: 'Sugerencia' }))
    const aviso = sugerencia.getByText('La altura 5000 no coincide con Av. Callao. Leele la dirección de vuelta al llamante.')
    expect(aviso.compareDocumentPosition(sugerencia.getByRole('textbox', { name: 'Calle' })) & Node.DOCUMENT_POSITION_FOLLOWING)
      .toBeTruthy()
  })

  test('El aviso de dirección que no cierra no impide derivar', async () => {
    const servicio = abrirLlamada(llamadaConAviso)
    const pedido = `POST /api/llamadas/${llamadaConAviso.llamada_id}/derivar`
    servicio.responder(pedido, () => contestacionPendiente().promesa)
    const operador = userEvent.setup()

    await screen.findByRole('group', { name: 'Sugerencia' })
    await operador.selectOptions(campoPrioridad(), 'P2')
    await operador.click(botonDerivar())

    expect(servicio.pedidosA(pedido).map(({ cuerpo }) => cuerpo)).toEqual([{ ajustes: { prioridad: 'P2' } }])
  })

  test.each([
    { nombre: 'Calle', descripcion: 'dicho Turno 2 · «Av. Corrientes»' },
    { nombre: 'Altura (opcional)', descripcion: 'dicho Turno 2 · «1540»' },
    { nombre: 'Primera esquina (opcional)', descripcion: 'dicho Turno 2 · «Montevideo»' },
    { nombre: 'Segunda esquina (opcional)', descripcion: 'inferido · callejero' },
    { nombre: 'Tipo de hecho', descripcion: 'ficha del dataset' },
    { nombre: 'Subtipo (opcional)', descripcion: 'ficha del dataset' },
    { nombre: 'Prioridad', descripcion: /^ficha del dataset\b/ },
  ])('$nombre muestra el origen del dato sugerido', async ({ nombre, descripcion }) => {
    abrirLlamada()

    await screen.findByRole('group', { name: 'Sugerencia' })
    const control = screen.getByLabelText(nombre)
    const rol = control instanceof HTMLSelectElement ? 'combobox' : 'textbox'
    expect(screen.getByRole(rol, { name: nombre, description: descripcion })).toBe(control)
  })

  test('Al corregir la calle se oculta su cita y al restaurar el valor vuelve', async () => {
    abrirLlamada()
    const operador = userEvent.setup()
    const calle = await screen.findByRole('textbox', { name: 'Calle', description: 'dicho Turno 2 · «Av. Corrientes»' })

    await operador.clear(calle)
    await operador.type(calle, 'Av. Córdoba')
    expect(screen.getByRole('textbox', { name: 'Calle', description: 'del operador' })).toBe(calle)
    expect(screen.queryByText('Turno 2 · «Av. Corrientes»')).toBeNull()

    await operador.clear(calle)
    await operador.type(calle, 'Av. Corrientes')
    expect(screen.getByRole('textbox', { name: 'Calle', description: 'dicho Turno 2 · «Av. Corrientes»' })).toBe(calle)
    expect(screen.getByText('Turno 2 · «Av. Corrientes»')).toBeTruthy()
  })

  test('El subtipo elegido muestra las preguntas y las instrucciones del catálogo', async () => {
    abrirLlamada(llamadaConAviso)
    const operador = userEvent.setup()
    const subtipo = await screen.findByRole('combobox', { name: 'Subtipo (opcional)' })

    await operador.selectOptions(subtipo, protocoloIncendio.nombre)

    const preguntas = within(screen.getByRole('region', { name: 'Preguntas del protocolo' }))
    for (const { texto } of protocoloIncendio.preguntas) {
      expect(preguntas.getByRole('checkbox', { name: texto })).toBeTruthy()
    }
    const instrucciones = within(screen.getByRole('region', { name: 'Leele al llamante, textual' }))
    expect(instrucciones.getByText(instruccionIncendio.texto)).toBeTruthy()
  })

  test('Al quitar el subtipo desaparecen sus preguntas e instrucciones', async () => {
    abrirLlamada()
    const operador = userEvent.setup()
    const subtipo = await screen.findByRole('combobox', { name: 'Subtipo (opcional)' })

    await operador.selectOptions(subtipo, 'Sin subtipo')

    expect(screen.queryByRole('checkbox')).toBeNull()
    expect(screen.queryByRole('heading', { name: 'Leele al llamante, textual' })).toBeNull()
  })

  test('Sin subtipo, el bloque del protocolo dice que falta y lo explica', async () => {
    abrirLlamada()
    const operador = userEvent.setup()
    const subtipo = await screen.findByRole('combobox', { name: 'Subtipo (opcional)' })
    const protocolo = within(screen.getByRole('region', { name: 'Protocolo' }))
    expect(protocolo.queryByText('Falta el subtipo.')).toBeNull()

    await operador.selectOptions(subtipo, 'Sin subtipo')

    expect(protocolo.getByText('Falta el subtipo.')).toBeTruthy()
    expect(subtipo.getAttribute('aria-describedby')).toContain('ayuda-subtipo')
    expect(document.getElementById('ayuda-subtipo')?.textContent).toMatch(/elegilo en «Hecho y prioridad»/)
  })

  test('La pregunta respondida por el servicio llega tildada con su cita', async () => {
    abrirLlamada()

    expect(await screen.findByRole('checkbox', {
      name: preguntaAtrapados.texto, checked: true, description: 'Turno 2 · «adentro quedó el cocinero»',
    })).toBeTruthy()
  })

  test('El checklist indica qué preguntas marcó y desmarcó el operador', async () => {
    abrirLlamada()
    const operador = userEvent.setup()
    await operador.click(await screen.findByRole('checkbox', { name: preguntaAtrapados.texto, checked: true }))
    await operador.click(screen.getByRole('checkbox', { name: preguntaGas.texto, checked: false }))

    expect(screen.getByRole('checkbox', {
      name: preguntaAtrapados.texto, checked: false, description: 'desmarcada por vos',
    })).toBeTruthy()
    expect(screen.getByRole('checkbox', { name: preguntaGas.texto, checked: true, description: 'marcada por vos' })).toBeTruthy()
  })
})

test('Mientras el modelo analiza se avisa y no se puede derivar hasta que responda', async () => {
  const servicio = prepararServicio()
  servicio.responder(alta, altaMientrasAnaliza(), 201)
  responderDuplicados(servicio, llamadaDelDataset.llamada_id)
  const analisis = `POST /api/llamadas/${llamadaDelDataset.llamada_id}/analisis`
  const pendiente = contestacionPendiente()
  servicio.responder(analisis, () => pendiente.promesa)
  servicio.responder(derivacion, () => contestacionPendiente().promesa)
  const operador = userEvent.setup()
  render(<App />)

  await operador.selectOptions(await screen.findByLabelText('Cargar un ejemplo'), ejemploIncendio.id)
  await operador.click(screen.getByRole('button', { name: 'Analizar llamada' }))

  expect((await screen.findByRole('status')).textContent).toContain('El modelo está leyendo la llamada')
  expect(servicio.pedidosA(analisis)).toHaveLength(1)
  expect(botonDerivar().disabled).toBe(true)
  expect(screen.getByRole('textbox', { name: 'Calle' }).matches(':disabled')).toBe(true)
  await operador.click(botonDerivar())
  expect(servicio.pedidosA(derivacion)).toEqual([])

  await act(async () => pendiente.entregar(contestar(llamadaDelDataset)))

  expect(botonDerivar().disabled).toBe(false)
  expect(screen.getByRole('textbox', { name: 'Calle' }).matches(':disabled')).toBe(false)
  expect(screen.queryByText(/El modelo está leyendo la llamada/)).toBeNull()
})
