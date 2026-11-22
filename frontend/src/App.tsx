import { useCallback, useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { analizarLlamada, consultarCatalogo, consultarEjemplos, consultarLlamada, consultarSalud, crearLlamada, derivarLlamada, ErrorApi, sumarTurno } from './api'
import type { Ajustes, Aviso, Catalogo, DetalleValidacion, Ejemplo, Llamada, Turno } from './api'
import CartaLlamada from './CartaLlamada'
import FormularioSugerencia from './FormularioSugerencia'
import FormularioTurno from './FormularioTurno'
import { calcularPausa, separarIntercambios } from './reproduccion'
import Transcripcion from './Transcripcion'
import { campoSugerencia, nombrarCampo } from './validacion'

const errorConexion = 'No se pudo conectar con el servicio.'
const gruposEjemplos = [
  { origen: 'dataset', etiqueta: 'Llamadas del dataset' },
  { origen: 'nueva', etiqueta: 'Llamadas nuevas' },
] as const

type Reproduccion = { intercambios: string[]; recibidos: number }

function leerIdentificador() {
  return new URLSearchParams(window.location.search).get('llamada') || null
}

function cambiarUrl(identificador: string | null) {
  const url = new URL(window.location.href)
  if (identificador === null) url.searchParams.delete('llamada')
  else url.searchParams.set('llamada', identificador)
  window.history.pushState(null, '', url)
}

function anunciarAvisos(avisos: Aviso[]) {
  const pendientes = avisos.filter(({ codigo }) => codigo !== 'modelo_no_disponible').length
  const mensajes = avisos.filter(({ codigo }) => codigo === 'modelo_no_disponible').map(({ mensaje }) => mensaje)
  if (pendientes === 1) mensajes.push('La sugerencia tiene un aviso para revisar antes de derivar.')
  if (pendientes > 1) mensajes.push(`La sugerencia tiene ${pendientes} avisos para revisar antes de derivar.`)
  return mensajes.join(' ')
}

function anunciarResultado(llamada: Llamada, anunciarTodosLosAvisos = false) {
  if (llamada.estado === 'derivada') return 'Carta de Llamada disponible.'
  if (llamada.estado === 'en_proceso') return 'Llamada en proceso.'
  if (llamada.estado !== 'esperando_operador') return ''

  const avisos = anunciarTodosLosAvisos ? llamada.sugerencia.avisos
    : llamada.sugerencia.avisos.filter(({ codigo }) => codigo === 'modelo_no_disponible')
  return ['Sugerencia lista.', anunciarAvisos(avisos)].filter(Boolean).join(' ')
}

function anunciarReanalisis(avisos: Aviso[]) {
  const cambio = avisos.find(({ codigo }) => codigo === 'prioridad_cambiada')
  const otrosAvisos = avisos.filter(({ codigo }) => codigo !== 'prioridad_cambiada')
  return ['Sugerencia actualizada.', cambio?.mensaje, anunciarAvisos(otrosAvisos)].filter(Boolean).join(' ')
}

function mensajeErrorTurno(fallo: unknown) {
  if (!(fallo instanceof ErrorApi)) return errorConexion
  const { detalle } = fallo
  if (Array.isArray(detalle)) return detalle.map(({ msg }) => msg).join(' ')
  return detalle ?? `El servicio respondió con un error (${fallo.estado}).`
}

function App() {
  const [modo, setModo] = useState<string | null>()
  const [catalogo, setCatalogo] = useState<Catalogo | null>()
  const [ejemplos, setEjemplos] = useState<Ejemplo[]>([])
  const [ejemploElegido, setEjemploElegido] = useState('')
  const [reproducirEjemplo, setReproducirEjemplo] = useState(false)
  const [reproduccion, setReproduccion] = useState<Reproduccion | null>(null)
  const [identificador, setIdentificador] = useState(leerIdentificador)
  const [llamada, setLlamada] = useState<Llamada | null>(null)
  const [huboAnalisis, setHuboAnalisis] = useState(false)
  const [transcripcion, setTranscripcion] = useState('')
  const [ocupado, setOcupado] = useState(false)
  const [error, setError] = useState<string | DetalleValidacion[] | null>(null)
  const [aviso, setAviso] = useState('')
  const [anuncio, setAnuncio] = useState('')
  const [sumando, setSumando] = useState<'turno' | 'intercambio' | null>(null)
  const [errorTurno, setErrorTurno] = useState('')
  const solicitud = useRef<AbortController | null>(null)
  const pausa = useRef<number | undefined>(undefined)
  const reanalizando = useRef(false)
  const regionAvisos = useRef<HTMLDivElement>(null)
  const bloqueado = ocupado || modo === undefined
  const analisisBloqueado = bloqueado || !catalogo
  const analizando = llamada?.estado === 'analizando'
  const analisisEnCurso = analizando && ocupado
  const sumandoIntercambio = sumando === 'intercambio'
  const nuevaLlamadaBloqueada = bloqueado && !analizando && !sumandoIntercambio
  const edicionBloqueada = (bloqueado || analizando) && !sumandoIntercambio
  const ejemploSeleccionado = ejemplos.find(({ id }) => id === ejemploElegido)
  const reproduciendo = reproduccion && (reproduccion.recibidos < reproduccion.intercambios.length || sumandoIntercambio)
  const estadoReproduccion = reproduccion
    ? (reproduciendo ? `Reproduciendo la llamada: intercambio ${reproduccion.recibidos} de ${reproduccion.intercambios.length}.` : 'La llamada terminó.')
    : ''
  const muestraSugerencia = analizando || llamada?.estado === 'esperando_operador'
  const muestraFormulario = muestraSugerencia && (analizando || huboAnalisis || Boolean(catalogo))
  const erroresGenerales = Array.isArray(error)
    ? error.filter((detalle) => !muestraFormulario || !campoSugerencia(detalle))
    : []
  const mostrarErrorArriba = typeof error === 'string' || erroresGenerales.length > 0

  const cargarCatalogo = useCallback((senal: AbortSignal) => {
    consultarCatalogo(senal).then(
      (respuesta) => { if (!senal.aborted) setCatalogo(respuesta) },
      () => { if (!senal.aborted) setCatalogo(null) },
    )
  }, [])

  useEffect(() => {
    const control = new AbortController()
    consultarSalud(control.signal).then(
      ({ llm_provider: proveedor, modelo }) => {
        if (!control.signal.aborted) setModo(modelo ? `${proveedor} · ${modelo}` : proveedor)
      },
      () => { if (!control.signal.aborted) setModo(null) },
    )
    cargarCatalogo(control.signal)
    consultarEjemplos(control.signal).then(
      (respuesta) => { if (!control.signal.aborted) setEjemplos(respuesta) },
      () => {},
    )
    return () => control.abort()
  }, [cargarCatalogo])

  function reintentarCatalogo() {
    setCatalogo(undefined)
    cargarCatalogo(new AbortController().signal)
  }

  const detenerReproduccion = useCallback(() => {
    window.clearTimeout(pausa.current)
    pausa.current = undefined
    setReproduccion(null)
  }, [])

  const solicitar = useCallback(async (operacion: (senal: AbortSignal) => Promise<void>) => {
    if (solicitud.current) return
    const control = new AbortController()
    solicitud.current = control
    setOcupado(true)
    setError(null)
    setAviso('')
    setAnuncio('')
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

  const recibirLlamada = useCallback(async (recibida: Llamada, senal: AbortSignal, origen: 'consulta' | 'alta' | 'turno' | 'intercambio' = 'consulta') => {
    if (senal.aborted) return
    const sumado = origen === 'intercambio' ? 'Se sumó un intercambio.' : 'Se sumó un turno.'
    const nuevoTurno = origen === 'turno' || origen === 'intercambio'
    const trasSumar = nuevoTurno || reanalizando.current
    setLlamada(recibida)
    if (recibida.estado === 'analizando') {
      reanalizando.current = trasSumar
      setAnuncio(nuevoTurno ? sumado : anunciarAvisos(recibida.sugerencia.avisos))
      const definitiva = await analizarLlamada(recibida.llamada_id, senal)
      if (senal.aborted) return
      setLlamada(definitiva)
      setHuboAnalisis(true)
      reanalizando.current = false
      if (trasSumar && definitiva.estado === 'esperando_operador') {
        setAnuncio(anunciarReanalisis(definitiva.sugerencia.avisos))
      } else {
        setAnuncio(anunciarResultado(definitiva, true))
      }
    } else if (nuevoTurno && recibida.estado === 'esperando_operador') {
      setAnuncio(`${sumado} ${anunciarReanalisis(recibida.sugerencia.avisos)}`)
    } else if (origen === 'alta') {
      setAnuncio(anunciarAvisos(recibida.sugerencia?.avisos ?? []) || 'Sugerencia lista.')
    } else {
      setAnuncio(anunciarResultado(recibida))
    }
  }, [])

  useEffect(() => {
    function abrirDesdeUrl() {
      solicitud.current?.abort()
      solicitud.current = null
      reanalizando.current = false
      detenerReproduccion()
      setSumando(null)
      setErrorTurno('')
      const actual = leerIdentificador()
      setIdentificador(actual)
      setLlamada(null)
      setHuboAnalisis(false)
      setTranscripcion('')
      setEjemploElegido('')
      setReproducirEjemplo(false)
      if (actual) {
        void solicitar(async (senal) => {
          await recibirLlamada(await consultarLlamada(actual, senal), senal)
        })
      } else {
        setOcupado(false)
        setError(null)
        setAviso('')
        setAnuncio('')
      }
    }

    abrirDesdeUrl()
    window.addEventListener('popstate', abrirDesdeUrl)
    return () => {
      window.removeEventListener('popstate', abrirDesdeUrl)
      solicitud.current?.abort()
      solicitud.current = null
    }
  }, [detenerReproduccion, recibirLlamada, solicitar])

  useEffect(() => {
    if (mostrarErrorArriba || aviso || modo === null || catalogo === null) {
      regionAvisos.current?.scrollIntoView({ block: 'nearest' })
    }
  }, [mostrarErrorArriba, aviso, modo, catalogo])

  function elegirEjemplo(id: string) {
    const ejemplo = ejemplos.find((opcion) => opcion.id === id)
    setEjemploElegido(id)
    setReproducirEjemplo(false)
    if (!ejemplo) return
    setTranscripcion(ejemplo.texto)
    setAnuncio(`Ejemplo cargado. ${ejemplo.titulo}`)
  }

  function analizar(evento: FormEvent<HTMLFormElement>) {
    evento.preventDefault()
    if (analisisBloqueado || !transcripcion.trim()) return
    const intercambios = reproducirEjemplo && ejemploSeleccionado ? separarIntercambios(ejemploSeleccionado.turnos) : []
    const [primero] = intercambios
    void solicitar(async (senal) => {
      const creada = await crearLlamada(primero ?? transcripcion, senal)
      if (senal.aborted) return
      cambiarUrl(creada.llamada_id)
      setIdentificador(creada.llamada_id)
      setTranscripcion('')
      setEjemploElegido('')
      setReproducirEjemplo(false)
      if (primero) setReproduccion({ intercambios, recibidos: 1 })
      try {
        await recibirLlamada(creada, senal, 'alta')
      } catch (fallo) {
        if (!primero) throw fallo
        if (senal.aborted) return
        detenerReproduccion()
        setErrorTurno(mensajeErrorTurno(fallo))
      }
    })
  }

  function reintentarAnalisis() {
    if (llamada?.estado !== 'analizando') return
    setErrorTurno('')
    void solicitar((senal) => recibirLlamada(llamada, senal))
  }

  const sumar = useCallback((id: string, turno: Turno, alAceptar: () => void, origen: 'turno' | 'intercambio' = 'turno') => {
    void solicitar(async (senal) => {
      setSumando(origen)
      setErrorTurno('')
      try {
        const ampliada = await sumarTurno(id, turno, senal)
        if (senal.aborted) return
        if (origen === 'turno') setSumando(null)
        alAceptar()
        await recibirLlamada(ampliada, senal, origen)
      } catch (fallo) {
        if (senal.aborted) return
        detenerReproduccion()
        setErrorTurno(mensajeErrorTurno(fallo))
      } finally {
        if (!senal.aborted) setSumando(null)
      }
    })
  }, [detenerReproduccion, recibirLlamada, solicitar])

  useEffect(() => {
    if (!reproduccion || bloqueado || llamada?.estado !== 'esperando_operador') return
    const siguiente = reproduccion.intercambios[reproduccion.recibidos]
    if (!siguiente) return

    const espera = window.setTimeout(() => {
      sumar(llamada.llamada_id, { texto: siguiente, hablante: null }, () => {
        setReproduccion((actual) => actual === reproduccion ? { ...actual, recibidos: actual.recibidos + 1 } : actual)
      }, 'intercambio')
    }, calcularPausa(siguiente))
    pausa.current = espera
    return () => {
      window.clearTimeout(espera)
      if (pausa.current === espera) pausa.current = undefined
    }
  }, [bloqueado, llamada, reproduccion, sumar])

  function sumarAMano(turno: Turno, alAceptar: () => void) {
    if (bloqueado || llamada?.estado !== 'esperando_operador') return
    sumar(llamada.llamada_id, turno, alAceptar)
  }

  function derivar(ajustes: Ajustes) {
    if (bloqueado || !catalogo || llamada?.estado !== 'esperando_operador') return
    if (solicitud.current) return
    const id = llamada.llamada_id
    detenerReproduccion()
    void solicitar(async (senal) => {
      try {
        const derivada = await derivarLlamada(id, ajustes, senal)
        if (senal.aborted) return
        setLlamada(derivada)
        setAnuncio(derivada.carta?.avisos?.length
          ? 'Carta derivada. Hay avisos sin confirmar.'
          : 'Carta derivada.')
      } catch (fallo) {
        if (senal.aborted) return
        if (!(fallo instanceof ErrorApi) || fallo.estado !== 409) throw fallo
        setLlamada(null)
        const actual = await consultarLlamada(id, senal)
        if (senal.aborted) return
        if (actual.estado === 'derivada') {
          setLlamada(actual)
          setAviso('La llamada ya estaba derivada.')
        } else {
          await recibirLlamada(actual, senal)
        }
      }
    })
  }

  function nuevaLlamada() {
    if (nuevaLlamadaBloqueada || (!analizando && !sumandoIntercambio && solicitud.current)) return
    solicitud.current?.abort()
    solicitud.current = null
    reanalizando.current = false
    detenerReproduccion()
    setSumando(null)
    setErrorTurno('')
    setOcupado(false)
    cambiarUrl(null)
    setIdentificador(null)
    setLlamada(null)
    setHuboAnalisis(false)
    setTranscripcion('')
    setEjemploElegido('')
    setReproducirEjemplo(false)
    setError(null)
    setAviso('')
    setAnuncio('Nueva llamada.')
  }

  const pieTranscripcion = (
    <>
      {estadoReproduccion && (
        <div className="panel estado-reproduccion">
          <p aria-hidden="true">{estadoReproduccion}</p>
          {reproduciendo && (
            <button type="button" className="secundario" onClick={() => {
              detenerReproduccion()
              setAnuncio('Reproducción detenida.')
            }}>Detener</button>
          )}
        </div>
      )}
      <FormularioTurno key={identificador} bloqueado={bloqueado || analizando} edicionBloqueada={edicionBloqueada}
        sumando={sumando === 'turno'} error={errorTurno} alSumar={sumarAMano} alEditar={() => setErrorTurno('')}
        alReintentar={errorTurno && analizando && !ocupado ? reintentarAnalisis : undefined} />
    </>
  )

  return (
    <main className={muestraSugerencia ? 'vista-operador' : undefined}>
      <header className="encabezado">
        <h1>Copiloto para Operadores de Sala</h1>
        <span className="modo">Modo: {modo === undefined ? 'consultando…' : modo ?? 'no disponible'}</span>
      </header>

      <div className="avisos" ref={regionAvisos} role={analisisEnCurso ? 'status' : undefined}
        aria-live="polite" aria-atomic={!analisisEnCurso}>
        {analisisEnCurso && <p className="aviso">El modelo está leyendo la llamada… La ubicación ya está leída.</p>}
        <span className="solo-lectores">{ocupado && !analizando
          ? (sumandoIntercambio ? 'Sumando intercambio…' : sumando ? 'Sumando turno…' : llamada?.estado === 'esperando_operador' ? 'Derivando carta…' : identificador ? 'Consultando llamada…' : 'Analizando llamada…')
          : anuncio}</span>
        <span className="solo-lectores">{estadoReproduccion}</span>
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
            <p>{erroresGenerales.length ? 'Revisá los datos.' : 'Revisá los campos marcados.'}</p>
            {erroresGenerales.length > 0 && (
              <ul>
                {erroresGenerales.map(({ loc, msg }, indice) => <li key={indice}>{nombrarCampo(loc)}: {msg}</li>)}
              </ul>
            )}
          </div>
        ) : error && (
          <p className="error">
            {error}
            {analizando && !ocupado && (
              <>{' '}<button type="button" className="secundario" onClick={reintentarAnalisis}>Reintentar el análisis</button></>
            )}
          </p>
        )}
      </div>

      {!identificador && (
        <form className="panel" onSubmit={analizar} onKeyDown={(evento) => {
          // Enter en la transcripción es un salto de línea: se analiza con Ctrl+Enter.
          if (evento.key !== 'Enter' || !(evento.ctrlKey || evento.metaKey)) return
          evento.preventDefault()
          if (!analisisBloqueado && transcripcion.trim()) evento.currentTarget.requestSubmit()
        }}>
          {ejemplos.length > 0 && (
            <label className="cargar-ejemplo">
              Cargar un ejemplo
              <select value={ejemploElegido} disabled={ocupado} onChange={(evento) => elegirEjemplo(evento.target.value)}>
                <option value="">Elegí una llamada…</option>
                {gruposEjemplos.map(({ origen, etiqueta }) => (
                  <optgroup key={origen} label={etiqueta}>
                    {ejemplos.filter((ejemplo) => ejemplo.origen === origen).map(({ id, titulo }) => (
                      <option key={id} value={id}>{origen === 'dataset' ? `${id} · ${titulo}` : titulo}</option>
                    ))}
                  </optgroup>
                ))}
              </select>
            </label>
          )}
          <label className="titulo-campo">
            Transcripción de la llamada
            <textarea rows={7} value={transcripcion} disabled={analisisBloqueado} required
              aria-describedby={catalogo ? undefined : 'estado-catalogo'}
              onChange={(evento) => {
                setTranscripcion(evento.target.value)
                setEjemploElegido('')
                setReproducirEjemplo(false)
                setAnuncio('')
              }} />
          </label>
          {ejemploSeleccionado && separarIntercambios(ejemploSeleccionado.turnos).length > 1 && (
            <label className="reproducir-ejemplo">
              <input type="checkbox" checked={reproducirEjemplo} disabled={analisisBloqueado}
                onChange={(evento) => setReproducirEjemplo(evento.target.checked)} />{' '}
              Reproducir de a un intercambio
            </label>
          )}
          <div className="acciones">
            <button type="submit" disabled={analisisBloqueado || !transcripcion.trim()} aria-keyshortcuts="Control+Enter Meta+Enter">
              {ocupado ? 'Analizando…' : 'Analizar llamada'}
            </button>
            <small className="atajo"><kbd>Ctrl</kbd> + <kbd>Enter</kbd></small>
          </div>
        </form>
      )}

      {muestraSugerencia && (
        muestraFormulario ? (
          <FormularioSugerencia key={llamada.llamada_id} analizando={analizando} pieTranscripcion={pieTranscripcion}
            turnos={llamada.turnos} sugerencia={llamada.sugerencia} catalogo={catalogo ?? null}
            derivacionBloqueada={bloqueado || analizando || !catalogo} edicionBloqueada={edicionBloqueada || !catalogo}
            ocupado={ocupado && !analizando && !sumando} nuevaLlamadaBloqueada={nuevaLlamadaBloqueada}
            alDerivar={derivar} errores={Array.isArray(error) ? error : []}
            alCambiarProtocolo={setAnuncio} alValidar={setError} alEmpezar={nuevaLlamada} />
        ) : (
          <div className="panel-operador">
            <div className="columna-transcripcion">
              <Transcripcion turnos={llamada.turnos} />
              {pieTranscripcion}
            </div>
            <div className="panel acciones">
              <button type="button" className="secundario" disabled={bloqueado} onClick={nuevaLlamada}>
                Nueva llamada
              </button>
            </div>
          </div>
        )
      )}

      {identificador && !muestraSugerencia && (
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
