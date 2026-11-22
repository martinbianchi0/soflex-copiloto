import { useRef, useState } from 'react'
import type { Turno } from './api'

export default function FormularioTurno({ bloqueado, sumando, error, alSumar, alEditar }: {
  bloqueado: boolean
  sumando: boolean
  error: string
  alSumar: (turno: Turno, alAceptar: () => void) => void
  alEditar: () => void
}) {
  const [texto, setTexto] = useState('')
  const [hablante, setHablante] = useState<'llamante' | 'operador'>('llamante')
  const area = useRef<HTMLTextAreaElement>(null)
  const puedeSumar = !bloqueado && Boolean(texto.trim())

  return (
    <form className="panel formulario-turno" onSubmit={(evento) => {
      evento.preventDefault()
      if (!puedeSumar) return
      // Una transcripción con marcas trae sus propios hablantes, igual que en el alta.
      const conMarcas = /^\s*(operador|llamante)\s*:/i.test(texto)
      alSumar({ texto, hablante: conMarcas ? null : hablante }, () => {
        setTexto('')
        setHablante('llamante')
        area.current?.focus()
      })
    }}>
      <fieldset>
        <legend>Sumar lo que se dijo después</legend>
        <label>
          Quién habla
          <select value={hablante} disabled={bloqueado} onChange={(evento) => {
            setHablante(evento.target.value === 'operador' ? 'operador' : 'llamante')
            alEditar()
          }}>
            <option value="llamante">Llamante</option>
            <option value="operador">Operador</option>
          </select>
        </label>
        <label className="campo">
          Texto del turno
          <textarea ref={area} rows={3} value={texto} readOnly={bloqueado}
            aria-invalid={error ? true : undefined} aria-describedby={error ? 'error-turno' : undefined}
            onChange={(evento) => {
              setTexto(evento.target.value)
              alEditar()
            }}
            onKeyDown={(evento) => {
              if (evento.key !== 'Enter' || !(evento.ctrlKey || evento.metaKey)) return
              evento.preventDefault()
              if (puedeSumar) evento.currentTarget.form?.requestSubmit()
            }} />
          {error && <span id="error-turno" className="error-campo" role="alert">{error}</span>}
        </label>
      </fieldset>
      <div className="acciones">
        <button type="submit" disabled={!puedeSumar} aria-keyshortcuts="Control+Enter Meta+Enter">
          {sumando ? 'Sumando…' : 'Sumar a la llamada'}
        </button>
        <small className="atajo"><kbd>Ctrl</kbd> + <kbd>Enter</kbd></small>
      </div>
    </form>
  )
}
