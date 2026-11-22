import { useEffect, useRef } from 'react'
import type { ReactNode } from 'react'
import { citaDato, nombresTiposHecho, textoOrigen, valorDato } from './api'
import type { Carta, Catalogo, Dato, Pregunta } from './api'
import { GrupoAvisos } from './AvisosSugerencia'
import Instrucciones from './Instrucciones'
import PrioridadEtiqueta from './PrioridadEtiqueta'

function DatoCarta({ etiqueta, dato, texto }: { etiqueta: string; dato: Dato<string | number>; texto?: ReactNode }) {
  const cita = citaDato(dato)
  return (
    <>
      <dt>{etiqueta}</dt>
      <dd>
        {texto ?? valorDato(dato) ?? 'Sin dato'}
        <small className="origen">
          {textoOrigen(dato)}{cita && <> «{cita.texto}»</>}
        </small>
      </dd>
    </>
  )
}

function estadoPregunta({ respondida, cita, del_operador }: Pregunta) {
  if (del_operador) return respondida ? 'Respondida · marcada por el operador' : 'Pendiente · desmarcada por el operador'
  if (!respondida) return 'Pendiente'
  return cita ? `Respondida · Turno ${cita.turno + 1} «${cita.texto}»` : 'Respondida'
}

export default function CartaLlamada({ carta, catalogo }: { carta: Carta; catalogo: Catalogo | null }) {
  const titulo = useRef<HTMLHeadingElement>(null)
  const { calle, altura, esquinas } = carta.ubicacion
  const tipoHecho = valorDato(carta.tipo_hecho)
  const subtipo = valorDato(carta.subtipo)
  const nombreSubtipo = catalogo?.protocolos.find(({ id }) => id === subtipo)?.nombre
  const prioridad = valorDato(carta.prioridad)
  const nivel = catalogo?.criterio.niveles.find(({ id }) => id === prioridad)

  useEffect(() => {
    if (document.activeElement === document.body) titulo.current?.focus()
  }, [])

  return (
    <>
      <h2 ref={titulo} tabIndex={-1}>Carta de Llamada</h2>
      <GrupoAvisos titulo="Quedó sin confirmar con el llamante" avisos={carta.avisos ?? []} />
      <dl className="datos-carta">
        <DatoCarta etiqueta="Calle" dato={calle} />
        <DatoCarta etiqueta="Altura" dato={altura} />
        {esquinas.map((dato, indice) => (
          <DatoCarta key={indice} etiqueta={indice === 0 ? 'Primera esquina' : 'Segunda esquina'} dato={dato} />
        ))}
        <DatoCarta etiqueta="Tipo de hecho" dato={carta.tipo_hecho} texto={tipoHecho ? nombresTiposHecho[tipoHecho] : undefined} />
        <DatoCarta etiqueta="Subtipo" dato={carta.subtipo} texto={nombreSubtipo} />
        <DatoCarta etiqueta="Prioridad" dato={carta.prioridad}
          texto={prioridad ? <PrioridadEtiqueta prioridad={prioridad} nombre={nivel?.nombre} /> : undefined} />
        <dt>Derivación</dt>
        <dd><time dateTime={carta.derivada_en}>{new Date(carta.derivada_en).toLocaleString('es-AR', { hourCycle: 'h23' })}</time></dd>
      </dl>
      <Instrucciones instrucciones={carta.instrucciones} />
      {carta.checklist.length > 0 && (
        <section className="detalles-sugerencia">
          <h3>Preguntas del protocolo</h3>
          <ul>
            {carta.checklist.map((pregunta) => (
              <li key={pregunta.id}>
                {pregunta.pregunta}
                <small className="cita">{estadoPregunta(pregunta)}</small>
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  )
}
