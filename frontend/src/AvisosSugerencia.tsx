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

const conGrupoPropio: Aviso['codigo'][] = ['dato_descartado', 'modelo_no_disponible', 'ficha_sin_actualizar', 'prioridad_cambiada', 'dictado_incompleto']

export default function AvisosSugerencia({ avisos }: { avisos: Aviso[] }) {
  return (
    <>
      <GrupoAvisos titulo="Sin sugerencia del modelo"
        avisos={avisos.filter(({ codigo }) => codigo === 'modelo_no_disponible')} />
      <GrupoAvisos titulo="Al sumar lo que se dijo después"
        avisos={avisos.filter(({ codigo }) => codigo === 'prioridad_cambiada' || codigo === 'ficha_sin_actualizar')} />
      <GrupoAvisos titulo="Para confirmar con el llamante"
        avisos={avisos.filter(({ codigo }) => !conGrupoPropio.includes(codigo))} />
      <GrupoAvisos titulo="Datos dictados"
        avisos={avisos.filter(({ codigo }) => codigo === 'dictado_incompleto')} />
      <GrupoAvisos titulo="Datos descartados por el sistema"
        avisos={avisos.filter(({ codigo }) => codigo === 'dato_descartado')} />
    </>
  )
}
