// Reemplaza `fetch` en un test: el panel hace sus pedidos de verdad (rutas, cuerpos, errores) y
// las respuestas salen de las guardadas en `respuestas/`.
import { afterEach, expect, vi } from 'vitest'

export type Pedido = { metodo: string; ruta: string; cuerpo: unknown }
export type Contestacion = { estado: number; cuerpo: unknown }
type Manejador = (pedido: Pedido) => Contestacion | Promise<Contestacion>

export function contestar(cuerpo: unknown, estado = 200): Contestacion {
  return { estado, cuerpo }
}

// Una respuesta que el test entrega cuando quiere, para probar qué pasa si llega tarde.
export function contestacionPendiente() {
  let entregar: (contestacion: Contestacion) => void = () => {}
  const promesa = new Promise<Contestacion>((resolver) => { entregar = resolver })
  return { promesa, entregar }
}

// Un pedido que el test no esperaba es un error del test o del panel, no algo para ignorar. Se
// comprueba acá, al cargar el módulo: un `afterEach` registrado dentro de un test no corre.
const sinAtender: string[] = []
afterEach(() => {
  const pendientes = sinAtender.splice(0)
  expect(pendientes).toEqual([])
})

export function simularServicio() {
  const manejadores = new Map<string, Manejador>()
  const pedidos: Pedido[] = []

  async function atender(entrada: RequestInfo | URL, opciones: RequestInit = {}) {
    const senal = opciones.signal
    const pedido: Pedido = {
      metodo: opciones.method ?? 'GET',
      ruta: String(entrada),
      cuerpo: typeof opciones.body === 'string' ? JSON.parse(opciones.body) : undefined,
    }
    const clave = `${pedido.metodo} ${pedido.ruta}`
    pedidos.push(pedido)
    const manejador = manejadores.get(clave)
    if (!manejador) sinAtender.push(clave)
    const { estado, cuerpo } = manejador
      ? await manejador(pedido)
      : contestar({ detail: `Sin respuesta simulada para ${clave}` }, 500)
    // Como el `fetch` real: un pedido cancelado no entrega su respuesta.
    if (senal?.aborted) throw new DOMException('Pedido cancelado', 'AbortError')
    return new Response(JSON.stringify(cuerpo), {
      status: estado,
      headers: { 'Content-Type': 'application/json' },
    })
  }

  vi.stubGlobal('fetch', vi.fn(atender))

  return {
    pedidos,
    /** `clave` es «MÉTODO ruta», por ejemplo «POST /api/llamadas». */
    responder(clave: string, respuesta: unknown | Manejador, estado = 200) {
      manejadores.set(clave, typeof respuesta === 'function' ? respuesta as Manejador : () => contestar(respuesta, estado))
    },
    pedidosA(clave: string) {
      return pedidos.filter(({ metodo, ruta }) => `${metodo} ${ruta}` === clave)
    },
  }
}
