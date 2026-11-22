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
  marcas: ReadonlyMap<string, MarcaChecklist>
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
  return { sugerencia, catalogo, campos: camposDe(sugerencia, catalogo), marcas: new Map() }
}

export function leerAltura(altura: string) {
  const texto = altura.trim()
  const numero = texto ? Number(texto) : null
  const invalida = numero !== null && (!/^\d+$/.test(texto) || numero < 1 || numero > 99999)
  return { numero, invalida }
}

export function actualizarBorrador(borrador: BorradorSugerencia, sugerencia: Sugerencia, catalogo: Catalogo | null): BorradorSugerencia {
  const { campos, marcas } = borrador
  const anterior = camposDe(borrador.sugerencia, borrador.catalogo)
  const nueva = camposDe(sugerencia, catalogo)

  function conservar<Campo extends keyof CamposSugerencia>(campo: Campo) {
    return campos[campo] === anterior[campo] ? nueva[campo] : campos[campo]
  }

  const categoria = conservar('categoria')
  const subtipo = subtipoDe(categoria, conservar('subtipo'), catalogo)
  const altura = leerAltura(campos.altura)
  return {
    sugerencia,
    catalogo,
    campos: {
      calle: conservar('calle'),
      altura: !altura.invalida && altura.numero === leerAltura(anterior.altura).numero ? nueva.altura : campos.altura,
      esquinaUno: conservar('esquinaUno'),
      esquinaDos: conservar('esquinaDos'),
      categoria,
      subtipo,
      prioridad: conservar('prioridad'),
    },
    marcas: subtipo === campos.subtipo ? marcas : new Map(),
  }
}
