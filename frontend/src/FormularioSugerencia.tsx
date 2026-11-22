import { useEffect, useRef, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { nombresTiposHecho, textoOrigen, valorDato } from './api'
import type { Ajustes, Catalogo, Criterio, Dato, DetalleValidacion, Pregunta, Prioridad, Sugerencia, TipoHecho, Turno } from './api'
import AvisosSugerencia from './AvisosSugerencia'
import DetallesSugerencia from './DetallesSugerencia'
import PrioridadEtiqueta from './PrioridadEtiqueta'
import Transcripcion from './Transcripcion'
import { campoSugerencia } from './validacion'

type Propiedades = {
  turnos: Turno[]
  sugerencia: Sugerencia
  catalogo: Catalogo
  bloqueado: boolean
  ocupado: boolean
  errores: DetalleValidacion[]
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

function CampoSugerido({ nombre, etiqueta, dato, opcional, errores = [], errorCompartido, children: dibujarControl }: {
  nombre: string
  etiqueta: string
  dato: Dato<unknown>
  opcional?: boolean
  errores?: string[]
  errorCompartido?: string
  children: (control: Control) => ReactNode
}) {
  const origen = `${nombre}-origen`
  const cita = dato.origen === 'dicho' ? `${nombre}-cita` : undefined
  const error = errores.length > 0 ? `error-${nombre}` : undefined
  const descripcion = [origen, cita, error, errorCompartido].filter(Boolean).join(' ')

  return (
    <div className="campo">
      <div className="etiqueta-campo">
        <label htmlFor={nombre}>{etiqueta}{opcional && <> <span className="opcional">(opcional)</span></>}</label>
        <small id={origen} className="origen">{textoOrigen(dato)}</small>
      </div>
      <div>
        {dibujarControl({ id: nombre, name: nombre, 'aria-describedby': descripcion, 'aria-invalid': error || errorCompartido ? true : undefined })}
        {dato.origen === 'dicho' && <small id={cita} className="cita">Turno {dato.cita.turno + 1} · «{dato.cita.texto}»</small>}
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
  turnos, sugerencia, catalogo, bloqueado, ocupado, errores, alCambiarProtocolo, alDerivar, alValidar, alEmpezar,
}: Propiedades) {
  const ubicacion = sugerencia.ubicacion
  const [primeraEsquina = faltante, segundaEsquina = faltante] = ubicacion.esquinas
  const calleSugerida = valorDato(ubicacion.calle) ?? ''
  const alturaSugerida = valorDato(ubicacion.altura)
  const categoriaSugerida = valorDato(sugerencia.tipo_hecho)
  const subtipoSugerido = valorDato(sugerencia.subtipo)
  const prioridadSugerida = valorDato(sugerencia.prioridad)
  const [calle, setCalle] = useState(calleSugerida)
  const [altura, setAltura] = useState(alturaSugerida?.toString() ?? '')
  const [esquinaUno, setEsquinaUno] = useState(valorDato(primeraEsquina) ?? '')
  const [esquinaDos, setEsquinaDos] = useState(valorDato(segundaEsquina) ?? '')
  const [categoria, setCategoria] = useState<TipoHecho | ''>(categoriaSugerida ?? '')
  // Un subtipo sugerido que no es de esa categoría en el catálogo se descarta: queda "Sin subtipo".
  const [subtipo, setSubtipo] = useState(() => catalogo.protocolos.some(
    (protocolo) => protocolo.id === subtipoSugerido && protocolo.categoria === categoriaSugerida,
  ) ? subtipoSugerido : null)
  const [prioridad, setPrioridad] = useState<Prioridad | ''>(prioridadSugerida ?? '')
  const [marcas, setMarcas] = useState(() => new Set<string>())
  const [enFoco, setEnFoco] = useState('')
  const formulario = useRef<HTMLFormElement>(null)
  const textoAltura = altura.trim()
  const numeroAltura = textoAltura ? Number(textoAltura) : null
  const alturaInvalida = numeroAltura !== null && (!/^\d+$/.test(textoAltura) || numeroAltura < 1 || numeroAltura > 99999)
  const datos = {
    calle: datoVisible(ubicacion.calle, calle || null),
    altura: datoVisible(ubicacion.altura, numeroAltura, alturaInvalida),
    primera_esquina: datoVisible(primeraEsquina, esquinaUno.trim() ? esquinaUno : null),
    segunda_esquina: datoVisible(segundaEsquina, esquinaDos.trim() ? esquinaDos : null),
    tipo_hecho: datoVisible(sugerencia.tipo_hecho, categoria || null),
    subtipo: datoVisible(sugerencia.subtipo, subtipo),
    prioridad: datoVisible(sugerencia.prioridad, prioridad || null),
  }
  const { niveles } = catalogo.criterio
  const nivelElegido = niveles.find(({ id }) => id === prioridad)
  const protocolos = catalogo.protocolos.filter((protocolo) => protocolo.categoria === categoria)
  const protocolo = protocolos.find(({ id }) => id === subtipo)
  // Los textos salen siempre del catálogo. De la sugerencia se toma sólo qué está respondido y
  // dónde, y sólo si es la misma pregunta del mismo subtipo.
  const sugeridas = subtipo === subtipoSugerido ? sugerencia.checklist : []
  const checklist = protocolo?.preguntas.map(({ id, texto }): Pregunta => {
    const base = sugeridas.find((item) => item.id === id && item.pregunta === texto) ??
      { id, pregunta: texto, respondida: false, cita: null, del_operador: false }
    return marcas.has(id) ? { ...base, respondida: !base.respondida, cita: null, del_operador: true } : base
  }) ?? []
  const citas = [
    ...Object.entries(datos).flatMap(([control, dato]) => dato.origen === 'dicho' ? [{ control, cita: dato.cita }] : []),
    ...checklist.flatMap(({ id, cita }) => cita ? [{ control: `pregunta-${id}`, cita }] : []),
  ]
  const citaActiva = bloqueado ? undefined : citas.find(({ control }) => control === enFoco)?.cita
  const erroresDe = (campo: NonNullable<ReturnType<typeof campoSugerencia>>) => errores
    .filter((error) => campoSugerencia(error) === campo).map(({ msg }) => msg)
  const erroresEsquinas = erroresDe('esquinas')
  const errorEsquinas = erroresEsquinas.length ? 'error-esquinas' : undefined

  useEffect(() => {
    if (!bloqueado && errores.length > 0) {
      formulario.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus()
    }
  }, [bloqueado, errores])

  function elegirSubtipo(elegido: string | null) {
    setSubtipo(elegido)
    setMarcas(new Set())
    const nombre = protocolos.find(({ id }) => id === elegido)?.nombre
    alCambiarProtocolo(nombre ? `${nombre}. Protocolo actualizado.` : 'Sin subtipo elegido.')
  }

  function marcarPregunta(id: string) {
    setMarcas((anteriores) => {
      const siguientes = new Set(anteriores)
      if (!siguientes.delete(id)) siguientes.add(id)
      return siguientes
    })
  }

  function enviar(evento: FormEvent<HTMLFormElement>) {
    evento.preventDefault()
    if (bloqueado) return

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
    const cambiosChecklist = checklist.filter(({ id }) => marcas.has(id)).map(({ id, respondida }) => ({ id, respondida }))
    if (cambiosChecklist.length) ajustes.checklist = cambiosChecklist
    alDerivar(ajustes)
  }

  return (
    <div className="panel-operador">
      <Transcripcion turnos={turnos} citas={citas.map(({ cita }) => cita)} citaActiva={citaActiva} />
      <form className="panel" ref={formulario} onSubmit={enviar} noValidate
        onFocus={(evento) => setEnFoco(evento.target.id)} onBlur={() => setEnFoco('')}>
        <fieldset disabled={bloqueado}>
          <legend>Sugerencia</legend>
          <AvisosSugerencia avisos={sugerencia.avisos} />
          <div className="direccion">
            <CampoSugerido nombre="calle" etiqueta="Calle" dato={datos.calle} errores={erroresDe('calle')}>
              {(control) => <input {...control} value={calle} onChange={(evento) => setCalle(evento.target.value)} required />}
            </CampoSugerido>
            <CampoSugerido nombre="altura" etiqueta="Altura" dato={datos.altura} errores={erroresDe('altura')} opcional>
              {(control) => <input {...control} inputMode="numeric" value={altura} onChange={(evento) => setAltura(evento.target.value)} />}
            </CampoSugerido>
          </div>
          <div className="esquinas">
            <CampoSugerido nombre="primera_esquina" etiqueta="Primera esquina" dato={datos.primera_esquina} errorCompartido={errorEsquinas} opcional>
              {(control) => <input {...control} value={esquinaUno} onChange={(evento) => setEsquinaUno(evento.target.value)} />}
            </CampoSugerido>
            <CampoSugerido nombre="segunda_esquina" etiqueta="Segunda esquina" dato={datos.segunda_esquina} errorCompartido={errorEsquinas} opcional>
              {(control) => <input {...control} value={esquinaDos} onChange={(evento) => setEsquinaDos(evento.target.value)} />}
            </CampoSugerido>
            {errorEsquinas && <p id={errorEsquinas} className="error-campo">{erroresEsquinas.join(' ')}</p>}
          </div>
          <div className="hecho">
            <CampoSugerido nombre="tipo_hecho" etiqueta="Tipo de hecho" dato={datos.tipo_hecho} errores={erroresDe('tipo_hecho')}>
              {(control) => (
                <select {...control} value={categoria} onChange={(evento) => {
                  setCategoria(evento.target.value as TipoHecho | '')
                  elegirSubtipo(null)
                }}>
                  {categoriaSugerida === null && <option value="">Elegir…</option>}
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
                    onChange={(evento) => setPrioridad(evento.target.value as Prioridad | '')}
                    aria-describedby={nivelElegido ? `${control['aria-describedby']} prioridad-definicion` : control['aria-describedby']}>
                    {prioridadSugerida === null && <option value="">Elegir…</option>}
                    {niveles.map(({ id, nombre }) => <option key={id} value={id}>{id} · {nombre}</option>)}
                  </select>
                  {prioridad && <PrioridadEtiqueta prioridad={prioridad} />}
                </div>
                {nivelElegido && <small id="prioridad-definicion" className="definicion-prioridad">{nivelElegido.definicion}</small>}
              </>
            )}
          </CampoSugerido>
        </fieldset>
        <CriterioPrioridad {...catalogo.criterio} />
        {!subtipo && (
          <p className="detalles-sugerencia" id="ayuda-subtipo">
            Elegí un subtipo para ver las instrucciones y las preguntas.
          </p>
        )}
        <DetallesSugerencia checklist={checklist} instrucciones={protocolo?.instrucciones ?? []}
          errores={erroresDe('checklist')} bloqueado={bloqueado} alMarcar={marcarPregunta} />
        <div className="acciones">
          <button type="submit" disabled={bloqueado}>
            {ocupado ? 'Derivando…' : 'Derivar Carta de Llamada'}
          </button>
          <button type="button" className="secundario" disabled={bloqueado} onClick={alEmpezar}>
            Nueva llamada
          </button>
        </div>
      </form>
    </div>
  )
}
