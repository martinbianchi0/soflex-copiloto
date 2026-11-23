// Parte un texto en oraciones para mostrarlas de a una por renglón. No cambia ni una letra: unidas
// con un espacio dan el texto original.
export function oraciones(texto: string): string[] {
  return texto.split(/(?<=[.!?])\s+(?=[\p{Lu}¿¡])/u)
}
