import { idDictado, valorDato } from './api'
import type { Ajustes, Aviso, Catalogo, DireccionAlternativa, MarcaChecklist, Prioridad, Sugerencia, TipoHecho } from './api'

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

// Con los ajustes de una carta ya derivada, el formulario vuelve a quedar como lo dejó el operador
// al mandarla: lo que cambió es suyo y lo demás sigue a la sugerencia vigente.
export function iniciarBorrador(sugerencia: Sugerencia, catalogo: Catalogo | null, ajustes: Ajustes | null = null): BorradorSugerencia {
  const borrador: BorradorSugerencia = {
    sugerencia, catalogo, campos: camposDe(sugerencia, catalogo), editados: new Set(), marcas: new Map(),
    dictadosQuitados: new Set(), avisosAtendidos: new Set(),
  }
  if (!ajustes) return borrador

  const { ubicacion, tipo_hecho: tipo, prioridad, checklist, dictados_quitados: quitados } = ajustes
  const campos = { ...borrador.campos }
  const editados = new Set<keyof CamposSugerencia>()
  if (ubicacion) {
    const [esquinaUno = '', esquinaDos = ''] = ubicacion.esquinas
    Object.assign(campos, { calle: ubicacion.calle, altura: ubicacion.altura?.toString() ?? '', esquinaUno, esquinaDos })
    camposUbicacion.forEach((campo) => editados.add(campo))
  }
  if (tipo) {
    Object.assign(campos, { categoria: tipo.categoria, subtipo: subtipoDe(tipo.categoria, tipo.subtipo, catalogo) })
    editados.add('categoria').add('subtipo')
  }
  if (prioridad) {
    campos.prioridad = prioridad
    editados.add('prioridad')
  }
  return {
    ...borrador,
    campos,
    editados,
    marcas: new Map((checklist ?? []).map(({ id, respondida, cita }) => [id, { id, respondida, cita: cita ?? null }])),
    dictadosQuitados: new Set((quitados ?? []).map(idDictado)),
    avisosAtendidos: ubicacion ? avisosSobreLaDireccion(sugerencia) : new Set(),
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

function esquinasDe({ esquinaUno, esquinaDos }: CamposSugerencia) {
  return [esquinaUno, esquinaDos].filter((esquina) => esquina.trim())
}

// Si la ubicación del formulario no es la sugerida. Entonces viaja entera como ajuste, y los avisos
// sobre la dirección sugerida que el operador ya tuvo a la vista dejan de mostrarse.
export function ubicacionCambiada({ sugerencia, campos }: BorradorSugerencia) {
  const { calle, altura, esquinas } = sugerencia.ubicacion
  const sugeridas = esquinas.map((dato) => valorDato(dato) ?? '').filter((esquina) => esquina.trim())
  const escritas = esquinasDe(campos)
  return campos.calle !== (valorDato(calle) ?? '') || leerAltura(campos.altura).numero !== valorDato(altura) ||
    escritas.length !== sugeridas.length || escritas.some((esquina, indice) => esquina !== sugeridas[indice])
}

// Las preguntas que se ven: las del subtipo elegido, según el catálogo; sin catálogo, las sugeridas.
function preguntasVisibles({ sugerencia, catalogo, campos }: BorradorSugerencia) {
  if (!catalogo) return sugerencia.checklist.map(({ id }) => id)
  const protocolo = catalogo.protocolos.find(({ id, categoria }) => id === campos.subtipo && categoria === campos.categoria)
  return protocolo?.preguntas.map(({ id }) => id) ?? []
}

// Lo que viaja al derivar o al actualizar la carta: todo lo que difiere de la sugerencia vigente.
export function ajustesDe(borrador: BorradorSugerencia): Ajustes {
  const { sugerencia, campos, marcas, dictadosQuitados } = borrador
  const { calle, altura, categoria, subtipo, prioridad } = campos
  const ajustes: Ajustes = {}
  if (ubicacionCambiada(borrador)) {
    ajustes.ubicacion = { calle, altura: leerAltura(altura).numero, esquinas: esquinasDe(campos) }
  }
  if (categoria && (categoria !== valorDato(sugerencia.tipo_hecho) || subtipo !== valorDato(sugerencia.subtipo))) {
    ajustes.tipo_hecho = { categoria, subtipo }
  }
  if (prioridad && prioridad !== valorDato(sugerencia.prioridad)) ajustes.prioridad = prioridad
  const cambios = preguntasVisibles(borrador).flatMap((id) => marcas.get(id) ?? [])
  if (cambios.length) ajustes.checklist = cambios
  const quitados = sugerencia.datos_dictados.filter((dato) => dictadosQuitados.has(idDictado(dato)))
    .map(({ tipo, valor }) => ({ tipo, valor }))
  if (quitados.length) ajustes.dictados_quitados = quitados
  return ajustes
}

// Lo que los ajustes cambian de verdad sobre esta sugerencia. Un campo igual al sugerido no cambia
// nada (los guardados pueden tenerlo si un turno trajo después lo mismo que había puesto el
// operador), y el servicio los devuelve sin los espacios de los bordes y sin lo que no se mandó.
function comparable(ajustes: Ajustes, sugerencia: Sugerencia) {
  const { ubicacion, tipo_hecho: tipo, prioridad, checklist, dictados_quitados: quitados } = ajustes
  const sugerida = sugerencia.ubicacion
  const direccion = ubicacion && [ubicacion.calle.trim(), ubicacion.altura ?? null, ubicacion.esquinas.map((esquina) => esquina.trim())]
  const direccionSugerida = [valorDato(sugerida.calle) ?? '', valorDato(sugerida.altura), sugerida.esquinas.flatMap((dato) => valorDato(dato) ?? [])]
  const hecho = tipo && [tipo.categoria, tipo.subtipo?.trim() ?? null]
  const hechoSugerido = [valorDato(sugerencia.tipo_hecho), valorDato(sugerencia.subtipo)]
  const dictados = new Set(sugerencia.datos_dictados.map(idDictado))
  const distinto = (valor: unknown, sugerido: unknown) => JSON.stringify(valor) !== JSON.stringify(sugerido)
  return JSON.stringify([
    direccion && distinto(direccion, direccionSugerida) ? direccion : null,
    hecho && distinto(hecho, hechoSugerido) ? hecho : null,
    prioridad && prioridad !== valorDato(sugerencia.prioridad) ? prioridad : null,
    (checklist ?? []).map(({ id, respondida, cita }) => JSON.stringify([id.trim(), respondida, cita ? [cita.turno, cita.texto.trim()] : null])).sort(),
    (quitados ?? []).map(({ tipo: clase, valor }) => ({ tipo: clase, valor: valor.trim() }))
      .filter((dato) => dictados.has(idDictado(dato)))
      .map(({ tipo: clase, valor }) => JSON.stringify([clase, valor])).sort(),
  ])
}

export function mismosAjustes(unos: Ajustes, otros: Ajustes, sugerencia: Sugerencia) {
  return comparable(unos, sugerencia) === comparable(otros, sugerencia)
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
