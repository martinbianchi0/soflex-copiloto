// Respuestas reales del servicio en modo `mock`, para simular la API en los tests.
// Las escribe `backend/herramientas/capturar_respuestas.py`, y un test del backend comprueba que
// sigan siendo las que da el servicio. No se editan a mano.
import type { Catalogo, DetalleValidacion, Duplicados, Ejemplo, Historial, Llamada, Plano, Salud } from '../api'
import catalogo from './respuestas/catalogo.json'
import duplicadosConOtra from './respuestas/duplicados-con-otra.json'
import duplicadosSinOtra from './respuestas/duplicados-sin-otra.json'
import ejemplos from './respuestas/ejemplos.json'
import errorFaltaLoMinimo from './respuestas/error-falta-lo-minimo.json'
import errorLlamadaInexistente from './respuestas/error-llamada-inexistente.json'
import errorSinPlano from './respuestas/error-sin-plano.json'
import errorYaDerivada from './respuestas/error-ya-derivada.json'
import historialTerminada from './respuestas/historial-terminada.json'
import llamadaConAviso from './respuestas/llamada-con-aviso.json'
import llamadaDelDataset from './respuestas/llamada-del-dataset.json'
import llamadaDelDatasetActualizada from './respuestas/llamada-del-dataset-actualizada.json'
import llamadaDelDatasetConTurnoTrasDerivar from './respuestas/llamada-del-dataset-con-turno-tras-derivar.json'
import llamadaDelDatasetDerivada from './respuestas/llamada-del-dataset-derivada.json'
import llamadaDelDatasetTerminada from './respuestas/llamada-del-dataset-terminada.json'
import llamadaPorTurnos from './respuestas/llamada-por-turnos.json'
import llamadaPorTurnosCartaDesactualizada from './respuestas/llamada-por-turnos-carta-desactualizada.json'
import llamadaPorTurnosConAltura from './respuestas/llamada-por-turnos-con-altura.json'
import llamadaPorTurnosDerivada from './respuestas/llamada-por-turnos-derivada.json'
import llamadaRepetida from './respuestas/llamada-repetida.json'
import llamadaSinDatos from './respuestas/llamada-sin-datos.json'
import plano from './respuestas/plano.json'
import salud from './respuestas/salud.json'

type ErrorDeLaApi = { detail: string | DetalleValidacion[] }

// Un JSON importado pierde los literales ("dicho" pasa a ser `string`): por eso la conversión.
function como<Respuesta>(respuesta: unknown) {
  return respuesta as Respuesta
}

export const respuestas = {
  salud: como<Salud>(salud),
  catalogo: como<Catalogo>(catalogo),
  ejemplos: como<Ejemplo[]>(ejemplos),
  plano: como<Plano>(plano),
  llamadaDelDataset: como<Llamada>(llamadaDelDataset),
  llamadaDelDatasetDerivada: como<Llamada>(llamadaDelDatasetDerivada),
  llamadaDelDatasetConTurnoTrasDerivar: como<Llamada>(llamadaDelDatasetConTurnoTrasDerivar),
  llamadaDelDatasetActualizada: como<Llamada>(llamadaDelDatasetActualizada),
  llamadaDelDatasetTerminada: como<Llamada>(llamadaDelDatasetTerminada),
  llamadaRepetida: como<Llamada>(llamadaRepetida),
  llamadaConAviso: como<Llamada>(llamadaConAviso),
  llamadaSinDatos: como<Llamada>(llamadaSinDatos),
  llamadaPorTurnos: como<Llamada>(llamadaPorTurnos),
  llamadaPorTurnosConAltura: como<Llamada>(llamadaPorTurnosConAltura),
  llamadaPorTurnosDerivada: como<Llamada>(llamadaPorTurnosDerivada),
  llamadaPorTurnosCartaDesactualizada: como<Llamada>(llamadaPorTurnosCartaDesactualizada),
  duplicadosSinOtra: como<Duplicados>(duplicadosSinOtra),
  duplicadosConOtra: como<Duplicados>(duplicadosConOtra),
  historialTerminada: como<Historial>(historialTerminada),
  errorFaltaLoMinimo: como<ErrorDeLaApi>(errorFaltaLoMinimo),
  errorYaDerivada: como<ErrorDeLaApi>(errorYaDerivada),
  errorSinPlano: como<ErrorDeLaApi>(errorSinPlano),
  errorLlamadaInexistente: como<ErrorDeLaApi>(errorLlamadaInexistente),
}
