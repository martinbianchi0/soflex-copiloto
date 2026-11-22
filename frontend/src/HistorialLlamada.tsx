import { useEffect, useState } from 'react'
import { consultarHistorial, nombresTiposHecho, textoOrigen, valorDato } from './api'
import type { Carta, Dato, Historial, ValorCambio } from './api'
import { nombrarCampo } from './validacion'

const horaLocal = new Intl.DateTimeFormat('es-AR', {
  hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
})
const nombresHechos: Partial<Record<string, string>> = nombresTiposHecho

function DatoHistorial({ dato, campo }: { dato: Dato<string | number>; campo: string }) {
  const valor = valorDato(dato)
  const texto = campo === 'tipo_hecho' && typeof valor === 'string' ? nombresHechos[valor] ?? valor : valor
  return <>{texto ?? 'Sin dato'}<small className="origen">{textoOrigen(dato)}</small></>
}

function ValorHistorial({ valor, campo }: { valor: ValorCambio; campo: string }) {
  if (Array.isArray(valor)) {
    if (!valor.length) return 'Sin esquinas'
    return (
      <ul>
        {valor.map((dato, indice) => <li key={indice}><DatoHistorial dato={dato} campo={campo} /></li>)}
      </ul>
    )
  }
  if ('respondida' in valor) return valor.respondida ? 'respondida' : valor.propuesta ? 'posible respuesta' : 'pendiente'
  return <DatoHistorial dato={valor} campo={campo} />
}

function nombreCampo(campo: string, checklist: Carta['checklist']) {
  const prefijo = 'pregunta '
  if (!campo.startsWith(prefijo)) return nombrarCampo([campo])
  return checklist.find(({ id }) => id === campo.slice(prefijo.length))?.pregunta ?? campo
}

function Cambios({ cambios, checklist }: Pick<Historial, 'cambios'> & Pick<Carta, 'checklist'>) {
  if (!cambios.length) return <p>El operador derivó la sugerencia sin cambios.</p>
  return (
    <table>
      <caption>Qué cambió el operador</caption>
      <thead>
        <tr><th scope="col">Campo</th><th scope="col">Sugerido</th><th scope="col">Final</th></tr>
      </thead>
      <tbody>
        {cambios.map(({ campo, sugerido, final }) => (
          <tr key={campo}>
            <th scope="row">{nombreCampo(campo, checklist)}</th>
            <td><ValorHistorial valor={sugerido} campo={campo} /></td>
            <td><ValorHistorial valor={final} campo={campo} /></td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

// Cuánto pasó entre que entró la llamada y se derivó la carta: lo que tardó en quedar lista para
// despachar.
function tiempoHastaDerivar(eventos: Historial['eventos']) {
  const recibida = eventos.find(({ tipo }) => tipo === 'recibida')
  const derivada = eventos.findLast(({ tipo }) => tipo === 'derivada')
  if (!recibida || !derivada) return null
  const segundos = Math.round((Date.parse(derivada.cuando) - Date.parse(recibida.cuando)) / 1000)
  if (!Number.isFinite(segundos) || segundos < 0) return null
  const minutos = Math.floor(segundos / 60)
  return minutos ? `${minutos} min ${segundos % 60} s` : `${segundos} s`
}

export default function HistorialLlamada({ carta }: { carta: Carta }) {
  const { llamada_id: identificador, checklist } = carta
  const [historial, setHistorial] = useState<Historial | 'error' | null>(null)

  useEffect(() => {
    const control = new AbortController()
    consultarHistorial(identificador, control.signal).then(
      (respuesta) => { if (!control.signal.aborted) setHistorial(respuesta) },
      () => { if (!control.signal.aborted) setHistorial('error') },
    )
    return () => control.abort()
  }, [identificador])

  return (
    <section className="historial" aria-labelledby="titulo-historial">
      <h3 id="titulo-historial">Historial</h3>
      {historial === null ? <p role="status">Cargando el historial…</p>
        : historial === 'error' ? <p role="status">No se pudo cargar el historial.</p>
          : (
            <>
              <ol role="list">
                {historial.eventos.map(({ tipo, cuando, detalle }) => (
                  <li key={`${tipo}-${cuando}`}>
                    <time dateTime={cuando}>{horaLocal.format(new Date(cuando))}</time>
                    <span>{detalle}</span>
                  </li>
                ))}
              </ol>
              {tiempoHastaDerivar(historial.eventos) && (
                <p className="tiempo-derivacion">
                  De la llamada recibida a la carta derivada: <strong>{tiempoHastaDerivar(historial.eventos)}</strong>
                </p>
              )}
              <Cambios cambios={historial.cambios} checklist={checklist} />
            </>
          )}
    </section>
  )
}
