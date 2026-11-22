import { nombresTiposHecho } from './api'
import type { PosibleDuplicado } from './api'

function momentoDeLaOtraLlamada(diferencia: number) {
  const minutos = Math.floor(Math.abs(diferencia) / 60_000)
  if (minutos === 0) return 'casi al mismo tiempo que esta'
  return `${minutos} min ${diferencia > 0 ? 'después' : 'antes'} que esta`
}

export default function AvisoDuplicados({ recibidaEn, posibles }: {
  recibidaEn: string
  posibles: PosibleDuplicado[]
}) {
  const momento = Date.parse(recibidaEn)

  return (
    <section className="avisos-sugerencia" aria-labelledby="titulo-duplicados">
      <h3 id="titulo-duplicados">Otra llamada del mismo lugar</h3>
      <ul>
        {posibles.map(({ llamada_id, recibida_en, ubicacion, categoria, derivada }) => (
          <li key={llamada_id}>
            Se recibió otra llamada en {ubicacion}
            {categoria !== 'NO_DETERMINADA' && ` (${nombresTiposHecho[categoria]})`}
            , {momentoDeLaOtraLlamada(Date.parse(recibida_en) - momento)}. Puede ser el mismo hecho.
            {derivada && ' Ya se derivó.'}{' '}
            <a href={`?llamada=${encodeURIComponent(llamada_id)}`} target="_blank" rel="noopener">Abrir</a>
          </li>
        ))}
      </ul>
    </section>
  )
}
