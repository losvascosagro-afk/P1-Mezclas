"""
Aplica (o revierte) el plan de carga del catálogo SENASA: data/senasa_carga.json.
La misma carga se puede hacer desde la app en /admin/catalogo-senasa.

Base de datos: la misma que usa la app (DATABASE_URL → PostgreSQL; si no, mezclas.db).

  python scripts/cargar_senasa.py                  # PRUEBA: muestra qué haría sin cambiar productos
                                                   # (sí prepara columnas nuevas y la copia de ensayos,
                                                   #  lo mismo que hace la app al arrancar)
  python scripts/cargar_senasa.py --aplicar        # aplica (con respaldo previo)
  python scripts/cargar_senasa.py --revertir       # deshace el lote aplicado
  python scripts/cargar_senasa.py --sqlite RUTA    # usar otra base SQLite (pruebas)
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import db  # noqa: E402
import catalogo_senasa as cs  # noqa: E402


def conectar():
    if db.BACKEND == 'postgres':
        import psycopg2
        return psycopg2.connect(db.DATABASE_URL, connect_timeout=10)
    import sqlite3
    conn = sqlite3.connect(db.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--aplicar', action='store_true', help='escribir en la base (sin esto es una prueba)')
    ap.add_argument('--revertir', action='store_true', help=f'deshacer el lote {cs.LOTE}')
    ap.add_argument('--sqlite', metavar='RUTA', help='usar esta base SQLite en vez de mezclas.db')
    ap.add_argument('--plan', default=None, help='ruta del plan (por defecto data/senasa_carga.json)')
    args = ap.parse_args()

    if args.sqlite:
        if db.BACKEND == 'postgres':
            sys.exit('--sqlite no se puede usar con DATABASE_URL definida')
        db.DB_PATH = os.path.abspath(args.sqlite)
    print('Base:', 'PostgreSQL (DATABASE_URL)' if db.BACKEND == 'postgres' else db.DB_PATH)
    print('Modo:', 'REVERTIR' if args.revertir else 'APLICAR' if args.aplicar else 'PRUEBA (no escribe)')

    db.init_db()   # columnas nuevas + copia congelada de los ensayos (idempotente)
    conn = conectar()
    try:
        if args.revertir:
            r = cs.revertir(conn)
            conn.commit()
            for k, v in r.items():
                print(f'{k}: {v}')
            return
        resumen, avisos = cs.aplicar(conn, cs.cargar_plan(args.plan), args.aplicar)
        for k, v in resumen.items():
            print(f'{k}: {v}')
        for a in avisos:
            print('  SALTEADO:', a)
        if args.aplicar:
            conn.commit()
            print(f'Aplicado. Lote: {cs.LOTE}')
        else:
            conn.rollback()
            print('Prueba terminada: no se escribió nada. Para aplicar: --aplicar')
    except RuntimeError as e:
        conn.rollback()
        sys.exit(str(e))
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    main()
