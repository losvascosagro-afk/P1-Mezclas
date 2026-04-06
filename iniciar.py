#!/usr/bin/env python
import sys
import os

# PRIMERO: Asegurar que Flask se encuentra (antes de cualquier otro import)
user_site = os.path.expanduser(r'~\AppData\Roaming\Python\Python312\site-packages')
if user_site not in sys.path:
    sys.path.insert(0, user_site)

# Ahora sí, importar
try:
    from app import app
    print("\n" + "="*60)
    print("  LABORATORIO - COMPATIBILIDAD DE MEZCLAS")
    print("  Abrí el navegador en: http://localhost:5000")
    print("="*60 + "\n")
    import webbrowser
    webbrowser.open('http://localhost:5000')
    app.run(host='0.0.0.0', port=5000, debug=False)
except ImportError as e:
    print(f"ERROR: {e}")
    print(f"\nPython path: {sys.path}")
    import traceback
    traceback.print_exc()
    input("\nPresiona Enter para salir...")
