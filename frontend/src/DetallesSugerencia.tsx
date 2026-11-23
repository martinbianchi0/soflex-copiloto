import type { Sugerencia } from './api'
import Instrucciones from './Instrucciones'

export default function DetallesSugerencia({
  checklist, instrucciones, errores, bloqueado, alMarcar,
}: Pick<Sugerencia, 'checklist' | 'instrucciones'> & {
  errores: string[]
  bloqueado: boolean
  alMarcar: (id: string) => void
}) {
  const error = errores.length > 0 ? 'error-checklist' : undefined
  return (
    <>
      <Instrucciones instrucciones={instrucciones} porOraciones />
      {(checklist.length > 0 || error) && (
        <section className="detalles-sugerencia" aria-labelledby="titulo-checklist" aria-describedby={error}
          aria-invalid={error ? true : undefined} tabIndex={error ? -1 : undefined}>
          <h3 id="titulo-checklist">Preguntas del protocolo</h3>
          {error && <p id={error} className="error-campo">{errores.join(' ')}</p>}
          {checklist.some(({ respondida, cita, del_operador }) => !respondida && !del_operador && cita) && (
            <p className="ayuda-checklist">Las posibles respuestas son una propuesta: marcá la pregunta si el llamante ya la contestó.</p>
          )}
          {checklist.length > 0 && (
            <fieldset className="checklist" disabled={bloqueado} aria-labelledby="titulo-checklist" aria-describedby={error}>
              {checklist.map(({ id, pregunta, respondida, cita, del_operador }) => {
                const control = `pregunta-${id}`
                const dicho = cita && `Turno ${cita.turno + 1} · «${cita.texto}»`
                const posible = !respondida && !del_operador && cita !== null
                let detalle = dicho
                if (del_operador) detalle = !respondida ? 'desmarcada por vos' : dicho ? `confirmada por vos · ${dicho}` : 'marcada por vos'
                else if (posible) detalle = `Posible respuesta · ${dicho}`

                return (
                  <div key={id} className={posible ? 'pregunta posible' : 'pregunta'}>
                    <input id={control} type="checkbox" checked={respondida} onChange={() => alMarcar(id)}
                      aria-describedby={detalle ? `${control}-detalle` : undefined} />
                    <div>
                      <label htmlFor={control}>{pregunta}</label>
                      {detalle && <small id={`${control}-detalle`} className="cita">{detalle}</small>}
                    </div>
                  </div>
                )
              })}
            </fieldset>
          )}
        </section>
      )}
    </>
  )
}
