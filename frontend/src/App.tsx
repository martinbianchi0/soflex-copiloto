import { useCallback, useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { actualizarCarta, analizarLlamada, consultarCatalogo, consultarDuplicados, consultarEjemplos, consultarLlamada, consultarSalud, crearLlamada, derivarLlamada, ErrorApi, sumarTurno, terminarLlamada, valorDato } from './api'
import type { Ajustes, Aviso, Carta, Catalogo, DetalleValidacion, Ejemplo, Llamada, PosibleDuplicado, Proveedor, Salud, Turno } from './api'
import AvisoDuplicados from './AvisoDuplicados'
import CartaLlamada from './CartaLlamada'
import FormularioSugerencia from './FormularioSugerencia'
import type { AccionCarta } from './FormularioSugerencia'
import FormularioTurno from './FormularioTurno'
import { calcularPausa, separarIntercambios } from './reproduccion'
import SelectorDeModo from './SelectorDeModo'
import Transcripcion from './Transcripcion'
import { campoSugerencia, nombrarCampo } from './validacion'

const errorConexion = 'No se pudo conectar con el servicio.'
const gruposEjemplos = [
  { origen: 'dataset', etiqueta: 'Llamadas del dataset' },
  { origen: 'nueva', etiqueta: 'Otros ejemplos' },
] as const

type Reproduccion = { intercambios: string[]; recibidos: number }
type LlamadaAbierta = Extract<Llamada, { estado: 'analizando' | 'esperando_operador' }>
type EstadoDuplicados = {
  llamadaId: string
  lugar: string
  recibidaEn: string | null
  posibles: PosibleDuplicado[]
  anuncio: number
}

// Mientras la llamada está abierta puede entrar otra del mismo lugar.
const REFRESCO_DE_DUPLICADOS_MS = 15_000

function estaAbierta(llamada: Llamada | null): llamada is LlamadaAbierta {
  return llamada?.estado === 'analizando' || llamada?.estado === 'esperando_operador'
}

function lugarDe({ sugerencia: { ubicacion } }: LlamadaAbierta) {
  return JSON.stringify([valorDato(ubicacion.calle), valorDato(ubicacion.altura), ubicacion.esquinas.map(valorDato)])
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

function anunciarAvisos(avisos: Aviso[], derivada = false) {
  const pendientes = avisos.filter(({ codigo }) => codigo !== 'modelo_no_disponible').length
  const mensajes = avisos.filter(({ codigo }) => codigo === 'modelo_no_disponible').map(({ mensaje }) => mensaje)
  const cuando = derivada ? '' : ' antes de derivar'
  if (pendientes === 1) mensajes.push(`La sugerencia tiene un aviso para revisar${cuando}.`)
  if (pendientes > 1) mensajes.push(`La sugerencia tiene ${pendientes} avisos para revisar${cuando}.`)
  return mensajes.join(' ')
}

function anunciarResultado(llamada: Llamada, anunciarTodosLosAvisos = false) {
  if (llamada.estado === 'terminada') return 'Llamada terminada. Carta de Llamada disponible.'
  if (llamada.estado === 'en_proceso') return 'Llamada en proceso.'
  if (llamada.estado !== 'esperando_operador') return ''

  const avisos = anunciarTodosLosAvisos ? llamada.sugerencia.avisos
    : llamada.sugerencia.avisos.filter(({ codigo }) => codigo === 'modelo_no_disponible')
  const estado = llamada.carta ? 'Carta derivada: la llamada sigue abierta.' : 'Sugerencia lista.'
  return [estado, anunciarAvisos(avisos, Boolean(llamada.carta)), anunciarCartaVieja(llamada)].filter(Boolean).join(' ')
}

function anunciarReanalisis(llamada: LlamadaAbierta) {
  const { avisos } = llamada.sugerencia
  const cambio = avisos.find(({ codigo }) => codigo === 'prioridad_cambiada')
  const otrosAvisos = avisos.filter(({ codigo }) => codigo !== 'prioridad_cambiada')
  return ['Sugerencia actualizada.', cambio?.mensaje, anunciarAvisos(otrosAvisos, Boolean(llamada.carta)), anunciarCartaVieja(llamada)]
    .filter(Boolean).join(' ')
}

// Lo que dijo el llamante después de derivar puede cambiar lo que saldría en la carta.
function anunciarCartaVieja(llamada: Llamada) {
  return llamada.carta_al_dia === false ? 'La carta derivada no tiene lo último: revisá y actualizala.' : ''
}

function anunciarCarta(previa: Carta | null, llamada: Llamada) {
  if (!previa) {
    const avisos = llamada.carta?.avisos?.length ? ' Hay avisos sin confirmar.' : ''
    return `Carta derivada.${avisos} La llamada sigue abierta: podés seguir con el protocolo.`
  }
  return llamada.carta?.actualizada_en !== previa.actualizada_en ? 'Carta actualizada.' : 'La carta ya tenía todo: no cambió.'
}

const anunciosDeAccion: Record<AccionCarta, string> = {
  derivar: 'Derivando carta…',
  actualizar: 'Actualizando la carta…',
  terminar: 'Terminando la llamada…',
}

function mensajeErrorTurno(fallo: unknown) {
  if (!(fallo instanceof ErrorApi)) return errorConexion
  const { detalle } = fallo
  if (Array.isArray(detalle)) return detalle.map(({ msg }) => msg).join(' ')
  return detalle ?? `El servicio respondió con un error (${fallo.estado}).`
}

function App() {
  const [salud, setSalud] = useState<Salud | null>()
  const [preferencia, setPreferencia] = useState<Proveedor>()
  const [catalogo, setCatalogo] = useState<Catalogo | null>()
  const [ejemplos, setEjemplos] = useState<Ejemplo[]>([])
  const [ejemploElegido, setEjemploElegido] = useState('')
  const [reproducirEjemplo, setReproducirEjemplo] = useState(false)
  const [reproduccion, setReproduccion] = useState<Reproduccion | null>(null)
  const [identificador, setIdentificador] = useState(leerIdentificador)
  const [llamada, setLlamada] = useState<Llamada | null>(null)
  const [duplicados, setDuplicados] = useState<EstadoDuplicados | null>(null)
  const [huboAnalisis, setHuboAnalisis] = useState(false)
  const [transcripcion, setTranscripcion] = useState('')
  const [ocupado, setOcupado] = useState(false)
  const [error, setError] = useState<string | DetalleValidacion[] | null>(null)
  const [aviso, setAviso] = useState('')
  const [anuncio, setAnuncio] = useState('')
  const [anuncioDireccion, setAnuncioDireccion] = useState('')
  const [sumando, setSumando] = useState<'turno' | 'intercambio' | null>(null)
  const [accionCarta, setAccionCarta] = useState<AccionCarta | null>(null)
  const [errorTurno, setErrorTurno] = useState('')
  const solicitud = useRef<AbortController | null>(null)
  const solicitudDuplicados = useRef<AbortController | null>(null)
  const pausa = useRef<number | undefined>(undefined)
  const reanalizando = useRef(false)
  const regionAvisos = useRef<HTMLDivElement>(null)
  const proveedorElegido = salud?.proveedores.find((proveedor) => proveedor === preferencia) ?? salud?.llm_provider
  const bloqueado = ocupado || salud === undefined
  const analisisBloqueado = bloqueado || !catalogo
  const analizando = llamada?.estado === 'analizando'
  const analisisEnCurso = analizando && ocupado
  const accionEnCurso = ocupado && !analizando && !sumando ? accionCarta : null
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
  const idAbierta = estaAbierta(llamada) ? llamada.llamada_id : null
  const lugarAbierto = estaAbierta(llamada) ? lugarDe(llamada) : null
  const duplicadosVisibles = muestraFormulario && duplicados?.llamadaId === idAbierta &&
    duplicados.lugar === lugarAbierto && duplicados.recibidaEn && duplicados.posibles.length > 0 ? duplicados : null
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
      (respuesta) => { if (!control.signal.aborted) setSalud(respuesta) },
      () => { if (!control.signal.aborted) setSalud(null) },
    )
    cargarCatalogo(control.signal)
    consultarEjemplos(control.signal).then(
      (respuesta) => { if (!control.signal.aborted) setEjemplos(respuesta) },
      // Sin ejemplos el panel sirve igual: el selector no aparece y la llamada se escribe.
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

  const pedirDuplicados = useCallback((id: string, lugar: string) => {
    solicitudDuplicados.current?.abort()
    const control = new AbortController()
    solicitudDuplicados.current = control
    consultarDuplicados(id, control.signal).then(
      ({ llamada_id, recibida_en: recibidaEn, posibles }) => {
        if (control.signal.aborted || llamada_id !== id) return
        setDuplicados((anterior) => {
          const vigente = anterior?.llamadaId === id && anterior.lugar === lugar ? anterior : null
          const conocidas = new Set(vigente?.posibles.map((posible) => posible.llamada_id))
          const hayOtraNueva = posibles.some((posible) => !conocidas.has(posible.llamada_id))
          // Se anuncia sólo cuando aparece una llamada que no estaba en la lista.
          return { llamadaId: id, lugar, recibidaEn, posibles, anuncio: (vigente?.anuncio ?? 0) + (hayOtraNueva ? 1 : 0) }
        })
      },
      // Si la consulta falla queda lo que había: es un aviso, y la consulta siguiente lo actualiza.
      () => {},
    )
  }, [])

  const mostrarLlamada = useCallback((recibida: Llamada | null) => {
    solicitudDuplicados.current?.abort()
    solicitudDuplicados.current = null
    setLlamada(recibida)
    if (recibida) setPreferencia(recibida.proveedor)
    if (!estaAbierta(recibida)) return

    const id = recibida.llamada_id
    const lugar = lugarDe(recibida)
    // El aviso de otra dirección no vale para esta: se quita sin esperar la respuesta.
    setDuplicados((anterior) => anterior?.llamadaId === id && anterior.lugar === lugar ? anterior : null)
    pedirDuplicados(id, lugar)
  }, [pedirDuplicados])

  useEffect(() => {
    if (idAbierta === null || lugarAbierto === null) return
    const refresco = window.setInterval(() => pedirDuplicados(idAbierta, lugarAbierto), REFRESCO_DE_DUPLICADOS_MS)
    return () => window.clearInterval(refresco)
  }, [idAbierta, lugarAbierto, pedirDuplicados])

  const recibirLlamada = useCallback(async (recibida: Llamada, senal: AbortSignal, origen: 'consulta' | 'alta' | 'turno' | 'intercambio' = 'consulta') => {
    if (senal.aborted) return
    const sumado = origen === 'intercambio' ? 'Se sumó un intercambio.' : 'Se sumó un turno.'
    const nuevoTurno = origen === 'turno' || origen === 'intercambio'
    const trasSumar = nuevoTurno || reanalizando.current
    mostrarLlamada(recibida)
    if (recibida.estado === 'analizando') {
      reanalizando.current = trasSumar
      setAnuncio(nuevoTurno ? sumado : anunciarAvisos(recibida.sugerencia.avisos))
      const definitiva = await analizarLlamada(recibida.llamada_id, senal)
      if (senal.aborted) return
      mostrarLlamada(definitiva)
      setHuboAnalisis(true)
      reanalizando.current = false
      if (trasSumar && definitiva.estado === 'esperando_operador') {
        setAnuncio(anunciarReanalisis(definitiva))
      } else {
        setAnuncio(anunciarResultado(definitiva, true))
      }
    } else if (nuevoTurno && recibida.estado === 'esperando_operador') {
      setAnuncio(`${sumado} ${anunciarReanalisis(recibida)}`)
    } else if (origen === 'alta') {
      setAnuncio(anunciarAvisos(recibida.sugerencia?.avisos ?? []) || 'Sugerencia lista.')
    } else {
      setAnuncio(anunciarResultado(recibida))
    }
  }, [mostrarLlamada])

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
      mostrarLlamada(null)
      setDuplicados(null)
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
      solicitudDuplicados.current?.abort()
    }
  }, [detenerReproduccion, mostrarLlamada, recibirLlamada, solicitar])

  useEffect(() => {
    if (mostrarErrorArriba || aviso || salud === null || catalogo === null) {
      regionAvisos.current?.scrollIntoView({ block: 'nearest' })
    }
  }, [mostrarErrorArriba, aviso, salud, catalogo])

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
    const proveedor = salud?.proveedores.length === 2 ? proveedorElegido : undefined
    void solicitar(async (senal) => {
      const creada = await crearLlamada(primero ?? transcripcion, senal, proveedor)
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

  // Un 409: la llamada cambió en otro lado (otra pestaña la derivó o la terminó). Se vuelve a pedir
  // y se muestra como está ahora. El formulario no se desarma: lo que el operador tenía en pantalla
  // sigue, y la barra dice si la carta no lo tiene.
  async function recuperarDe409(fallo: unknown, id: string, derivada: boolean, senal: AbortSignal) {
    if (!(fallo instanceof ErrorApi) || fallo.estado !== 409) throw fallo
    const actual = await consultarLlamada(id, senal)
    if (senal.aborted) return
    if (actual.estado === 'terminada') {
      mostrarLlamada(actual)
      setAviso('La llamada ya estaba terminada.')
    } else if (!derivada && actual.carta) {
      mostrarLlamada(actual)
      setAviso('La llamada ya estaba derivada. Lo que tenés en pantalla sigue acá: si hay cambios, actualizá la carta.')
    } else {
      await recibirLlamada(actual, senal)
    }
  }

  // Derivar la carta o, si ya se derivó, mandar una versión nueva. La reproducción sigue: la
  // llamada no termina al derivar.
  function derivar(ajustes: Ajustes) {
    if (bloqueado || !catalogo || llamada?.estado !== 'esperando_operador') return
    if (solicitud.current) return
    const { llamada_id: id, carta: previa } = llamada
    setAccionCarta(previa ? 'actualizar' : 'derivar')
    void solicitar(async (senal) => {
      try {
        const respuesta = previa ? await actualizarCarta(id, ajustes, senal) : await derivarLlamada(id, ajustes, senal)
        if (senal.aborted) return
        mostrarLlamada(respuesta)
        setAnuncio(anunciarCarta(previa, respuesta))
      } catch (fallo) {
        if (senal.aborted) return
        await recuperarDe409(fallo, id, Boolean(previa), senal)
      }
    })
  }

  // Cierra la llamada. Con cambios que la carta no tiene, primero la actualiza: si eso falla (por
  // ejemplo, falta un dato), la llamada sigue abierta.
  function terminar(ajustes: Ajustes | null) {
    if (bloqueado || llamada?.estado !== 'esperando_operador' || !llamada.carta) return
    if (solicitud.current) return
    const id = llamada.llamada_id
    setAccionCarta('terminar')
    void solicitar(async (senal) => {
      try {
        if (ajustes) {
          const actualizada = await actualizarCarta(id, ajustes, senal)
          if (senal.aborted) return
          mostrarLlamada(actualizada)
        }
        const terminada = await terminarLlamada(id, senal)
        if (senal.aborted) return
        detenerReproduccion()
        mostrarLlamada(terminada)
        setAnuncio(ajustes ? 'Carta actualizada. Llamada terminada.' : 'Llamada terminada.')
      } catch (fallo) {
        if (senal.aborted) return
        await recuperarDe409(fallo, id, true, senal)
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
    mostrarLlamada(null)
    setDuplicados(null)
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
        <SelectorDeModo salud={salud} proveedor={llamada?.proveedor ?? proveedorElegido}
          bloqueado={ocupado || llamada !== null} alElegir={setPreferencia} />
      </header>

      <div className="avisos" ref={regionAvisos} role={analisisEnCurso ? 'status' : undefined}
        aria-live="polite" aria-atomic={false}>
        <div aria-atomic={!analisisEnCurso}>
          {analisisEnCurso && <p className="aviso">El modelo está leyendo la llamada… La ubicación ya está leída.</p>}
          <span className="solo-lectores">{ocupado && !analizando
            ? (sumandoIntercambio ? 'Sumando intercambio…' : sumando ? 'Sumando turno…' : accionEnCurso ? anunciosDeAccion[accionEnCurso] : identificador ? 'Consultando llamada…' : 'Analizando llamada…')
            : anuncio}</span>
          <span className="solo-lectores">{estadoReproduccion}</span>
          {aviso && <p className="aviso">{aviso}</p>}
          {salud === null && error !== errorConexion && <p className="error">{errorConexion}</p>}
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
        <span className="solo-lectores" aria-atomic="true">{muestraFormulario && anuncioDireccion}</span>
        <span className="solo-lectores" aria-atomic="true">
          {duplicadosVisibles && (
            <span key={duplicadosVisibles.anuncio}>Hay otra llamada reciente del mismo lugar.</span>
          )}
        </span>
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
            carta={llamada.carta} ajustesEnviados={llamada.ajustes} cartaAlDia={llamada.carta_al_dia}
            avisoDuplicados={duplicadosVisibles?.recibidaEn && (
              <AvisoDuplicados recibidaEn={duplicadosVisibles.recibidaEn} posibles={duplicadosVisibles.posibles} />
            )}
            derivacionBloqueada={bloqueado || analizando || !catalogo} edicionBloqueada={edicionBloqueada || !catalogo}
            accion={accionEnCurso} nuevaLlamadaBloqueada={nuevaLlamadaBloqueada}
            alDerivar={derivar} alTerminar={terminar} errores={Array.isArray(error) ? error : []}
            alCambiarProtocolo={setAnuncio} alAnunciarDireccion={setAnuncioDireccion}
            alValidar={setError} alEmpezar={nuevaLlamada} />
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
          {llamada?.estado === 'terminada' && <CartaLlamada carta={llamada.carta} catalogo={catalogo ?? null} />}
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
