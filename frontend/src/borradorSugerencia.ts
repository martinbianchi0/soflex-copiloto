import { valorDato } from './api'
import type { Aviso, Catalogo, DireccionAlternativa, MarcaChecklist, Prioridad, Sugerencia, TipoHecho } from './api'

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
  // Los avisos sobre la dirección que estaban a la vista la última vez que el operador la cambió.
  avisosAtendidos: ReadonlySet<string>
  direccionAlternativa?: string
}

const camposUbicacion = ['calle', 'altura', 'esquinaUno', 'esquinaDos'] as const
const avisosDeDireccion: Aviso['codigo'][] = ['sin_calle', 'falta_altura', 'calle_ambigua', 'direccion_no_cierra', 'cruce_sin_confirmar']

function avisosSobreLaDireccion(sugerencia: Sugerencia) {
  return new Set(sugerencia.avisos.filter(({ codigo }) => avisosDeDireccion.includes(codigo)).map(({ mensaje }) => mensaje))
}

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
    dictadosQuitados: new Set(), avisosAtendidos: new Set(),
  }
}

export function editarCampo<Campo extends keyof CamposSugerencia>(
  borrador: BorradorSugerencia, campo: Campo, valor: CamposSugerencia[Campo],
): BorradorSugerencia {
  const esDeUbicacion = camposUbicacion.some((nombre) => nombre === campo)
  return {
    ...borrador,
    campos: { ...borrador.campos, [campo]: valor },
    editados: new Set([...borrador.editados, campo]),
    avisosAtendidos: esDeUbicacion ? avisosSobreLaDireccion(borrador.sugerencia) : borrador.avisosAtendidos,
  }
}

// Un aviso sobre la dirección habla de la sugerida. Si el operador la cambió con el aviso a la
// vista, ya no describe lo que va a salir y se quita; vuelve si restaura la sugerida. Uno que
// llega después de ese cambio, al sumar un turno, se muestra: es información nueva.
export function avisosVigentes(borrador: BorradorSugerencia, ubicacionCambiada: boolean): Aviso[] {
  const { avisos } = borrador.sugerencia
  return ubicacionCambiada ? avisos.filter(({ mensaje }) => !borrador.avisosAtendidos.has(mensaje)) : avisos
}

export function leerAltura(altura: string) {
  const texto = altura.trim()
  const numero = texto ? Number(texto) : null
  const invalida = numero !== null && (!/^\d+$/.test(texto) || numero < 1 || numero > 99999)
  return { numero, invalida }
}

export function usarDireccion(borrador: BorradorSugerencia, direccion: DireccionAlternativa): BorradorSugerencia {
  const [esquinaUno = '', esquinaDos = ''] = direccion.esquinas
  return {
    ...borrador,
    campos: {
      ...borrador.campos, calle: direccion.calle, altura: direccion.altura?.toString() ?? '',
      esquinaUno, esquinaDos,
    },
    editados: new Set([...borrador.editados, ...camposUbicacion]),
    avisosAtendidos: avisosSobreLaDireccion(borrador.sugerencia),
  }
}

export function actualizarBorrador(borrador: BorradorSugerencia, sugerencia: Sugerencia, catalogo: Catalogo | null): BorradorSugerencia {
  const { campos, editados, marcas } = borrador
  const anterior = camposDe(borrador.sugerencia, borrador.catalogo)
  const nueva = camposDe(sugerencia, catalogo)
  const conservarUbicacion = camposUbicacion.some((campo) => editados.has(campo))
  const avisosQueSiguen = avisosSobreLaDireccion(sugerencia)
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
    avisosAtendidos: new Set([...borrador.avisosAtendidos].filter((mensaje) => avisosQueSiguen.has(mensaje))),
    direccionAlternativa,
  }
}
