import { valorDato } from './api'
import type { Catalogo, MarcaChecklist, Prioridad, Sugerencia, TipoHecho } from './api'

export type CamposSugerencia = {
  calle: string
  altura: string
  esquinaUno: string
  esquinaDos: string
  categoria: TipoHecho | ''
  subtipo: string | null
  prioridad: Prioridad | ''
}

export type BorradorSugerencia = {
  sugerencia: Sugerencia
  catalogo: Catalogo | null
  campos: CamposSugerencia
  editados: ReadonlySet<keyof CamposSugerencia>
  marcas: ReadonlyMap<string, MarcaChecklist>
  dictadosQuitados: ReadonlySet<string>
  direccionAlternativa?: string
}

const camposUbicacion = ['calle', 'altura', 'esquinaUno', 'esquinaDos'] as const

function subtipoDe(categoria: CamposSugerencia['categoria'], subtipo: string | null, catalogo: Catalogo | null) {
  return !catalogo || catalogo.protocolos.some(
    (protocolo) => protocolo.id === subtipo && protocolo.categoria === categoria,
  ) ? subtipo : null
}

function camposDe(sugerencia: Sugerencia, catalogo: Catalogo | null): CamposSugerencia {
  const { calle, altura, esquinas } = sugerencia.ubicacion
  const [primera, segunda] = esquinas
  const categoria = valorDato(sugerencia.tipo_hecho) ?? ''
  return {
    calle: valorDato(calle) ?? '',
    altura: valorDato(altura)?.toString() ?? '',
    esquinaUno: primera ? valorDato(primera) ?? '' : '',
    esquinaDos: segunda ? valorDato(segunda) ?? '' : '',
    categoria,
    subtipo: subtipoDe(categoria, valorDato(sugerencia.subtipo), catalogo),
    prioridad: valorDato(sugerencia.prioridad) ?? '',
  }
}

export function iniciarBorrador(sugerencia: Sugerencia, catalogo: Catalogo | null): BorradorSugerencia {
  return {
    sugerencia, catalogo, campos: camposDe(sugerencia, catalogo), editados: new Set(), marcas: new Map(),
    dictadosQuitados: new Set(),
  }
}

export function leerAltura(altura: string) {
  const texto = altura.trim()
  const numero = texto ? Number(texto) : null
  const invalida = numero !== null && (!/^\d+$/.test(texto) || numero < 1 || numero > 99999)
  return { numero, invalida }
}

export function actualizarBorrador(borrador: BorradorSugerencia, sugerencia: Sugerencia, catalogo: Catalogo | null): BorradorSugerencia {
  const { campos, editados, marcas } = borrador
  const anterior = camposDe(borrador.sugerencia, borrador.catalogo)
  const nueva = camposDe(sugerencia, catalogo)
  const conservarUbicacion = camposUbicacion.some((campo) => editados.has(campo))
  const cambioDireccion = anterior.calle !== nueva.calle || anterior.altura !== nueva.altura

  function conservar<Campo extends keyof CamposSugerencia>(campo: Campo) {
    return editados.has(campo) ? campos[campo] : nueva[campo]
  }

  // Las preguntas marcadas son de un protocolo: mientras quede alguna, el tipo no cambia.
  const protocoloFijado = marcas.size > 0
  const categoria = protocoloFijado ? campos.categoria : conservar('categoria')
  const subtipo = subtipoDe(categoria, protocoloFijado ? campos.subtipo : conservar('subtipo'), catalogo)
  const ubicacion = conservarUbicacion ? campos : nueva
  let direccionAlternativa = borrador.direccionAlternativa
  if (conservarUbicacion && cambioDireccion) {
    direccionAlternativa = nueva.calle ? [nueva.calle, nueva.altura].filter(Boolean).join(' ') : undefined
  }
  return {
    sugerencia,
    catalogo,
    editados,
    campos: {
      calle: ubicacion.calle,
      altura: ubicacion.altura,
      esquinaUno: ubicacion.esquinaUno,
      esquinaDos: ubicacion.esquinaDos,
      categoria,
      subtipo,
      prioridad: conservar('prioridad'),
    },
    marcas: subtipo === campos.subtipo ? marcas : new Map(),
    // Se conserva aunque el dato no esté en esta sugerencia: si vuelve, vuelve destildado.
    dictadosQuitados: borrador.dictadosQuitados,
    direccionAlternativa,
  }
}
