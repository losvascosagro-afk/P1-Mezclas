"""
Muestras del laboratorio: qué productos del catálogo tenemos físicamente.

Por ahora sólo "tenemos / no tenemos" (una fila en `muestras_lab` por producto).
La búsqueda "¿Tenemos…?" mira nombre, empresa y principio activo, igual que el
buscador de productos de los ensayos.
"""
from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for

from db import get_db

bp = Blueprint('muestras', __name__)

_COLS = 'p.id_producto, p.nombre_comercial, p.categoria, p.empresa, p.principio_activo, p.formulacion'


def _filtro(q):
    """Condición SQL + parámetros: cada palabra debe estar en nombre, empresa o activo."""
    palabras = q.split()
    cond = ''.join(' AND (p.nombre_comercial LIKE ? OR p.empresa LIKE ? OR p.principio_activo LIKE ?)'
                   for _ in palabras)
    return cond, [f'%{w}%' for w in palabras for _ in range(3)]


def ids_en_lab(db):
    return {r[0] for r in db.execute('SELECT id_producto FROM muestras_lab').fetchall()}


@bp.route('/muestras')
def index():
    db = get_db()
    q = request.args.get('q', '').strip()
    cond, params = _filtro(q)
    tenemos = db.execute(f'''
        SELECT {_COLS}, m.fecha_alta FROM muestras_lab m JOIN productos p ON p.id_producto = m.id_producto
        WHERE 1=1{cond} ORDER BY p.nombre_comercial''', params).fetchall()
    catalogo = []
    if q:
        # productos del catálogo que coinciden y que no tenemos
        catalogo = db.execute(f'''
            SELECT {_COLS} FROM productos p
            WHERE COALESCE(p.oculto, 0) = 0{cond}
              AND p.id_producto NOT IN (SELECT id_producto FROM muestras_lab)
            ORDER BY p.nombre_comercial LIMIT 50''', params).fetchall()
    total = db.execute('SELECT COUNT(*) FROM muestras_lab').fetchone()[0]
    return render_template('muestras.html', q=q, tenemos=tenemos, catalogo=catalogo, total=total)


@bp.route('/muestras/<int:id_producto>/agregar', methods=['POST'])
def agregar(id_producto):
    db = get_db()
    p = db.execute('SELECT nombre_comercial FROM productos WHERE id_producto=?', (id_producto,)).fetchone()
    if p and id_producto not in ids_en_lab(db):
        db.execute('INSERT INTO muestras_lab (id_producto, fecha_alta) VALUES (?, ?)',
                   (id_producto, datetime.now().strftime('%Y-%m-%d')))
        db.commit()
        flash(f'{p[0]}: marcado como que lo tenemos en el laboratorio.', 'success')
    return redirect(url_for('muestras.index', q=request.form.get('q', '')))


@bp.route('/muestras/<int:id_producto>/quitar', methods=['POST'])
def quitar(id_producto):
    db = get_db()
    p = db.execute('SELECT nombre_comercial FROM productos WHERE id_producto=?', (id_producto,)).fetchone()
    db.execute('DELETE FROM muestras_lab WHERE id_producto=?', (id_producto,))
    db.commit()
    if p:
        flash(f'{p[0]}: quitado de las muestras del laboratorio.', 'info')
    return redirect(url_for('muestras.index', q=request.form.get('q', '')))
