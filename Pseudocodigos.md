# Algoritmos y pseudocodigos de PlanATi

## RF-04: Buscar establecimiento por nombre o categoria

### Algoritmo

1. Mostrar al usuario las opciones de busqueda: nombre o categoria.
2. Leer la opcion seleccionada.
3. Solicitar el texto que desea buscar.
4. Recorrer la lista de establecimientos.
5. Comparar el texto con el nombre o la categoria, sin diferenciar mayusculas y minusculas.
6. Mostrar los establecimientos que coincidan.
7. Si no hay coincidencias, mostrar un mensaje indicando que no se encontraron establecimientos.

### Pseudocodigo

```text
INICIO
    MOSTRAR "Buscar por nombre o categoria"
    LEER tipo_busqueda
    LEER texto_busqueda
    encontrados <- lista vacia

    PARA cada establecimiento EN establecimientos HACER
        SI tipo_busqueda ES "nombre" Y texto_busqueda aparece en establecimiento.nombre ENTONCES
            AGREGAR establecimiento A encontrados
        FIN SI

        SI tipo_busqueda ES "categoria" Y texto_busqueda aparece en establecimiento.categoria ENTONCES
            AGREGAR establecimiento A encontrados
        FIN SI
    FIN PARA

    SI encontrados esta vacia ENTONCES
        MOSTRAR "No se encontraron establecimientos"
    SI NO
        MOSTRAR encontrados
    FIN SI
FIN
```

## RF-06: Consultar informacion detallada

### Algoritmo

1. Solicitar el nombre del establecimiento.
2. Recorrer la lista de establecimientos.
3. Comparar el nombre ingresado con el nombre de cada establecimiento.
4. Si se encuentra, mostrar toda su informacion y sus reseñas.
5. Si no se encuentra, mostrar un mensaje indicando que no existe.

### Pseudocodigo

```text
INICIO
    LEER nombre_buscado
    establecimiento_encontrado <- FALSO

    PARA cada establecimiento EN establecimientos HACER
        SI establecimiento.nombre coincide con nombre_buscado ENTONCES
            MOSTRAR nombre, categoria, ubicacion, descripcion y horario
            MOSTRAR puntuacion y reseñas
            establecimiento_encontrado <- VERDADERO
        FIN SI
    FIN PARA

    SI establecimiento_encontrado ES FALSO ENTONCES
        MOSTRAR "Establecimiento no encontrado"
    FIN SI
FIN
```

## RF-07: Publicar reseña y asignar puntuacion

### Algoritmo

1. Solicitar el nombre del establecimiento.
2. Buscar el establecimiento en la lista.
3. Si no existe, mostrar un mensaje y terminar la operacion.
4. Solicitar el texto de la reseña.
5. Solicitar una puntuacion.
6. Verificar que la puntuacion sea un numero entre 1 y 5 y que la reseña no este vacia.
7. Guardar la reseña y la puntuacion.
8. Mostrar un mensaje de confirmacion.

### Pseudocodigo

```text
INICIO
    LEER nombre_buscado
    buscar establecimiento por nombre

    SI no se encuentra el establecimiento ENTONCES
        MOSTRAR "Establecimiento no encontrado"
    SI NO
        LEER texto_reseña
        LEER puntuacion

        SI texto_reseña esta vacio O puntuacion < 1 O puntuacion > 5 ENTONCES
            MOSTRAR "Datos invalidos"
        SI NO
            GUARDAR texto_reseña y puntuacion en las reseñas
            MOSTRAR "Reseña publicada correctamente"
        FIN SI
    FIN SI
FIN
```
