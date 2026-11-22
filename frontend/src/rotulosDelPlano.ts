import type { CuadraDelPlano } from './api'

function rotuloVisible(cuadra: CuadraDelPlano, limiteX: number, limiteY: number) {
  const { x1, x2, y1, y2 } = cuadra
  const dx = x2 - x1
  const dy = y1 - y2
  let inicio = 0
  let fin = 1
  // El SVG recorta en el eje más corto. Se mide y se rotula sólo el segmento que queda a la vista.
  for (const [origen, delta, limite] of [[x1, dx, limiteX], [-y1, dy, limiteY]]) {
    if (delta === 0) {
      if (Math.abs(origen) > limite) return null
      continue
    }
    const a = (-limite - origen) / delta
    const b = (limite - origen) / delta
    inicio = Math.max(inicio, Math.min(a, b))
    fin = Math.min(fin, Math.max(a, b))
  }
  const largo = (fin - inicio) * Math.hypot(dx, dy)
  if (largo <= 0) return null

  const angulo = Math.atan2(dx < 0 ? -dy : dy, Math.abs(dx)) * 180 / Math.PI
  // El punto del tramo visible que queda a esa fracción de su largo.
  const en = (fraccion: number) => {
    const t = inicio + fraccion * (fin - inicio)
    return { x: x1 + t * dx, y: -y1 + t * dy, angulo }
  }
  return { en, largo, principal: cuadra.principal }
}

type Punto = [number, number]

// Medidas aproximadas del texto de un rótulo, en píxeles de pantalla.
const ANCHO_DE_LETRA = 6.2
const ALTO_DE_ROTULO = 11
const FRACCIONES_DEL_ROTULO = [0.5, 0.3, 0.7, 0.15, 0.85, 0, 1]

function puntosDelRotulo(nombre: string, { x, y, angulo }: { x: number; y: number; angulo: number }, escala: number) {
  const radianes = angulo * Math.PI / 180
  const [ux, uy] = [Math.cos(radianes), Math.sin(radianes)]
  // El texto va apoyado sobre la línea: su centro queda del lado de «arriba» del rótulo girado.
  const [cx, cy] = [x * escala + uy * 8, y * escala - ux * 8]
  const mitad = nombre.length * ANCHO_DE_LETRA / 2
  const puntos: Punto[] = []
  for (let paso = -mitad; paso <= mitad; paso += ANCHO_DE_LETRA) puntos.push([cx + paso * ux, cy + paso * uy])
  return puntos
}

function distanciaAlPunto({ x1, y1, x2, y2 }: CuadraDelPlano) {
  const [dx, dy] = [x2 - x1, y2 - y1]
  const largo = dx * dx + dy * dy
  const fraccion = largo ? Math.max(0, Math.min(1, -(x1 * dx + y1 * dy) / largo)) : 0
  return Math.hypot(x1 + fraccion * dx, y1 + fraccion * dy)
}

// Un rótulo por calle, sin pisar a otro ni salirse del dibujo. Primero la calle pedida y después
// las más cercanas al punto, que son las que sirven para confirmar; la que no entra queda sin rótulo.
export function ubicarRotulos(cuadras: CuadraDelPlano[], escala: number, ancho: number, alto: number, largoEscala: number) {
  const [limiteX, limiteY] = [ancho / (2 * escala), alto / (2 * escala)]
  const porCalle = new Map<string, CuadraDelPlano[]>()
  for (const cuadra of cuadras) porCalle.set(cuadra.nombre, [...(porCalle.get(cuadra.nombre) ?? []), cuadra])
  const calles = Array.from(porCalle, ([nombre, tramos]) => ({
    nombre,
    principal: tramos[0].principal,
    distancia: Math.min(...tramos.map(distanciaAlPunto)),
    opciones: tramos
      .map((tramo) => rotuloVisible(tramo, limiteX, limiteY))
      .filter((rotulo) => rotulo !== null)
      .sort((a, b) => b.largo - a.largo),
  })).sort((a, b) => Number(b.principal) - Number(a.principal) || a.distancia - b.distancia)

  // Lo que ya ocupa lugar: el punto, la «N» y la barra de escala.
  const ocupados: Punto[] = [[0, 0], [ancho / 2 - 17, -alto / 2 + 17], [ancho / 2 - 17, -alto / 2 + 34]]
  for (let x = 0; x <= largoEscala; x += ANCHO_DE_LETRA) ocupados.push([-ancho / 2 + 12 + x, alto / 2 - 20])
  const entra = ([x, y]: Punto) =>
    Math.abs(x) <= ancho / 2 - 3 && Math.abs(y) <= alto / 2 - 3
    && ocupados.every(([ox, oy]) => Math.hypot(x - ox, y - oy) >= ALTO_DE_ROTULO)

  const ubicados = []
  for (const { nombre, principal, opciones } of calles) {
    // Primero centrado en alguna cuadra; si no entra, corrido hacia uno de sus extremos.
    const lugares = FRACCIONES_DEL_ROTULO.flatMap((fraccion) => opciones.map((opcion) => opcion.en(fraccion)))
    const lugar = lugares.find((posible) => puntosDelRotulo(nombre, posible, escala).every(entra))
    if (!lugar) continue
    ocupados.push(...puntosDelRotulo(nombre, lugar, escala))
    ubicados.push({ nombre, principal, ...lugar })
  }
  return ubicados
}
