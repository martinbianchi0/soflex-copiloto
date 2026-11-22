import { useEffect } from 'react'
import type { Aviso, DireccionAlternativa } from './api'

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

export default function AvisosSugerencia({ avisos, alternativa, alUsarDireccion, alAnunciarDireccion }: {
  avisos: Aviso[]
  alternativa: DireccionAlternativa | null
  alUsarDireccion: (direccion: DireccionAlternativa) => void
  alAnunciarDireccion: (mensaje: string) => void
}) {
  const direccion = alternativa ? [alternativa.calle, alternativa.altura].join(' ').trim() : ''
  // Con altura, dos calles son las que limitan la cuadra; una sola, la esquina.
  const entre = alternativa?.altura != null && alternativa.esquinas.length === 2
  const esquinas = alternativa?.esquinas.length ? `, ${entre ? 'entre' : 'esquina'} ${alternativa.esquinas.join(' y ')}` : ''
  const confirmar = 'Confirmala con el llamante antes de usarla.'
  useEffect(() => {
    alAnunciarDireccion(direccion ? `El modelo leyó otra dirección: ${direccion}${esquinas}. ${confirmar}` : '')
    return () => alAnunciarDireccion('')
  }, [alAnunciarDireccion, direccion, esquinas, confirmar])

  return (
    <>
      <GrupoAvisos titulo="Sin sugerencia del modelo"
        avisos={avisos.filter(({ codigo }) => codigo === 'modelo_no_disponible')} />
      <GrupoAvisos titulo="Al sumar lo que se dijo después"
        avisos={avisos.filter(({ codigo }) => codigo === 'prioridad_cambiada' || codigo === 'ficha_sin_actualizar')} />
      <GrupoAvisos titulo="Para confirmar con el llamante"
        avisos={avisos.filter(({ codigo }) => !conGrupoPropio.includes(codigo))} />
      {alternativa && (
        <div className="avisos-sugerencia">
          <div>El modelo leyó otra dirección: <strong>{direccion}</strong>{esquinas}. {confirmar}</div>
          <button type="button" className="secundario" onClick={() => alUsarDireccion(alternativa)}
            onKeyDown={(evento) => { if (evento.key === 'Enter') evento.stopPropagation() }}>
            Usar esta dirección
          </button>
        </div>
      )}
      <GrupoAvisos titulo="Datos dictados"
        avisos={avisos.filter(({ codigo }) => codigo === 'dictado_incompleto')} />
      <GrupoAvisos titulo="Datos descartados por el sistema"
        avisos={avisos.filter(({ codigo }) => codigo === 'dato_descartado')} />
    </>
  )
}
