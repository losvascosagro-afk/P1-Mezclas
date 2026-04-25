import os
import io
from datetime import datetime
from flask import (Flask, render_template, request, redirect, url_for,
                   flash, jsonify, send_file, send_from_directory, g)
from werkzeug.utils import secure_filename
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                Paragraph, Spacer, Image, HRFlowable)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.utils import ImageReader

from db import get_db, close_db, init_db, BACKEND, BASE_DIR

# En Vercel el filesystem es efímero; usamos /tmp para uploads.
# Localmente se usa static/uploads/ (persistente y servido directamente).
IS_VERCEL = bool(os.environ.get('VERCEL'))
if IS_VERCEL:
    UPLOAD_FOLDER = '/tmp/uploads'
else:
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'tiff', 'tif', 'bmp', 'gif'}

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'mezclas_lab_2026_key')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024  # 32MB max

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


@app.teardown_appcontext
def teardown_db(e=None):
    close_db(e)



def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def _float_or_none(v):
    if v is None or v == '':
        return None
    try:
        return float(v)
    except Exception:
        return None


# Ruta para servir uploads (necesaria en Vercel donde /tmp no es static)
@app.route('/uploads/<path:filename>')
def serve_upload(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)


# ──────────────────────────────────────────────────────────
# DASHBOARD
# ──────────────────────────────────────────────────────────
@app.route('/')
def dashboard():
    db = get_db()
    stats = {
        'clientes': db.execute('SELECT COUNT(*) FROM clientes').fetchone()[0],
        'productos': db.execute('SELECT COUNT(*) FROM productos').fetchone()[0],
        'ensayos':   db.execute('SELECT COUNT(*) FROM ensayos').fetchone()[0],
        'estables':  db.execute(
            "SELECT COUNT(*) FROM ensayos WHERE LOWER(resultado_final) = 'estable'").fetchone()[0],
        'inestables': db.execute(
            "SELECT COUNT(*) FROM ensayos WHERE LOWER(resultado_final) = 'inestable'").fetchone()[0],
    }
    recientes = db.execute('''
        SELECT e.id_ensayo, e.fecha, e.resultado_final, e.objetivo,
               c.razon_social,
               (SELECT COUNT(*) FROM fotos_ensayo WHERE id_ensayo=e.id_ensayo) as fotos
        FROM ensayos e
        LEFT JOIN clientes c ON e.id_cliente = c.id_cliente
        ORDER BY e.fecha DESC, e.id_ensayo DESC LIMIT 10
    ''').fetchall()
    return render_template('dashboard.html', stats=stats, recientes=recientes)


# ──────────────────────────────────────────────────────────
# CLIENTES
# ──────────────────────────────────────────────────────────
@app.route('/clientes')
def clientes():
    db = get_db()
    q = request.args.get('q', '')
    if q:
        rows = db.execute(
            'SELECT * FROM clientes WHERE razon_social LIKE ? OR localidad LIKE ? '
            'OR provincia LIKE ? OR rubro LIKE ? ORDER BY razon_social',
            (f'%{q}%',) * 4).fetchall()
    else:
        rows = db.execute('SELECT * FROM clientes ORDER BY razon_social').fetchall()
    return render_template('clientes.html', clientes=rows, q=q)


@app.route('/clientes/nuevo', methods=['GET', 'POST'])
def cliente_nuevo():
    if request.method == 'POST':
        db = get_db()
        db.execute(
            'INSERT INTO clientes (razon_social,tecnico_responsable,cuit,condicion_iva,'
            'grupo,rubro,direccion,localidad,provincia) VALUES (?,?,?,?,?,?,?,?,?)',
            (request.form['razon_social'],
             request.form.get('tecnico_responsable') or None,
             request.form.get('cuit') or None,
             request.form.get('condicion_iva') or None,
             request.form.get('grupo') or None,
             request.form.get('rubro') or None,
             request.form.get('direccion') or None,
             request.form.get('localidad') or None,
             request.form.get('provincia') or None))
        db.commit()
        flash('Cliente agregado exitosamente.', 'success')
        return redirect(url_for('clientes'))
    return render_template('cliente_form.html', c=None, titulo='Nuevo Cliente')


@app.route('/clientes/<int:id>')
def cliente_detalle(id):
    db = get_db()
    c = db.execute('SELECT * FROM clientes WHERE id_cliente=?', (id,)).fetchone()
    if not c:
        flash('Cliente no encontrado.', 'danger')
        return redirect(url_for('clientes'))
    ensayos = db.execute(
        'SELECT * FROM ensayos WHERE id_cliente=? ORDER BY fecha DESC', (id,)).fetchall()
    return render_template('cliente_detalle.html', c=c, ensayos=ensayos)


@app.route('/clientes/<int:id>/editar', methods=['GET', 'POST'])
def cliente_editar(id):
    db = get_db()
    c = db.execute('SELECT * FROM clientes WHERE id_cliente=?', (id,)).fetchone()
    if not c:
        flash('Cliente no encontrado.', 'danger')
        return redirect(url_for('clientes'))
    if request.method == 'POST':
        db.execute(
            'UPDATE clientes SET razon_social=?,tecnico_responsable=?,cuit=?,condicion_iva=?,'
            'grupo=?,rubro=?,direccion=?,localidad=?,provincia=? WHERE id_cliente=?',
            (request.form['razon_social'],
             request.form.get('tecnico_responsable') or None,
             request.form.get('cuit') or None,
             request.form.get('condicion_iva') or None,
             request.form.get('grupo') or None,
             request.form.get('rubro') or None,
             request.form.get('direccion') or None,
             request.form.get('localidad') or None,
             request.form.get('provincia') or None, id))
        db.commit()
        flash('Cliente actualizado.', 'success')
        return redirect(url_for('cliente_detalle', id=id))
    return render_template('cliente_form.html', c=c, titulo='Editar Cliente')


@app.route('/clientes/<int:id>/eliminar', methods=['POST'])
def cliente_eliminar(id):
    db = get_db()
    n = db.execute('SELECT COUNT(*) FROM ensayos WHERE id_cliente=?', (id,)).fetchone()[0]
    if n:
        flash(f'No se puede eliminar: tiene {n} ensayo(s) asociado(s).', 'danger')
        return redirect(url_for('cliente_detalle', id=id))
    db.execute('DELETE FROM clientes WHERE id_cliente=?', (id,))
    db.commit()
    flash('Cliente eliminado.', 'success')
    return redirect(url_for('clientes'))


# ──────────────────────────────────────────────────────────
# PRODUCTOS
# ──────────────────────────────────────────────────────────
@app.route('/productos')
def productos():
    db = get_db()
    q = request.args.get('q', '')
    cat = request.args.get('categoria', '')
    sql = 'SELECT * FROM productos WHERE 1=1'
    params = []
    if q:
        sql += ' AND (nombre_comercial LIKE ? OR empresa LIKE ? OR principio_activo LIKE ?)'
        params.extend([f'%{q}%'] * 3)
    if cat:
        sql += ' AND categoria=?'
        params.append(cat)
    sql += ' ORDER BY nombre_comercial'
    rows = db.execute(sql, params).fetchall()
    cats = db.execute(
        'SELECT DISTINCT categoria FROM productos WHERE categoria IS NOT NULL ORDER BY categoria'
    ).fetchall()
    return render_template('productos.html', productos=rows, q=q, cat_sel=cat, categorias=cats)


@app.route('/productos/nuevo', methods=['GET', 'POST'])
def producto_nuevo():
    if request.method == 'POST':
        db = get_db()
        precio = _float_or_none(request.form.get('precio_unit_usd'))
        db.execute(
            'INSERT INTO productos (nombre_comercial,categoria,empresa,formulacion,'
            'principio_activo,unidad_medida,familia,precio_unit_usd) VALUES (?,?,?,?,?,?,?,?)',
            (request.form['nombre_comercial'],
             request.form.get('categoria') or None,
             request.form.get('empresa') or None,
             request.form.get('formulacion') or None,
             request.form.get('principio_activo') or None,
             request.form.get('unidad_medida') or 'L',
             request.form.get('familia') or None, precio))
        db.commit()
        flash('Producto agregado.', 'success')
        return redirect(url_for('productos'))
    return render_template('producto_form.html', p=None, titulo='Nuevo Producto')


@app.route('/productos/<int:id>/editar', methods=['GET', 'POST'])
def producto_editar(id):
    db = get_db()
    p = db.execute('SELECT * FROM productos WHERE id_producto=?', (id,)).fetchone()
    if not p:
        flash('Producto no encontrado.', 'danger')
        return redirect(url_for('productos'))
    if request.method == 'POST':
        precio = _float_or_none(request.form.get('precio_unit_usd'))
        db.execute(
            'UPDATE productos SET nombre_comercial=?,categoria=?,empresa=?,formulacion=?,'
            'principio_activo=?,unidad_medida=?,familia=?,precio_unit_usd=? WHERE id_producto=?',
            (request.form['nombre_comercial'],
             request.form.get('categoria') or None,
             request.form.get('empresa') or None,
             request.form.get('formulacion') or None,
             request.form.get('principio_activo') or None,
             request.form.get('unidad_medida') or 'L',
             request.form.get('familia') or None, precio, id))
        db.commit()
        flash('Producto actualizado.', 'success')
        return redirect(url_for('productos'))
    return render_template('producto_form.html', p=p, titulo='Editar Producto')


@app.route('/productos/<int:id>/eliminar', methods=['POST'])
def producto_eliminar(id):
    db = get_db()
    db.execute('DELETE FROM productos WHERE id_producto=?', (id,))
    db.commit()
    flash('Producto eliminado.', 'success')
    return redirect(url_for('productos'))


@app.route('/api/productos')
def api_productos():
    db = get_db()
    q = request.args.get('q', '')
    rows = db.execute(
        'SELECT id_producto,nombre_comercial,categoria,empresa,unidad_medida '
        'FROM productos WHERE nombre_comercial LIKE ? ORDER BY nombre_comercial LIMIT 30',
        (f'%{q}%',)).fetchall()
    return jsonify([dict(r) for r in rows])


# ──────────────────────────────────────────────────────────
# ENSAYOS
# ──────────────────────────────────────────────────────────
@app.route('/ensayos')
def ensayos():
    db = get_db()
    q = request.args.get('q', '')
    res = request.args.get('resultado', '')
    sql = '''
        SELECT e.*, c.razon_social,
               (SELECT COUNT(*) FROM fotos_ensayo WHERE id_ensayo=e.id_ensayo) AS fotos,
               (SELECT COUNT(*) FROM detalle_mezcla WHERE id_ensayo=e.id_ensayo) AS nproductos
        FROM ensayos e
        LEFT JOIN clientes c ON e.id_cliente=c.id_cliente
        WHERE 1=1
    '''
    params = []
    if q:
        sql += ' AND (c.razon_social LIKE ? OR e.objetivo LIKE ?)'
        params.extend([f'%{q}%'] * 2)
    if res:
        sql += ' AND LOWER(e.resultado_final) LIKE ?'
        params.append(f'%{res.lower()}%')
    sql += ' ORDER BY e.fecha DESC, e.id_ensayo DESC'
    rows = db.execute(sql, params).fetchall()
    return render_template('ensayos.html', ensayos=rows, q=q, res_sel=res)


@app.route('/ensayos/nuevo', methods=['GET', 'POST'])
def ensayo_nuevo():
    db = get_db()
    if request.method == 'POST':
        _insert_sql = (
            'INSERT INTO ensayos (fecha,id_cliente,objetivo,tipo_agua,ph,conductividad,'
            'dureza,volumen_simulado,temperatura,tiempo_observacion,resultado_final,'
            'recomendacion,espuma,precipitado,separacion_fases,redispersion,obs_microscopio)'
            ' VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)'
        )
        if BACKEND == 'postgres':
            _insert_sql += ' RETURNING id_ensayo'
        cur = db.execute(
            _insert_sql,
            (request.form.get('fecha') or datetime.now().strftime('%Y-%m-%d'),
             request.form.get('id_cliente') or None,
             request.form.get('objetivo') or None,
             request.form.get('tipo_agua') or None,
             _float_or_none(request.form.get('ph')),
             _float_or_none(request.form.get('conductividad')),
             _float_or_none(request.form.get('dureza')),
             _float_or_none(request.form.get('volumen_simulado')),
             _float_or_none(request.form.get('temperatura')),
             _float_or_none(request.form.get('tiempo_observacion')),
             request.form.get('resultado_final') or None,
             request.form.get('recomendacion') or None,
             request.form.get('espuma') or 'No',
             request.form.get('precipitado') or 'No',
             request.form.get('separacion_fases') or 'No',
             request.form.get('redispersion') or 'No',
             request.form.get('obs_microscopio') or None))
        eid = cur.lastrowid
        _save_detalles(db, eid, request.form)
        db.commit()
        flash('Ensayo creado exitosamente.', 'success')
        return redirect(url_for('ensayo_detalle', id=eid))
    clientes_list = db.execute('SELECT id_cliente,razon_social FROM clientes ORDER BY razon_social').fetchall()
    productos_list = db.execute('SELECT id_producto,nombre_comercial,categoria,empresa,unidad_medida FROM productos ORDER BY nombre_comercial').fetchall()
    return render_template('ensayo_form.html', e=None, clientes=clientes_list,
                           productos=productos_list, detalles=[], titulo='Nuevo Ensayo')


@app.route('/ensayos/<int:id>')
def ensayo_detalle(id):
    db = get_db()
    e = db.execute('''
        SELECT e.*, c.razon_social, c.tecnico_responsable, c.cuit,
               c.localidad, c.provincia, c.direccion
        FROM ensayos e LEFT JOIN clientes c ON e.id_cliente=c.id_cliente
        WHERE e.id_ensayo=?
    ''', (id,)).fetchone()
    if not e:
        flash('Ensayo no encontrado.', 'danger')
        return redirect(url_for('ensayos'))
    detalles = db.execute('''
        SELECT dm.*, p.nombre_comercial, p.categoria, p.empresa,
               p.formulacion, p.principio_activo
        FROM detalle_mezcla dm
        LEFT JOIN productos p ON dm.id_producto=p.id_producto
        WHERE dm.id_ensayo=? ORDER BY dm.orden_carga
    ''', (id,)).fetchall()
    fotos = db.execute(
        'SELECT * FROM fotos_ensayo WHERE id_ensayo=? ORDER BY fecha_carga', (id,)).fetchall()
    return render_template('ensayo_detalle.html', e=e, detalles=detalles, fotos=fotos)


@app.route('/ensayos/<int:id>/editar', methods=['GET', 'POST'])
def ensayo_editar(id):
    db = get_db()
    e = db.execute('SELECT * FROM ensayos WHERE id_ensayo=?', (id,)).fetchone()
    if not e:
        flash('Ensayo no encontrado.', 'danger')
        return redirect(url_for('ensayos'))
    if request.method == 'POST':
        db.execute(
            'UPDATE ensayos SET fecha=?,id_cliente=?,objetivo=?,tipo_agua=?,ph=?,'
            'conductividad=?,dureza=?,volumen_simulado=?,temperatura=?,tiempo_observacion=?,'
            'resultado_final=?,recomendacion=?,espuma=?,precipitado=?,'
            'separacion_fases=?,redispersion=?,obs_microscopio=? WHERE id_ensayo=?',
            (request.form.get('fecha'),
             request.form.get('id_cliente') or None,
             request.form.get('objetivo') or None,
             request.form.get('tipo_agua') or None,
             _float_or_none(request.form.get('ph')),
             _float_or_none(request.form.get('conductividad')),
             _float_or_none(request.form.get('dureza')),
             _float_or_none(request.form.get('volumen_simulado')),
             _float_or_none(request.form.get('temperatura')),
             _float_or_none(request.form.get('tiempo_observacion')),
             request.form.get('resultado_final') or None,
             request.form.get('recomendacion') or None,
             request.form.get('espuma') or 'No',
             request.form.get('precipitado') or 'No',
             request.form.get('separacion_fases') or 'No',
             request.form.get('redispersion') or 'No',
             request.form.get('obs_microscopio') or None, id))
        db.execute('DELETE FROM detalle_mezcla WHERE id_ensayo=?', (id,))
        _save_detalles(db, id, request.form)
        db.commit()
        flash('Ensayo actualizado.', 'success')
        return redirect(url_for('ensayo_detalle', id=id))
    clientes_list = db.execute('SELECT id_cliente,razon_social FROM clientes ORDER BY razon_social').fetchall()
    productos_list = db.execute('SELECT id_producto,nombre_comercial,categoria,empresa,unidad_medida FROM productos ORDER BY nombre_comercial').fetchall()
    detalles = db.execute(
        'SELECT dm.*,p.nombre_comercial FROM detalle_mezcla dm '
        'LEFT JOIN productos p ON dm.id_producto=p.id_producto '
        'WHERE dm.id_ensayo=? ORDER BY dm.orden_carga', (id,)).fetchall()
    return render_template('ensayo_form.html', e=e, clientes=clientes_list,
                           productos=productos_list, detalles=detalles, titulo='Editar Ensayo')


@app.route('/ensayos/<int:id>/eliminar', methods=['POST'])
def ensayo_eliminar(id):
    db = get_db()
    fotos = db.execute('SELECT nombre_archivo FROM fotos_ensayo WHERE id_ensayo=?', (id,)).fetchall()
    for f in fotos:
        p = os.path.join(UPLOAD_FOLDER, f['nombre_archivo'])
        if os.path.exists(p):
            os.remove(p)
    db.execute('DELETE FROM fotos_ensayo WHERE id_ensayo=?', (id,))
    db.execute('DELETE FROM detalle_mezcla WHERE id_ensayo=?', (id,))
    db.execute('DELETE FROM ensayos WHERE id_ensayo=?', (id,))
    db.commit()
    flash('Ensayo eliminado.', 'success')
    return redirect(url_for('ensayos'))


def _save_detalles(db, eid, form):
    pids = form.getlist('producto_id[]')
    ords = form.getlist('orden_carga[]')
    doss = form.getlist('dosis[]')
    unis = form.getlist('unidad[]')
    obss = form.getlist('det_obs[]')
    for i, pid in enumerate(pids):
        if pid:
            db.execute(
                'INSERT INTO detalle_mezcla (id_ensayo,orden_carga,id_producto,dosis,unidad,observacion)'
                ' VALUES (?,?,?,?,?,?)',
                (eid,
                 int(ords[i]) if i < len(ords) and ords[i] else i + 1,
                 int(pid),
                 _float_or_none(doss[i] if i < len(doss) else None),
                 unis[i] if i < len(unis) and unis[i] else 'L',
                 obss[i] if i < len(obss) and obss[i] else None))


# ──────────────────────────────────────────────────────────
# FOTOS
# ──────────────────────────────────────────────────────────
@app.route('/ensayos/<int:id>/foto', methods=['POST'])
def foto_upload(id):
    db = get_db()
    if 'foto' not in request.files:
        flash('No se seleccionó archivo.', 'danger')
        return redirect(url_for('ensayo_detalle', id=id))
    file = request.files['foto']
    if file.filename == '':
        flash('No se seleccionó archivo.', 'danger')
        return redirect(url_for('ensayo_detalle', id=id))
    if file and allowed_file(file.filename):
        ext = file.filename.rsplit('.', 1)[1].lower()
        fname = f"ens{id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{ext}"
        img_bytes = file.read()
        # Guardar en filesystem local (solo funciona localmente)
        try:
            with open(os.path.join(UPLOAD_FOLDER, fname), 'wb') as fh:
                fh.write(img_bytes)
        except Exception:
            pass
        db.execute(
            'INSERT INTO fotos_ensayo (id_ensayo,nombre_archivo,descripcion,fecha_carga,imagen_data)'
            ' VALUES (?,?,?,?,?)',
            (id, fname, request.form.get('descripcion', ''),
             datetime.now().strftime('%Y-%m-%d %H:%M'),
             img_bytes))
        db.commit()
        flash('Foto agregada.', 'success')
    else:
        flash('Formato no permitido. Use JPG, PNG, TIFF o BMP.', 'danger')
    return redirect(url_for('ensayo_detalle', id=id))


@app.route('/fotos/<int:fid>')
def foto_serve(fid):
    db = get_db()
    f = db.execute('SELECT nombre_archivo, imagen_data FROM fotos_ensayo WHERE id_foto=?', (fid,)).fetchone()
    if not f or not f['imagen_data']:
        return '', 404
    ext = (f['nombre_archivo'] or 'img.jpg').rsplit('.', 1)[-1].lower()
    mime = {'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png',
            'tiff': 'image/tiff', 'tif': 'image/tiff', 'bmp': 'image/bmp'}.get(ext, 'image/jpeg')
    data = bytes(f['imagen_data']) if not isinstance(f['imagen_data'], bytes) else f['imagen_data']
    return send_file(io.BytesIO(data), mimetype=mime)


@app.route('/fotos/<int:fid>/eliminar', methods=['POST'])
def foto_eliminar(fid):
    db = get_db()
    f = db.execute('SELECT * FROM fotos_ensayo WHERE id_foto=?', (fid,)).fetchone()
    if f:
        p = os.path.join(UPLOAD_FOLDER, f['nombre_archivo'])
        if os.path.exists(p):
            os.remove(p)
        db.execute('DELETE FROM fotos_ensayo WHERE id_foto=?', (fid,))
        db.commit()
        flash('Foto eliminada.', 'success')
        return redirect(url_for('ensayo_detalle', id=f['id_ensayo']))
    return redirect(url_for('ensayos'))


# ──────────────────────────────────────────────────────────
# GENERACIÓN DE PDF
# ──────────────────────────────────────────────────────────
@app.route('/ensayos/<int:id>/pdf')
def ensayo_pdf(id):
    db = get_db()
    e = db.execute('''
        SELECT e.*, c.razon_social, c.tecnico_responsable, c.cuit,
               c.localidad, c.provincia, c.direccion, c.condicion_iva
        FROM ensayos e LEFT JOIN clientes c ON e.id_cliente=c.id_cliente
        WHERE e.id_ensayo=?
    ''', (id,)).fetchone()
    if not e:
        flash('Ensayo no encontrado.', 'danger')
        return redirect(url_for('ensayos'))
    detalles = db.execute('''
        SELECT dm.*, p.nombre_comercial, p.categoria, p.empresa,
               p.formulacion, p.principio_activo, p.unidad_medida
        FROM detalle_mezcla dm
        LEFT JOIN productos p ON dm.id_producto=p.id_producto
        WHERE dm.id_ensayo=? ORDER BY dm.orden_carga
    ''', (id,)).fetchall()
    fotos = db.execute(
        'SELECT * FROM fotos_ensayo WHERE id_ensayo=? ORDER BY fecha_carga', (id,)).fetchall()
    buf = _build_pdf(e, detalles, fotos)
    fecha_str = (e['fecha'] or 'sin_fecha').replace('-', '')
    fname = f"Informe_Mezcla_{id:04d}_{fecha_str}.pdf"
    return send_file(buf, mimetype='application/pdf', as_attachment=True, download_name=fname)


def _build_pdf(e, detalles, fotos):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            rightMargin=1.8*cm, leftMargin=1.8*cm,
                            topMargin=1.8*cm, bottomMargin=1.8*cm)

    C_TEAL    = colors.HexColor('#1A7A7A')   # verde DMA Agro
    C_TEAL_LT = colors.HexColor('#E6F5F5')   # teal muy claro para fondos alternos
    C_DARK    = colors.HexColor('#2D2D2D')   # casi negro para encabezados de tabla
    C_LGRAY   = colors.HexColor('#F5F5F5')
    C_WHITE   = colors.white
    C_RED     = colors.HexColor('#C62828')
    C_BLACK   = colors.black

    LAB_NAME  = 'Laboratorio de Análisis de Compatibilidad de Agroquímicos y Calidad de Agua'
    LOGO_PATH = os.path.join(BASE_DIR, 'LOGO ORIGINAL.png')

    resultado = str(e['resultado_final'] or '').strip()
    estable = 'inestable' not in resultado.lower() and 'estable' in resultado.lower()
    C_RESULT = C_TEAL if estable else C_RED

    def sty(name='body', **kw):
        base = {
            'body':    dict(fontName='Helvetica', fontSize=9, textColor=C_BLACK, spaceAfter=2),
            'label':   dict(fontName='Helvetica-Bold', fontSize=9, textColor=C_DARK),
            'th':      dict(fontName='Helvetica-Bold', fontSize=9, textColor=C_WHITE),
            'thc':     dict(fontName='Helvetica-Bold', fontSize=9, textColor=C_WHITE, alignment=TA_CENTER),
            'center':  dict(fontName='Helvetica', fontSize=9, alignment=TA_CENTER),
            'title':   dict(fontName='Helvetica-Bold', fontSize=13, textColor=C_WHITE, alignment=TA_LEFT),
            'sub':     dict(fontName='Helvetica', fontSize=10, textColor=C_WHITE, alignment=TA_LEFT),
            'footer':  dict(fontName='Helvetica', fontSize=7, textColor=colors.gray, alignment=TA_CENTER),
            'caption': dict(fontName='Helvetica', fontSize=8, textColor=colors.gray, alignment=TA_CENTER),
            'obs':     dict(fontName='Helvetica', fontSize=9, textColor=C_BLACK, leading=14),
        }
        d = {**base.get(name, base['body']), **kw}
        return ParagraphStyle(f'S_{name}_{id(kw)}', **d)

    def sec(text, bg=None):
        bg = bg or C_TEAL
        t = Table([[Paragraph(text, sty('label', textColor=C_WHITE, fontSize=10, leftIndent=6))]], colWidths=[17.4*cm])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0),(-1,-1), bg),
            ('TOPPADDING', (0,0),(-1,-1), 5),
            ('BOTTOMPADDING', (0,0),(-1,-1), 5),
        ]))
        return t

    story = []

    # ── HEADER: teal izquierda (texto) + blanco derecha (logo) ──
    title_col = [
        Paragraph(LAB_NAME.upper(), sty('title')),
        Spacer(1, 4),
        Paragraph(f'INFORME DE ENSAYO  N° {e["id_ensayo"]:04d}', sty('sub')),
    ]
    logo_cell = Spacer(1, 1)
    if os.path.exists(LOGO_PATH):
        try:
            ir = ImageReader(LOGO_PATH)
            iw, ih = ir.getSize()
            logo_w = 3.8 * cm
            logo_h = logo_w * ih / iw
            logo_img = Image(LOGO_PATH, width=logo_w, height=logo_h)
            logo_img.hAlign = 'CENTER'
            logo_cell = logo_img
        except Exception:
            pass

    hdr = Table([[title_col, logo_cell]], colWidths=[12.4*cm, 5.0*cm])
    hdr.setStyle(TableStyle([
        ('BACKGROUND', (0,0),(0,-1), C_TEAL),
        ('BACKGROUND', (1,0),(1,-1), C_WHITE),
        ('TOPPADDING', (0,0),(-1,-1), 12),
        ('BOTTOMPADDING', (0,0),(-1,-1), 10),
        ('LEFTPADDING', (0,0),(0,-1), 10),
        ('RIGHTPADDING', (-1,0),(-1,-1), 8),
        ('VALIGN', (0,0),(-1,-1), 'MIDDLE'),
        ('BOX', (0,0),(-1,-1), 0.5, C_TEAL),
    ]))
    story += [hdr, Spacer(1, 8)]

    # ── DATE / RESULT BAR ──
    bar = Table([[
        Paragraph(f'<b>Fecha:</b>  {e["fecha"] or "—"}', sty()),
        Paragraph(f'<b>Objetivo:</b>  {e["objetivo"] or "—"}', sty()),
        Paragraph(f'<font color="white"><b>  {resultado.upper() or "SIN RESULTADO"}  </b></font>',
                  sty('center', textColor=C_WHITE)),
    ]], colWidths=[4*cm, 9.4*cm, 4*cm])
    bar.setStyle(TableStyle([
        ('BACKGROUND', (0,0),(1,0), C_TEAL_LT),
        ('BACKGROUND', (2,0),(2,0), C_RESULT),
        ('VALIGN', (0,0),(-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0),(-1,-1), 7), ('BOTTOMPADDING', (0,0),(-1,-1), 7),
        ('LEFTPADDING', (0,0),(-1,-1), 8), ('RIGHTPADDING', (0,0),(-1,-1), 8),
        ('BOX', (0,0),(-1,-1), 0.5, colors.lightgrey),
        ('INNERGRID', (0,0),(-1,-1), 0.5, colors.lightgrey),
    ]))
    story += [bar, Spacer(1, 8)]

    # ── CLIENTE ──
    story.append(sec('DATOS DEL CLIENTE'))
    cli = Table([
        [Paragraph('Razón Social:', sty('label')), Paragraph(e['razon_social'] or '—', sty()),
         Paragraph('Técnico:', sty('label')), Paragraph(e['tecnico_responsable'] or '—', sty())],
        [Paragraph('C.U.I.T.:', sty('label')), Paragraph(e['cuit'] or '—', sty()),
         Paragraph('Localidad:', sty('label')),
         Paragraph(f"{e['localidad'] or '—'}, {e['provincia'] or ''}", sty())],
    ], colWidths=[3*cm, 5.7*cm, 2.7*cm, 6*cm])
    cli.setStyle(TableStyle([
        ('ROWBACKGROUNDS', (0,0),(-1,-1), [C_WHITE, C_LGRAY]),
        ('TOPPADDING', (0,0),(-1,-1), 5), ('BOTTOMPADDING', (0,0),(-1,-1), 5),
        ('LEFTPADDING', (0,0),(-1,-1), 6), ('RIGHTPADDING', (0,0),(-1,-1), 6),
        ('BOX', (0,0),(-1,-1), 0.5, colors.lightgrey),
        ('INNERGRID', (0,0),(-1,-1), 0.3, colors.lightgrey),
    ]))
    story += [cli, Spacer(1, 7)]

    # ── CONDICIONES ──
    story.append(sec('CONDICIONES DEL ENSAYO'))
    cond = Table([
        [Paragraph('Tipo de Agua', sty('label')), Paragraph(e['tipo_agua'] or '—', sty()),
         Paragraph('pH', sty('label')), Paragraph(str(e['ph'] or '—'), sty()),
         Paragraph('Conductividad (µS/cm)', sty('label')), Paragraph(str(e['conductividad'] or '—'), sty())],
        [Paragraph('Dureza (mg/L CaCO₃)', sty('label')), Paragraph(str(e['dureza'] or '—'), sty()),
         Paragraph('Volumen (L)', sty('label')), Paragraph(str(e['volumen_simulado'] or '—'), sty()),
         Paragraph('Temperatura (°C)', sty('label')), Paragraph(str(e['temperatura'] or '—'), sty())],
        [Paragraph('Tiempo Obs. (h)', sty('label')), Paragraph(str(e['tiempo_observacion'] or '—'), sty()),
         Paragraph('', sty()), Paragraph('', sty()),
         Paragraph('', sty()), Paragraph('', sty())],
    ], colWidths=[3.8*cm, 2.4*cm, 1.4*cm, 1.8*cm, 4*cm, 4*cm])
    cond.setStyle(TableStyle([
        ('ROWBACKGROUNDS', (0,0),(-1,-1), [C_WHITE, C_LGRAY, C_WHITE]),
        ('TOPPADDING', (0,0),(-1,-1), 5), ('BOTTOMPADDING', (0,0),(-1,-1), 5),
        ('LEFTPADDING', (0,0),(-1,-1), 6), ('RIGHTPADDING', (0,0),(-1,-1), 6),
        ('BOX', (0,0),(-1,-1), 0.5, colors.lightgrey),
        ('INNERGRID', (0,0),(-1,-1), 0.3, colors.lightgrey),
    ]))
    story += [cond, Spacer(1, 7)]

    # ── COMPOSICIÓN DE LA MEZCLA ──
    story.append(sec('COMPOSICIÓN DE LA MEZCLA'))
    if detalles:
        mhdr = [Paragraph(t, sty('thc')) for t in ['#', 'Producto', 'Categoría', 'Empresa', 'Principio Activo', 'Dosis', 'Ud.']]
        mrows = [mhdr]
        for i, d in enumerate(detalles):
            mrows.append([
                Paragraph(str(d['orden_carga'] or i+1), sty('center')),
                Paragraph(d['nombre_comercial'] or '—', sty()),
                Paragraph(d['categoria'] or '—', sty()),
                Paragraph(d['empresa'] or '—', sty()),
                Paragraph(d['principio_activo'] or '—', sty()),
                Paragraph(str(d['dosis'] or '—'), sty('center')),
                Paragraph(d['unidad'] or 'L', sty('center')),
            ])
        mt = Table(mrows, colWidths=[1*cm, 3.7*cm, 2.5*cm, 2.5*cm, 4.2*cm, 1.8*cm, 1.7*cm])
        ms = [
            ('BACKGROUND', (0,0),(-1,0), C_DARK),
            ('TOPPADDING', (0,0),(-1,-1), 4), ('BOTTOMPADDING', (0,0),(-1,-1), 4),
            ('LEFTPADDING', (0,0),(-1,-1), 5), ('RIGHTPADDING', (0,0),(-1,-1), 5),
            ('BOX', (0,0),(-1,-1), 0.5, colors.lightgrey),
            ('INNERGRID', (0,0),(-1,-1), 0.3, colors.lightgrey),
            ('VALIGN', (0,0),(-1,-1), 'MIDDLE'),
        ]
        for i in range(1, len(mrows)):
            if i % 2 == 0:
                ms.append(('BACKGROUND', (0,i),(-1,i), C_TEAL_LT))
        mt.setStyle(TableStyle(ms))
        story.append(mt)
    else:
        story.append(Paragraph('Sin productos registrados.', sty()))
    story.append(Spacer(1, 7))

    # ── OBSERVACIONES VISUALES ──
    story.append(sec('OBSERVACIONES VISUALES'))

    def ind(val):
        v = str(val or 'No').strip()
        bg = C_RED if v.lower() in ('si', 'sí') else C_TEAL
        return Paragraph(f'<font color="white"><b> {v.upper()} </b></font>',
                         sty('center', textColor=C_WHITE, fontName='Helvetica-Bold', fontSize=9))

    ov = Table([
        [Paragraph('Parámetro', sty('th')), Paragraph('Resultado', sty('thc')),
         Paragraph('Parámetro', sty('th')), Paragraph('Resultado', sty('thc'))],
        [Paragraph('Espuma', sty('label')), ind(e['espuma']),
         Paragraph('Precipitado', sty('label')), ind(e['precipitado'])],
        [Paragraph('Separación de Fases', sty('label')), ind(e['separacion_fases']),
         Paragraph('Redispersión', sty('label')), ind(e['redispersion'])],
    ], colWidths=[5*cm, 3.7*cm, 5*cm, 3.7*cm])

    def _obs_bg(val):
        return C_RED if str(val or '').lower() in ('si', 'sí') else C_TEAL

    ov.setStyle(TableStyle([
        ('BACKGROUND', (0,0),(-1,0), C_DARK),
        ('ROWBACKGROUNDS', (0,1),(-1,-1), [C_WHITE, C_LGRAY]),
        ('BACKGROUND', (1,1),(1,1), _obs_bg(e['espuma'])),
        ('BACKGROUND', (3,1),(3,1), _obs_bg(e['precipitado'])),
        ('BACKGROUND', (1,2),(1,2), _obs_bg(e['separacion_fases'])),
        ('BACKGROUND', (3,2),(3,2), _obs_bg(e['redispersion'])),
        ('TOPPADDING', (0,0),(-1,-1), 6), ('BOTTOMPADDING', (0,0),(-1,-1), 6),
        ('LEFTPADDING', (0,0),(-1,-1), 8), ('RIGHTPADDING', (0,0),(-1,-1), 8),
        ('BOX', (0,0),(-1,-1), 0.5, colors.lightgrey),
        ('INNERGRID', (0,0),(-1,-1), 0.3, colors.lightgrey),
        ('VALIGN', (0,0),(-1,-1), 'MIDDLE'),
    ]))
    story += [ov, Spacer(1, 7)]

    # ── CONCLUSIÓN ──
    story.append(sec('CONCLUSIÓN Y RECOMENDACIÓN', bg=C_RESULT))
    conc = Table([
        [Paragraph('Resultado Final:', sty('label')),
         Paragraph(f'<font color="white"><b>  {resultado.upper() or "—"}  </b></font>',
                   sty('center', textColor=C_WHITE, fontName='Helvetica-Bold', fontSize=10))],
        [Paragraph('Recomendación:', sty('label')),
         Paragraph(e['recomendacion'] or '—', sty())],
    ], colWidths=[3.5*cm, 13.9*cm])
    conc.setStyle(TableStyle([
        ('BACKGROUND', (1,0),(1,0), C_RESULT),
        ('ROWBACKGROUNDS', (0,0),(0,-1), [C_TEAL_LT, C_WHITE]),
        ('ROWBACKGROUNDS', (1,1),(1,1), [C_WHITE]),
        ('TOPPADDING', (0,0),(-1,-1), 7), ('BOTTOMPADDING', (0,0),(-1,-1), 7),
        ('LEFTPADDING', (0,0),(-1,-1), 8), ('RIGHTPADDING', (0,0),(-1,-1), 8),
        ('BOX', (0,0),(-1,-1), 0.5, colors.lightgrey),
        ('INNERGRID', (0,0),(-1,-1), 0.3, colors.lightgrey),
        ('VALIGN', (0,0),(-1,-1), 'TOP'),
    ]))
    story += [conc, Spacer(1, 7)]

    # ── MICROSCOPÍA ──
    if e['obs_microscopio']:
        story.append(sec('OBSERVACIONES AL MICROSCOPIO'))
        mic = Table([[Paragraph(e['obs_microscopio'], sty('obs'))]], colWidths=[17.4*cm])
        mic.setStyle(TableStyle([
            ('BACKGROUND', (0,0),(-1,-1), C_TEAL_LT),
            ('TOPPADDING', (0,0),(-1,-1), 8), ('BOTTOMPADDING', (0,0),(-1,-1), 8),
            ('LEFTPADDING', (0,0),(-1,-1), 10), ('RIGHTPADDING', (0,0),(-1,-1), 10),
            ('BOX', (0,0),(-1,-1), 0.5, colors.lightgrey),
        ]))
        story += [mic, Spacer(1, 7)]

    # ── FOTOS ──
    if fotos:
        story.append(sec('IMÁGENES DE MICROSCOPÍA'))
        foto_pairs = [fotos[i:i+2] for i in range(0, len(fotos), 2)]
        for pair in foto_pairs:
            cells = []
            for foto in pair:
                cell = []
                img_data = foto['imagen_data']
                if img_data:
                    try:
                        raw = bytes(img_data) if not isinstance(img_data, bytes) else img_data
                        img = Image(io.BytesIO(raw), width=7.8*cm, height=5.8*cm)
                        img.hAlign = 'CENTER'
                        cell.append(img)
                    except Exception:
                        cell.append(Paragraph('[Imagen no disponible]', sty()))
                else:
                    fp = os.path.join(UPLOAD_FOLDER, foto['nombre_archivo'])
                    if os.path.exists(fp):
                        try:
                            img = Image(fp, width=7.8*cm, height=5.8*cm)
                            img.hAlign = 'CENTER'
                            cell.append(img)
                        except Exception:
                            cell.append(Paragraph('[Imagen no disponible]', sty()))
                    else:
                        cell.append(Paragraph('[Imagen no disponible]', sty()))
                if foto['descripcion']:
                    cell.append(Paragraph(foto['descripcion'], sty('caption')))
                cells.append(cell)
            while len(cells) < 2:
                cells.append([Spacer(0.1, 0.1)])
            ft = Table([cells], colWidths=[8.7*cm, 8.7*cm])
            ft.setStyle(TableStyle([
                ('VALIGN', (0,0),(-1,-1), 'TOP'),
                ('ALIGN', (0,0),(-1,-1), 'CENTER'),
                ('TOPPADDING', (0,0),(-1,-1), 6), ('BOTTOMPADDING', (0,0),(-1,-1), 6),
                ('LEFTPADDING', (0,0),(-1,-1), 6), ('RIGHTPADDING', (0,0),(-1,-1), 6),
                ('BOX', (0,0),(-1,-1), 0.3, colors.lightgrey),
                ('INNERGRID', (0,0),(-1,-1), 0.3, colors.lightgrey),
            ]))
            story.append(ft)
        story.append(Spacer(1, 8))

    # ── FIRMAS ──
    story.append(Spacer(1, 12))
    firma_path = os.path.join(BASE_DIR, 'Firma_DMA_SinFondo-ok.jpg')
    if not os.path.exists(firma_path):
        firma_path = os.path.join(BASE_DIR, 'static', 'firma_dma.jpg')

    def _sig_cell(with_firma):
        cell = []
        if with_firma and os.path.exists(firma_path):
            try:
                ir = ImageReader(firma_path)
                fw, fh = ir.getSize()
                target_w = 1.8 * cm
                target_h = target_w * fh / fw
                fi = Image(firma_path, width=target_w, height=target_h)
                fi.hAlign = 'CENTER'
                cell.append(fi)
            except Exception:
                cell.append(Spacer(1, 1.8*cm))
        else:
            cell.append(Spacer(1, 1.8*cm))
        cell.append(HRFlowable(width='85%', thickness=0.5, color=colors.gray, hAlign='CENTER'))
        cell.append(Paragraph(
            'Director de Laboratorio' if with_firma else 'Técnico Responsable',
            sty('center', textColor=colors.gray, fontSize=8)))
        return cell

    sig = Table([[_sig_cell(False), _sig_cell(True)]], colWidths=[8.7*cm, 8.7*cm])
    sig.setStyle(TableStyle([
        ('TOPPADDING', (0,0),(-1,-1), 4), ('BOTTOMPADDING', (0,0),(-1,-1), 4),
        ('VALIGN', (0,0),(-1,-1), 'BOTTOM'),
    ]))
    story.append(sig)
    story.append(Spacer(1, 10))

    # ── FOOTER ──
    story.append(HRFlowable(width='100%', thickness=0.5, color=C_TEAL))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        f'Informe generado el {datetime.now().strftime("%d/%m/%Y a las %H:%M")}  ·  '
        f'{LAB_NAME}  ·  Informe N° {e["id_ensayo"]:04d}',
        sty('footer')))

    doc.build(story)
    buf.seek(0)
    return buf


if __name__ == '__main__':
    init_db()
    print()
    print("=" * 55)
    print("  Laboratorio de Análisis de Compatibilidad de Agroquímicos")
    print("  Abrir en el navegador: http://localhost:5000")
    print("=" * 55)
    print()
    app.run(debug=False, host='127.0.0.1', port=5000)
