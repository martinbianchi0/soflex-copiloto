import { useEffect, useRef, useState } from 'react'
import type { FormEvent, KeyboardEvent, ReactNode } from 'react'
import { citaDato, idDictado, nombresTiposHecho, textoOrigen, valorDato } from './api'
import type { Ajustes, Catalogo, Criterio, Dato, DetalleValidacion, Pregunta, Prioridad, Sugerencia, TipoHecho, Turno } from './api'
import { actualizarBorrador, iniciarBorrador, leerAltura } from './borradorSugerencia'
import type { CamposSugerencia } from './borradorSugerencia'
import AvisosSugerencia from './AvisosSugerencia'
import DatosDictados from './DatosDictados'
import DetallesSugerencia from './DetallesSugerencia'
import MiniMapa from './MiniMapa'
import PrioridadEtiqueta from './PrioridadEtiqueta'
import Transcripcion from './Transcripcion'
import { campoSugerencia } from './validacion'

type Propiedades = {
  turnos: Turno[]
  sugerencia: Sugerencia
  catalogo: Catalogo | null
  analizando: boolean
  derivacionBloqueada: boolean
  edicionBloqueada: boolean
  ocupado: boolean
  nuevaLlamadaBloqueada: boolean
  errores: DetalleValidacion[]
  pieTranscripcion: ReactNode
  avisoDuplicados: ReactNode
  alCambiarProtocolo: (mensaje: string) => void
  alDerivar: (ajustes: Ajustes) => void
  alValidar: (errores: DetalleValidacion[]) => void
  alEmpezar: () => void
}

type Control = { id: string; name: string; 'aria-describedby': string; 'aria-invalid'?: true }
const faltante = { origen: 'falta' } as const

function datoVisible<Valor>(dato: Dato<Valor>, valor: Valor | null, invalido = false): Dato<Valor> {
  return invalido || valor !== valorDato(dato) ? { origen: 'operador', valor } : dato
}

function CampoSugerido({ nombre, etiqueta, dato, opcional, nota, errores = [], errorCompartido, children: dibujarControl }: {
  nombre: string
  etiqueta: string
  dato: Dato<unknown>
  opcional?: boolean
  nota?: string
  errores?: string[]
  errorCompartido?: string
  children: (control: Control) => ReactNode
}) {
  const origen = `${nombre}-origen`
  const cita = citaDato(dato)
  const idCita = cita ? `${nombre}-cita` : undefined
  const error = errores.length > 0 ? `error-${nombre}` : undefined
  const idNota = nota ? `${nombre}-nota` : undefined
  const descripcion = [origen, idCita, idNota, error, errorCompartido].filter(Boolean).join(' ')

  return (
    <div className="campo">
      <div className="etiqueta-campo">
        <label htmlFor={nombre}>{etiqueta}{opcional && <> <span className="opcional">(opcional)</span></>}</label>
        <small id={origen} className="origen">{textoOrigen(dato)}</small>
      </div>
      <div>
        {dibujarControl({ id: nombre, name: nombre, 'aria-describedby': descripcion, 'aria-invalid': error || errorCompartido ? true : undefined })}
        {cita && <small id={idCita} className="cita">Turno {cita.turno + 1} · «{cita.texto}»</small>}
        {nota && <small id={idNota} className="cita">{nota}</small>}
        {error && <p id={error} className="error-campo">{errores.join(' ')}</p>}
      </div>
    </div>
  )
}

function CriterioPrioridad({ niveles, reglas }: Criterio) {
  return (
    <details className="criterio-prioridad">
      <summary>Criterio de prioridad</summary>
      {niveles.map(({ id, nombre, definicion, senales }) => (
        <div key={id}>
          <h3>{id} · {nombre}</h3>
          <p>{definicion}</p>
          <ul>{senales.map((senal) => <li key={senal}>{senal}</li>)}</ul>
        </div>
      ))}
      <h3>Reglas</h3>
      <ul>{reglas.map((regla) => <li key={regla}>{regla}</li>)}</ul>
    </details>
  )
}

export default function FormularioSugerencia({
  turnos, sugerencia: recibida, catalogo, analizando, derivacionBloqueada, edicionBloqueada, ocupado,
  nuevaLlamadaBloqueada, errores, pieTranscripcion, avisoDuplicados,
  alCambiarProtocolo, alDerivar, alValidar, alEmpezar,
}: Propiedades) {
  const [borrador, setBorrador] = useState(() => iniciarBorrador(recibida, catalogo))
  // Durante el reanálisis se conserva la última sugerencia completa como base de las ediciones.
  if (borrador.catalogo !== catalogo || (!analizando && borrador.sugerencia !== recibida)) {
    setBorrador(actualizarBorrador(borrador, analizando ? borrador.sugerencia : recibida, catalogo))
  }
  const { sugerencia, campos, marcas, dictadosQuitados, direccionAlternativa } = borrador
  const { calle, altura, esquinaUno, esquinaDos, categoria, subtipo, prioridad } = campos
  const ubicacion = sugerencia.ubicacion
  const [primeraEsquina = faltante, segundaEsquina = faltante] = ubicacion.esquinas
  const calleSugerida = valorDato(ubicacion.calle) ?? ''
  const alturaSugerida = valorDato(ubicacion.altura)
  const categoriaSugerida = valorDato(sugerencia.tipo_hecho)
  const subtipoSugerido = valorDato(sugerencia.subtipo)
  const prioridadSugerida = valorDato(sugerencia.prioridad)
  const [enFoco, setEnFoco] = useState('')
  const formulario = useRef<HTMLFormElement>(null)
  const { numero: numeroAltura, invalida: alturaInvalida } = leerAltura(altura)
  const datos = {
    calle: datoVisible(ubicacion.calle, calle || null),
    altura: datoVisible(ubicacion.altura, numeroAltura, alturaInvalida),
    primera_esquina: datoVisible(primeraEsquina, esquinaUno.trim() ? esquinaUno : null),
    segunda_esquina: datoVisible(segundaEsquina, esquinaDos.trim() ? esquinaDos : null),
    tipo_hecho: datoVisible(sugerencia.tipo_hecho, categoria || null),
    subtipo: datoVisible(sugerencia.subtipo, subtipo),
    prioridad: datoVisible(sugerencia.prioridad, prioridad || null),
  }
  // Una entrecalle del callejero vale para la dirección sugerida: si el operador la cambia, el
  // servicio la vuelve a comprobar al derivar y la quita si ya no corresponde.
  const cambioLaDireccion = datos.calle.origen === 'operador' || datos.altura.origen === 'operador'
  const notaDeEsquina = (dato: Dato<unknown>) => cambioLaDireccion && dato.origen === 'inferido' && dato.fuente === 'callejero'
    ? 'Era de la dirección sugerida: se vuelve a comprobar al derivar.'
    : undefined
  const niveles = catalogo?.criterio.niveles ?? []
  const nivelElegido = niveles.find(({ id }) => id === prioridad)
  const protocolos = catalogo?.protocolos.filter((protocolo) => protocolo.categoria === categoria) ?? []
  const protocolo = protocolos.find(({ id }) => id === subtipo)
  // Los textos salen siempre del catálogo. De la sugerencia se toma sólo qué está respondido y
  // dónde, y sólo si es la misma pregunta del mismo subtipo.
  const sugeridas = subtipo === subtipoSugerido ? sugerencia.checklist : []
  const baseChecklist = protocolo?.preguntas.map(({ id, texto }): Pregunta => (
    sugeridas.find((item) => item.id === id && item.pregunta === texto) ??
    { id, pregunta: texto, respondida: false, cita: null, del_operador: false }
  )) ?? (catalogo ? [] : sugerencia.checklist)
  const checklist = baseChecklist.map((pregunta) => {
    const marca = marcas.get(pregunta.id)
    return marca ? { ...pregunta, ...marca, del_operador: true } : pregunta
  })
  const citas = [
    ...Object.entries(datos).flatMap(([control, dato]) => {
      const cita = citaDato(dato)
      return cita ? [{ control, cita }] : []
    }),
    ...checklist.flatMap(({ id, cita }) => cita ? [{ control: `pregunta-${id}`, cita }] : []),
    ...sugerencia.datos_dictados.map((dato) => ({ control: idDictado(dato), cita: dato.cita })),
  ]
  const citaActiva = edicionBloqueada ? undefined : citas.find(({ control }) => control === enFoco)?.cita
  const erroresDe = (campo: NonNullable<ReturnType<typeof campoSugerencia>>) => errores
    .filter((error) => campoSugerencia(error) === campo).map(({ msg }) => msg)
  const erroresEsquinas = erroresDe('esquinas')
  const errorEsquinas = erroresEsquinas.length ? 'error-esquinas' : undefined

  // Cuando la sugerencia queda editable, el foco va al primer dato que falta para derivar. Si no
  // falta ninguno, queda en la transcripción, que es lo primero que se revisa.
  const huboFocoInicial = useRef(false)
  useEffect(() => {
    if (edicionBloqueada || huboFocoInicial.current) return
    huboFocoInicial.current = true
    const primerFaltante = !calle ? 'calle' : !categoria || categoria === 'NO_DETERMINADA' ? 'tipo_hecho' : !prioridad ? 'prioridad' : null
    if (primerFaltante) document.getElementById(primerFaltante)?.focus()
  }, [edicionBloqueada, calle, categoria, prioridad])

  useEffect(() => {
    if (!edicionBloqueada && errores.length > 0) {
      formulario.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus()
    }
  }, [edicionBloqueada, errores])

  function editar<Campo extends keyof CamposSugerencia>(campo: Campo, valor: CamposSugerencia[Campo]) {
    setBorrador((actual) => ({
      ...actual, campos: { ...actual.campos, [campo]: valor }, editados: new Set([...actual.editados, campo]),
    }))
  }

  function elegirSubtipo(elegido: string | null, tipo = categoria) {
    setBorrador((actual) => ({
      ...actual, campos: { ...actual.campos, categoria: tipo, subtipo: elegido }, marcas: new Map(),
      editados: new Set([...actual.editados, 'categoria', 'subtipo']),
    }))
    const nombre = protocolos.find(({ id }) => id === elegido)?.nombre
    alCambiarProtocolo(nombre ? `${nombre}. Protocolo actualizado.` : 'Sin subtipo elegido.')
  }

  function marcarPregunta(id: string) {
    const pregunta = checklist.find((item) => item.id === id)
    const sugerida = baseChecklist.find((item) => item.id === id)
    if (!pregunta || !sugerida) return
    const respondida = !pregunta.respondida
    const cita = respondida ? pregunta.cita ?? sugerida.cita : null
    setBorrador((actual) => {
      const marcas = new Map(actual.marcas)
      // Volver a como estaba no es un cambio del operador: la pregunta recupera su origen y su cita.
      if (respondida === sugerida.respondida) marcas.delete(id)
      else marcas.set(id, { id, respondida, cita })
      return { ...actual, marcas }
    })
  }

  function marcarDictado(id: string) {
    setBorrador((actual) => {
      const quitados = new Set(actual.dictadosQuitados)
      if (quitados.has(id)) quitados.delete(id)
      else quitados.add(id)
      return { ...actual, dictadosQuitados: quitados }
    })
  }

  function enviar(evento: FormEvent<HTMLFormElement>) {
    evento.preventDefault()
    if (derivacionBloqueada) return

    const esquinas = [esquinaUno, esquinaDos].filter((esquina) => esquina.trim())
    const pendientes: DetalleValidacion[] = []
    if (!calle.trim()) pendientes.push({ loc: ['calle'], msg: 'Ingresá una calle.' })
    const nombres = [calle, ...esquinas].map((nombre) => nombre.trim().toLowerCase())
    if (new Set(nombres).size !== nombres.length) {
      pendientes.push({ loc: ['esquinas'], msg: 'La calle y las esquinas tienen que ser distintas entre sí.' })
    }
    if (alturaInvalida) {
      pendientes.push({ loc: ['altura'], msg: 'Ingresá un número entero entre 1 y 99999.' })
    }
    if (!prioridad) pendientes.push({ loc: ['prioridad'], msg: 'Elegí una prioridad.' })
    if (pendientes.length) {
      alValidar(pendientes)
      return
    }

    const ajustes: Ajustes = {}
    const esquinasSugeridas = ubicacion.esquinas.map((dato) => valorDato(dato) ?? '').filter((esquina) => esquina.trim())
    if (calle !== calleSugerida || numeroAltura !== alturaSugerida ||
      esquinas.length !== esquinasSugeridas.length ||
      esquinas.some((esquina, indice) => esquina !== esquinasSugeridas[indice])) {
      ajustes.ubicacion = { calle, altura: numeroAltura, esquinas }
    }
    if (categoria && (categoria !== categoriaSugerida || subtipo !== subtipoSugerido)) {
      ajustes.tipo_hecho = { categoria, subtipo }
    }
    if (prioridad && prioridad !== prioridadSugerida) ajustes.prioridad = prioridad
    const cambiosChecklist = checklist.flatMap(({ id }) => marcas.get(id) ?? [])
    if (cambiosChecklist.length) ajustes.checklist = cambiosChecklist
    const quitados = sugerencia.datos_dictados.filter((dato) => dictadosQuitados.has(idDictado(dato)))
      .map(({ tipo, valor }) => ({ tipo, valor }))
    if (quitados.length) ajustes.dictados_quitados = quitados
    alDerivar(ajustes)
  }

  function alTeclear(evento: KeyboardEvent<HTMLFormElement>) {
    if (evento.key !== 'Enter') return
    if (evento.ctrlKey || evento.metaKey) {
      evento.preventDefault()
      formulario.current?.requestSubmit()
    } else if (evento.target instanceof HTMLInputElement || evento.target instanceof HTMLSelectElement) {
      // Enter dentro de un campo o de un desplegable no deriva: una carta derivada no se puede
      // deshacer, y el foco suele quedar en el desplegable de la prioridad.
      evento.preventDefault()
    }
  }

  return (
    <div className="panel-operador">
      <div className="columna-transcripcion">
        <Transcripcion turnos={turnos} citas={citas.map(({ cita }) => cita)} citaActiva={citaActiva} />
        {pieTranscripcion}
      </div>
      <form className="panel" ref={formulario} onSubmit={enviar} onKeyDown={alTeclear} noValidate
        onFocus={(evento) => setEnFoco(evento.target.id)} onBlur={() => setEnFoco('')}>
        <fieldset disabled={edicionBloqueada}>
          <legend>Sugerencia</legend>
          {avisoDuplicados}
          <AvisosSugerencia avisos={sugerencia.avisos} />
          <div className="direccion">
            <CampoSugerido nombre="calle" etiqueta="Calle" dato={datos.calle} errores={erroresDe('calle')}
              nota={direccionAlternativa ? `El análisis ahora sugiere otra dirección: ${direccionAlternativa}.` : undefined}>
              {(control) => <input {...control} value={calle} onChange={(evento) => editar('calle', evento.target.value)} required />}
            </CampoSugerido>
            <CampoSugerido nombre="altura" etiqueta="Altura" dato={datos.altura} errores={erroresDe('altura')} opcional>
              {(control) => <input {...control} inputMode="numeric" value={altura} onChange={(evento) => editar('altura', evento.target.value)} />}
            </CampoSugerido>
          </div>
          <div className="esquinas">
            <CampoSugerido nombre="primera_esquina" etiqueta="Primera esquina" dato={datos.primera_esquina} nota={notaDeEsquina(datos.primera_esquina)} errorCompartido={errorEsquinas} opcional>
              {(control) => <input {...control} value={esquinaUno} onChange={(evento) => editar('esquinaUno', evento.target.value)} />}
            </CampoSugerido>
            <CampoSugerido nombre="segunda_esquina" etiqueta="Segunda esquina" dato={datos.segunda_esquina} nota={notaDeEsquina(datos.segunda_esquina)} errorCompartido={errorEsquinas} opcional>
              {(control) => <input {...control} value={esquinaDos} onChange={(evento) => editar('esquinaDos', evento.target.value)} />}
            </CampoSugerido>
            {errorEsquinas && <p id={errorEsquinas} className="error-campo">{erroresEsquinas.join(' ')}</p>}
          </div>
          <MiniMapa calle={calle} altura={altura} esquinas={[esquinaUno, esquinaDos]} />
          <DatosDictados datos={sugerencia.datos_dictados} edicion={{ quitados: dictadosQuitados, alMarcar: marcarDictado }} />
          <div className="hecho">
            <CampoSugerido nombre="tipo_hecho" etiqueta="Tipo de hecho" dato={datos.tipo_hecho} errores={erroresDe('tipo_hecho')}>
              {(control) => (
                <select {...control} value={categoria} onChange={(evento) => {
                  elegirSubtipo(null, evento.target.value as TipoHecho | '')
                }}>
                  {(categoriaSugerida === null || categoria === '') && <option value="">Elegir…</option>}
                  {Object.entries(nombresTiposHecho).map(([opcion, nombre]) => (
                    <option key={opcion} value={opcion}>{nombre}</option>
                  ))}
                </select>
              )}
            </CampoSugerido>
            <CampoSugerido nombre="subtipo" etiqueta="Subtipo" dato={datos.subtipo} errores={erroresDe('subtipo')} opcional>
              {(control) => (
                <select {...control} value={subtipo ?? ''} onChange={(evento) => elegirSubtipo(evento.target.value || null)}
                  aria-describedby={subtipo ? control['aria-describedby'] : `${control['aria-describedby']} ayuda-subtipo`}>
                  <option value="">Sin subtipo</option>
                  {!catalogo && subtipoSugerido && <option value={subtipoSugerido}>{subtipoSugerido}</option>}
                  {protocolos.map(({ id, nombre }) => <option key={id} value={id}>{nombre}</option>)}
                </select>
              )}
            </CampoSugerido>
          </div>
          <CampoSugerido nombre="prioridad" etiqueta="Prioridad" dato={datos.prioridad} errores={erroresDe('prioridad')}>
            {(control) => (
              <>
                <div className="control-prioridad">
                  <select {...control} value={prioridad} required
                    onChange={(evento) => editar('prioridad', evento.target.value as Prioridad | '')}
                    aria-describedby={nivelElegido ? `${control['aria-describedby']} prioridad-definicion` : control['aria-describedby']}>
                    {(prioridadSugerida === null || prioridad === '') && <option value="">Elegir…</option>}
                    {!catalogo && prioridadSugerida && <option value={prioridadSugerida}>{prioridadSugerida}</option>}
                    {niveles.map(({ id, nombre }) => <option key={id} value={id}>{id} · {nombre}</option>)}
                  </select>
                  {prioridad && <PrioridadEtiqueta prioridad={prioridad} />}
                </div>
                {nivelElegido && <small id="prioridad-definicion" className="definicion-prioridad">{nivelElegido.definicion}</small>}
              </>
            )}
          </CampoSugerido>
        </fieldset>
        {catalogo && <CriterioPrioridad {...catalogo.criterio} />}
        {!subtipo && (
          <p className="detalles-sugerencia" id="ayuda-subtipo">
            Elegí un subtipo para ver las instrucciones y las preguntas.
          </p>
        )}
        <DetallesSugerencia checklist={checklist} instrucciones={protocolo?.instrucciones ?? (catalogo ? [] : sugerencia.instrucciones)}
          errores={erroresDe('checklist')} bloqueado={edicionBloqueada} alMarcar={marcarPregunta} />
        <div className="acciones">
          <button type="submit" disabled={derivacionBloqueada} aria-keyshortcuts="Control+Enter Meta+Enter">
            {ocupado ? 'Derivando…' : 'Derivar Carta de Llamada'}
          </button>
          <small className="atajo"><kbd>Ctrl</kbd> + <kbd>Enter</kbd></small>
          <button type="button" className="secundario" disabled={nuevaLlamadaBloqueada} onClick={alEmpezar}>
            Nueva llamada
          </button>
        </div>
      </form>
    </div>
  )
}
