import { nombresTiposHecho, textoOrigen, valorDato } from './api'
import type { Carta, Dato } from './api'
import DetallesSugerencia from './DetallesSugerencia'

function DatoCarta({ etiqueta, dato, texto }: { etiqueta: string; dato: Dato<string | number>; texto?: string }) {
  return (
    <>
      <dt>{etiqueta}</dt>
      <dd>
        {texto ?? valorDato(dato) ?? 'Sin dato'}
        <small className="origen">
          {textoOrigen(dato)}{dato.origen === 'dicho' && <> «{dato.cita.texto}»</>}
        </small>
      </dd>
    </>
  )
}

export default function CartaLlamada({ carta }: { carta: Carta }) {
  const { calle, altura, esquinas } = carta.ubicacion
  const tipoHecho = valorDato(carta.tipo_hecho)

  return (
    <>
      <h2>Carta de Llamada</h2>
      <dl className="datos-carta">
        <DatoCarta etiqueta="Calle" dato={calle} />
        <DatoCarta etiqueta="Altura" dato={altura} />
        {esquinas.map((dato, indice) => (
          <DatoCarta key={indice} etiqueta={indice === 0 ? 'Primera esquina' : 'Segunda esquina'} dato={dato} />
        ))}
        <DatoCarta etiqueta="Tipo de hecho" dato={carta.tipo_hecho} texto={tipoHecho ? nombresTiposHecho[tipoHecho] : undefined} />
        <DatoCarta etiqueta="Prioridad" dato={carta.prioridad} />
        <dt>Derivación</dt>
        <dd><time dateTime={carta.derivada_en}>{new Date(carta.derivada_en).toLocaleString('es-AR', { hourCycle: 'h23' })}</time></dd>
      </dl>
      <DetallesSugerencia checklist={carta.checklist} instrucciones={carta.instrucciones} />
    </>
  )
}
