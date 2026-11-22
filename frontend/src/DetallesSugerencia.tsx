import type { Sugerencia } from './api'

export default function DetallesSugerencia({
  checklist, instrucciones,
}: Pick<Sugerencia, 'checklist' | 'instrucciones'>) {
  return (
    <>
      {checklist.length > 0 && (
        <section className="detalles-sugerencia">
          <h3>Preguntas del protocolo</h3>
          <ul>
            {checklist.map(({ id, pregunta, respondida, cita }) => (
              <li key={id}>
                {pregunta} <strong>{respondida ? 'Respondida' : 'Pendiente'}</strong>
                {cita && <small className="cita">«{cita.texto}»</small>}
              </li>
            ))}
          </ul>
        </section>
      )}
      {instrucciones.length > 0 && (
        <section className="detalles-sugerencia">
          <h3>Instrucciones de pre-arribo (leer textual)</h3>
          <ul className="instrucciones">{instrucciones.map(({ id, texto }) => <li key={id}>{texto}</li>)}</ul>
        </section>
      )}
    </>
  )
}
