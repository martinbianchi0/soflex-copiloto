// Lo que todo test con DOM necesita: importarlo deja el documento limpio entre un test y otro.
import { cleanup } from '@testing-library/react'
import { afterEach, beforeEach, vi } from 'vitest'

// jsdom no trae `ResizeObserver`. El plano lo usa para saber su tamaño; sin tamaño no ubica
// rótulos, y eso se prueba aparte, en `rotulosDelPlano.test.ts`.
class ObservadorSinMedidas {
  observe() {}
  unobserve() {}
  disconnect() {}
}

// Tampoco implementa el desplazamiento que el panel pide al mostrar un error.
HTMLElement.prototype.scrollIntoView ??= () => {}

beforeEach(() => {
  vi.stubGlobal('ResizeObserver', ObservadorSinMedidas)
  window.history.replaceState(null, '', '/')
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})
