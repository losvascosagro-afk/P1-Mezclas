"""
Métricas de las mezclas evaluadas.

La unidad es la MEZCLA, igual que en el dashboard: cada ensayo simple es una
mezcla, y cada comparativo aporta todas las suyas (mezclas_ensayo). Los
productos de cada mezcla se leen de la copia congelada (detalle_mezcla.snap_*),
así las métricas muestran lo que realmente se ensayó.

Sólo lee: no cambia ningún dato.
"""
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime

from flask import Blueprint, render_template, request

from db import get_db

bp = Blueprint('metricas', __name__)


@bp.app_template_filter('fecha_ar')
def fecha_ar(v):
    """'2026-06-02' → '02/06/2026'."""
    v = str(v or '')[:10]
    return f'{v[8:10]}/{v[5:7]}/{v[:4]}' if len(v) == 10 else (v or '—')

MESES = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']
RESULTADOS = ['Estable', 'Estable con observaciones', 'Inestable', 'Requiere más ensayos']
OBS = [('espuma', 'Espuma'), ('precipitado', 'Precipitado'),
       ('separacion_fases', 'Separación de fases'), ('redispersion', 'Redispersión')]
# Valores que NO son un problema. "No" en redispersión (datos viejos) = sin problema.
_SIN_PROBLEMA = {'', 'no', 'no aplica', 'total'}
MIN_APARICIONES = 5   # para porcentajes por producto/formulación: menos que esto no dice nada


def _resultado(v):
    v = (v or '').strip()
    for r in RESULTADOS:
        if v.lower() == r.lower():
            return r
    return 'Sin resultado'


def _grado(v):
    """Texto del grado de una observación con problema, o None si no hay problema."""
    v = (v or '').strip()
    if v.lower() in _SIN_PROBLEMA:
        return None
    return 'Sí (sin grado)' if v.lower() in ('si', 'sí') else v


def _mezclas(db, desde=None, hasta=None):
    """Lista de mezclas: dict con fecha, cliente, resultado, observaciones y productos."""
    cond, params = '', []
    if desde:
        cond, params = ' AND e.fecha >= ? AND e.fecha < ?', [desde, hasta]
    simples = db.execute(f'''
        SELECT e.id_ensayo, NULL, e.fecha, e.id_cliente, c.razon_social, e.resultado_final, {', '.join('e.' + c for c, _ in OBS)},
               c.localidad, c.provincia
        FROM ensayos e LEFT JOIN clientes c ON c.id_cliente = e.id_cliente
        WHERE COALESCE(e.tipo, '') <> 'comparativo'{cond}''', params).fetchall()
    comparadas = db.execute(f'''
        SELECT e.id_ensayo, m.id_mezcla, e.fecha, e.id_cliente, c.razon_social, m.resultado_final, {', '.join('m.' + c for c, _ in OBS)},
               c.localidad, c.provincia
        FROM mezclas_ensayo m JOIN ensayos e ON e.id_ensayo = m.id_ensayo
        LEFT JOIN clientes c ON c.id_cliente = e.id_cliente
        WHERE e.tipo = 'comparativo'{cond}''', params).fetchall()

    productos = defaultdict(list)   # (id_ensayo, id_mezcla o None) → productos
    for r in db.execute('''SELECT id_ensayo, id_mezcla, snap_nombre, snap_categoria, snap_formulacion, snap_empresa
                           FROM detalle_mezcla ORDER BY id_ensayo, orden_carga''').fetchall():
        productos[(r[0], r[1])].append({
            'nombre': (r[2] or '').strip() or '(sin nombre)',
            'categoria': (r[3] or '').strip().upper() or 'SIN CATEGORÍA',
            'formulacion': _formulacion(r[4]),
            'empresa': _norm(r[5]) or 'SIN DATO',
        })

    out = []
    for r in list(simples) + list(comparadas):
        out.append({
            'id_ensayo': r[0], 'fecha': str(r[2] or ''), 'id_cliente': r[3],
            'cliente': (r[4] or '').strip() or '(sin cliente)',
            'resultado': _resultado(r[5]),
            'obs': {c: _grado(r[6 + i]) for i, (c, _) in enumerate(OBS)},
            'productos': productos.get((r[0], r[1]), []),
            'localidad': _norm(r[10]), 'provincia': _provincia(r[11]),
        })
    return out


def _norm(v):
    """Mayúscula, sin tildes ni espacios de más: 'Atanor' y 'ATANOR' cuentan juntas."""
    v = unicodedata.normalize('NFKD', str(v or '')).encode('ascii', 'ignore').decode()
    return ' '.join(v.upper().split())


def _provincia(v):
    v = _norm(v)
    return {'CABA': 'CABA', 'CAPITAL FEDERAL': 'CABA', 'CIUDAD DE BUENOS AIRES': 'CABA'}.get(v, v)


def _formulacion(v):
    """Código de formulación: 'WP (POLVO MOJABLE)' → 'WP'."""
    v = (v or '').strip().upper()
    return v.split(' ')[0].split('(')[0] if v else 'SIN DATO'


def _pct(a, b):
    return round(100 * a / b) if b else 0


def _ranking(mezclas, clave, top=None):
    """Por cada valor de `clave` (función mezcla → set de valores): en cuántas
    mezclas aparece y cuántas de esas no fueron estables."""
    veces, problemas, inestables = Counter(), Counter(), Counter()
    for m in mezclas:
        for v in clave(m):
            veces[v] += 1
            if m['resultado'] != 'Estable':
                problemas[v] += 1
            if m['resultado'] == 'Inestable':
                inestables[v] += 1
    filas = [{'nombre': v, 'veces': n, 'problemas': problemas[v], 'inestables': inestables[v],
              'pct_problemas': _pct(problemas[v], n), 'pct_inestables': _pct(inestables[v], n),
              'pct_mezclas': _pct(n, len(mezclas))}
             for v, n in veces.most_common()]
    return filas[:top] if top else filas


def _por_cliente(mezclas, primeras):
    """Una fila por empresa cliente: consultas (ensayos), mezclas, resultados y fechas."""
    g = defaultdict(list)
    for m in mezclas:
        if m['id_cliente']:
            g[m['id_cliente']].append(m)
    filas = []
    for cid, ms in g.items():
        fechas = sorted(m['fecha'][:10] for m in ms if m['fecha'])
        estables = sum(1 for m in ms if m['resultado'] == 'Estable')
        filas.append({
            'id': cid, 'nombre': ms[0]['cliente'], 'zona': ms[0]['localidad'] or ms[0]['provincia'],
            'consultas': len({m['id_ensayo'] for m in ms}),
            'dias': len(set(fechas)), 'mezclas': len(ms),
            'pct_estable': _pct(estables, len(ms)), 'no_estables': len(ms) - estables,
            'primera': fechas[0] if fechas else '', 'ultima': fechas[-1] if fechas else '',
            'cliente_desde': primeras.get(cid, ''),
        })
    filas.sort(key=lambda f: (-f['consultas'], -f['mezclas'], f['nombre']))
    return filas


def calcular(mezclas, primeras=None, desde=None):
    total = len(mezclas)
    res = Counter(m['resultado'] for m in mezclas)

    # Por mes (orden cronológico)
    por_mes = defaultdict(Counter)
    for m in mezclas:
        if len(m['fecha']) >= 7:
            por_mes[m['fecha'][:7]][m['resultado']] += 1
    meses = [{'clave': k, 'etiqueta': f"{MESES[int(k[5:7]) - 1]} {k[2:4]}",
              'total': sum(c.values()), 'res': dict(c)} for k, c in sorted(por_mes.items())]
    max_mes = max((x['total'] for x in meses), default=0)

    # Según cantidad de productos
    grupos = [('2 o menos', lambda n: n <= 2), ('3', lambda n: n == 3), ('4', lambda n: n == 4),
              ('5', lambda n: n == 5), ('6', lambda n: n == 6), ('7 o más', lambda n: n >= 7)]
    por_cant = []
    for etiqueta, f in grupos:
        g = [m for m in mezclas if f(len(m['productos']))]
        if g:
            c = Counter(m['resultado'] for m in g)
            por_cant.append({'etiqueta': etiqueta, 'total': len(g), 'res': dict(c),
                             'pct_problemas': _pct(len(g) - c['Estable'], len(g))})
    n_prod = [len(m['productos']) for m in mezclas if m['productos']]

    # Observaciones visuales
    obs = []
    for campo, etiqueta in OBS:
        grados = Counter(m['obs'][campo] for m in mezclas if m['obs'][campo])
        n = sum(grados.values())
        obs.append({'etiqueta': etiqueta, 'veces': n, 'pct': _pct(n, total),
                    'grados': grados.most_common()})

    productos = _ranking(mezclas, lambda m: {p['nombre'].upper() for p in m['productos']})
    formulaciones = _ranking(mezclas, lambda m: {p['formulacion'] for p in m['productos']})
    categorias = _ranking(mezclas, lambda m: {p['categoria'] for p in m['productos']})
    adyuvantes = _ranking(mezclas, lambda m: {p['nombre'].upper() for p in m['productos']
                                              if p['categoria'] == 'ADYUVANTE'})
    con_ady = sum(1 for m in mezclas if any(p['categoria'] == 'ADYUVANTE' for p in m['productos']))

    # Productos cuyas mezclas salen no estables más seguido que el promedio.
    # Por porcentaje (no por cantidad, que castiga a los más usados) y con un
    # mínimo de apariciones para que el porcentaje signifique algo.
    pct_general = _pct(total - res['Estable'], total)
    alertas = sorted((p for p in productos if p['veces'] >= MIN_APARICIONES and p['pct_problemas'] > pct_general),
                     key=lambda p: (-p['pct_problemas'], -p['veces']))[:15]

    # Harrier Bio (producto propio): sus mezclas contra el resto
    def _tasa(g):
        return {'n': len(g), 'pct_estable': _pct(sum(1 for m in g if m['resultado'] == 'Estable'), len(g))}
    tiene_hb = [any('HARRIER' in p['nombre'].upper() for p in m['productos']) for m in mezclas]
    con_hb = [m for m, t in zip(mezclas, tiene_hb) if t]
    sin_hb = [m for m, t in zip(mezclas, tiene_hb) if not t]
    harrier = {'con': _tasa(con_hb), 'sin': _tasa(sin_hb), 'pct_mezclas': _pct(len(con_hb), total)}

    clientes = _por_cliente(mezclas, primeras or {})
    nuevos = [c for c in clientes if desde and c['cliente_desde'] and c['cliente_desde'] >= desde]
    volvieron = [c for c in clientes if c['dias'] > 1]
    provincias = Counter(m['provincia'] or 'SIN DATO' for m in mezclas).most_common()
    localidades = Counter(m['localidad'] for m in mezclas if m['localidad']).most_common(10)
    fabricantes = _ranking(mezclas, lambda m: {p['empresa'] for p in m['productos']})

    return {
        'total': total, 'res': res,
        'pct': {r: _pct(res[r], total) for r in RESULTADOS + ['Sin resultado']},
        'ensayos': len({m['id_ensayo'] for m in mezclas}),
        'clientes_n': len({m['id_cliente'] for m in mezclas if m['id_cliente']}),
        'prom_productos': round(sum(n_prod) / len(n_prod), 1) if n_prod else 0,
        'meses': meses, 'max_mes': max_mes,
        'por_cant': por_cant, 'obs': obs,
        'productos': productos[:15],
        'formulaciones': [f for f in formulaciones if f['veces'] >= MIN_APARICIONES],
        'formulaciones_pocas': [f['nombre'] for f in formulaciones if f['veces'] < MIN_APARICIONES],
        'categorias': categorias,
        'adyuvantes': adyuvantes[:10], 'con_ady': con_ady, 'pct_con_ady': _pct(con_ady, total),
        'alertas': alertas, 'pct_general': pct_general, 'harrier': harrier,
        'clientes': clientes, 'max_consultas': max((c['consultas'] for c in clientes), default=0),
        'nuevos': len(nuevos), 'volvieron': len(volvieron),
        'pct_volvieron': _pct(len(volvieron), len(clientes)),
        'prom_mezclas_cliente': round(total / len(clientes), 1) if clientes else 0,
        'provincias': provincias, 'localidades': localidades,
        'max_loc': localidades[0][1] if localidades else 0,
        'fabricantes': fabricantes[:15],
    }


@bp.route('/metricas')
def index():
    from app import campanas_disponibles, campana_rango, campana_etiqueta
    db = get_db()
    campanas = campanas_disponibles(db)
    sel = request.args.get('campana', 'todas')
    campana = int(sel) if sel.isdigit() and int(sel) in campanas else None
    desde, hasta = campana_rango(campana) if campana is not None else (None, None)
    primeras = {r[0]: str(r[1] or '')[:10] for r in db.execute(
        "SELECT id_cliente, MIN(fecha) FROM ensayos WHERE id_cliente IS NOT NULL GROUP BY id_cliente").fetchall()}
    m = calcular(_mezclas(db, desde, hasta), primeras, desde)
    return render_template('metricas.html', m=m, campana=campana,
                           campanas=[(c, campana_etiqueta(c)) for c in campanas],
                           periodo=f'Campaña {campana_etiqueta(campana)}' if campana is not None else 'Desde el inicio',
                           min_apariciones=MIN_APARICIONES, resultados=RESULTADOS,
                           hoy=datetime.now().strftime('%d/%m/%Y'))
