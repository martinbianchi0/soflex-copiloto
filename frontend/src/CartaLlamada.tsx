import type { Carta, Sugerencia } from './api'

const nombres: Record<keyof Sugerencia, string> = {
  ubicacion: 'Ubicación',
  tipo_hecho: 'Tipo de hecho',
  prioridad: 'Prioridad',
}

export default function CartaLlamada({ carta }: { carta: Carta }) {
  const { calle, altura, esquinas } = carta.ubicacion

  return (
    <>
      <h2>Carta de Llamada</h2>
      <dl className="datos-carta">
        <dt>Ubicación</dt>
        <dd>{calle}{altura !== null && ` ${altura}`}</dd>
        {!!esquinas.length && <><dt>Esquinas</dt><dd>{esquinas.join(' y ')}</dd></>}
        <dt>Tipo de hecho</dt>
        <dd>{carta.tipo_hecho}</dd>
        <dt>Prioridad</dt>
        <dd>{carta.prioridad}</dd>
      </dl>
      <p className="ajustes">
        {carta.ajustado_por_operador.length
          ? <>Campos ajustados: {carta.ajustado_por_operador.map((campo) => nombres[campo]).join(', ')}</>
          : 'Sin ajustes del operador'}
      </p>
    </>
  )
}
