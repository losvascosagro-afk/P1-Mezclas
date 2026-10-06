"""
Aplica (o revierte) el plan de carga del catálogo SENASA: data/senasa_carga.json.

Base de datos: la misma que usa la app (DATABASE_URL → PostgreSQL; si no, mezclas.db).

  python scripts/cargar_senasa.py                  # PRUEBA: muestra qué haría sin cambiar productos
                                                   # (sí prepara columnas nuevas y la copia de ensayos,
                                                   #  lo mismo que hace la app al arrancar)
  python scripts/cargar_senasa.py --aplicar        # aplica (con respaldo previo)
  python scripts/cargar_senasa.py --revertir LOTE  # deshace un lote aplicado
  python scripts/cargar_senasa.py --sqlite RUTA    # usar otra base SQLite (pruebas)

Garantías:
  - Antes de tocar productos congela los datos de producto en todos los ensayos
    (init_db) y verifica que no quede ningún detalle sin copia.
  - Cada actualización se aplica sólo si el producto existe y su nombre es el
    esperado; si no, se saltea y se informa.
  - No se borra ningún producto: los duplicados se ocultan.
  - Todo cambio queda en la tabla productos_cambios (lote, valor anterior y nuevo),
    que es lo que usa --revertir.
  - Todo corre en una sola transacción: si algo falla, no queda nada a medias.
"""
import argparse
import json
import os
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import db  # noqa: E402

PLAN = os.path.join(ROOT, 'data', 'senasa_carga.json')
LOTE = 'senasa-2026-10-06'
CAMPOS_ALTA = ['nombre_comercial', 'categoria', 'empresa', 'formulacion', 'principio_activo',
               'unidad_medida', 'familia', 'registro_senasa']

_SCHEMA_LOG = {
    'sqlite': '''CREATE TABLE IF NOT EXISTS productos_cambios (
        id INTEGER PRIMARY KEY AUTOINCREMENT, lote TEXT, id_producto INTEGER,
        accion TEXT, campo TEXT, antes TEXT, despues TEXT, fecha TEXT)''',
    'postgres': '''CREATE TABLE IF NOT EXISTS productos_cambios (
        id SERIAL PRIMARY KEY, lote TEXT, id_producto INTEGER,
        accion TEXT, campo TEXT, antes TEXT, despues TEXT, fecha TEXT)''',
}


def conectar():
    if db.BACKEND == 'postgres':
        import psycopg2
        import psycopg2.extras
        conn = psycopg2.connect(db.DATABASE_URL, connect_timeout=10)
        conn.cursor_factory = psycopg2.extras.DictCursor
        return conn
    import sqlite3
    conn = sqlite3.connect(db.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def q(conn, sql, params=()):
    return db._exec(conn, sql, params)


def respaldo(conn):
    os.makedirs(os.path.join(ROOT, 'backups'), exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    ruta = os.path.join(ROOT, 'backups', f'productos_{db.BACKEND}_{ts}.json')
    cur = q(conn, 'SELECT * FROM productos ORDER BY id_producto')
    cols = [d[0] for d in cur.description]
    filas = [dict(zip(cols, r)) for r in cur.fetchall()]
    with open(ruta, 'x', encoding='utf-8') as f:   # 'x': nunca pisa un respaldo existente
        json.dump(filas, f, ensure_ascii=False, indent=1, default=str)
    return ruta, len(filas)


def insertar_altas(conn, filas):
    sql = f'INSERT INTO productos ({",".join(CAMPOS_ALTA)}) VALUES ({",".join("?" * len(CAMPOS_ALTA))})'
    valores = [tuple(a.get(c) for c in CAMPOS_ALTA) for a in filas]
    if db.BACKEND == 'postgres':
        import psycopg2.extras
        cur = conn.cursor()
        psycopg2.extras.execute_values(
            cur, f'INSERT INTO productos ({",".join(CAMPOS_ALTA)}) VALUES %s', valores, page_size=500)
    else:
        conn.executemany(sql, valores)


def aplicar(conn, plan, escribir):
    ahora = datetime.now().isoformat(timespec='seconds')
    q(conn, _SCHEMA_LOG[db.BACKEND])
    if q(conn, 'SELECT COUNT(*) FROM productos_cambios WHERE lote=?', (LOTE,)).fetchone()[0]:
        sys.exit(f'El lote {LOTE} ya fue aplicado en esta base. Para rehacerlo: --revertir {LOTE}')
    if escribir:
        ruta, n = respaldo(conn)
        print(f'Respaldo de {n} productos en {ruta}')

    db.snapshot_existentes(conn)
    sin_copia = q(conn, 'SELECT COUNT(*) FROM detalle_mezcla WHERE snap_nombre IS NULL '
                        'AND id_producto IS NOT NULL').fetchone()[0]
    if sin_copia:
        sys.exit(f'{sin_copia} detalles de ensayo sin copia congelada: no se continúa.')

    log = []
    salteados = []

    # ── Actualizaciones ──
    n_upd = 0
    for u in plan['actualizaciones']:
        row = q(conn, 'SELECT * FROM productos WHERE id_producto=?', (u['id_producto'],)).fetchone()
        if row is None:
            salteados.append(f"id {u['id_producto']} ({u['nombre_esperado']}): no existe")
            continue
        if row['nombre_comercial'] != u['nombre_esperado']:
            salteados.append(f"id {u['id_producto']}: se esperaba '{u['nombre_esperado']}' "
                             f"y la base tiene '{row['nombre_comercial']}'")
            continue
        cambios = {k: v for k, v in u['cambios'].items() if row[k] != v}
        if not cambios:
            continue
        sets = ', '.join(f'{k}=?' for k in cambios)
        q(conn, f'UPDATE productos SET {sets} WHERE id_producto=?', tuple(cambios.values()) + (u['id_producto'],))
        for k, v in cambios.items():
            log.append((LOTE, u['id_producto'], 'UPDATE', k, row[k], v, ahora))
        n_upd += 1

    # ── Ocultar duplicados ──
    n_oc = 0
    for o in plan['ocultar']:
        row = q(conn, 'SELECT nombre_comercial, oculto FROM productos WHERE id_producto=?',
                (o['id_producto'],)).fetchone()
        if row is None or row['nombre_comercial'] != o['nombre_esperado']:
            salteados.append(f"ocultar id {o['id_producto']}: no coincide el nombre")
            continue
        q(conn, 'UPDATE productos SET oculto=1 WHERE id_producto=?', (o['id_producto'],))
        log.append((LOTE, o['id_producto'], 'UPDATE', 'oculto', row['oculto'], 1, ahora))
        n_oc += 1

    # ── Altas: se saltean las que ya existen en la base por registro o por nombre.
    #    Altas con la misma marca entre sí (otra empresa/activo) se cargan todas. ──
    regs_existentes, nombres_existentes = set(), set()
    for r in q(conn, 'SELECT nombre_comercial, registro_senasa FROM productos').fetchall():
        nombres_existentes.add((r['nombre_comercial'] or '').strip().upper())
        regs_existentes.update(x.strip() for x in (r['registro_senasa'] or '').split('|') if x.strip())
    nuevas, ya = [], 0
    for a in plan['altas']:
        if a['registro_senasa'] in regs_existentes or a['nombre_comercial'].upper() in nombres_existentes:
            ya += 1
            continue
        nuevas.append(a)
    max_id = q(conn, 'SELECT COALESCE(MAX(id_producto),0) FROM productos').fetchone()[0]
    insertar_altas(conn, nuevas)
    q(conn, 'INSERT INTO productos_cambios (lote,id_producto,accion,campo,antes,despues,fecha) '
            "SELECT ?, id_producto, 'INSERT', 'registro_senasa', NULL, registro_senasa, ? "
            'FROM productos WHERE id_producto > ?', (LOTE, ahora, max_id))

    for entrada in log:
        q(conn, 'INSERT INTO productos_cambios (lote,id_producto,accion,campo,antes,despues,fecha) '
                'VALUES (?,?,?,?,?,?,?)', tuple(None if x is None else str(x) if i in (4, 5) else x
                                                for i, x in enumerate(entrada)))

    total = q(conn, 'SELECT COUNT(*) FROM productos').fetchone()[0]
    print(f'Productos actualizados: {n_upd}')
    print(f'Productos ocultados:    {n_oc}')
    print(f'Altas nuevas:           {len(nuevas)}  (ya existían: {ya})')
    print(f'Total de productos:     {total}')
    for s in salteados:
        print('  SALTEADO:', s)
    return len(salteados)


def revertir(conn, lote):
    q(conn, _SCHEMA_LOG[db.BACKEND])
    filas = q(conn, 'SELECT * FROM productos_cambios WHERE lote=? ORDER BY id DESC', (lote,)).fetchall()
    if not filas:
        sys.exit(f'No hay cambios registrados para el lote {lote}.')
    borrados, conservados, restaurados, conflictos = 0, [], 0, []
    for f in filas:
        pid = f['id_producto']
        if f['accion'] == 'INSERT':
            usado = q(conn, 'SELECT COUNT(*) FROM detalle_mezcla WHERE id_producto=?', (pid,)).fetchone()[0]
            if usado:
                conservados.append(pid)
                continue
            q(conn, 'DELETE FROM productos WHERE id_producto=?', (pid,))
            borrados += 1
        else:
            campo = f['campo']
            actual = q(conn, f'SELECT {campo} FROM productos WHERE id_producto=?', (pid,)).fetchone()
            if actual is None:
                continue
            if str(actual[0]) != str(f['despues']):
                conflictos.append(f'id {pid}.{campo}: se editó después de la carga, no se revierte')
                continue
            antes = f['antes']
            if campo == 'oculto':
                antes = int(antes) if antes not in (None, 'None') else 0
            q(conn, f'UPDATE productos SET {campo}=? WHERE id_producto=?', (antes, pid))
            restaurados += 1
    q(conn, 'DELETE FROM productos_cambios WHERE lote=?', (lote,))
    print(f'Altas borradas: {borrados}')
    print(f'Altas conservadas porque ya se usan en ensayos: {len(conservados)} {conservados[:20]}')
    print(f'Campos restaurados: {restaurados}')
    for c in conflictos:
        print('  CONFLICTO:', c)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--aplicar', action='store_true', help='escribir en la base (sin esto es una prueba)')
    ap.add_argument('--revertir', metavar='LOTE', help='deshacer un lote aplicado')
    ap.add_argument('--sqlite', metavar='RUTA', help='usar esta base SQLite en vez de mezclas.db')
    ap.add_argument('--plan', default=PLAN)
    args = ap.parse_args()

    if args.sqlite:
        if db.BACKEND == 'postgres':
            sys.exit('--sqlite no se puede usar con DATABASE_URL definida')
        db.DB_PATH = os.path.abspath(args.sqlite)
    destino = 'PostgreSQL (DATABASE_URL)' if db.BACKEND == 'postgres' else db.DB_PATH
    print(f'Base: {destino}')
    print('Modo:', 'REVERTIR ' + args.revertir if args.revertir else 'APLICAR' if args.aplicar else 'PRUEBA (no escribe)')

    db.init_db()   # columnas nuevas + copia congelada de los ensayos (idempotente)
    conn = conectar()
    try:
        if args.revertir:
            revertir(conn, args.revertir)
            conn.commit()
            print('Revertido.')
            return
        with open(args.plan, encoding='utf-8') as f:
            plan = json.load(f)
        aplicar(conn, plan, args.aplicar)
        if args.aplicar:
            conn.commit()
            print(f'Aplicado. Lote: {LOTE}')
        else:
            conn.rollback()
            print('Prueba terminada: no se escribió nada. Para aplicar: --aplicar')
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    main()
