import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { consultarPlano, ErrorApi } from './api'
import type { PedidoDePlano, Plano } from './api'
import { leerAltura } from './borradorSugerencia'
import { ubicarRotulos } from './rotulosDelPlano'

function DibujoPlano({ plano }: { plano: Plano }) {
  const { radio_m: radio, cuadras, exacto } = plano
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
      preserveAspectRatio="xMidYMid slice" role="img" aria-label="Plano de la cuadra">
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
    if (invalida) return { pedido: null, falta: 'Sin plano: la altura tiene que ser un número entre 1 y 99999.' }
    if (numero === null && esquinas.length === 0) {
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
