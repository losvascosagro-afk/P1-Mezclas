"""
Ensayos comparativos: un ensayo con varias mezclas (p. ej. Harrier Bio vs. candidatos).

Datos comunes en `ensayos` (tipo='comparativo'): fecha, cliente, objetivo,
descripción general (obs_mezcla), volúmenes, tiempos de observación y la
conclusión general (recomendacion). Cada mezcla en `mezclas_ensayo` con su agua,
observaciones, resultado y microscopía; sus productos en `detalle_mezcla` y sus
fotos en `fotos_ensayo`, ambos con id_mezcla.
"""
import io
import os
from datetime import datetime

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for

import observaciones
from db import BACKEND, SNAP_COLS, get_db

bp = Blueprint('comparativos', __name__)

CAMPOS_MEZCLA = ['nombre', 'descripcion', 'tipo_agua', 'ph', 'dureza', 'temperatura', 'conductividad',
                 'espuma', 'precipitado', 'separacion_fases', 'redispersion', 'obs_microscopio',
                 'resultado_final']
_NUMERICOS = {'ph', 'dureza', 'temperatura', 'conductividad'}
OBS_VISUALES = observaciones.ETIQUETAS
RESULTADOS = ['Estable', 'Inestable', 'Estable con observaciones', 'Requiere más ensayos']
TIPOS_AGUA = ['Estándar laboratorio', 'Agua de pozo', 'Agua de red', 'Agua destilada',
              'Agua de lluvia', 'Agua dura', 'Agua blanda', 'Otra']


@bp.app_template_filter('num')
def num(v):
    """Número sin decimales de más: 75.0 → 75, 7.80 → 7.8. Vacío → '—'."""
    if v is None or v == '':
        return '—'
    try:
        return f'{float(v):g}'
    except (TypeError, ValueError):
        return v


def _app():
    import app   # import diferido: app registra este módulo al final de su carga
    return app


# ──────────────────────────────────────────────────────────
# Lectura
# ──────────────────────────────────────────────────────────

def cargar_mezclas(db, eid):
    """Mezclas del ensayo con sus productos (copia congelada) y fotos."""
    a = _app()
    mezclas = [dict(m) for m in db.execute(
        'SELECT * FROM mezclas_ensayo WHERE id_ensayo=? ORDER BY orden, id_mezcla', (eid,)).fetchall()]
    detalles = db.execute(f'''
        SELECT dm.*, {a._DET_COLS}
        FROM detalle_mezcla dm LEFT JOIN productos p ON dm.id_producto=p.id_producto
        WHERE dm.id_ensayo=? ORDER BY dm.orden_carga, dm.id_detalle''', (eid,)).fetchall()
    fotos = db.execute('SELECT * FROM fotos_ensayo WHERE id_ensayo=? ORDER BY fecha_carga, id_foto',
                       (eid,)).fetchall()
    por_id = {m['id_mezcla']: m for m in mezclas}
    for m in mezclas:
        m['detalles'], m['fotos'] = [], []
    generales = []
    for d in detalles:
        if d['id_mezcla'] in por_id:
            por_id[d['id_mezcla']]['detalles'].append(d)
    for f in fotos:
        (por_id[f['id_mezcla']]['fotos'] if f['id_mezcla'] in por_id else generales).append(f)
    return mezclas, generales


def _ensayo(db, eid):
    return db.execute('''
        SELECT e.*, c.razon_social, c.tecnico_responsable, c.cuit,
               c.localidad, c.provincia, c.direccion, c.condicion_iva
        FROM ensayos e LEFT JOIN clientes c ON e.id_cliente=c.id_cliente
        WHERE e.id_ensayo=?''', (eid,)).fetchone()


def _mezclas_para_form(mezclas):
    """Datos de las mezclas para que el formulario las arme (JSON)."""
    out = []
    for m in mezclas:
        out.append({
            'id_mezcla': m['id_mezcla'],
            **{c: m[c] for c in CAMPOS_MEZCLA},
            'productos': [{'id_producto': d['id_producto'], 'nombre': d['nombre_comercial'] or '',
                           'orden': d['orden_carga'], 'dosis': d['dosis'], 'unidad': d['unidad'] or 'L',
                           'obs': d['observacion'] or ''} for d in m['detalles']],
            'fotos': [{'id': f['id_foto'], 'descripcion': f['descripcion'] or ''} for f in m['fotos']],
        })
    return out


# ──────────────────────────────────────────────────────────
# Guardado
# ──────────────────────────────────────────────────────────

def _valor(form, k, campo):
    v = form.get(f'm{k}_{campo}')
    if campo in _NUMERICOS:
        return _app()._float_or_none(v)
    if campo in observaciones.ESCALAS:
        return v or observaciones.POR_DEFECTO[campo]
    return (v or '').strip() or None


def _guardar_ensayo(db, form, eid=None):
    campos = ('fecha', 'id_cliente', 'objetivo', 'obs_mezcla', 'volumenes', 'tiempos_obs', 'recomendacion')
    valores = (form.get('fecha') or datetime.now().strftime('%Y-%m-%d'),
               form.get('id_cliente') or None,
               form.get('objetivo') or None,
               form.get('obs_mezcla') or None,
               form.get('volumenes') or None,
               form.get('tiempos_obs') or None,
               form.get('recomendacion') or None)
    if eid is None:
        sql = (f'INSERT INTO ensayos ({",".join(campos)},tipo) VALUES ({",".join("?" * len(campos))},?)')
        if BACKEND == 'postgres':
            sql += ' RETURNING id_ensayo'
        return db.execute(sql, valores + ('comparativo',)).lastrowid
    db.execute(f'UPDATE ensayos SET {",".join(c + "=?" for c in campos)} WHERE id_ensayo=?', valores + (eid,))
    return eid


def _guardar_mezclas(db, eid, form):
    """Crea, actualiza y quita mezclas según el formulario. Al editar, cada
    producto que ya estaba conserva su copia congelada."""
    a = _app()
    existentes = {r['id_mezcla'] for r in db.execute(
        'SELECT id_mezcla FROM mezclas_ensayo WHERE id_ensayo=?', (eid,)).fetchall()}
    vistas = set()
    por_clave = {}   # clave del formulario → id_mezcla (para subir las fotos a su mezcla)
    for orden, k in enumerate(form.getlist('mezcla_key[]'), start=1):
        vals = [_valor(form, k, c) for c in CAMPOS_MEZCLA]
        if not vals[0]:
            vals[0] = f'Mezcla {orden}'
        idm = form.get(f'm{k}_id_mezcla')
        idm = int(idm) if idm and idm.isdigit() and int(idm) in existentes else None
        if idm:
            db.execute(f'UPDATE mezclas_ensayo SET orden=?, {",".join(c + "=?" for c in CAMPOS_MEZCLA)} '
                       'WHERE id_mezcla=?', [orden] + vals + [idm])
        else:
            sql = (f'INSERT INTO mezclas_ensayo (id_ensayo,orden,{",".join(CAMPOS_MEZCLA)}) '
                   f'VALUES (?,?,{",".join("?" * len(CAMPOS_MEZCLA))})')
            if BACKEND == 'postgres':
                sql += ' RETURNING id_mezcla'
            idm = db.execute(sql, [eid, orden] + vals).lastrowid
        vistas.add(idm)
        por_clave[k] = idm
        previos = {r['id_producto']: r for r in db.execute(
            'SELECT * FROM detalle_mezcla WHERE id_mezcla=?', (idm,)).fetchall()}
        db.execute('DELETE FROM detalle_mezcla WHERE id_mezcla=?', (idm,))
        a._save_detalles(db, eid, form, previos, prefijo=f'm{k}_', id_mezcla=idm)
    for idm in existentes - vistas:
        # mezcla quitada: sus fotos quedan en el ensayo como fotos generales
        db.execute('DELETE FROM detalle_mezcla WHERE id_mezcla=?', (idm,))
        db.execute('UPDATE fotos_ensayo SET id_mezcla=NULL WHERE id_mezcla=?', (idm,))
        db.execute('DELETE FROM mezclas_ensayo WHERE id_mezcla=?', (idm,))
    return por_clave


def _form(db, e, mezclas, titulo):
    return render_template('ensayo_comparativo_form.html', e=e, titulo=titulo,
                           mezclas_json=_mezclas_para_form(mezclas), tipos_agua=TIPOS_AGUA,
                           resultados=RESULTADOS, obs_visuales=OBS_VISUALES,
                           today=datetime.now().strftime('%Y-%m-%d'))


@bp.route('/ensayos/comparativo/nuevo', methods=['GET', 'POST'])
def nuevo():
    db = get_db()
    if request.method == 'POST':
        eid = _guardar_ensayo(db, request.form)
        por_clave = _guardar_mezclas(db, eid, request.form)
        db.commit()
        flash('Ensayo comparativo creado.', 'success')
        if request.headers.get('X-Fotos') == '1':
            return jsonify({'id_ensayo': eid, 'mezclas': por_clave})
        return redirect(url_for('ensayo_detalle', id=eid))
    return _form(db, None, [], 'Nuevo Ensayo Comparativo')


def editar(db, eid):
    """Lo llama /ensayos/<id>/editar cuando el ensayo es comparativo."""
    if request.method == 'POST':
        _guardar_ensayo(db, request.form, eid)
        por_clave = _guardar_mezclas(db, eid, request.form)
        db.commit()
        flash('Ensayo comparativo actualizado.', 'success')
        if request.headers.get('X-Fotos') == '1':
            return jsonify({'id_ensayo': eid, 'mezclas': por_clave})
        return redirect(url_for('ensayo_detalle', id=eid))
    mezclas, _ = cargar_mezclas(db, eid)
    return _form(db, _ensayo(db, eid), mezclas, f'Editar Ensayo Comparativo N° {eid:04d}')


def detalle(db, e):
    mezclas, generales = cargar_mezclas(db, e['id_ensayo'])
    return render_template('ensayo_comparativo_detalle.html', e=e, mezclas=mezclas,
                           fotos_generales=generales, obs_visuales=OBS_VISUALES)


# ──────────────────────────────────────────────────────────
# Duplicar un ensayo (simple o comparativo)
# ──────────────────────────────────────────────────────────

@bp.route('/ensayos/<int:id>/duplicar', methods=['POST'])
def duplicar(id):
    """Copia el ensayo con fecha de hoy, sus mezclas y productos (sin fotos).
    Los productos toman los datos actuales del catálogo."""
    db = get_db()
    e = db.execute('SELECT * FROM ensayos WHERE id_ensayo=?', (id,)).fetchone()
    if not e:
        flash('Ensayo no encontrado.', 'danger')
        return redirect(url_for('ensayos'))
    cols = [c for c in e.keys() if c != 'id_ensayo']
    vals = [datetime.now().strftime('%Y-%m-%d') if c == 'fecha' else e[c] for c in cols]
    sql = f'INSERT INTO ensayos ({",".join(cols)}) VALUES ({",".join("?" * len(cols))})'
    if BACKEND == 'postgres':
        sql += ' RETURNING id_ensayo'
    nuevo_id = db.execute(sql, vals).lastrowid

    mapa = {None: None}
    for m in db.execute('SELECT * FROM mezclas_ensayo WHERE id_ensayo=? ORDER BY orden', (id,)).fetchall():
        mcols = ['orden'] + CAMPOS_MEZCLA
        sql = (f'INSERT INTO mezclas_ensayo (id_ensayo,{",".join(mcols)}) '
               f'VALUES (?,{",".join("?" * len(mcols))})')
        if BACKEND == 'postgres':
            sql += ' RETURNING id_mezcla'
        mapa[m['id_mezcla']] = db.execute(sql, [nuevo_id] + [m[c] for c in mcols]).lastrowid

    snap_sel = ','.join(c for _, c in SNAP_COLS)
    snap_ins = ','.join(s for s, _ in SNAP_COLS)
    for d in db.execute('SELECT * FROM detalle_mezcla WHERE id_ensayo=? ORDER BY id_detalle', (id,)).fetchall():
        prod = db.execute(f'SELECT {snap_sel} FROM productos WHERE id_producto=?', (d['id_producto'],)).fetchone()
        snap = tuple(prod) if prod else tuple(d[s] for s, _ in SNAP_COLS)
        db.execute(f'INSERT INTO detalle_mezcla (id_ensayo,id_mezcla,orden_carga,id_producto,dosis,unidad,'
                   f'observacion,{snap_ins}) VALUES (?,?,?,?,?,?,?,{",".join("?" * len(SNAP_COLS))})',
                   (nuevo_id, mapa.get(d['id_mezcla']), d['orden_carga'], d['id_producto'], d['dosis'],
                    d['unidad'], d['observacion']) + snap)
    db.commit()
    flash(f'Ensayo duplicado como N° {nuevo_id:04d} (sin fotos). Revisá los datos y guardá.', 'success')
    return redirect(url_for('ensayo_editar', id=nuevo_id))


# ──────────────────────────────────────────────────────────
# PDF
# ──────────────────────────────────────────────────────────

def pdf(db, e):
    mezclas, generales = cargar_mezclas(db, e['id_ensayo'])
    from informe_comparativo import construir
    return construir(e, mezclas, generales, _app().UPLOAD_FOLDER)
