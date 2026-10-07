"""
Informe PDF de un ensayo comparativo (varias mezclas).

Misma estética que el informe de ensayo simple (app._build_pdf): encabezado
teal con logo, secciones oscuras, marca de agua, firmas y pie. Estructura:
datos generales → resumen comparativo (una fila por mezcla) → una sección por
mezcla (agua, composición, observaciones, microscopía y fotos) → conclusión.
"""
import io
import os
from datetime import datetime

import observaciones
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (HRFlowable, Image, KeepTogether, Paragraph,
                                SimpleDocTemplate, Spacer, Table, TableStyle)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LAB_NAME = 'Laboratorio de Análisis de Compatibilidad de Agroquímicos y Calidad de Agua'
LOGO_PATH = os.path.join(BASE_DIR, 'LOGO ORIGINAL.png')

C_TEAL = colors.HexColor('#1A7A7A')
C_DARK = colors.HexColor('#2D2D2D')
C_LGRAY = colors.HexColor('#F2F2F2')
C_BORDER = colors.HexColor('#CCCCCC')
C_WHITE = colors.white
C_RED = colors.HexColor('#C62828')
C_ORANGE = colors.HexColor('#E67E00')
C_BLUE = colors.HexColor('#1565C0')
C_BLACK = colors.black
ANCHO = 17.4 * cm

_BASE_STY = {
    'body': dict(fontName='Helvetica', fontSize=9, textColor=C_BLACK, spaceAfter=2),
    'label': dict(fontName='Helvetica-Bold', fontSize=9, textColor=C_DARK),
    'th': dict(fontName='Helvetica-Bold', fontSize=8, textColor=C_WHITE),
    'thc': dict(fontName='Helvetica-Bold', fontSize=8, textColor=C_WHITE, alignment=TA_CENTER),
    'center': dict(fontName='Helvetica', fontSize=9, alignment=TA_CENTER),
    'title': dict(fontName='Helvetica-Bold', fontSize=13, textColor=C_WHITE, alignment=TA_LEFT),
    'sub': dict(fontName='Helvetica', fontSize=10, textColor=C_WHITE, alignment=TA_LEFT),
    'footer': dict(fontName='Helvetica', fontSize=7, textColor=colors.gray, alignment=TA_CENTER),
    'caption': dict(fontName='Helvetica', fontSize=8, textColor=colors.gray, alignment=TA_CENTER),
    'obs': dict(fontName='Helvetica', fontSize=9, textColor=C_BLACK, leading=14),
}
_n_sty = [0]


def sty(name='body', **kw):
    _n_sty[0] += 1
    return ParagraphStyle(f'C_{name}_{_n_sty[0]}', **{**_BASE_STY.get(name, _BASE_STY['body']), **kw})


def _esc(v):
    s = '' if v in (None, 'None') else str(v)
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def _num(v):
    if v in (None, '', 'None'):
        return '—'
    try:
        f = float(v)
        return (f'{f:g}').replace('.', ',')
    except (TypeError, ValueError):
        return _esc(v)


def color_resultado(res):
    r = (res or '').lower()
    if 'inestable' in r:
        return C_RED
    if 'observaci' in r:
        return C_ORANGE
    if 'estable' in r:
        return C_TEAL
    if 'ensayo' in r:
        return C_BLUE
    return colors.gray


def sec(text, bg=None):
    t = Table([[Paragraph(text, sty('label', textColor=C_WHITE, leftIndent=6))]], colWidths=[ANCHO])
    t.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), bg or C_DARK),
                           ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 5)]))
    return t


def _caja(texto, borde=C_TEAL):
    t = Table([[Paragraph(texto, sty('obs'))]], colWidths=[ANCHO])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), C_WHITE), ('LINEBEFORE', (0, 0), (0, -1), 2.5, borde),
        ('LEFTPADDING', (0, 0), (-1, -1), 10), ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('BOX', (0, 0), (-1, -1), 0.5, C_BORDER)]))
    return t


def _grilla(filas, anchos):
    t = Table(filas, colWidths=anchos)
    t.setStyle(TableStyle([
        ('ROWBACKGROUNDS', (0, 0), (-1, -1), [C_WHITE, C_LGRAY]),
        ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 6), ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('BOX', (0, 0), (-1, -1), 0.5, C_BORDER), ('INNERGRID', (0, 0), (-1, -1), 0.3, C_BORDER),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE')]))
    return t


def _badge_res(res, ancho):
    c = Table([[Paragraph(f'<font color="white"><b>{_esc(res or "SIN RESULTADO").upper()}</b></font>',
                          sty('center', fontSize=7.5, leading=9, textColor=C_WHITE))]], colWidths=[ancho])
    c.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), color_resultado(res)),
                           ('TOPPADDING', (0, 0), (-1, -1), 3), ('BOTTOMPADDING', (0, 0), (-1, -1), 3)]))
    return c


def _agua_txt(m):
    partes = [_esc(m['tipo_agua']) if m['tipo_agua'] else '']
    if m['ph'] not in (None, ''):
        partes.append(f'pH {_num(m["ph"])}')
    if m['dureza'] not in (None, ''):
        partes.append(f'{_num(m["dureza"])} mg/L CaCO<sub>3</sub>')
    if m['temperatura'] not in (None, ''):
        partes.append(f'{_num(m["temperatura"])} °C')
    if m['conductividad'] not in (None, ''):
        partes.append(f'{_num(m["conductividad"])} µS/cm')
    return ' · '.join(p for p in partes if p) or '—'


def _composicion(detalles):
    sc = sty('center', fontSize=8, leading=10)
    sb = sty('body', fontSize=8, leading=10)
    spa = sty('body', fontSize=7.5, leading=9.5)
    filas = [[Paragraph(t, sty('thc')) for t in
              ['#', 'Producto', 'Categoría', 'Empresa', 'Form.', 'Principio Activo', 'Dosis', 'Ud.']]]
    obs_rows = []
    for i, d in enumerate(detalles):
        filas.append([Paragraph(str(d['orden_carga'] or i + 1), sc),
                      Paragraph(_esc(d['nombre_comercial'] or '—').upper(), sb),
                      Paragraph(_esc(d['categoria'] or '—').upper(), sb),
                      Paragraph(_esc(d['empresa'] or '—').upper(), sb),
                      Paragraph(f'<b>{_esc(d["formulacion"] or "—")}</b>', sc),
                      Paragraph(_esc(d['principio_activo'] or '—').upper(), spa),
                      Paragraph(_num(d['dosis']), sc),
                      Paragraph(_esc(d['unidad'] or 'L').upper(), sc)])
        if d['observacion'] and str(d['observacion']).strip():
            filas.append(['', Paragraph(f'<i><font color="#1A7A7A">Obs:</font> {_esc(d["observacion"]).strip()}</i>',
                                        sty('body', fontSize=7, leading=9, textColor=colors.HexColor('#555555'))),
                          '', '', '', '', '', ''])
            obs_rows.append(len(filas) - 1)
    t = Table(filas, colWidths=[0.8 * cm, 3.4 * cm, 2.3 * cm, 2.6 * cm, 1.3 * cm, 4.4 * cm, 1.4 * cm, 1.2 * cm],
              repeatRows=1)
    st = [('BACKGROUND', (0, 0), (-1, 0), C_DARK),
          ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
          ('LEFTPADDING', (0, 0), (-1, -1), 5), ('RIGHTPADDING', (0, 0), (-1, -1), 5),
          ('BOX', (0, 0), (-1, -1), 0.5, C_BORDER), ('INNERGRID', (0, 0), (-1, -1), 0.3, C_BORDER),
          ('VALIGN', (0, 0), (-1, -1), 'MIDDLE')]
    for r in obs_rows:
        st += [('SPAN', (1, r), (7, r)), ('LINEBEFORE', (1, r), (1, r), 2, C_TEAL)]
    t.setStyle(TableStyle(st))
    return t


# Fotos cargadas desde esta fecha van en un recuadro de 8×8 cm. Los ensayos con
# alguna foto anterior conservan el tamaño viejo (7,5×5,5 cm) para que sus PDF
# ya entregados salgan idénticos.
FOTOS_8X8_DESDE = '2026-10-07 10:45'


def caja_fotos(fotos):
    """(ancho, alto) máximos de las fotos en el PDF de este ensayo."""
    if all((f['fecha_carga'] or '') >= FOTOS_8X8_DESDE for f in fotos):
        return 8 * cm, 8 * cm
    return 7.5 * cm, 5.5 * cm


def _fit_image(src, max_w=7.5 * cm, max_h=5.5 * cm):
    ir = ImageReader(src)
    iw, ih = ir.getSize()
    scale = min(max_w / iw, max_h / ih)
    img = Image(src, width=iw * scale, height=ih * scale)
    img.hAlign = 'CENTER'
    return img


def _fotos(fotos, upload_folder, titulo, caja):
    out = []
    pares = [fotos[i:i + 2] for i in range(0, len(fotos), 2)]
    for n, par in enumerate(pares):
        celdas = []
        for f in par:
            celda = []
            try:
                datos = f['imagen_data']
                if datos:
                    celda.append(_fit_image(io.BytesIO(bytes(datos)), *caja))
                else:
                    celda.append(_fit_image(os.path.join(upload_folder, f['nombre_archivo']), *caja))
            except Exception:
                celda.append(Paragraph('[Imagen no disponible]', sty()))
            if f['descripcion']:
                celda.append(Paragraph(_esc(f['descripcion']), sty('caption')))
            celdas.append(celda)
        while len(celdas) < 2:
            celdas.append([Spacer(0.1, 0.1)])
        ft = Table([celdas], colWidths=[8.7 * cm, 8.7 * cm])
        ft.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                                ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                                ('BOX', (0, 0), (-1, -1), 0.3, colors.lightgrey),
                                ('INNERGRID', (0, 0), (-1, -1), 0.3, colors.lightgrey)]))
        out.append(KeepTogether([sec(titulo), ft]) if n == 0 else ft)
    return out


def construir(e, mezclas, fotos_generales, upload_folder):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=1.8 * cm, leftMargin=1.8 * cm,
                            topMargin=1.8 * cm, bottomMargin=1.8 * cm)
    story = []
    caja = caja_fotos([f for m in mezclas for f in m['fotos']] + list(fotos_generales))

    # ── Encabezado ──
    titulo = [Paragraph(LAB_NAME.upper(), sty('title')), Spacer(1, 4),
              Paragraph(f'INFORME DE ENSAYO COMPARATIVO  N° {e["id_ensayo"]:04d}', sty('sub'))]
    logo = Spacer(1, 1)
    if os.path.exists(LOGO_PATH):
        try:
            iw, ih = ImageReader(LOGO_PATH).getSize()
            logo = Image(LOGO_PATH, width=3.8 * cm, height=3.8 * cm * ih / iw)
        except Exception:
            pass
    hdr = Table([[titulo, logo]], colWidths=[12.4 * cm, 5.0 * cm])
    hdr.setStyle(TableStyle([('BACKGROUND', (0, 0), (0, -1), C_TEAL), ('BACKGROUND', (1, 0), (1, -1), C_WHITE),
                             ('TOPPADDING', (0, 0), (-1, -1), 12), ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
                             ('LEFTPADDING', (0, 0), (0, -1), 10), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                             ('ALIGN', (1, 0), (1, -1), 'CENTER'), ('BOX', (0, 0), (-1, -1), 0.5, C_TEAL)]))
    story += [hdr, Spacer(1, 8)]

    bar = _grilla([[Paragraph(f'<b>Fecha:</b>  {_esc(e["fecha"]) or "—"}', sty()),
                    Paragraph(f'<b>Objetivo:</b>  {_esc(e["objetivo"]) or "—"}', sty()),
                    Paragraph(f'<b>Mezclas comparadas:</b>  {len(mezclas)}', sty())]],
                  [4 * cm, 9.4 * cm, 4 * cm])
    story += [bar, Spacer(1, 4)]
    if e['obs_mezcla']:
        story += [_caja(f'<b><font color="#1A7A7A">DESCRIPCIÓN DEL ENSAYO</font></b><br/>{_esc(e["obs_mezcla"])}'),
                  Spacer(1, 6)]

    def _v(v):
        return _esc(v).strip().upper() or '—'
    loc = ', '.join(p.strip().upper() for p in [e['localidad'] or '', e['provincia'] or ''] if p and p.strip())
    cli = _grilla([[Paragraph('Razón Social:', sty('label')), Paragraph(_v(e['razon_social']), sty()),
                    Paragraph('Técnico:', sty('label')), Paragraph(_v(e['tecnico_responsable']), sty())],
                   [Paragraph('C.U.I.T.:', sty('label')), Paragraph(_v(e['cuit']), sty()),
                    Paragraph('Localidad:', sty('label')), Paragraph(_esc(loc) or '—', sty())]],
                  [3 * cm, 5.7 * cm, 2.7 * cm, 6 * cm])
    story += [KeepTogether([sec('DATOS DEL CLIENTE'), cli]), Spacer(1, 7)]

    vols = ' / '.join(f'{v.strip()} L' for v in (e['volumenes'] or '').split(',') if v.strip()) or '—'
    tobs = ' / '.join(f'{t.strip()} min' for t in (e['tiempos_obs'] or '').split(',') if t.strip()) or '—'
    cond = _grilla([[Paragraph('Volúmenes de caldo', sty('label')), Paragraph(vols, sty()),
                     Paragraph('Tiempos de observación', sty('label')), Paragraph(tobs, sty())]],
                   [3.6 * cm, 5.1 * cm, 3.9 * cm, 4.8 * cm])
    story += [KeepTogether([sec('CONDICIONES GENERALES'), cond]), Spacer(1, 7)]

    # ── Resumen comparativo ──
    sc = sty('center', fontSize=8, leading=10)
    filas = [[Paragraph(t, sty('thc')) for t in
              ['Mezcla', 'Agua', 'Espuma', 'Precip.', 'Separ. fases', 'Redisp.', 'Resultado']]]
    estilos = []
    for i, m in enumerate(mezclas, start=1):
        fila = [Paragraph(f'<b>{_esc(m["nombre"])}</b>', sty('body', fontSize=8.5, leading=10.5)),
                Paragraph(_agua_txt(m), sty('body', fontSize=7.5, leading=9.5))]
        for j, campo in enumerate(['espuma', 'precipitado', 'separacion_fases', 'redispersion'], start=2):
            texto, bg, fg = observaciones.estilo(campo, m[campo], pdf=True)
            fila.append(Paragraph(f'<font color="{fg}"><b>{_esc(texto).upper()}</b></font>',
                                  sty('center', fontSize=7.5, leading=9)))
            estilos.append(('BACKGROUND', (j, i), (j, i), colors.HexColor(bg)))
        fila.append(_badge_res(m['resultado_final'], 3.2 * cm))
        filas.append(fila)
    res = Table(filas, colWidths=[3.2 * cm, 3.7 * cm, 1.6 * cm, 1.6 * cm, 1.8 * cm, 2.1 * cm, 3.4 * cm], repeatRows=1)
    res.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), C_DARK),
                             ('ROWBACKGROUNDS', (0, 1), (1, -1), [C_WHITE, C_LGRAY]),
                             ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
                             ('LEFTPADDING', (0, 0), (-1, -1), 5), ('RIGHTPADDING', (0, 0), (-1, -1), 5),
                             ('BOX', (0, 0), (-1, -1), 0.5, C_BORDER), ('INNERGRID', (0, 0), (-1, -1), 0.3, C_BORDER),
                             ('VALIGN', (0, 0), (-1, -1), 'MIDDLE')] + estilos))
    story += [KeepTogether([sec('RESUMEN COMPARATIVO'), res]), Spacer(1, 7)]

    if e['recomendacion']:
        story += [KeepTogether([sec('CONCLUSIÓN GENERAL', bg=C_TEAL), _caja(_esc(e['recomendacion']))]),
                  Spacer(1, 7)]

    # ── Una sección por mezcla ──
    for i, m in enumerate(mezclas, start=1):
        bloque = [sec(f'MEZCLA {i}  —  {_esc(m["nombre"]).upper()}', bg=C_TEAL)]
        info = [[Paragraph('Agua', sty('label')), Paragraph(_agua_txt(m), sty()),
                 Paragraph('Resultado', sty('label')), _badge_res(m['resultado_final'], 4.2 * cm)]]
        bloque.append(_grilla(info, [2.2 * cm, 8.4 * cm, 2.4 * cm, 4.4 * cm]))
        if m['descripcion']:
            bloque += [Spacer(1, 3), _caja(f'<b><font color="#1A7A7A">DESCRIPCIÓN</font></b><br/>{_esc(m["descripcion"])}')]
        # el encabezado de la mezcla viaja junto con su composición
        if m['detalles']:
            bloque += [Spacer(1, 4), sec('Composición'), _composicion(m['detalles'])]
        story += [KeepTogether(bloque), Spacer(1, 4)]
        obs, fondos = [], []
        for c, lbl in observaciones.ETIQUETAS:
            texto, bg, fg = observaciones.estilo(c, m[c], pdf=True)
            obs.append([Paragraph(lbl, sty('label')),
                        Paragraph(f'<font color="{fg}"><b>{_esc(texto).upper()}</b></font>', sc)])
            fondos.append(colors.HexColor(bg))
        ov = Table([obs[0] + obs[1], obs[2] + obs[3]], colWidths=[5 * cm, 3.7 * cm, 5 * cm, 3.7 * cm])
        ov_st = [('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
                 ('LEFTPADDING', (0, 0), (-1, -1), 8), ('BOX', (0, 0), (-1, -1), 0.5, C_BORDER),
                 ('INNERGRID', (0, 0), (-1, -1), 0.3, C_BORDER), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE')]
        for (r, c), fondo in zip([(0, 1), (0, 3), (1, 1), (1, 3)], fondos):
            ov_st.append(('BACKGROUND', (c, r), (c, r), fondo))
        ov.setStyle(TableStyle(ov_st))
        story += [KeepTogether([sec('Observaciones visuales'), ov]), Spacer(1, 4)]
        if m['obs_microscopio']:
            story += [KeepTogether([sec('Observaciones al microscopio'), _caja(_esc(m['obs_microscopio']))]),
                      Spacer(1, 4)]
        if m['fotos']:
            story += _fotos(m['fotos'], upload_folder, f'Imágenes — {_esc(m["nombre"])}', caja)
        story.append(Spacer(1, 10))

    if fotos_generales:
        story += _fotos(fotos_generales, upload_folder, 'IMÁGENES GENERALES DEL ENSAYO', caja)
        story.append(Spacer(1, 8))

    # ── Firmas y pie ──
    story.append(Spacer(1, 12))
    firma = os.path.join(BASE_DIR, 'Firma_DMA_SinFondo-ok.jpg')
    if not os.path.exists(firma):
        firma = os.path.join(BASE_DIR, 'static', 'firma_dma.jpg')

    def _firma(con_firma):
        celda = []
        if con_firma and os.path.exists(firma):
            try:
                fw, fh = ImageReader(firma).getSize()
                celda.append(Image(firma, width=1.8 * cm, height=1.8 * cm * fh / fw))
            except Exception:
                celda.append(Spacer(1, 1.8 * cm))
        else:
            celda.append(Spacer(1, 1.8 * cm))
        celda.append(HRFlowable(width='85%', thickness=0.5, color=colors.gray, hAlign='CENTER'))
        celda.append(Paragraph('Director de Laboratorio' if con_firma else 'Técnico Responsable',
                               sty('center', textColor=colors.gray, fontSize=8)))
        return celda
    sig = Table([[_firma(False), _firma(True)]], colWidths=[8.7 * cm, 8.7 * cm])
    sig.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'BOTTOM'), ('ALIGN', (0, 0), (-1, -1), 'CENTER')]))
    story += [KeepTogether([sig]), Spacer(1, 10), HRFlowable(width='100%', thickness=0.5, color=C_BORDER),
              Spacer(1, 4),
              Paragraph(f'Informe generado el {datetime.now().strftime("%d/%m/%Y a las %H:%M")}  ·  '
                        f'{LAB_NAME}  ·  Informe comparativo N° {e["id_ensayo"]:04d}', sty('footer'))]

    def _marca_agua(canvas, _doc):
        if not os.path.exists(LOGO_PATH):
            return
        try:
            canvas.saveState()
            canvas.setFillAlpha(0.06)
            iw, ih = ImageReader(LOGO_PATH).getSize()
            pw, ph = A4
            w = pw * 0.55
            h = w * ih / iw
            canvas.drawImage(LOGO_PATH, (pw - w) / 2, (ph - h) / 2, width=w, height=h,
                             mask='auto', preserveAspectRatio=True)
            canvas.restoreState()
        except Exception:
            pass

    doc.build(story, onFirstPage=_marca_agua, onLaterPages=_marca_agua)
    buf.seek(0)
    return buf
