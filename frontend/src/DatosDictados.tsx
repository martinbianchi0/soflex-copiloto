import { idDictado } from './api'
import type { DatoDictado } from './api'

export default function DatosDictados({ datos, edicion }: {
  datos: DatoDictado[]
  edicion?: { quitados: ReadonlySet<string>; alMarcar: (id: string) => void }
}) {
  if (!datos.length) return null

  return (
    <section className="detalles-sugerencia" aria-labelledby="titulo-dictados"
      aria-describedby={edicion ? 'ayuda-dictados' : undefined}>
      <h3 id="titulo-dictados">Datos que dictó el llamante</h3>
      {edicion && <p id="ayuda-dictados" className="ayuda-checklist">Destildá el que esté mal: no va en la carta.</p>}
      <ul className={edicion ? 'dictados-editables' : undefined} role={edicion ? 'list' : undefined}>
        {datos.map((dato) => {
          const id = idDictado(dato)
          const nombre = `${dato.tipo === 'patente' ? 'Patente' : 'Teléfono'} ${dato.valor}`
          return (
            <li key={id} className={edicion ? 'pregunta' : undefined}>
              {edicion && <input id={id} type="checkbox" checked={!edicion.quitados.has(id)}
                aria-describedby={`${id}-cita`} onChange={() => edicion.alMarcar(id)} />}
              <div>
                {edicion ? <label htmlFor={id}>{nombre}</label> : nombre}
                <small id={`${id}-cita`} className="cita">Turno {dato.cita.turno + 1} · «{dato.cita.texto}»</small>
              </div>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
