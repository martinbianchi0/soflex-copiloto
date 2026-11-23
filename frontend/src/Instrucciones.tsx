import type { Sugerencia } from './api'
import { oraciones } from './oraciones'

// En el formulario, cada oración va en su renglón: el operador se las indica al llamante de a una.
// El texto es el del protocolo, sin cambios. La carta lo muestra entero.
export default function Instrucciones({
  instrucciones, titulo = 'Indicale al llamante', porOraciones = false,
}: Pick<Sugerencia, 'instrucciones'> & { titulo?: string; porOraciones?: boolean }) {
  if (instrucciones.length === 0) return null

  return (
    <section className="instrucciones" aria-labelledby="titulo-instrucciones">
      <h3 id="titulo-instrucciones">{titulo}</h3>
      <ul>
        {instrucciones.flatMap(({ id, texto }) => (porOraciones ? oraciones(texto) : [texto]).map((renglon, indice) => (
          <li key={`${id}-${indice}`}>{renglon}</li>
        )))}
      </ul>
    </section>
  )
}
