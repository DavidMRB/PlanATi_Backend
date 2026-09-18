# Analisis de requerimientos de PlanATi

## RF-04

**REQUERIMIENTO:** La plataforma debera permitir buscar establecimientos por nombre o categoria.

**PROBLEMA QUE RESUELVE:** Evita que el usuario tenga que revisar todos los establecimientos uno por uno para encontrar un lugar de su interes.

**DATOS DE ENTRADA:** Texto de busqueda ingresado por el usuario y opcion de buscar por nombre o por categoria.

**PROCESO:** Comparar el texto ingresado con el nombre o la categoria de cada establecimiento guardado en la lista.

**RESULTADO:** Mostrar los establecimientos que coincidan con el texto buscado o informar que no se encontro ninguno.

**CONDICIONES NECESARIAS:** Debe existir una lista de establecimientos y el usuario debe ingresar un texto de busqueda. La comparacion no diferencia entre mayusculas y minusculas.

**INFORMACION QUE DEBE ALMACENARSE:** Nombre y categoria de cada establecimiento.

## RF-06

**REQUERIMIENTO:** La plataforma debera permitir consultar la informacion detallada de un establecimiento.

**PROBLEMA QUE RESUELVE:** Permite que el usuario conozca mejor un establecimiento antes de decidir si desea visitarlo.

**DATOS DE ENTRADA:** Nombre del establecimiento que el usuario desea consultar.

**PROCESO:** Buscar en la lista el establecimiento cuyo nombre coincida con el nombre ingresado.

**RESULTADO:** Mostrar el nombre, categoria, ubicacion, descripcion, horario, puntuacion y reseñas del establecimiento encontrado.

**CONDICIONES NECESARIAS:** Debe existir una lista de establecimientos y el establecimiento consultado debe estar registrado.

**INFORMACION QUE DEBE ALMACENARSE:** Nombre, categoria, ubicacion, descripcion, horario, puntuacion y reseñas de cada establecimiento.

## RF-07

**REQUERIMIENTO:** La plataforma debera permitir a los usuarios publicar reseñas y asignar una puntuacion de 1 a 5.

**PROBLEMA QUE RESUELVE:** Permite conocer la opinion de los usuarios sobre los establecimientos y expresar una valoracion.

**DATOS DE ENTRADA:** Nombre del establecimiento, texto de la reseña y puntuacion entre 1 y 5.

**PROCESO:** Verificar que el establecimiento exista y que la puntuacion este dentro del rango permitido. Luego, guardar la reseña y la puntuacion en la lista correspondiente.

**RESULTADO:** Mostrar un mensaje confirmando que la reseña fue publicada.

**CONDICIONES NECESARIAS:** El establecimiento debe estar registrado, la reseña no debe estar vacia y la puntuacion debe ser un numero entero entre 1 y 5.

**INFORMACION QUE DEBE ALMACENARSE:** Nombre del establecimiento relacionado, texto de la reseña y puntuacion asignada.

## Relacion entre los requerimientos

Los tres requerimientos forman un flujo sencillo dentro del programa. Primero, mediante **RF-04**, el usuario busca un establecimiento por nombre o categoria. Despues, mediante **RF-06**, puede consultar la informacion detallada del establecimiento encontrado. Finalmente, mediante **RF-07**, puede publicar una reseña y asignar una puntuacion de 1 a 5 para ese establecimiento.
