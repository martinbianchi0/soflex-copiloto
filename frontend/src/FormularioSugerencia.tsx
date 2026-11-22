import { useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { nombresTiposHecho, textoOrigen, valorDato } from './api'
import type { Ajustes, Catalogo, Criterio, Dato, DetalleValidacion, Prioridad, Sugerencia, TipoHecho } from './api'
import AvisosSugerencia from './AvisosSugerencia'
import DetallesSugerencia from './DetallesSugerencia'

type Propiedades = {
  sugerencia: Sugerencia
  catalogo: Catalogo
  bloqueado: boolean
  ocupado: boolean
  erroresSubtipo: string
  alDerivar: (ajustes: Ajustes) => void
  alValidar: (errores: DetalleValidacion[]) => void
  alEmpezar: () => void
}

type Control = { id: string; name: string; 'aria-describedby': string }
const faltante = { origen: 'falta' } as const

function CampoSugerido({ nombre, etiqueta, dato, opcional, children: dibujarControl }: {
  nombre: string
  etiqueta: string
  dato: Dato<unknown>
  opcional?: boolean
  children: (control: Control) => ReactNode
}) {
  const origen = `${nombre}-origen`
  const cita = `${nombre}-cita`
  const descripcion = dato.origen === 'dicho' ? `${origen} ${cita}` : origen

  return (
    <div className="campo">
      <div className="etiqueta-campo">
        <label htmlFor={nombre}>{etiqueta}{opcional && <> <span className="opcional">(opcional)</span></>}</label>
        <small id={origen} className="origen">{textoOrigen(dato)}</small>
      </div>
      <div>
        {dibujarControl({ id: nombre, name: nombre, 'aria-describedby': descripcion })}
        {dato.origen === 'dicho' && <small id={cita} className="cita">Turno {dato.cita.turno + 1} · «{dato.cita.texto}»</small>}
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
  sugerencia, catalogo, bloqueado, ocupado, erroresSubtipo, alDerivar, alValidar, alEmpezar,
}: Propiedades) {
  const ubicacion = sugerencia.ubicacion
  const [primeraEsquina = faltante, segundaEsquina = faltante] = ubicacion.esquinas
  const calleSugerida = valorDato(ubicacion.calle) ?? ''
  const alturaSugerida = valorDato(ubicacion.altura)
  const categoriaSugerida = valorDato(sugerencia.tipo_hecho)
  const subtipoSugerido = valorDato(sugerencia.subtipo)
  const prioridadSugerida = valorDato(sugerencia.prioridad)
  const [categoria, setCategoria] = useState<TipoHecho | ''>(categoriaSugerida ?? '')
  // Un subtipo sugerido que no es de esa categoría en el catálogo se descarta: queda "Sin subtipo".
  const [subtipo, setSubtipo] = useState(() => catalogo.protocolos.some(
    (protocolo) => protocolo.id === subtipoSugerido && protocolo.categoria === categoriaSugerida,
  ) ? subtipoSugerido : null)
  const [prioridadElegida, setPrioridadElegida] = useState<Prioridad | ''>(prioridadSugerida ?? '')
  const { niveles } = catalogo.criterio
  const nivelElegido = niveles.find(({ id }) => id === prioridadElegida)
  const protocolos = catalogo.protocolos.filter((protocolo) => protocolo.categoria === categoria)
  const protocolo = protocolos.find(({ id }) => id === subtipo)
  // Los textos salen siempre del catálogo. De la sugerencia se toma sólo qué está respondido y
  // dónde, y sólo si es la misma pregunta del mismo subtipo.
  const sugeridas = subtipo === subtipoSugerido ? sugerencia.checklist : []
  const checklist = protocolo?.preguntas.map(({ id, texto }) => (
    sugeridas.find((item) => item.id === id && item.pregunta === texto) ??
      { id, pregunta: texto, respondida: false, cita: null }
  )) ?? []
  const instrucciones = protocolo?.instrucciones ?? []

  function enviar(evento: FormEvent<HTMLFormElement>) {
    evento.preventDefault()
    if (bloqueado) return

    const datos = new FormData(evento.currentTarget)
    const valor = (campo: string) => String(datos.get(campo) ?? '')
    const calle = valor('calle')
    const textoAltura = valor('altura').trim()
    const altura = textoAltura ? Number(textoAltura) : null
    const esquinas = [valor('primera_esquina'), valor('segunda_esquina')].filter((esquina) => esquina.trim())
    const prioridad = valor('prioridad') as Prioridad | ''

    const errores: DetalleValidacion[] = []
    if (!calle.trim()) errores.push({ loc: ['calle'], msg: 'Ingresá una calle.' })
    const nombres = [calle, ...esquinas].map((nombre) => nombre.trim().toLowerCase())
    if (new Set(nombres).size !== nombres.length) {
      errores.push({ loc: ['esquinas'], msg: 'La calle y las esquinas tienen que ser distintas entre sí.' })
    }
    if (altura !== null && (!/^\d+$/.test(textoAltura) || altura < 1 || altura > 99999)) {
      errores.push({ loc: ['altura'], msg: 'Ingresá un número entero entre 1 y 99999.' })
    }
    if (!prioridad) errores.push({ loc: ['prioridad'], msg: 'Elegí una prioridad.' })
    if (errores.length) {
      alValidar(errores)
      return
    }

    const ajustes: Ajustes = {}
    const esquinasSugeridas = ubicacion.esquinas.map((dato) => valorDato(dato) ?? '').filter((esquina) => esquina.trim())
    if (calle !== calleSugerida || altura !== alturaSugerida ||
      esquinas.length !== esquinasSugeridas.length ||
      esquinas.some((esquina, indice) => esquina !== esquinasSugeridas[indice])) {
      ajustes.ubicacion = { calle, altura, esquinas }
    }
    if (categoria && (categoria !== categoriaSugerida || subtipo !== subtipoSugerido)) {
      ajustes.tipo_hecho = { categoria, subtipo }
    }
    if (prioridad && prioridad !== prioridadSugerida) ajustes.prioridad = prioridad
    alDerivar(ajustes)
  }

  return (
    <form className="panel" onSubmit={enviar} noValidate>
      <fieldset disabled={bloqueado}>
        <legend>Sugerencia</legend>
        <AvisosSugerencia avisos={sugerencia.avisos} />
        <div className="direccion">
          <CampoSugerido nombre="calle" etiqueta="Calle" dato={ubicacion.calle}>
            {(control) => <input {...control} defaultValue={calleSugerida} required />}
          </CampoSugerido>
          <CampoSugerido nombre="altura" etiqueta="Altura" dato={ubicacion.altura} opcional>
            {(control) => <input {...control} inputMode="numeric" defaultValue={alturaSugerida ?? ''} />}
          </CampoSugerido>
        </div>
        <div className="esquinas">
          <CampoSugerido nombre="primera_esquina" etiqueta="Primera esquina" dato={primeraEsquina} opcional>
            {(control) => <input {...control} defaultValue={valorDato(primeraEsquina) ?? ''} />}
          </CampoSugerido>
          <CampoSugerido nombre="segunda_esquina" etiqueta="Segunda esquina" dato={segundaEsquina} opcional>
            {(control) => <input {...control} defaultValue={valorDato(segundaEsquina) ?? ''} />}
          </CampoSugerido>
        </div>
        <div className="hecho">
          <CampoSugerido nombre="tipo_hecho" etiqueta="Tipo de hecho" dato={sugerencia.tipo_hecho}>
            {(control) => (
              <select {...control} value={categoria} onChange={(evento) => {
                setCategoria(evento.target.value as TipoHecho | '')
                setSubtipo(null)
              }}>
                {categoriaSugerida === null && <option value="">Elegir…</option>}
                {Object.entries(nombresTiposHecho).map(([opcion, nombre]) => (
                  <option key={opcion} value={opcion}>{nombre}</option>
                ))}
              </select>
            )}
          </CampoSugerido>
          <CampoSugerido nombre="subtipo" etiqueta="Subtipo" dato={sugerencia.subtipo} opcional>
            {(control) => (
              <select {...control} value={subtipo ?? ''} onChange={(evento) => setSubtipo(evento.target.value || null)}
                aria-invalid={Boolean(erroresSubtipo)}
                aria-describedby={[control['aria-describedby'], erroresSubtipo, subtipo ? '' : 'ayuda-subtipo'].filter(Boolean).join(' ')}>
                <option value="">Sin subtipo</option>
                {protocolos.map(({ id, nombre }) => <option key={id} value={id}>{nombre}</option>)}
              </select>
            )}
          </CampoSugerido>
          <CampoSugerido nombre="prioridad" etiqueta="Prioridad" dato={sugerencia.prioridad}>
            {(control) => (
              <>
                <select {...control} value={prioridadElegida} required
                  onChange={(evento) => setPrioridadElegida(evento.target.value as Prioridad | '')}
                  aria-describedby={nivelElegido ? `${control['aria-describedby']} prioridad-definicion` : control['aria-describedby']}>
                  {prioridadSugerida === null && <option value="">Elegir…</option>}
                  {niveles.map(({ id, nombre }) => <option key={id} value={id}>{id} · {nombre}</option>)}
                </select>
                {nivelElegido && <small id="prioridad-definicion" className="definicion-prioridad">{nivelElegido.definicion}</small>}
              </>
            )}
          </CampoSugerido>
        </div>
      </fieldset>
      <CriterioPrioridad {...catalogo.criterio} />
      {subtipo ? <DetallesSugerencia checklist={checklist} instrucciones={instrucciones} /> : (
        <p className="detalles-sugerencia" id="ayuda-subtipo">
          Elegí un subtipo para ver las preguntas del protocolo y las instrucciones de pre-arribo.
        </p>
      )}
      <div className="acciones">
        <button type="submit" disabled={bloqueado}>
          {ocupado ? 'Derivando…' : 'Derivar Carta de Llamada'}
        </button>
        <button type="button" className="secundario" disabled={bloqueado} onClick={alEmpezar}>
          Nueva llamada
        </button>
      </div>
    </form>
  )
}
