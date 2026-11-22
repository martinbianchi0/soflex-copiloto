import type { Sugerencia } from './api'

export default function Instrucciones({ instrucciones }: Pick<Sugerencia, 'instrucciones'>) {
  if (instrucciones.length === 0) return null

  return (
    <section className="instrucciones" aria-labelledby="titulo-instrucciones">
      <h3 id="titulo-instrucciones">Leele al llamante</h3>
      <ul>{instrucciones.map(({ id, texto }) => <li key={id}>{texto}</li>)}</ul>
    </section>
  )
}
