import { describe, expect, test } from 'vitest'
import type { Llamada, Prioridad, Sugerencia, TipoHecho } from './api'
import { actualizarBorrador, iniciarBorrador, leerAltura } from './borradorSugerencia'
import type { BorradorSugerencia, CamposSugerencia } from './borradorSugerencia'
import { respuestas } from './pruebas/respuestas'

function sugerenciaDe(llamada: Llamada) {
  if (!llamada.sugerencia) throw new Error(`La llamada ${llamada.llamada_id} no trae sugerencia`)
  return llamada.sugerencia
}

const { catalogo } = respuestas
const corrientes = sugerenciaDe(respuestas.llamadaDelDataset)
const sanJuan = sugerenciaDe(respuestas.llamadaPorTurnos)
const sanJuanConAltura = sugerenciaDe(respuestas.llamadaPorTurnosConAltura)

function conCategoria(sugerencia: Sugerencia, valor: TipoHecho) {
  const variante = structuredClone(sugerencia)
  variante.tipo_hecho = { origen: 'inferido', fuente: 'modelo', valor }
  return variante
}

function conSubtipo(sugerencia: Sugerencia, valor: string) {
  const variante = structuredClone(sugerencia)
  variante.subtipo = { origen: 'inferido', fuente: 'modelo', valor }
  return variante
}

function conPrioridad(sugerencia: Sugerencia, valor: Prioridad) {
  const variante = structuredClone(sugerencia)
  variante.prioridad = { origen: 'inferido', fuente: 'modelo', valor }
  return variante
}

function conAltura(sugerencia: Sugerencia, valor: number) {
  const variante = structuredClone(sugerencia)
  variante.ubicacion.altura = { origen: 'dicho', valor, cita: { turno: 3, texto: String(valor) } }
  return variante
}

function sinCalle(sugerencia: Sugerencia) {
  const variante = structuredClone(sugerencia)
  variante.ubicacion.calle = { origen: 'falta' }
  return variante
}

function editar<Campo extends keyof CamposSugerencia>(borrador: BorradorSugerencia, campo: Campo, valor: CamposSugerencia[Campo]) {
  return { ...borrador, campos: { ...borrador.campos, [campo]: valor }, editados: new Set([...borrador.editados, campo]) }
}

function conPreguntaDesmarcada(borrador: BorradorSugerencia) {
  const { id } = corrientes.checklist[0]
  return { ...borrador, marcas: new Map([[id, { id, respondida: false, cita: null }]]) }
}

describe('Al abrir la sugerencia', () => {
  test('los campos salen de la sugerencia y la altura se muestra como texto', () => {
    expect(iniciarBorrador(corrientes, catalogo).campos).toEqual({
      calle: 'Av. Corrientes', altura: '1540', esquinaUno: 'Montevideo', esquinaDos: 'Parana',
      categoria: 'INCENDIO_RESCATE', subtipo: 'SFX-001', prioridad: 'P1',
    })
  })

  test('el operador empieza sin ediciones, marcas ni dictados quitados', () => {
    const { editados, marcas, dictadosQuitados } = iniciarBorrador(corrientes, catalogo)
    expect({ editados, marcas, dictadosQuitados }).toEqual({
      editados: new Set(), marcas: new Map(), dictadosQuitados: new Set(),
    })
  })

  test('los datos de texto que faltan quedan vacíos', () => {
    expect(iniciarBorrador(sanJuan, catalogo).campos).toEqual({
      calle: 'Av. San Juan', altura: '', esquinaUno: '', esquinaDos: '',
      categoria: 'ACCIDENTE_VIAL', subtipo: null, prioridad: '',
    })
  })

  test('el subtipo queda vacío si el catálogo lo asigna a otra categoría', () => {
    const sugerencia = conCategoria(corrientes, 'ACCIDENTE_VIAL')
    expect(iniciarBorrador(sugerencia, catalogo).campos.subtipo).toBeNull()
  })

  test('el subtipo sugerido se conserva mientras el catálogo no está disponible', () => {
    const sugerencia = conCategoria(corrientes, 'ACCIDENTE_VIAL')
    expect(iniciarBorrador(sugerencia, null).campos.subtipo).toBe('SFX-001')
  })
})

describe('La altura escrita', () => {
  test.each(['', '   '])('el texto %j deja la altura sin número y es válido', (texto) => {
    expect(leerAltura(texto)).toEqual({ numero: null, invalida: false })
  })

  test.each([
    ['1540', 1540], [' 1540 ', 1540], ['1', 1], ['99999', 99999],
  ])('el texto %j da la altura válida %i', (texto, numero) => {
    expect(leerAltura(texto)).toEqual({ numero, invalida: false })
  })

  test.each(['0', '100000', '15a', '1.5', '-3'])('el texto %j es una altura inválida', (texto) => {
    expect(leerAltura(texto).invalida).toBe(true)
  })
})

describe('Al llegar otra sugerencia', () => {
  test('si el operador todavía no editó, aparecen la altura y las esquinas nuevas', () => {
    const borrador = iniciarBorrador(sanJuan, catalogo)
    expect(actualizarBorrador(borrador, sanJuanConAltura, catalogo).campos).toEqual({
      calle: 'Av. San Juan', altura: '2100', esquinaUno: 'Sarandi', esquinaDos: 'Rincon',
      categoria: 'ACCIDENTE_VIAL', subtipo: null, prioridad: '',
    })
  })

  test('se conserva la prioridad elegida y se actualizan los campos que el operador no tocó', () => {
    const borrador = editar(iniciarBorrador(corrientes, catalogo), 'prioridad', 'P2')
    expect(actualizarBorrador(borrador, sanJuanConAltura, catalogo).campos).toEqual({
      calle: 'Av. San Juan', altura: '2100', esquinaUno: 'Sarandi', esquinaDos: 'Rincon',
      categoria: 'ACCIDENTE_VIAL', subtipo: null, prioridad: 'P2',
    })
  })

  test('la categoría que eligió el operador se conserva aunque cambie la sugerida', () => {
    const borrador = editar(iniciarBorrador(corrientes, catalogo), 'categoria', 'EMERGENCIA_MEDICA')
    expect(actualizarBorrador(borrador, sanJuan, catalogo).campos.categoria).toBe('EMERGENCIA_MEDICA')
  })

  test('el subtipo que eligió el operador se conserva aunque se sugiera otro', () => {
    const borrador = editar(iniciarBorrador(corrientes, catalogo), 'subtipo', 'SFX-002')
    const sugerencia = conSubtipo(corrientes, 'SFX-003')
    expect(actualizarBorrador(borrador, sugerencia, catalogo).campos.subtipo).toBe('SFX-002')
  })

  test.each([
    { campo: 'calle', valor: 'Av. Entre Rios', calle: 'Av. Entre Rios', altura: '', esquinaUno: '', esquinaDos: '' },
    { campo: 'altura', valor: '2000', calle: 'Av. San Juan', altura: '2000', esquinaUno: '', esquinaDos: '' },
    { campo: 'esquinaUno', valor: 'Pichincha', calle: 'Av. San Juan', altura: '', esquinaUno: 'Pichincha', esquinaDos: '' },
    { campo: 'esquinaDos', valor: 'Combate de los Pozos', calle: 'Av. San Juan', altura: '', esquinaUno: '', esquinaDos: 'Combate de los Pozos' },
  ] as const)('editar $campo conserva la ubicación entera', ({ campo, valor, ...ubicacion }) => {
    const borrador = editar(iniciarBorrador(sanJuan, catalogo), campo, valor)
    expect(actualizarBorrador(borrador, sanJuanConAltura, catalogo).campos).toEqual({
      ...ubicacion, categoria: 'ACCIDENTE_VIAL', subtipo: null, prioridad: '',
    })
  })

  test('si se conserva la ubicación editada, la dirección nueva se ofrece como alternativa', () => {
    const borrador = editar(iniciarBorrador(sanJuan, catalogo), 'calle', 'Av. Entre Rios')
    expect(actualizarBorrador(borrador, sanJuanConAltura, catalogo).direccionAlternativa).toBe('Av. San Juan 2100')
  })

  test('un cambio de prioridad con la misma dirección sugerida no genera una alternativa', () => {
    const borrador = editar(iniciarBorrador(sanJuanConAltura, catalogo), 'calle', 'Av. Entre Rios')
    const sugerencia = conPrioridad(sanJuanConAltura, 'P2')
    expect(actualizarBorrador(borrador, sugerencia, catalogo).direccionAlternativa).toBeUndefined()
  })

  test('la dirección alternativa existente se conserva si la dirección sugerida sigue igual', () => {
    const borrador = editar(iniciarBorrador(sanJuan, catalogo), 'calle', 'Av. Entre Rios')
    const intermedio = actualizarBorrador(borrador, sanJuanConAltura, catalogo)
    const sugerencia = conPrioridad(sanJuanConAltura, 'P2')
    expect(actualizarBorrador(intermedio, sugerencia, catalogo).direccionAlternativa).toBe('Av. San Juan 2100')
  })

  test('la alternativa desaparece si la sugerencia nueva no trae calle', () => {
    const borrador = editar(iniciarBorrador(sanJuan, catalogo), 'calle', 'Av. Entre Rios')
    const intermedio = actualizarBorrador(borrador, sanJuanConAltura, catalogo)
    expect(actualizarBorrador(intermedio, sinCalle(sanJuanConAltura), catalogo).direccionAlternativa).toBeUndefined()
  })

  test('la altura editada sigue protegida después de coincidir con una sugerencia intermedia', () => {
    const borrador = editar(iniciarBorrador(sanJuan, catalogo), 'altura', '2100')
    const intermedio = actualizarBorrador(borrador, sanJuanConAltura, catalogo)
    const { campos, editados } = actualizarBorrador(intermedio, conAltura(sanJuanConAltura, 2150), catalogo)
    expect({ altura: campos.altura, editados }).toEqual({ altura: '2100', editados: new Set(['altura']) })
  })

  test('la pregunta desmarcada por el operador sigue desmarcada si el subtipo es el mismo', () => {
    const borrador = conPreguntaDesmarcada(iniciarBorrador(corrientes, catalogo))
    const sugerencia = conPrioridad(corrientes, 'P2')
    expect(actualizarBorrador(borrador, sugerencia, catalogo).marcas).toEqual(new Map([
      ['SFX-001-Q1', { id: 'SFX-001-Q1', respondida: false, cita: null }],
    ]))
  })

  test('mientras haya una pregunta marcada, el subtipo no cambia aunque se sugiera otro', () => {
    const borrador = conPreguntaDesmarcada(iniciarBorrador(corrientes, catalogo))
    const { campos, marcas } = actualizarBorrador(borrador, conSubtipo(corrientes, 'SFX-002'), catalogo)
    expect({ subtipo: campos.subtipo, marcas }).toEqual({ subtipo: 'SFX-001', marcas: borrador.marcas })
  })

  test('sin preguntas marcadas ni un subtipo elegido, el subtipo sigue al sugerido', () => {
    const borrador = iniciarBorrador(corrientes, catalogo)
    expect(actualizarBorrador(borrador, conSubtipo(corrientes, 'SFX-002'), catalogo).campos.subtipo).toBe('SFX-002')
  })

  test('las marcas se vacían si el catálogo no admite el subtipo en la categoría elegida', () => {
    const borrador = conPreguntaDesmarcada(iniciarBorrador(corrientes, null))
    const editado = editar(borrador, 'categoria', 'ACCIDENTE_VIAL')
    expect(actualizarBorrador(editado, corrientes, catalogo).marcas).toEqual(new Map())
  })

  test('los dictados que quitó el operador se recuerdan en cada actualización', () => {
    const borrador = { ...iniciarBorrador(sanJuan, catalogo), dictadosQuitados: new Set(['patente:ZA345BD']) }
    const intermedio = actualizarBorrador(borrador, sanJuanConAltura, catalogo)
    const final = actualizarBorrador(intermedio, conAltura(sanJuanConAltura, 2150), catalogo)
    expect([intermedio.dictadosQuitados, final.dictadosQuitados]).toEqual([
      new Set(['patente:ZA345BD']), new Set(['patente:ZA345BD']),
    ])
  })

  test('el borrador recibido queda intacto cuando llega otra sugerencia', () => {
    const borrador = conPreguntaDesmarcada(editar(iniciarBorrador(corrientes, catalogo), 'prioridad', 'P2'))
    const anterior = structuredClone(borrador)
    actualizarBorrador(borrador, sanJuanConAltura, catalogo)
    expect(borrador).toEqual(anterior)
  })
})
