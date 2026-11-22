import type { Aviso } from './api'

export function GrupoAvisos({ titulo, avisos }: { titulo: string; avisos: Aviso[] }) {
  if (avisos.length === 0) return null

  return (
    <section className="avisos-sugerencia">
      <h3>{titulo}</h3>
      <ul>{avisos.map(({ mensaje }, indice) => <li key={indice}>{mensaje}</li>)}</ul>
    </section>
  )
}

// Avisos sobre cómo se armó la sugerencia, no sobre algo que haya que preguntarle al llamante.
const sobreElAnalisis: Aviso['codigo'][] = ['dato_descartado', 'modelo_no_disponible', 'ficha_sin_actualizar', 'prioridad_cambiada']

export default function AvisosSugerencia({ avisos }: { avisos: Aviso[] }) {
  return (
    <>
      <GrupoAvisos titulo="El modelo no respondió"
        avisos={avisos.filter(({ codigo }) => codigo === 'modelo_no_disponible')} />
      <GrupoAvisos titulo="Al sumar lo que se dijo después"
        avisos={avisos.filter(({ codigo }) => codigo === 'prioridad_cambiada' || codigo === 'ficha_sin_actualizar')} />
      <GrupoAvisos titulo="Para confirmar con el llamante"
        avisos={avisos.filter(({ codigo }) => !sobreElAnalisis.includes(codigo))} />
      <GrupoAvisos titulo="Datos descartados por el sistema"
        avisos={avisos.filter(({ codigo }) => codigo === 'dato_descartado')} />
    </>
  )
}
