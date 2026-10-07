"""
Escalas de las observaciones visuales (espuma, precipitado, separación de fases
y redispersión) y sus colores. Las usan formularios, fichas y PDFs.

Datos viejos: los ensayos cargados antes de la escala tienen "Si"/"No"; se
muestran tal cual ("Sí" en rojo, "No" como bueno), sin inventarles un grado.
"""

VERDE, AMARILLO, NARANJA, ROJO, GRIS = '#2E7D32', '#FDD835', '#EF6C00', '#C62828', '#9E9E9E'
TEAL_PDF = '#1A7A7A'   # en los PDF lo "bueno" va en el verde DMA, como siempre

_GRADO = [('No', VERDE), ('Leve', AMARILLO), ('Medio', NARANJA), ('Grave', ROJO)]

ESCALAS = {
    'espuma': _GRADO,
    'precipitado': _GRADO,
    'separacion_fases': _GRADO,
    'redispersion': [('No aplica', GRIS), ('Total', VERDE), ('Parcial', AMARILLO),
                     ('Difícil', NARANJA), ('No redispersa', ROJO)],
}
ETIQUETAS = [('espuma', 'Espuma'), ('precipitado', 'Precipitado'),
             ('separacion_fases', 'Separación de Fases'), ('redispersion', 'Redispersión')]
POR_DEFECTO = {campo: escala[0][0] for campo, escala in ESCALAS.items()}


def es_viejo_si(valor):
    return str(valor or '').strip().lower() in ('si', 'sí')


def estilo(campo, valor, pdf=False):
    """(texto, color de fondo, color de texto) para mostrar una observación."""
    v = (valor or '').strip() or ('No' if campo != 'redispersion' else '')
    if es_viejo_si(v):
        return 'Sí', ROJO, '#FFFFFF'
    if v == 'No':                     # dato nuevo o viejo: sin problema
        return 'No', TEAL_PDF if pdf else VERDE, '#FFFFFF'
    for texto, color in ESCALAS.get(campo, []):
        if texto == v:
            if pdf and color == VERDE:
                color = TEAL_PDF
            return texto, color, '#212121' if color == AMARILLO else '#FFFFFF'
    return (v or '—'), GRIS, '#FFFFFF'


def opciones(campo, valor_actual=None):
    """Opciones del formulario. Si el ensayo tiene un valor anterior a la escala
    ("Si", o "No" en redispersión), se agrega para no perderlo al editar."""
    ops = [texto for texto, _ in ESCALAS[campo]]
    v = (valor_actual or '').strip()
    if v and v not in ops:
        ops.append(v)
    return ops


def etiqueta_opcion(valor):
    return 'Sí (sin grado)' if es_viejo_si(valor) else valor
