"""
Arma el plan de carga del catálogo SENASA (data/senasa_carga.json).

Lee:
  - SENASA_formulados_<fecha>.xlsx      base del registro SENASA
  - Productos_a_agregar_SENASA_v2.xlsx  decisiones revisadas a mano (hoja REVISAR, columna INCLUIR)
  - mezclas.db                          productos de la app (ids y nombres esperados)

No modifica ninguna base: sólo escribe el JSON. Lo aplica scripts/cargar_senasa.py.

Uso:  python scripts/armar_carga_senasa.py
"""
import json
import os
import re
import sqlite3
import sys
import unicodedata
from datetime import date

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SENASA_XLSX = os.path.join(ROOT, 'SENASA_formulados_2026-10-06.xlsx')
REVISION_XLSX = os.path.join(ROOT, 'Productos_a_agregar_SENASA_v2.xlsx')
APP_DB = os.path.join(ROOT, 'mezclas.db')
SALIDA = os.path.join(ROOT, 'data', 'senasa_carga.json')

APTITUDES = ['Herbicida', 'Fungicida', 'Insecticida', 'Acaricida', 'Coadyuvante']
CATEGORIA = {'Herbicida': 'HERBICIDA', 'Fungicida': 'FUNGICIDA', 'Insecticida': 'INSECTICIDA',
             'Acaricida': 'ACARICIDA', 'Coadyuvante': 'ADYUVANTE'}
SOLIDAS = {'WG', 'WP', 'SG', 'SP', 'GR', 'DP', 'GB', 'RB', 'TB', 'DS', 'SS', 'WS', 'BB', 'AB', 'BR', 'FT', 'FF'}

# ── Resoluciones acordadas con el usuario (2026-10-06) ─────────────────────
# Producto de la app con varios registros marcados "CORREGIR": registro del que
# se toman los datos. El resto queda vinculado y no se agrega.
FUENTE_CORRECCION = {
    11: '36610',   # ATRANEX 90            → ADAMA ATRANEX 90 WG
    14: '36973',   # ATRAZINA MAX 90 SIGMA → ATRAZINA MAX SIGMA
    60: '31220',   # GESAPRIM 90           → GESAPRIM 90 WDG
    68: '38375',   # IMAZETAPIR 10,6       → IMAZETAPIR 10,6 SIGMA
    87: '39430',   # MARGEN                → MARGEN 96 PRO
    120: '41409',  # S-METOLACLORO EBC     → S-METOLACLORO EBC 96%
    129: '33566',  # SULFOSATO             → SULFOSATO TOUCHDOWN
    141: '36755',  # TRAC 90               → TRAC 90 WG
    149: '39824',  # RESOLUTOR ACA         → RESOLUTOR 24 ACA
    130: '34926',  # SUPER ESTRELLA 2      → SUPER ESTRELLA II (misma sal)
    107: '37928',  # PINAR                 → PINAR SURCOS (mismos datos)
    52: '34365',   # ESTRELLA AURUM        → su propio registro exacto (conserva la sal)
    86: '36641',   # MARCH II              → registro "MARCH II" exacto (sal potásica, como la app)
}
# El usuario confirmó que estos productos de la app son OTRO registro distinto del de
# nombre exacto: el registro de nombre exacto se agrega como producto nuevo.
CONFIRMADO_OTRO_REGISTRO = {1, 51, 78}   # 2,4 D ACTION, ESPUELA, LA TIJERETA PLATINUM
# Registros que el usuario marcó como "el mismo" pero que pasan a ser productos nuevos.
REGISTROS_A_AGREGAR = {'40545', '41755'}   # PINAR 5 ME, PINAR ELITE (otra formulación)
# Pendientes de definir: se vinculan sin corregir y sus candidatos no se agregan.
PENDIENTES = {}
# Productos de la app duplicados: se ocultan (no se borran).
OCULTAR = {13: 'ATRATOP 90 duplicado de id 12'}

# ── Sal / éster: relación concentración / equivalente ácido ────────────────
ACIDOS = {
    'GLIFOSATO': (169.07, {
        'sal monoamónica': 186.10, 'sal diamónica': 203.13, 'sal potásica': 207.16,
        'sal isopropilamina': 228.18, 'sal dimetilamina': 214.15, 'sal sódica': 191.05,
        'sal trimesio': 245.23}),
    '2,4 D': (221.04, {
        'sal dimetilamina (DMA)': 266.12, 'éster etilhexílico': 333.25, 'sal colina': 324.20,
        'sal isopropilamina': 280.15, 'sal triisopropanolamina (TIPA)': 412.31,
        'éster butílico': 277.14, 'sal dietanolamina': 326.18, 'sal sódica': 243.02}),
    'DICAMBA': (221.04, {
        'sal dimetilamina (DMA)': 266.12, 'sal diglicolamina (DGA)': 326.18, 'sal sódica': 243.02,
        'sal potásica': 259.13, 'sal BAPMA': 365.28, 'sal isopropilamina': 280.15}),
    'PICLORAM': (241.46, {
        'sal potásica': 279.55, 'sal triisopropanolamina (TIPA)': 432.73,
        'sal trietanolamina (TEA)': 390.65}),
    'IMAZETAPIR': (289.33, {'sal amónica': 306.36}),
    'IMAZAPIR': (261.28, {'sal isopropilamina': 320.39, 'sal amónica': 278.31}),
    'IMAZAPIC': (275.30, {'sal amónica': 292.33}),
    'IMAZAMOX': (305.33, {'sal amónica': 322.36}),
    '2,4-DB': (249.09, {'sal dimetilamina (DMA)': 294.17}),
    'M.C.P.A.': (200.62, {'sal dimetilamina (DMA)': 245.70, 'sal potásica': 238.71,
                          'sal sódica': 222.60, 'éster etilhexílico': 312.83}),
    'FOMESAFEN': (438.76, {'sal sódica': 460.74}),
    'AMINOPIRALID': (207.01, {'sal potásica': 245.10, 'sal triisopropanolamina (TIPA)': 398.28}),
    'TRICLOPIR': (256.47, {'éster butotílico': 356.63, 'sal trietanolamina (TEA)': 405.66}),
    'DIQUAT': (184.24, {'dibromuro': 344.05}),
}
TOL = 0.008
PISTAS_NOMBRE = [
    (r'ETIL ?HEXIL|\bEHE\b|\b2EH\b', 'éster etilhexílico'), (r'\bDMA\b', 'sal dimetilamina (DMA)'),
    (r'COLINA', 'sal colina'), (r'\bDGA\b', 'sal diglicolamina (DGA)'), (r'\bTIPA\b', 'sal triisopropanolamina (TIPA)'),
    (r'POTASIC|\bSAL K\b', 'sal potásica'), (r'MONOAMONIC', 'sal monoamónica'),
    (r'ISOPROPILAMIN|\bIPA\b', 'sal isopropilamina'), (r'BUTOTIL', 'éster butotílico'),
]
# Formas escritas en el texto libre de la app (para conservarlas al corregir)
FORMAS_APP = [
    (r'SAL POTASICA|SAL K\b', 'sal potásica'), (r'MONOAMONICA', 'sal monoamónica'),
    (r'DIAMONICA', 'sal diamónica'), (r'ISOPROPILAMINA', 'sal isopropilamina'),
    (r'SAL AMONICA|AMONICA', 'sal amónica'), (r'\bDMA\b|DIMETILAMINA', 'sal dimetilamina (DMA)'),
    (r'COLINA', 'sal colina'), (r'SODICA', 'sal sódica'),
    (r'ETIL ?HEXIL', 'éster etilhexílico'),
]
# Sin tildes, igual que los datos que ya tiene la app: el buscador no distingue
# "potasica" de "potásica" si ambos están escritos igual.
SIN_DET = '(SAL/ESTER SIN DETERMINAR)'


def norm(s):
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return ''
    s = unicodedata.normalize('NFKD', str(s)).encode('ascii', 'ignore').decode().upper()
    return re.sub(r'\s+', ' ', re.sub(r'[^A-Z0-9]+', ' ', s)).strip()


def sin_acentos(s):
    return unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode()


def compact(s):
    return norm(s).replace(' ', '')


def num(x):
    if x is None or pd.isna(x):
        return ''
    return f'{x:.2f}'.rstrip('0').rstrip('.').replace('.', ',')


# Letras acentuadas que SENASA entrega como carácter de reemplazo (U+FFFD).
# Lista cerrada relevada sobre la base del 2026-10-06.
_ACENTOS_ROTOS = {
    'AGR�COLA': 'AGRÍCOLA', '�XIDO': 'ÓXIDO', 'L�QUIDO': 'LÍQUIDO',
    'METALDEH�DO': 'METALDEHÍDO', 'REL�MPAGO': 'RELÁMPAGO', 'ACCI�N': 'ACCIÓN',
    'PAT�BULO': 'PATÍBULO', 'MA�Z': 'MAÍZ', 'PULVERIZACI�N': 'PULVERIZACIÓN',
    'POSEID�N': 'POSEIDÓN', 'CL�SICO': 'CLÁSICO', 'TRIB�SICO': 'TRIBÁSICO',
    '�NICO': 'ÚNICO', 'CLORIMUR�N': 'CLORIMURÓN', 'TECNOLOG�A': 'TECNOLOGÍA',
}


def limpio(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    v = str(v)
    for roto, ok in _ACENTOS_ROTOS.items():
        v = re.sub(re.escape(roto), ok, v, flags=re.IGNORECASE)
    # el resto de los caracteres de reemplazo son ®, ™ o © de las marcas
    v = re.sub(r'[�®™©]', ' ', v)
    v = re.sub(r'\s+', ' ', v).strip()
    return v or None


def forma_senasa(activo, conc, ea, marca):
    """(forma, método). Nunca asigna si hay ambigüedad."""
    if activo not in ACIDOS:
        return '', 'no aplica'
    pm_ac, formas = ACIDOS[activo]
    pista = [f for pat, f in PISTAS_NOMBRE if re.search(pat, norm(marca)) and f in formas]
    if ea and not pd.isna(ea) and ea > 0 and conc and not pd.isna(conc):
        r = conc / ea
        cerca = [f for f, pm in formas.items() if abs(r - pm / pm_ac) <= TOL]
        if len(cerca) == 1:
            if pista and pista[0] != cerca[0]:
                return '', f'SIN DETERMINAR: relación {r:.3f} indica {cerca[0]}, el nombre {pista[0]}'
            return cerca[0], f'relación conc/EA = {r:.3f}'
        if len(cerca) > 1 and len(pista) == 1 and pista[0] in cerca:
            return pista[0], f'relación {r:.3f} (ambigua) resuelta por nombre'
        return '', f'SIN DETERMINAR: relación {r:.3f}'
    if len(pista) == 1:
        return pista[0], 'sólo por nombre comercial'
    return '', 'SIN DETERMINAR: sin equivalente ácido'


def productos_senasa():
    """Dict registro → datos del producto en el formato de la app."""
    P = pd.read_excel(SENASA_XLSX, sheet_name='Productos', dtype={'N° registro': str})
    A = pd.read_excel(SENASA_XLSX, sheet_name='Activos', dtype={'N° registro': str})
    sel = P[P[APTITUDES].eq('X').any(axis=1) & P['Prefijo reg.'].isna()]
    acts = {k: g for k, g in A.groupby('N° registro')}
    out = {}
    for _, p in sel.iterrows():
        reg, marca = p['N° registro'], p['Marca']
        sigla = limpio(p['Formulación (sigla)']) or ''
        partes, activos = [], []
        g = acts.get(reg)
        for _, a in (g.iterrows() if g is not None else []):
            forma, metodo = forma_senasa(a['Principio activo'], a['Concentración'], a['Equivalente ácido'], marca)
            uni = limpio(a['Unidad (SENASA)']) or '%'
            t = a['Principio activo']
            if forma:
                t += ' ' + sin_acentos(forma).upper()
            elif metodo.startswith('SIN DETERMINAR'):
                t += ' ' + SIN_DET
            t += f" {num(a['Concentración'])}" + ('%' if uni == '%' else ' ' + uni)
            if not pd.isna(a['Equivalente ácido']):
                t += f" (EA {num(a['Equivalente ácido'])}%)"
            partes.append(t)
            activos.append(a['Principio activo'])
        apts = [x for x in APTITUDES if p[x] == 'X']
        out[reg] = {
            'registro_senasa': reg,
            'nombre_comercial': limpio(marca).upper(),
            'categoria': CATEGORIA[apts[0]],
            'empresa': limpio(p['Firma titular']),
            'formulacion': sigla or None,
            'principio_activo': ' + '.join(partes) or None,
            'unidad_medida': 'Kg' if sigla in SOLIDAS else 'L',
            'familia': limpio(p['Grupos MoA (FRAC/IRAC/HRAC)']),
            '_activos': activos,
            '_fecha': str(p['Fecha inscripción'])[:10] if not pd.isna(p['Fecha inscripción']) else '',
        }
    return out


def conservar_sal(texto_senasa, texto_app, activos):
    """Si SENASA no determina la sal/éster y la app sí (producto monoactivo), usa la de la app."""
    if not texto_senasa or SIN_DET not in texto_senasa or len(activos) != 1:
        return texto_senasa, False
    t = norm(texto_app)
    formas = []
    for pat, f in FORMAS_APP:
        if re.search(pat, t) and f not in formas:
            formas.append(f)
            t = re.sub(pat, '', t)
    if len(formas) != 1:
        return texto_senasa, False
    return texto_senasa.replace(SIN_DET, sin_acentos(formas[0]).upper()), True


def main():
    for f in (SENASA_XLSX, REVISION_XLSX, APP_DB):
        if not os.path.exists(f):
            sys.exit(f'Falta {f}')
    sen = productos_senasa()

    con = sqlite3.connect(APP_DB)
    con.row_factory = sqlite3.Row
    app = {r['id_producto']: dict(r) for r in con.execute('SELECT * FROM productos')}
    con.close()

    rev = pd.read_excel(REVISION_XLSX, sheet_name='REVISAR', dtype={'SENASA registro': str})
    alt = pd.read_excel(REVISION_XLSX, sheet_name='Productos_a_agregar', dtype={'N° registro SENASA': str})

    def final(row):
        d = row['DECISIÓN']
        if isinstance(d, str) and d.strip():
            return d.strip()
        s = row['SUGERENCIA']
        return 'ES OTRO PRODUCTO' if s.startswith('ES OTRO') else s if s.startswith('ES EL MISMO') else 'SIN DECISIÓN'
    rev['final'] = rev.apply(final, axis=1)

    # Registros que NO se agregan (el usuario dijo que es el mismo o que está repetido)
    reclamados = set(rev.loc[rev['final'].str.startswith(('ES EL MISMO', 'REPETIDO', 'SIN DECISIÓN')), 'SENASA registro'])
    reclamados -= REGISTROS_A_AGREGAR

    # ── Coincidencias exactas por nombre (no estaban en REVISAR) ──
    por_nombre = {}
    for reg, s in sen.items():
        por_nombre.setdefault(compact(s['nombre_comercial']), []).append(reg)
    exactos = {}
    for pid, a in app.items():
        regs = por_nombre.get(compact(a['nombre_comercial']), [])
        if regs:
            # si hay más de uno, el de la misma formulación; si no, el más reciente
            form_app = norm(a['formulacion']).split(' ')[0] if a['formulacion'] else ''
            regs = sorted(regs, key=lambda r: sen[r]['_fecha'], reverse=True)
            regs.sort(key=lambda r: sen[r]['formulacion'] != form_app)
            exactos[pid] = regs[0]

    # ── Acción por producto de la app ──
    acciones = {}
    for pid, g in rev.groupby('APP id'):
        corr = g[g['final'].str.contains('CORREGIR')]
        vinc = g[g['final'].str.startswith('ES EL MISMO')]
        regs_vinc = list(dict.fromkeys(vinc['SENASA registro']))
        if pid in PENDIENTES:
            acciones[pid] = ('PENDIENTE', None, [], PENDIENTES[pid])
            continue
        if len(corr):
            fuente = FUENTE_CORRECCION.get(pid)
            if fuente is None:
                if corr['SENASA registro'].nunique() > 1:
                    sys.exit(f'Producto {pid} con varias fuentes de corrección y sin resolución')
                fuente = corr['SENASA registro'].iloc[0]
                tipo = corr['final'].iloc[0]
            else:
                tipo = 'ES EL MISMO - CORREGIR TODO'
            accion = 'CORREGIR_NOMBRE' if tipo.endswith('NOMBRE') else 'CORREGIR_TODO'
            regs = [fuente] + [r for r in regs_vinc if r != fuente]
            acciones[pid] = (accion, fuente, regs, '')
        elif regs_vinc:
            acciones[pid] = ('VINCULAR', None, regs_vinc, '')
    # exactos sin decisión en REVISAR → CORREGIR TODO con su registro exacto (punto 5);
    # con decisión → el registro de nombre exacto también queda vinculado (no se duplica)
    for pid, reg in exactos.items():
        if pid not in acciones:
            acciones[pid] = ('CORREGIR_TODO', reg, [reg], 'nombre exacto en SENASA')
        elif pid not in CONFIRMADO_OTRO_REGISTRO and reg not in acciones[pid][2]:
            accion, fuente, regs, nota = acciones[pid]
            if accion == 'PENDIENTE':
                continue
            acciones[pid] = (accion, fuente, regs + [reg], nota)

    usados_como_fuente = {a[1] for a in acciones.values() if a[1]}
    vinculados = {r for a in acciones.values() for r in a[2]}
    # registros exactos que quedaron libres porque su producto de la app se corrigió con otro
    liberados = {reg for pid, reg in exactos.items() if reg not in vinculados}

    actualizaciones, avisos = [], []
    for pid, (accion, fuente, regs, nota) in sorted(acciones.items()):
        a = app.get(pid)
        if a is None:
            avisos.append(f'id {pid} no existe en la base local')
            continue
        cambios = {'registro_senasa': ' | '.join(regs)} if regs else {}
        if accion in ('CORREGIR_NOMBRE', 'CORREGIR_TODO'):
            if fuente not in sen:
                avisos.append(f'{a["nombre_comercial"]} (id {pid}): registro {fuente} fuera de las 5 categorías; sólo se vincula')
                accion = 'VINCULAR'
            else:
                s = sen[fuente]
                cambios['nombre_comercial'] = s['nombre_comercial']
                if accion == 'CORREGIR_TODO':
                    pa, conservada = conservar_sal(s['principio_activo'], a['principio_activo'], s['_activos'])
                    cambios.update({k: s[k] for k in ('categoria', 'empresa', 'formulacion', 'unidad_medida', 'familia')})
                    cambios['principio_activo'] = pa
                    if conservada:
                        nota = (nota + '; ' if nota else '') + 'sal/éster tomada de la app'
        # sólo los campos que realmente cambian
        cambios = {k: v for k, v in cambios.items() if (a.get(k) or None) != (v or None)}
        actualizaciones.append({'id_producto': pid, 'nombre_esperado': a['nombre_comercial'],
                                'accion': accion, 'registro_fuente': fuente, 'cambios': cambios, 'nota': nota})

    ocultar = [{'id_producto': pid, 'nombre_esperado': app[pid]['nombre_comercial'], 'motivo': m}
               for pid, m in OCULTAR.items() if pid in app]

    # ── Altas ──
    incluir = alt[alt['INCLUIR'].astype(str).str.upper().str.startswith('S')]['N° registro SENASA']
    regs_alta = (set(incluir) - reclamados - vinculados) | ((REGISTROS_A_AGREGAR | liberados) - vinculados)
    altas = [{k: v for k, v in sen[r].items() if not k.startswith('_')}
             for r in sorted(regs_alta, key=lambda r: sen[r]['nombre_comercial']) if r in sen]

    plan = {
        'generado': date.today().isoformat(),
        'fuente_senasa': os.path.basename(SENASA_XLSX),
        'revision': os.path.basename(REVISION_XLSX),
        'pendientes': PENDIENTES,
        'avisos': avisos,
        'actualizaciones': actualizaciones,
        'ocultar': ocultar,
        'altas': altas,
    }
    os.makedirs(os.path.dirname(SALIDA), exist_ok=True)
    with open(SALIDA, 'w', encoding='utf-8') as f:
        json.dump(plan, f, ensure_ascii=False, indent=1)

    cuenta = pd.Series([u['accion'] for u in actualizaciones]).value_counts().to_dict()
    print(f'Plan escrito en {SALIDA}')
    print(f'  Actualizaciones: {len(actualizaciones)} {cuenta}')
    print(f'  Ocultar: {len(ocultar)}')
    print(f'  Altas: {len(altas)}  (incluye {len((REGISTROS_A_AGREGAR | liberados) - vinculados)} liberados/reasignados)')
    for a in avisos:
        print('  AVISO:', a)


if __name__ == '__main__':
    main()
