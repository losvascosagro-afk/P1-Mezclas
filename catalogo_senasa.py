"""
Carga del catálogo SENASA (data/senasa_carga.json) en la base de la app.

Lo usan la página /admin/catalogo-senasa y scripts/cargar_senasa.py.

Garantías:
  - Antes de tocar productos congela los datos de producto en todos los ensayos
    y verifica que no quede ningún detalle sin copia.
  - Cada actualización se aplica sólo si el producto existe y su nombre es el
    esperado; si no, se saltea y se informa.
  - No se borra ningún producto: los duplicados se ocultan.
  - Respaldo de la tabla productos (productos_respaldo) y registro de cada cambio
    (productos_cambios), que es lo que usa revertir().
  - Quien llama decide commit o rollback: todo ocurre en una sola transacción.
"""
import json
import os
from datetime import datetime

import db

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PLAN_PATH = os.path.join(BASE_DIR, 'data', 'senasa_carga.json')
LOTE = 'senasa-2026-10-06'
CAMPOS_ALTA = ['nombre_comercial', 'categoria', 'empresa', 'formulacion', 'principio_activo',
               'unidad_medida', 'familia', 'registro_senasa']

_SCHEMA = {
    'sqlite': [
        '''CREATE TABLE IF NOT EXISTS productos_cambios (
            id INTEGER PRIMARY KEY AUTOINCREMENT, lote TEXT, id_producto INTEGER,
            accion TEXT, campo TEXT, antes TEXT, despues TEXT, fecha TEXT)''',
        '''CREATE TABLE IF NOT EXISTS productos_respaldo (
            id INTEGER PRIMARY KEY AUTOINCREMENT, lote TEXT, fecha TEXT, datos TEXT)''',
    ],
    'postgres': [
        '''CREATE TABLE IF NOT EXISTS productos_cambios (
            id SERIAL PRIMARY KEY, lote TEXT, id_producto INTEGER,
            accion TEXT, campo TEXT, antes TEXT, despues TEXT, fecha TEXT)''',
        '''CREATE TABLE IF NOT EXISTS productos_respaldo (
            id SERIAL PRIMARY KEY, lote TEXT, fecha TEXT, datos TEXT)''',
    ],
}


def cargar_plan(ruta=None):
    with open(ruta or PLAN_PATH, encoding='utf-8') as f:
        return json.load(f)


def raw(conn):
    """Conexión de la app (get_db) o conexión cruda → conexión cruda del driver."""
    return getattr(conn, '_conn', conn)


def _q(conn, sql, params=()):
    if db.BACKEND == 'postgres':
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute(db._pg_sql(sql), params or ())
        return cur
    return conn.execute(sql, params or ())


def _muchos(conn, sql, filas):
    """Ejecuta el mismo INSERT/UPDATE para muchas filas con pocos viajes a la base."""
    if not filas:
        return
    if db.BACKEND == 'postgres':
        import psycopg2.extras
        psycopg2.extras.execute_batch(conn.cursor(), db._pg_sql(sql), filas, page_size=500)
    else:
        conn.executemany(sql, filas)


def _preparar(conn):
    for sql in _SCHEMA[db.BACKEND]:
        _q(conn, sql)


def estado(conn):
    """Si el lote ya está aplicado y con qué resultado."""
    conn = raw(conn)
    _preparar(conn)
    filas = _q(conn, 'SELECT accion, COUNT(*) AS n, MIN(fecha) AS fecha FROM productos_cambios '
                     'WHERE lote=? GROUP BY accion', (LOTE,)).fetchall()
    return {f['accion']: (f['n'], f['fecha']) for f in filas}


def aplicar(conn, plan, escribir):
    """Aplica el plan. Devuelve (resumen, avisos). No hace commit ni rollback."""
    conn = raw(conn)
    ahora = datetime.now().isoformat(timespec='seconds')
    _preparar(conn)
    if _q(conn, 'SELECT COUNT(*) FROM productos_cambios WHERE lote=?', (LOTE,)).fetchone()[0]:
        raise RuntimeError(f'El lote {LOTE} ya fue aplicado en esta base.')

    db.snapshot_existentes(conn)
    sin_copia = _q(conn, 'SELECT COUNT(*) FROM detalle_mezcla WHERE snap_nombre IS NULL '
                         'AND id_producto IS NOT NULL').fetchone()[0]
    if sin_copia:
        raise RuntimeError(f'{sin_copia} detalles de ensayo sin copia congelada: no se continúa.')

    cur = _q(conn, 'SELECT * FROM productos ORDER BY id_producto')
    cols = [d[0] for d in cur.description]
    productos = {r['id_producto']: dict(zip(cols, r)) for r in cur.fetchall()}
    if escribir:
        _q(conn, 'INSERT INTO productos_respaldo (lote, fecha, datos) VALUES (?,?,?)',
           (LOTE, ahora, json.dumps(list(productos.values()), ensure_ascii=False, default=str)))

    log, avisos = [], []

    # ── Actualizaciones ──
    por_columnas = {}
    aplicados = {}   # id_producto → cambios efectivamente aplicados
    n_upd = 0
    for u in plan['actualizaciones']:
        p = productos.get(u['id_producto'])
        if p is None:
            avisos.append(f"id {u['id_producto']} ({u['nombre_esperado']}): no existe")
            continue
        if p['nombre_comercial'] != u['nombre_esperado']:
            avisos.append(f"id {u['id_producto']}: se esperaba «{u['nombre_esperado']}» "
                          f"y la base tiene «{p['nombre_comercial']}»")
            continue
        cambios = {k: v for k, v in u['cambios'].items() if p.get(k) != v}
        if not cambios:
            continue
        aplicados[u['id_producto']] = cambios
        clave = tuple(sorted(cambios))
        por_columnas.setdefault(clave, []).append(tuple(cambios[k] for k in clave) + (u['id_producto'],))
        for k in clave:
            log.append((LOTE, u['id_producto'], 'UPDATE', k, _txt(p.get(k)), _txt(cambios[k]), ahora))
        n_upd += 1
    for clave, filas in por_columnas.items():
        _muchos(conn, f'UPDATE productos SET {", ".join(f"{k}=?" for k in clave)} WHERE id_producto=?', filas)

    # ── Ocultar duplicados ──
    n_oc = 0
    for o in plan['ocultar']:
        p = productos.get(o['id_producto'])
        if p is None or p['nombre_comercial'] != o['nombre_esperado']:
            avisos.append(f"ocultar id {o['id_producto']}: no coincide el nombre")
            continue
        _q(conn, 'UPDATE productos SET oculto=1 WHERE id_producto=?', (o['id_producto'],))
        log.append((LOTE, o['id_producto'], 'UPDATE', 'oculto', _txt(p.get('oculto')), '1', ahora))
        n_oc += 1

    # ── Altas: se saltean las que ya existen en la base por registro o por nombre ──
    #    Se compara contra los nombres y registros como quedan DESPUÉS de las correcciones.
    regs, nombres = set(), set()
    for pid, p in productos.items():
        final = {**p, **aplicados.get(pid, {})}
        nombres.add((final['nombre_comercial'] or '').strip().upper())
        regs.update(x.strip() for x in (final.get('registro_senasa') or '').split('|') if x.strip())
    nuevas = [a for a in plan['altas']
              if a['registro_senasa'] not in regs and a['nombre_comercial'].upper() not in nombres]
    ya = len(plan['altas']) - len(nuevas)
    max_id = _q(conn, 'SELECT COALESCE(MAX(id_producto),0) FROM productos').fetchone()[0]
    if db.BACKEND == 'postgres':
        import psycopg2.extras
        psycopg2.extras.execute_values(
            conn.cursor(), f'INSERT INTO productos ({",".join(CAMPOS_ALTA)}) VALUES %s',
            [tuple(a.get(c) for c in CAMPOS_ALTA) for a in nuevas], page_size=1000)
    else:
        _muchos(conn, f'INSERT INTO productos ({",".join(CAMPOS_ALTA)}) VALUES ({",".join("?" * len(CAMPOS_ALTA))})',
                [tuple(a.get(c) for c in CAMPOS_ALTA) for a in nuevas])
    _q(conn, 'INSERT INTO productos_cambios (lote,id_producto,accion,campo,antes,despues,fecha) '
             "SELECT ?, id_producto, 'INSERT', 'registro_senasa', NULL, registro_senasa, ? "
             'FROM productos WHERE id_producto > ?', (LOTE, ahora, max_id))
    _muchos(conn, 'INSERT INTO productos_cambios (lote,id_producto,accion,campo,antes,despues,fecha) '
                  'VALUES (?,?,?,?,?,?,?)', log)

    total = _q(conn, 'SELECT COUNT(*) FROM productos WHERE COALESCE(oculto,0)=0').fetchone()[0]
    resumen = {'actualizados': n_upd, 'ocultados': n_oc, 'altas': len(nuevas),
               'altas_ya_existentes': ya, 'total_visibles': total}
    return resumen, avisos


def _txt(v):
    return None if v is None else str(v)


def revertir(conn, lote=LOTE):
    """Deshace un lote. Devuelve un resumen. No hace commit ni rollback."""
    conn = raw(conn)
    _preparar(conn)
    filas = _q(conn, 'SELECT * FROM productos_cambios WHERE lote=? ORDER BY id DESC', (lote,)).fetchall()
    if not filas:
        raise RuntimeError(f'No hay cambios registrados para el lote {lote}.')
    usados = {r[0] for r in _q(conn, 'SELECT DISTINCT id_producto FROM detalle_mezcla').fetchall()}
    borrar, conservados, restaurados, conflictos = [], [], 0, []
    for f in filas:
        pid = f['id_producto']
        if f['accion'] == 'INSERT':
            (conservados if pid in usados else borrar).append(pid)
            continue
        campo = f['campo']
        actual = _q(conn, f'SELECT {campo} FROM productos WHERE id_producto=?', (pid,)).fetchone()
        if actual is None:
            continue
        if _txt(actual[0]) != f['despues']:
            conflictos.append(f'id {pid}.{campo}: se editó después de la carga, no se revierte')
            continue
        antes = f['antes']
        if campo == 'oculto':
            antes = int(antes) if antes is not None else 0
        _q(conn, f'UPDATE productos SET {campo}=? WHERE id_producto=?', (antes, pid))
        restaurados += 1
    _muchos(conn, 'DELETE FROM productos WHERE id_producto=?', [(p,) for p in borrar])
    _q(conn, 'DELETE FROM productos_cambios WHERE lote=?', (lote,))
    return {'altas_borradas': len(borrar), 'altas_conservadas_en_uso': conservados,
            'campos_restaurados': restaurados, 'conflictos': conflictos}
