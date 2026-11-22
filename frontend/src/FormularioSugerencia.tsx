import type { FormEvent, ReactNode } from 'react'
import { nombresTiposHecho, prioridades, textoOrigen, valorDato } from './api'
import type { Ajustes, Dato, DetalleValidacion, Prioridad, Sugerencia, TipoHecho } from './api'
import DetallesSugerencia from './DetallesSugerencia'

type Propiedades = {
  sugerencia: Sugerencia
  bloqueado: boolean
  ocupado: boolean
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
      {dibujarControl({ id: nombre, name: nombre, 'aria-describedby': descripcion })}
      {dato.origen === 'dicho' && <small id={cita} className="cita">«{dato.cita.texto}»</small>}
    </div>
  )
}

export default function FormularioSugerencia({
  sugerencia, bloqueado, ocupado, alDerivar, alValidar, alEmpezar,
}: Propiedades) {
  const ubicacion = sugerencia.ubicacion
  const [primeraEsquina = faltante, segundaEsquina = faltante] = ubicacion.esquinas
  const calleSugerida = valorDato(ubicacion.calle) ?? ''
  const alturaSugerida = valorDato(ubicacion.altura)
  const tipoSugerido = valorDato(sugerencia.tipo_hecho)
  const prioridadSugerida = valorDato(sugerencia.prioridad)

  function enviar(evento: FormEvent<HTMLFormElement>) {
    evento.preventDefault()
    if (bloqueado) return

    const datos = new FormData(evento.currentTarget)
    const valor = (campo: string) => String(datos.get(campo) ?? '')
    const calle = valor('calle')
    const textoAltura = valor('altura').trim()
    const altura = textoAltura ? Number(textoAltura) : null
    const esquinas = [valor('primera_esquina'), valor('segunda_esquina')].filter((esquina) => esquina.trim())
    const tipoHecho = valor('tipo_hecho') as TipoHecho | ''
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
    if (tipoHecho && tipoHecho !== tipoSugerido) ajustes.tipo_hecho = tipoHecho
    if (prioridad && prioridad !== prioridadSugerida) ajustes.prioridad = prioridad
    alDerivar(ajustes)
  }

  return (
    <form className="panel" onSubmit={enviar} noValidate>
      <fieldset disabled={bloqueado}>
        <legend>Sugerencia</legend>
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
              <select {...control} defaultValue={tipoSugerido ?? ''}>
                {tipoSugerido === null && <option value="">Elegir…</option>}
                {Object.entries(nombresTiposHecho).map(([opcion, nombre]) => (
                  <option key={opcion} value={opcion}>{nombre}</option>
                ))}
              </select>
            )}
          </CampoSugerido>
          <CampoSugerido nombre="prioridad" etiqueta="Prioridad" dato={sugerencia.prioridad}>
            {(control) => (
              <select {...control} defaultValue={prioridadSugerida ?? ''} required>
                {prioridadSugerida === null && <option value="">Elegir…</option>}
                {prioridades.map((opcion) => <option key={opcion}>{opcion}</option>)}
              </select>
            )}
          </CampoSugerido>
        </div>
      </fieldset>
      <DetallesSugerencia checklist={sugerencia.checklist} instrucciones={sugerencia.instrucciones} />
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
