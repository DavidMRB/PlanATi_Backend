# Pruebas del prototipo PlanATi

| Requerimiento | Datos utilizados | Resultado esperado | Resultado obtenido |
|---------------|------------------|--------------------|--------------------|
| RF-04 | Opcion `2`, categoria `Cafe` | Mostrar Cafe Caobos y Bocaditos Cafe. | Se mostraron Cafe Caobos y Bocaditos Cafe. |
| RF-06 | Nombre exacto `Sky Bar Ventura` | Mostrar nombre, categoria, ubicacion, descripcion, horario, puntuacion y reseñas. | Se mostro la informacion detallada de Sky Bar Ventura y se indico que todavia no tenia reseñas. |
| RF-07 | Establecimiento `Cafe Caobos`, reseña `Buen cafe y ambiente tranquilo`, puntuacion `5` | Guardar la reseña y mostrar un mensaje de confirmacion. | La reseña se guardo en la lista de Cafe Caobos y se mostro el mensaje `Reseña publicada correctamente.` |

## Correcciones realizadas

Fue necesario validar que la puntuacion fuera un numero entero entre 1 y 5, controlar los establecimientos inexistentes y rechazar reseñas vacias. Despues de estas validaciones, las pruebas se realizaron correctamente.
