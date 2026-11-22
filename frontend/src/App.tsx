import { useCallback, useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { consultarCatalogo, consultarLlamada, consultarSalud, crearLlamada, derivarLlamada, ErrorApi } from './api'
import type { Ajustes, Catalogo, DetalleValidacion, Llamada } from './api'
import CartaLlamada from './CartaLlamada'
import FormularioSugerencia from './FormularioSugerencia'

const errorConexion = 'No se pudo conectar con el servicio.'
const nombresCampos: Record<string, string> = {
  ajustes: 'Ajustes',
  ubicacion: 'Ubicación',
  calle: 'Calle',
  altura: 'Altura',
  esquinas: 'Esquinas',
  tipo_hecho: 'Tipo de hecho',
  categoria: 'Tipo de hecho',
  subtipo: 'Subtipo',
  prioridad: 'Prioridad',
  turnos: 'Turnos',
  texto: 'Texto de la transcripción',
  llamada_id: 'Identificador de la llamada',
}

function nombrarCampo(loc: DetalleValidacion['loc']) {
  const ruta = loc[0] === 'body' ? loc.slice(1) : loc
  const campo = ruta.findLast((parte) => typeof parte === 'string')
  if (campo && Object.hasOwn(nombresCampos, campo)) return nombresCampos[campo]
  return ruta.join('.') || 'Solicitud'
}

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
  const [catalogo, setCatalogo] = useState<Catalogo | null>()
  const [identificador, setIdentificador] = useState(leerIdentificador)
  const [llamada, setLlamada] = useState<Llamada | null>(null)
  const [transcripcion, setTranscripcion] = useState('')
  const [ocupado, setOcupado] = useState(false)
  const [error, setError] = useState<string | DetalleValidacion[] | null>(null)
  const [aviso, setAviso] = useState('')
  const solicitud = useRef<AbortController | null>(null)
  const regionAvisos = useRef<HTMLDivElement>(null)
  const bloqueado = ocupado || modo === undefined
  const analisisBloqueado = bloqueado || !catalogo
  const erroresSubtipo = Array.isArray(error)
    ? error.flatMap(({ loc }, indice) => loc.at(-1) === 'subtipo' ? [`error-campo-${indice}`] : []).join(' ')
    : ''

  const cargarCatalogo = useCallback((senal: AbortSignal) => {
    consultarCatalogo(senal).then(
      (respuesta) => { if (!senal.aborted) setCatalogo(respuesta) },
      () => { if (!senal.aborted) setCatalogo(null) },
    )
  }, [])

  useEffect(() => {
    const control = new AbortController()
    consultarSalud(control.signal).then(
      (salud) => { if (!control.signal.aborted) setModo(salud.llm_provider) },
      () => { if (!control.signal.aborted) setModo(null) },
    )
    cargarCatalogo(control.signal)
    return () => control.abort()
  }, [cargarCatalogo])

  function reintentarCatalogo() {
    setCatalogo(undefined)
    cargarCatalogo(new AbortController().signal)
  }

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
      } else if (fallo instanceof ErrorApi) {
        // El servicio contestó: se muestra lo que dijo, no un problema de conexión.
        setError(typeof fallo.detalle === 'string' ? fallo.detalle : `El servicio respondió con un error (${fallo.estado}).`)
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
    if (error || aviso || modo === null || catalogo === null) {
      regionAvisos.current?.scrollIntoView({ block: 'nearest' })
    }
  }, [error, aviso, modo, catalogo])

  function analizar(evento: FormEvent<HTMLFormElement>) {
    evento.preventDefault()
    if (analisisBloqueado || !transcripcion.trim()) return
    void solicitar(async (senal) => {
      const creada = await crearLlamada(transcripcion, senal)
      if (senal.aborted) return
      cambiarUrl(creada.llamada_id)
      setIdentificador(creada.llamada_id)
      setLlamada(creada)
      setTranscripcion('')
      // Los avisos aparecen junto con el formulario: se anuncian acá para quien no ve la pantalla.
      const porConfirmar = creada.sugerencia?.avisos.length ?? 0
      if (porConfirmar > 0) {
        setAviso(porConfirmar === 1
          ? 'La sugerencia tiene un aviso para revisar antes de derivar.'
          : `La sugerencia tiene ${porConfirmar} avisos para revisar antes de derivar.`)
      }
    })
  }

  function derivar(ajustes: Ajustes) {
    if (bloqueado || !catalogo || llamada?.estado !== 'esperando_operador') return
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
        {catalogo === undefined && <p id="estado-catalogo" className="aviso">Cargando el catálogo de protocolos…</p>}
        {catalogo === null && (
          <p id="estado-catalogo" className="error">
            No se pudo cargar el catálogo de protocolos.{' '}
            <button type="button" className="secundario" onClick={reintentarCatalogo}>Reintentar</button>
          </p>
        )}
        {Array.isArray(error) ? (
          <div className="error">
            <p>Revisá los datos:</p>
            <ul>
              {error.map(({ loc, msg }, indice) => (
                <li key={indice} id={`error-campo-${indice}`}>{nombrarCampo(loc)}: {msg}</li>
              ))}
            </ul>
          </div>
        ) : error && <p className="error">{error}</p>}
      </div>

      {!identificador && (
        <form className="panel" onSubmit={analizar}>
          <label className="titulo-campo">
            Transcripción de la llamada
            <textarea rows={7} value={transcripcion} disabled={analisisBloqueado} required
              aria-describedby={catalogo ? undefined : 'estado-catalogo'}
              onChange={(evento) => setTranscripcion(evento.target.value)} />
          </label>
          <div className="acciones">
            <button type="submit" disabled={analisisBloqueado || !transcripcion.trim()}>
              {ocupado ? 'Analizando…' : 'Analizar llamada'}
            </button>
          </div>
        </form>
      )}

      {llamada?.estado === 'esperando_operador' && (
        <>
          <section className="panel">
            <h2>Transcripción de la llamada</h2>
            {llamada.turnos.map(({ texto, hablante }, indice) => (
              <p key={indice} className={hablante === 'llamante' ? 'turno turno-llamante' : 'turno'}>
                <small className="numero-turno">Turno {indice + 1}</small>
                {hablante && <strong>{hablante === 'operador' ? 'Operador' : 'Llamante'}: </strong>}
                {texto}
              </p>
            ))}
          </section>
          {catalogo ? (
            <FormularioSugerencia key={llamada.llamada_id} sugerencia={llamada.sugerencia} catalogo={catalogo}
              bloqueado={bloqueado} ocupado={ocupado} alDerivar={derivar} erroresSubtipo={erroresSubtipo}
              alValidar={setError} alEmpezar={nuevaLlamada} />
          ) : (
            // Sin catálogo no hay formulario, pero el operador no queda encerrado en esta llamada.
            <div className="panel acciones">
              <button type="button" className="secundario" disabled={bloqueado} onClick={nuevaLlamada}>
                Nueva llamada
              </button>
            </div>
          )}
        </>
      )}

      {identificador && llamada?.estado !== 'esperando_operador' && (
        <section className="panel">
          {ocupado && <p role="status">Consultando la llamada…</p>}
          {llamada?.estado === 'en_proceso' && <h2>Llamada en proceso</h2>}
          {llamada?.estado === 'derivada' && <CartaLlamada carta={llamada.carta} catalogo={catalogo ?? null} />}
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
