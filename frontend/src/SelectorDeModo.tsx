import { useId } from 'react'
import type { Proveedor, Salud } from './api'

const ayuda = 'El modo se elige antes de analizar. Una llamada abierta sigue con el suyo.'

type Props = {
  salud: Salud | null | undefined
  proveedor: Proveedor | undefined
  bloqueado: boolean
  alElegir: (proveedor: Proveedor) => void
}

export default function SelectorDeModo({ salud, proveedor, bloqueado, alElegir }: Props) {
  const idAyuda = useId()

  if (salud?.proveedores.length === 2) {
    return (
      <fieldset className="selector-de-modo" disabled={bloqueado} aria-describedby={idAyuda} title={ayuda}>
        <legend>Modo</legend>
        <span className="solo-lectores" id={idAyuda}>{ayuda}</span>
        <div className="opciones-modo">
          <label>
            <input type="radio" name="modo" value="mock" checked={proveedor === 'mock'} onChange={() => alElegir('mock')} />
            <span>mock (sólo reglas)</span>
          </label>
          <label>
            <input type="radio" name="modo" value="ollama" checked={proveedor === 'ollama'} onChange={() => alElegir('ollama')} />
            <span>ollama · {salud.modelo}</span>
          </label>
        </div>
      </fieldset>
    )
  }

  let texto = 'no disponible'
  if (salud === undefined) texto = 'consultando…'
  else if (salud) texto = salud.modelo ? `${salud.llm_provider} · ${salud.modelo}` : salud.llm_provider

  return <span className="modo" title="El modo se elige al levantar el servicio.">Modo: {texto}</span>
}
