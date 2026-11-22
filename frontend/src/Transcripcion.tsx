import { useEffect, useRef } from 'react'
import type { Cita, Turno } from './api'

function resaltar(texto: string, citas: Cita[], citaActiva?: Cita) {
  if (citas.length === 0) return texto

  const rangos = citas.flatMap((cita) => {
    if (!cita.texto) return []
    const literal = cita.texto.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    return Array.from(texto.matchAll(new RegExp(literal, 'giu')), (coincidencia) => ({
      desde: coincidencia.index,
      hasta: coincidencia.index + coincidencia[0].length,
      activa: cita === citaActiva,
    }))
  })
  if (rangos.length === 0) return texto

  const ocupados = new Uint8Array(texto.length)
  const activos = new Uint8Array(texto.length)
  const visibles: typeof rangos = []
  // El fragmento más largo ocupa primero su lugar, incluso si se enfoca uno más corto.
  rangos.sort((a, b) => (b.hasta - b.desde) - (a.hasta - a.desde))
  for (const rango of rangos) {
    const { desde, hasta, activa } = rango
    if (activa) activos.fill(1, desde, hasta)
    if (ocupados.subarray(desde, hasta).includes(1)) continue
    ocupados.fill(1, desde, hasta)
    visibles.push(rango)
  }
  visibles.sort((a, b) => a.desde - b.desde)

  let cursor = 0
  const fragmentos = visibles.flatMap(({ desde, hasta }) => {
    const anterior = texto.slice(cursor, desde)
    cursor = hasta
    return [anterior, (
      <mark key={desde} className={activos.subarray(desde, hasta).includes(1) ? 'cita-activa' : undefined}>
        {texto.slice(desde, hasta)}
      </mark>
    )]
  })
  return [...fragmentos, texto.slice(cursor)]
}

export default function Transcripcion({ turnos, citas = [], citaActiva }: {
  turnos: Turno[]
  citas?: Cita[]
  citaActiva?: Cita
}) {
  const panel = useRef<HTMLElement>(null)

  useEffect(() => {
    if (document.activeElement === document.body) panel.current?.focus()
  }, [])

  useEffect(() => {
    const contenedor = panel.current
    const marca = citaActiva && contenedor?.querySelector('mark.cita-activa')
    if (!contenedor || !marca || contenedor.scrollHeight <= contenedor.clientHeight) return

    const { top, bottom } = marca.getBoundingClientRect()
    const { top: inicio, bottom: fin } = contenedor.getBoundingClientRect()
    if (top < inicio || bottom > fin) contenedor.scrollTop += top - inicio - 24
  }, [citaActiva])

  return (
    <section className="panel transcripcion" aria-labelledby="titulo-transcripcion" tabIndex={0} ref={panel}>
      <h2 id="titulo-transcripcion">Transcripción de la llamada</h2>
      {turnos.map(({ texto, hablante }, indice) => (
        <p key={indice} className={hablante === 'llamante' ? 'turno turno-llamante' : 'turno'}>
          <small className="numero-turno">Turno {indice + 1}</small>
          {hablante && <strong>{hablante === 'operador' ? 'Operador' : 'Llamante'}: </strong>}
          {resaltar(texto, citas.filter(({ turno }) => turno === indice), citaActiva)}
        </p>
      ))}
    </section>
  )
}
