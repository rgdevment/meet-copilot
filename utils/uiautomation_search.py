import uiautomation as auto

def spy_windows():
    print("🕵️ BUSCANDO VENTANA DE SUBTÍTULOS...\n")

    # Buscamos en todas las ventanas de primer nivel
    root = auto.GetRootControl()
    found = False

    for window in root.GetChildren():
        # Filtramos para no ver basura, buscamos palabras clave
        name = window.Name
        class_name = window.ClassName

        # Palabras clave comunes en varios idiomas
        keywords = ["live caption", "subtítulos", "legenda", "caption", "directo"]

        if any(k in name.lower() for k in keywords):
            found = True
            print(f"✅ ENCONTRADO POSIBLE CANDIDATO:")
            print(f"   Nombre exacto: '{name}'")
            print(f"   ClassName:     '{class_name}'")
            print("   --- Estructura interna (Hijos) ---")

            # Miramos qué tiene dentro para ver dónde está el texto
            try:
                for child in window.GetChildren():
                    print(f"      ➡️ Tipo: {child.ControlTypeName} | Nombre/Texto: '{child.Name}'")
                    # Si tiene nietos, miramos un nivel más
                    for grand in child.GetChildren():
                        print(f"         Testing nieto: {grand.ControlTypeName} | '{grand.Name}'")
            except:
                print("      (No se pudo leer hijos)")
            print("\n" + "="*30 + "\n")

    if not found:
        print("❌ NO SE ENCONTRÓ NADA. ¿Seguro que Win+Ctrl+L está activo?")
        print("Listando TODAS las ventanas visibles por si tiene un nombre raro:")
        for window in root.GetChildren():
            if window.Name:
                print(f" - {window.Name}")

if __name__ == "__main__":
    spy_windows()
