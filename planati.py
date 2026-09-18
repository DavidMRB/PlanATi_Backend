# Prototipo basico de PlanATi para consola

from buscar import buscar_establecimientos
from consultar import consultar_establecimiento
from resenas import publicar_resena

establecimientos = [
    {
        "nombre": "Cafe Caobos",
        "categoria": "Cafe",
        "ubicacion": "Barrio Caobos, Cucuta",
        "descripcion": "Cafe con bebidas calientes y un ambiente tranquilo.",
        "horario": "Lunes a sabado, 8:00 a.m. a 8:00 p.m.",
        "reseñas": []
    },
    {
        "nombre": "Sky Bar Ventura",
        "categoria": "Bar",
        "ubicacion": "Centro Comercial Ventura Plaza, Cucuta",
        "descripcion": "Bar con bebidas y ambiente para compartir.",
        "horario": "Martes a domingo, 4:00 p.m. a 12:00 a.m.",
        "reseñas": []
    },
    {
        "nombre": "Restaurante Londeros",
        "categoria": "Restaurante",
        "ubicacion": "Avenida Libertadores, Cucuta",
        "descripcion": "Restaurante de comida variada para compartir en familia.",
        "horario": "Lunes a domingo, 11:00 a.m. a 10:00 p.m.",
        "reseñas": []
    },
    {
        "nombre": "Bocaditos Cafe",
        "categoria": "Cafe",
        "ubicacion": "Barrio La Riviera, Cucuta",
        "descripcion": "Cafe con productos de pasteleria y bocadillos.",
        "horario": "Lunes a sabado, 7:00 a.m. a 7:00 p.m.",
        "reseñas": []
    }
]


def mostrar_menu():
    print("\n===== PlanATi =====")
    print("1. Buscar establecimiento")
    print("2. Consultar establecimiento")
    print("3. Publicar reseña")
    print("4. Salir")


opcion = ""
while opcion != "4":
    mostrar_menu()
    opcion = input("Seleccione una opcion: ").strip()

    if opcion == "1":
        buscar_establecimientos(establecimientos)
    elif opcion == "2":
        consultar_establecimiento(establecimientos)
    elif opcion == "3":
        publicar_resena(establecimientos)
    elif opcion == "4":
        print("Gracias por utilizar PlanATi.")
    else:
        print("Opcion invalida. Seleccione una opcion del 1 al 4.")
