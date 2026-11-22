import type { FormEvent } from 'react'
import { prioridades } from './api'
import type { Ajustes, DetalleValidacion, Prioridad, Sugerencia } from './api'

type Propiedades = {
  sugerencia: Sugerencia
  bloqueado: boolean
  ocupado: boolean
  alDerivar: (ajustes: Ajustes) => void
  alValidar: (errores: DetalleValidacion[]) => void
  alEmpezar: () => void
}

export default function FormularioSugerencia({
  sugerencia, bloqueado, ocupado, alDerivar, alValidar, alEmpezar,
}: Propiedades) {
  const ubicacion = sugerencia.ubicacion

  function enviar(evento: FormEvent<HTMLFormElement>) {
    evento.preventDefault()
    if (bloqueado) return

    const datos = new FormData(evento.currentTarget)
    const valor = (campo: string) => String(datos.get(campo) ?? '')
    const calle = valor('calle')
    const textoAltura = valor('altura').trim()
    const altura = textoAltura ? Number(textoAltura) : null
    const esquinas = [valor('primera_esquina'), valor('segunda_esquina')].filter((esquina) => esquina.trim())
    const tipoHecho = valor('tipo_hecho')
    const prioridad = valor('prioridad') as Prioridad

    const errores: DetalleValidacion[] = []
    if (!calle.trim()) errores.push({ loc: ['Calle'], msg: 'Ingresá una calle.' })
    const nombres = [calle, ...esquinas].map((nombre) => nombre.trim().toLowerCase())
    if (new Set(nombres).size !== nombres.length) {
      errores.push({ loc: ['Esquinas'], msg: 'La calle y las esquinas tienen que ser distintas entre sí.' })
    }
    if (altura !== null && (!/^\d+$/.test(textoAltura) || altura < 1 || altura > 99999)) {
      errores.push({ loc: ['Altura'], msg: 'Ingresá un número entero entre 1 y 99999.' })
    }
    if (!tipoHecho.trim()) errores.push({ loc: ['Tipo de hecho'], msg: 'Ingresá el tipo de hecho.' })
    if (errores.length) {
      alValidar(errores)
      return
    }

    const ajustes: Ajustes = {}
    if (calle !== ubicacion.calle || altura !== ubicacion.altura ||
      esquinas.length !== ubicacion.esquinas.length ||
      esquinas.some((esquina, indice) => esquina !== ubicacion.esquinas[indice])) {
      ajustes.ubicacion = { calle, altura, esquinas }
    }
    if (tipoHecho !== sugerencia.tipo_hecho) ajustes.tipo_hecho = tipoHecho
    if (prioridad !== sugerencia.prioridad) ajustes.prioridad = prioridad
    alDerivar(ajustes)
  }

  return (
    <form className="panel" onSubmit={enviar} noValidate>
      <fieldset disabled={bloqueado}>
        <legend>Sugerencia</legend>
        <div className="direccion">
          <label>
            Calle
            <input name="calle" defaultValue={ubicacion.calle} required />
          </label>
          <label>
            Altura <span className="opcional">(opcional)</span>
            <input name="altura" inputMode="numeric" defaultValue={ubicacion.altura ?? ''} />
          </label>
        </div>
        <div className="esquinas">
          <label>
            Primera esquina <span className="opcional">(opcional)</span>
            <input name="primera_esquina" defaultValue={ubicacion.esquinas[0] ?? ''} />
          </label>
          <label>
            Segunda esquina <span className="opcional">(opcional)</span>
            <input name="segunda_esquina" defaultValue={ubicacion.esquinas[1] ?? ''} />
          </label>
        </div>
        <div className="hecho">
          <label>
            Tipo de hecho
            <input name="tipo_hecho" defaultValue={sugerencia.tipo_hecho} required />
          </label>
          <label>
            Prioridad
            <select name="prioridad" defaultValue={sugerencia.prioridad}>
              {prioridades.map((opcion) => <option key={opcion}>{opcion}</option>)}
            </select>
          </label>
        </div>
      </fieldset>
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
