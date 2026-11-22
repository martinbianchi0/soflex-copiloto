import type { Sugerencia } from './api'

export default function Instrucciones({
  instrucciones, titulo = 'Leele al llamante, textual',
}: Pick<Sugerencia, 'instrucciones'> & { titulo?: string }) {
  if (instrucciones.length === 0) return null

  return (
    <section className="instrucciones" aria-labelledby="titulo-instrucciones">
      <h3 id="titulo-instrucciones">{titulo}</h3>
      <ul>{instrucciones.map(({ id, texto }) => <li key={id}>{texto}</li>)}</ul>
    </section>
  )
}
