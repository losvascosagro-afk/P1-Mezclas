import sys
import os

# Configurar PYTHONPATH PRIMERO
user_site = os.path.expanduser(r'~\AppData\Roaming\Python\Python312\site-packages')
if user_site not in sys.path:
    sys.path.insert(0, user_site)

print("\n" + "="*60)
print("  LABORATORIO - COMPATIBILIDAD DE MEZCLAS")
print("  http://localhost:5000")
print("="*60 + "\n")

# Abrir navegador
import webbrowser
import time
time.sleep(2)
webbrowser.open('http://localhost:5000')

# Importar y ejecutar app directamente (no como subprocess)
try:
    from app import app
    app.run(host='0.0.0.0', port=5000, debug=False)
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
    input("\nPresiona Enter para salir...")
