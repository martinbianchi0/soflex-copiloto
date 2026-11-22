import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { consultarPlano, ErrorApi } from './api'
import type { CuadraDelPlano, PedidoDePlano, Plano } from './api'
import { leerAltura } from './borradorSugerencia'

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
function ubicarRotulos(cuadras: CuadraDelPlano[], escala: number, ancho: number, alto: number, largoEscala: number) {
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

function DibujoPlano({ plano }: { plano: Plano }) {
  const { radio_m: radio, cuadras, leyenda, exacto } = plano
  const svg = useRef<SVGSVGElement>(null)
  const [tamano, setTamano] = useState<{ ancho: number; alto: number } | null>(null)
  useLayoutEffect(() => {
    const elemento = svg.current
    if (!elemento) return
    const medir = () => {
      const { width: ancho, height: alto } = elemento.getBoundingClientRect()
      if (ancho > 0 && alto > 0) setTamano((anterior) => (anterior?.ancho === ancho && anterior.alto === alto ? anterior : { ancho, alto }))
    }
    // Se mide antes del primer dibujo, y de nuevo cada vez que cambia el tamaño.
    medir()
    const observador = new ResizeObserver(medir)
    observador.observe(elemento)
    return () => observador.disconnect()
  }, [])

  const { ancho, alto } = tamano ?? { ancho: 2 * radio, alto: 2 * radio }
  const escala = Math.max(ancho, alto) / (2 * radio)
  const limiteX = ancho / (2 * escala)
  const limiteY = alto / (2 * escala)
  const largoEscala = 100 * escala
  // Hasta conocer el tamaño real del dibujo no se sabe qué rótulos entran.
  const rotulos = tamano ? ubicarRotulos(cuadras, escala, ancho, alto, largoEscala) : []

  return (
    <svg ref={svg} viewBox={`${-radio} ${-radio} ${2 * radio} ${2 * radio}`}
      preserveAspectRatio="xMidYMid slice" role="img" aria-label={leyenda}>
      {cuadras.map(({ x1, y1, x2, y2, principal }, indice) => (
        <line key={indice} className={principal ? 'mini-mapa-cuadra principal' : 'mini-mapa-cuadra'}
          x1={x1} y1={-y1} x2={x2} y2={-y2} />
      ))}
      {rotulos.map(({ nombre, x, y, angulo, principal }) => (
        <text key={nombre} className={principal ? 'mini-mapa-rotulo principal' : 'mini-mapa-rotulo'}
          transform={`translate(${x} ${y}) rotate(${angulo}) scale(${1 / escala})`} y={-4}>{nombre}</text>
      ))}
      <circle className={exacto ? 'mini-mapa-punto exacto' : 'mini-mapa-punto'} cx={0} cy={0} r={5 / escala} />
      <g className="mini-mapa-referencia" transform={`translate(${limiteX - 17 / escala} ${-limiteY + 17 / escala}) scale(${1 / escala})`}>
        <text>N</text>
        <path d="M0 24V7m-4 5 4-5 4 5" />
      </g>
      <g className="mini-mapa-referencia" transform={`translate(${-limiteX + 12 / escala} ${limiteY - 12 / escala}) scale(${1 / escala})`}>
        <text x={largoEscala / 2} y={-6}>100 m</text>
        <path d={`M0 -3V0H${largoEscala}v-3`} />
      </g>
    </svg>
  )
}

export default function MiniMapa({ calle, altura, esquinas: [primera, segunda] }: {
  calle: string
  altura: string
  esquinas: [string, string]
}) {
  const { pedido, falta } = useMemo<{ pedido: PedidoDePlano | null; falta: string }>(() => {
    const { numero, invalida } = leerAltura(altura)
    const esquinas = [primera, segunda].filter((esquina) => esquina.trim())
    if (!calle.trim()) return { pedido: null, falta: 'Sin plano: falta la calle.' }
    if (invalida || (numero === null && esquinas.length === 0)) {
      return { pedido: null, falta: 'Sin plano: falta la altura o una esquina.' }
    }
    return { pedido: { calle, altura: numero, esquinas }, falta: '' }
  }, [calle, altura, primera, segunda])
  const [respuesta, setRespuesta] = useState<{ pedido: PedidoDePlano; plano: Plano | null; motivo: string } | null>(null)

  useEffect(() => {
    if (!pedido) return
    const controlador = new AbortController()
    const senal = controlador.signal
    const recibir = (plano: Plano | null, motivo = '') => {
      if (!senal.aborted) setRespuesta({ pedido, plano, motivo })
    }
    const espera = window.setTimeout(() => {
      void consultarPlano(pedido, senal).then(recibir, (error: unknown) => recibir(
        null,
        error instanceof ErrorApi && error.estado === 404
          ? 'Sin plano: esa dirección no se pudo ubicar en el callejero.'
          : 'Sin plano: no se pudo consultar.',
      ))
    }, 400)
    return () => {
      window.clearTimeout(espera)
      controlador.abort()
    }
  }, [pedido])

  const vigente = respuesta?.pedido === pedido ? respuesta : null
  const plano = vigente?.plano
  return (
    <figure className="mini-mapa">
      {plano ? (
        <>
          <DibujoPlano plano={plano} />
          <figcaption>{plano.leyenda}</figcaption>
        </>
      ) : (
        <p>{pedido ? (vigente?.motivo ?? 'Buscando plano…') : falta}</p>
      )}
    </figure>
  )
}
