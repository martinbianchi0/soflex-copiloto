import { useRef, useState } from 'react'
import type { Turno } from './api'

export default function FormularioTurno({ bloqueado, edicionBloqueada, sumando, error, alSumar, alEditar, alReintentar }: {
  bloqueado: boolean
  edicionBloqueada: boolean
  sumando: boolean
  error: string
  alSumar: (turno: Turno, alAceptar: () => void) => void
  alEditar: () => void
  alReintentar?: () => void
}) {
  const [texto, setTexto] = useState('')
  const [hablante, setHablante] = useState<'llamante' | 'operador'>('llamante')
  const area = useRef<HTMLTextAreaElement>(null)
  const puedeSumar = !bloqueado && Boolean(texto.trim())

  return (
    <form className="panel formulario-turno" onKeyDown={(evento) => {
      if (evento.key !== 'Enter' || !(evento.ctrlKey || evento.metaKey)) return
      evento.preventDefault()
      if (puedeSumar) evento.currentTarget.requestSubmit()
    }} onSubmit={(evento) => {
      evento.preventDefault()
      if (!puedeSumar) return
      // Una transcripción con marcas trae sus propios hablantes, igual que en el alta.
      const conMarcas = /^\s*(operador|llamante)\s*:/i.test(texto)
      const formulario = evento.currentTarget
      alSumar({ texto, hablante: conMarcas ? null : hablante }, () => {
        setTexto('')
        setHablante('llamante')
        // El foco vuelve al texto para seguir sumando, salvo que el operador lo haya llevado a
        // otro lado mientras tanto (a leer la transcripción, por ejemplo).
        const enFoco = document.activeElement
        if (!enFoco || enFoco === document.body || formulario.contains(enFoco)) area.current?.focus()
      })
    }}>
      <fieldset>
        <legend>Sumar lo que se dijo después</legend>
        {/* Una sola fila: quién habla y qué dijo. Las etiquetas quedan para los lectores de pantalla. */}
        <div className="fila-turno">
          <label>
            <span className="solo-lectores">Quién habla</span>
            <select value={hablante} disabled={edicionBloqueada} onChange={(evento) => {
              setHablante(evento.target.value === 'operador' ? 'operador' : 'llamante')
              alEditar()
            }}>
              <option value="llamante">Llamante</option>
              <option value="operador">Operador</option>
            </select>
          </label>
          <label className="campo">
            <span className="solo-lectores">Texto del turno</span>
            <textarea ref={area} rows={1} placeholder="Lo que se dijo después…" value={texto} readOnly={edicionBloqueada}
              aria-invalid={error ? true : undefined} aria-describedby={error ? 'error-turno' : undefined}
              onChange={(evento) => {
                setTexto(evento.target.value)
                alEditar()
              }} />
            {error && <span id="error-turno" className="error-campo" role="alert">{error}</span>}
          </label>
        </div>
      </fieldset>
      <div className="acciones">
        <button type="submit" disabled={!puedeSumar} aria-keyshortcuts="Control+Enter Meta+Enter">
          {sumando ? 'Sumando…' : 'Sumar a la llamada'}
        </button>
        <small className="atajo"><kbd>Ctrl</kbd> + <kbd>Enter</kbd></small>
        {alReintentar && <button type="button" className="secundario" onClick={alReintentar}>Reintentar el análisis</button>}
      </div>
    </form>
  )
}
