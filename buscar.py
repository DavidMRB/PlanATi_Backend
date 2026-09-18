def buscar_establecimientos(establecimientos):
    print("\n1. Buscar por nombre")
    print("2. Buscar por categoria")
    tipo_busqueda = input("Seleccione una opcion: ").strip()

    if tipo_busqueda == "1":
        campo = "nombre"
    elif tipo_busqueda == "2":
        campo = "categoria"
    else:
        print("Opcion de busqueda invalida.")
        return

    texto_busqueda = input("Ingrese el texto que desea buscar: ").strip().lower()
    if texto_busqueda == "":
        print("Debe ingresar un texto de busqueda.")
        return

    encontrados = []
    for establecimiento in establecimientos:
        valor = establecimiento[campo].lower()
        if texto_busqueda in valor:
            encontrados.append(establecimiento)

    if len(encontrados) == 0:
        print("No se encontraron establecimientos.")
    else:
        print("\nEstablecimientos encontrados:")
        for establecimiento in encontrados:
            print("- " + establecimiento["nombre"] + " (" + establecimiento["categoria"] + ")")
