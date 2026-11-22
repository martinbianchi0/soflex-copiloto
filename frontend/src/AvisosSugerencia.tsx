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

export default function AvisosSugerencia({ avisos }: { avisos: Aviso[] }) {
  return (
    <>
      <GrupoAvisos titulo="Para confirmar con el llamante"
        avisos={avisos.filter(({ codigo }) => codigo !== 'dato_descartado')} />
      <GrupoAvisos titulo="Datos descartados por el sistema"
        avisos={avisos.filter(({ codigo }) => codigo === 'dato_descartado')} />
    </>
  )
}
