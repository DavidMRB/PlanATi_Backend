def encontrar_establecimiento(establecimientos, nombre_buscado):
    for establecimiento in establecimientos:
        if establecimiento["nombre"].lower() == nombre_buscado.lower():
            return establecimiento
    return None


def publicar_resena(establecimientos):
    nombre_buscado = input("Ingrese el nombre del establecimiento: ").strip()
    establecimiento = encontrar_establecimiento(establecimientos, nombre_buscado)

    if establecimiento is None:
        print("Establecimiento no encontrado.")
        return

    texto = input("Escriba su reseña: ").strip()
    if texto == "":
        print("La reseña no puede estar vacia.")
        return

    puntuacion_texto = input("Asigne una puntuacion de 1 a 5: ").strip()
    try:
        puntuacion = int(puntuacion_texto)
    except ValueError:
        print("La puntuacion debe ser un numero entero entre 1 y 5.")
        return

    if puntuacion < 1 or puntuacion > 5:
        print("La puntuacion debe estar entre 1 y 5.")
        return

    nueva_resena = {"texto": texto, "puntuacion": puntuacion}
    establecimiento["reseñas"].append(nueva_resena)
    print("Reseña publicada correctamente.")
