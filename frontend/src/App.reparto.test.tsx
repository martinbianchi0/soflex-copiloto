// @vitest-environment jsdom
import { render, screen, within } from '@testing-library/react'
import { describe, expect, test } from 'vitest'
import { explicacionOrigen } from './api'
import App from './App'
import './pruebas/dom'
import { respuestas } from './pruebas/respuestas'
import { simularServicio } from './pruebas/servicio'

const { llamadaConAviso, llamadaDelDataset } = respuestas

function abrirLlamada(llamada = llamadaDelDataset) {
  const identificador = llamada.llamada_id
  const servicio = simularServicio()
  servicio.responder('GET /api/health', respuestas.salud)
  servicio.responder('GET /api/catalogo', respuestas.catalogo)
  servicio.responder('GET /api/ejemplos', respuestas.ejemplos)
  servicio.responder('POST /api/mapa', respuestas.plano)
  servicio.responder(`GET /api/llamadas/${identificador}`, llamada)
  const duplicados = structuredClone(respuestas.duplicadosSinOtra)
  duplicados.llamada_id = identificador
  servicio.responder(`GET /api/llamadas/${identificador}/duplicados`, duplicados)
  window.history.replaceState(null, '', `/?llamada=${identificador}`)
  render(<App />)
  return servicio
}

function estaAntes(primero: Element, segundo: Element) {
  return Boolean(primero.compareDocumentPosition(segundo) & Node.DOCUMENT_POSITION_FOLLOWING)
}

describe('El reparto de la sugerencia', () => {
  test('Los datos van en tres bloques: dónde es, qué pasó y cuán urgente, y el protocolo', async () => {
    abrirLlamada()
    await screen.findByRole('group', { name: 'Sugerencia' })

    const ubicacion = within(screen.getByRole('region', { name: 'Ubicación' }))
    for (const campo of ['Calle', 'Altura (opcional)', 'Primera esquina (opcional)', 'Segunda esquina (opcional)']) {
      expect(ubicacion.getByRole('textbox', { name: campo })).toBeTruthy()
    }
    expect(ubicacion.queryByRole('combobox')).toBeNull()

    const hecho = within(screen.getByRole('region', { name: 'Hecho y prioridad' }))
    for (const campo of ['Tipo de hecho', 'Subtipo (opcional)', 'Prioridad']) {
      expect(hecho.getByRole('combobox', { name: campo })).toBeTruthy()
    }
    expect(hecho.queryByRole('textbox')).toBeNull()
    expect(hecho.getByText('Criterio de prioridad')).toBeTruthy()

    const protocolo = within(screen.getByRole('region', { name: 'Protocolo' }))
    expect(protocolo.getByRole('region', { name: 'Indicale al llamante' })).toBeTruthy()
    expect(protocolo.getByRole('region', { name: 'Preguntas del protocolo' })).toBeTruthy()
  })

  test('El orden del documento es el de la pantalla, y Derivar queda después del protocolo', async () => {
    abrirLlamada()
    await screen.findByRole('group', { name: 'Sugerencia' })
    const enOrden = [
      screen.getByRole('region', { name: 'Ubicación' }),
      screen.getByRole('region', { name: 'Hecho y prioridad' }),
      screen.getByRole('region', { name: 'Protocolo' }),
      screen.getByRole('button', { name: 'Derivar Carta de Llamada' }),
    ]

    enOrden.slice(1).forEach((elemento, indice) => expect(estaAntes(enOrden[indice], elemento)).toBe(true))
  })

  test('Cada campo lleva su origen, con la explicación de qué significa', async () => {
    abrirLlamada(llamadaConAviso)
    await screen.findByRole('group', { name: 'Sugerencia' })
    const { calle, altura } = llamadaConAviso.sugerencia!.ubicacion
    const origenes = { calle, altura, segunda_esquina: { origen: 'falta' } as const }

    for (const [campo, dato] of Object.entries(origenes)) {
      const origen = document.getElementById(`${campo}-origen`)
      expect(origen?.getAttribute('title')).toBe(explicacionOrigen(dato))
      expect(origen?.closest('.campo')?.getAttribute('data-origen')).toBe(dato.origen)
    }
    expect(explicacionOrigen({ origen: 'falta' })).toMatch(/Nadie lo dijo/)
  })

  test('Arriba de los campos se explica de dónde puede salir un dato', async () => {
    abrirLlamada()
    await screen.findByRole('group', { name: 'Sugerencia' })

    const leyenda = within(screen.getByRole('list', { name: 'De dónde sale cada dato' }))
    expect(leyenda.getAllByRole('listitem').map((item) => item.textContent)).toEqual([
      'Dicho lo dijo el llamante',
      'Inferido lo completó el sistema: confirmalo',
      'Falta nadie lo dijo',
      'Del operador lo cambiaste vos',
    ])
  })

  test('Sumar un turno ocupa una fila y conserva los nombres de sus controles', async () => {
    abrirLlamada()
    await screen.findByRole('group', { name: 'Sugerencia' })

    const turno = within(screen.getByRole('group', { name: 'Sumar lo que se dijo después' }))
    expect(turno.getByRole('combobox', { name: 'Quién habla' })).toBeTruthy()
    expect(turno.getByRole<HTMLTextAreaElement>('textbox', { name: /Texto del turno/ }).rows).toBe(1)
    expect(screen.getByRole('button', { name: 'Sumar a la llamada' })).toBeTruthy()
  })
})
