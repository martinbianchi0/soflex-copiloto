import { useCallback, useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { consultarLlamada, consultarSalud, crearLlamada, derivarLlamada, ErrorApi } from './api'
import type { Ajustes, DetalleValidacion, Llamada } from './api'
import CartaLlamada from './CartaLlamada'
import FormularioSugerencia from './FormularioSugerencia'

const errorConexion = 'No se pudo conectar con el servicio.'

function leerIdentificador() {
  return new URLSearchParams(window.location.search).get('llamada') || null
}

function cambiarUrl(identificador: string | null) {
  const url = new URL(window.location.href)
  if (identificador === null) url.searchParams.delete('llamada')
  else url.searchParams.set('llamada', identificador)
  window.history.pushState(null, '', url)
}

function App() {
  const [modo, setModo] = useState<string | null>()
  const [identificador, setIdentificador] = useState(leerIdentificador)
  const [llamada, setLlamada] = useState<Llamada | null>(null)
  const [transcripcion, setTranscripcion] = useState('')
  const [ocupado, setOcupado] = useState(false)
  const [error, setError] = useState<string | DetalleValidacion[] | null>(null)
  const [aviso, setAviso] = useState('')
  const solicitud = useRef<AbortController | null>(null)
  const regionAvisos = useRef<HTMLDivElement>(null)
  const bloqueado = ocupado || modo === undefined

  useEffect(() => {
    const control = new AbortController()
    consultarSalud(control.signal).then(
      (salud) => { if (!control.signal.aborted) setModo(salud.llm_provider) },
      () => { if (!control.signal.aborted) setModo(null) },
    )
    return () => control.abort()
  }, [])

  const solicitar = useCallback(async (operacion: (senal: AbortSignal) => Promise<void>) => {
    if (solicitud.current) return
    const control = new AbortController()
    solicitud.current = control
    setOcupado(true)
    setError(null)
    setAviso('')
    try {
      await operacion(control.signal)
    } catch (fallo) {
      if (control.signal.aborted) return
      if (fallo instanceof ErrorApi && fallo.estado === 404) {
        setError('No existe esa llamada.')
      } else if (fallo instanceof ErrorApi && fallo.estado === 422 && Array.isArray(fallo.detalle)) {
        setError(fallo.detalle)
      } else {
        setError(errorConexion)
      }
    } finally {
      if (solicitud.current === control) {
        solicitud.current = null
        setOcupado(false)
      }
    }
  }, [])

  useEffect(() => {
    function abrirDesdeUrl() {
      solicitud.current?.abort()
      solicitud.current = null
      const actual = leerIdentificador()
      setIdentificador(actual)
      setLlamada(null)
      setTranscripcion('')
      if (actual) {
        void solicitar(async (senal) => {
          const recuperada = await consultarLlamada(actual, senal)
          if (!senal.aborted) setLlamada(recuperada)
        })
      } else {
        setOcupado(false)
        setError(null)
        setAviso('')
      }
    }

    abrirDesdeUrl()
    window.addEventListener('popstate', abrirDesdeUrl)
    return () => {
      window.removeEventListener('popstate', abrirDesdeUrl)
      solicitud.current?.abort()
      solicitud.current = null
    }
  }, [solicitar])

  useEffect(() => {
    if (error || aviso || modo === null) regionAvisos.current?.scrollIntoView({ block: 'nearest' })
  }, [error, aviso, modo])

  function analizar(evento: FormEvent<HTMLFormElement>) {
    evento.preventDefault()
    if (bloqueado || !transcripcion.trim()) return
    void solicitar(async (senal) => {
      const creada = await crearLlamada(transcripcion, senal)
      if (senal.aborted) return
      cambiarUrl(creada.llamada_id)
      setIdentificador(creada.llamada_id)
      setLlamada(creada)
      setTranscripcion('')
    })
  }

  function derivar(ajustes: Ajustes) {
    if (bloqueado || llamada?.estado !== 'esperando_operador') return
    const id = llamada.llamada_id
    void solicitar(async (senal) => {
      try {
        const derivada = await derivarLlamada(id, ajustes, senal)
        if (!senal.aborted) setLlamada(derivada)
      } catch (fallo) {
        if (senal.aborted) return
        if (!(fallo instanceof ErrorApi) || fallo.estado !== 409) throw fallo
        setAviso('La llamada ya estaba derivada.')
        setLlamada(null)
        const actual = await consultarLlamada(id, senal)
        if (!senal.aborted) setLlamada(actual)
      }
    })
  }

  function nuevaLlamada() {
    if (bloqueado || solicitud.current) return
    cambiarUrl(null)
    setIdentificador(null)
    setLlamada(null)
    setTranscripcion('')
    setError(null)
    setAviso('')
  }

  return (
    <main>
      <header className="encabezado">
        <h1>Copiloto para Operadores de Sala</h1>
        <span className="modo">Modo: {modo === undefined ? 'consultando…' : modo ?? 'no disponible'}</span>
      </header>

      <div className="avisos" ref={regionAvisos} aria-live="polite" aria-atomic="true">
        {aviso && <p className="aviso">{aviso}</p>}
        {modo === null && error !== errorConexion && <p className="error">{errorConexion}</p>}
        {Array.isArray(error) ? (
          <div className="error">
            <p>Revisá los datos:</p>
            <ul>
              {error.map(({ loc, msg }, indice) => (
                <li key={indice}>{(loc[0] === 'body' ? loc.slice(1) : loc).join('.') || 'Solicitud'}: {msg}</li>
              ))}
            </ul>
          </div>
        ) : error && <p className="error">{error}</p>}
      </div>

      {!identificador && (
        <form className="panel" onSubmit={analizar}>
          <label className="titulo-campo">
            Transcripción de la llamada
            <textarea rows={7} value={transcripcion} disabled={bloqueado} required
              onChange={(evento) => setTranscripcion(evento.target.value)} />
          </label>
          <div className="acciones">
            <button type="submit" disabled={bloqueado || !transcripcion.trim()}>
              {ocupado ? 'Analizando…' : 'Analizar llamada'}
            </button>
          </div>
        </form>
      )}

      {llamada?.estado === 'esperando_operador' && (
        <>
          <section className="panel">
            <h2>Transcripción de la llamada</h2>
            <p className="transcripcion">{llamada.turnos.map(({ texto }) => texto).join('\n\n')}</p>
          </section>
          <FormularioSugerencia key={llamada.llamada_id} sugerencia={llamada.sugerencia}
            bloqueado={bloqueado} ocupado={ocupado} alDerivar={derivar}
            alValidar={setError} alEmpezar={nuevaLlamada} />
        </>
      )}

      {identificador && llamada?.estado !== 'esperando_operador' && (
        <section className="panel">
          {ocupado && <p role="status">Consultando la llamada…</p>}
          {llamada?.estado === 'en_proceso' && <h2>Llamada en proceso</h2>}
          {llamada?.estado === 'derivada' && <CartaLlamada carta={llamada.carta} />}
          <div className="acciones">
            <button type="button" className="secundario" disabled={bloqueado} onClick={nuevaLlamada}>
              Nueva llamada
            </button>
          </div>
        </section>
      )}
    </main>
  )
}

export default App
