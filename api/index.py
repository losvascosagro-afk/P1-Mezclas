"""
Entry point para Vercel.
Vercel busca una variable 'app' (WSGI callable) en este archivo.
"""
import sys
import os
import traceback

# Agrega el directorio raíz del proyecto al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from db import init_db

# Inicializa las tablas en cada cold start (CREATE TABLE IF NOT EXISTS es idempotente)
try:
    init_db()
except Exception as e:
    traceback.print_exc()
    print(f"WARNING: init_db() falló: {e} — la app continúa igual")
