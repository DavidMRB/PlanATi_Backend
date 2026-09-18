def encontrar_establecimiento(establecimientos, nombre_buscado):
    for establecimiento in establecimientos:
        if establecimiento["nombre"].lower() == nombre_buscado.lower():
            return establecimiento
    return None


def obtener_puntuacion(establecimiento):
    reseñas = establecimiento["reseñas"]
    if len(reseñas) == 0:
        return "Sin puntuaciones"

    suma = 0
    for reseña in reseñas:
        suma = suma + reseña["puntuacion"]
    promedio = suma / len(reseñas)
    return str(round(promedio, 1)) + " / 5"


def consultar_establecimiento(establecimientos):
    nombre_buscado = input("Ingrese el nombre exacto del establecimiento: ").strip()
    establecimiento = encontrar_establecimiento(establecimientos, nombre_buscado)

    if establecimiento is None:
        print("Establecimiento no encontrado.")
        return

    print("\nNombre: " + establecimiento["nombre"])
    print("Categoria: " + establecimiento["categoria"])
    print("Ubicacion: " + establecimiento["ubicacion"])
    print("Descripcion: " + establecimiento["descripcion"])
    print("Horario: " + establecimiento["horario"])
    print("Puntuacion: " + obtener_puntuacion(establecimiento))

    if len(establecimiento["reseñas"]) == 0:
        print("Reseñas: Todavia no hay reseñas.")
    else:
        print("Reseñas:")
        for reseña in establecimiento["reseñas"]:
            print("- " + reseña["texto"] + " | Puntuacion: " + str(reseña["puntuacion"]) + " / 5")
