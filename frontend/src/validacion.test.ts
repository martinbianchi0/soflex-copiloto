import { describe, expect, test } from 'vitest'
import type { DetalleValidacion } from './api'
import { respuestas } from './pruebas/respuestas'
import { campoSugerencia, nombrarCampo } from './validacion'

const { detail } = respuestas.errorFaltaLoMinimo
if (!Array.isArray(detail)) throw new Error('La respuesta no trae los errores de validación')
const [errorCalle, errorPrioridad] = detail

function errorEn(loc: DetalleValidacion['loc']) {
  const error = structuredClone(errorCalle)
  error.loc = loc
  return error
}

describe('El nombre del campo en un error', () => {
  test.each([
    [errorCalle, 'Calle'], [errorPrioridad, 'Prioridad'],
  ])('un dato obligatorio que falta se muestra como %j con el nombre %s', ({ loc }, nombre) => {
    expect(nombrarCampo(loc)).toBe(nombre)
  })

  test('un error de texto de un turno se muestra como Texto de la transcripción', () => {
    expect(nombrarCampo(['body', 'turnos', 0, 'texto'])).toBe('Texto de la transcripción')
  })

  test('un índice al final de la ruta no reemplaza el nombre del campo', () => {
    expect(nombrarCampo(['body', 'turnos', 0])).toBe('Turnos')
  })

  test('un campo desconocido muestra la ruta con puntos y sin el body inicial', () => {
    expect(nombrarCampo(['body', 'ajustes', 'campo_nuevo'])).toBe('ajustes.campo_nuevo')
  })

  test('una ruta vacía se muestra como Solicitud', () => {
    expect(nombrarCampo([])).toBe('Solicitud')
  })

  test('constructor se muestra con su ruta como cualquier campo desconocido', () => {
    expect(nombrarCampo(['constructor'])).toBe('constructor')
  })
})

describe('El campo de la sugerencia que recibe el error', () => {
  test.each([
    [errorCalle, 'calle'], [errorPrioridad, 'prioridad'],
  ])('el error real %j se asigna al campo %s', (error, campo) => {
    expect(campoSugerencia(error)).toBe(campo)
  })

  test('un error en la ubicación se asigna a la calle', () => {
    expect(campoSugerencia(errorEn(['body', 'ajustes', 'ubicacion']))).toBe('calle')
  })

  test('un error en la categoría se asigna al tipo de hecho', () => {
    expect(campoSugerencia(errorEn(['body', 'ajustes', 'tipo_hecho', 'categoria']))).toBe('tipo_hecho')
  })

  test('un error dentro de una pregunta se asigna al checklist', () => {
    expect(campoSugerencia(errorEn(['body', 'ajustes', 'checklist', 0, 'cita', 'texto']))).toBe('checklist')
  })

  test('un error dentro de una entrecalle se asigna a esquinas', () => {
    expect(campoSugerencia(errorEn(['body', 'ajustes', 'ubicacion', 'esquinas', 0, 'calle']))).toBe('esquinas')
  })

  test('un error de un campo desconocido queda sin asignar', () => {
    expect(campoSugerencia(errorEn(['body', 'ajustes', 'campo_nuevo']))).toBeUndefined()
  })
})
