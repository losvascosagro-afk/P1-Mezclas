"""Todo el texto de los informes PDF en MAYÚSCULA.

Paragraph de reportlab con el texto pasado a mayúscula, sin tocar las
etiquetas (<b>, <font color="...">, <br/>) ni las entidades (&amp;).
En pantalla lo mismo se hace con CSS (text-transform en style.css).
"""
import copy
import re

import os

from reportlab.lib.fonts import addMapping
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph as _Paragraph

# Letra de los informes: Outfit (la misma que en pantalla), en static/fonts.
# Nombres: 'Outfit' y 'Outfit-Bold'. Outfit no tiene itálica: <i> sale derecho.
_FUENTES = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'fonts')
pdfmetrics.registerFont(TTFont('Outfit', os.path.join(_FUENTES, 'Outfit-Regular.ttf')))
pdfmetrics.registerFont(TTFont('Outfit-Bold', os.path.join(_FUENTES, 'Outfit-Bold.ttf')))
for _familia in ('Outfit', 'Outfit-Bold'):
    for _i in (0, 1):
        addMapping(_familia, 0, _i, 'Outfit')
        addMapping(_familia, 1, _i, 'Outfit-Bold')

_MARCAS = re.compile(r'(<[^>]*>|&[#\w]+;)')


def mayus(texto):
    if not isinstance(texto, str):
        return texto
    partes = _MARCAS.split(texto)
    # Las partes impares son etiquetas/entidades; µ queda igual (su
    # mayúscula es la letra griega, que Outfit no tiene).
    return ''.join(p if i % 2 else p.replace('µ', '\0').upper().replace('\0', 'µ')
                   for i, p in enumerate(partes))


LETRA_MINIMA = 6  # pt; más chico no se achica (prefiere cortar la palabra)


class Paragraph(_Paragraph):
    """En mayúscula, y si una palabra no entra en el ancho de la celda,
    achica la letra lo justo para que entre en vez de partirla."""

    def __init__(self, text, style=None, *args, **kwargs):
        self._args = (mayus(text), args, kwargs)
        super().__init__(mayus(text), style, *args, **kwargs)

    def wrap(self, availWidth, availHeight):
        ancho = self.minWidth()
        tam = self.style.fontSize
        if ancho > availWidth > 0 and tam > LETRA_MINIMA:
            nuevo = max(LETRA_MINIMA, tam * availWidth / ancho * 0.98)
            factor = nuevo / tam
            estilo = copy.copy(self.style)
            estilo.fontSize = nuevo
            estilo.leading = (self.style.leading or tam * 1.2) * factor
            texto, args, kwargs = self._args
            super().__init__(texto, estilo, *args, **kwargs)
        return super().wrap(availWidth, availHeight)


def _primera_mayus(texto):
    """Pone en mayúscula solo la primera letra del texto (fuera de etiquetas)."""
    if not isinstance(texto, str):
        return texto
    partes = _MARCAS.split(texto)
    for i in range(0, len(partes), 2):
        p = partes[i]
        for j, ch in enumerate(p):
            if ch.isalpha():
                partes[i] = p[:j] + ch.upper() + p[j + 1:]
                return ''.join(partes)
            if not ch.isspace():
                return ''.join(partes)
    return ''.join(partes)


class TextoLibre(_Paragraph):
    """Para los textos largos que escribe el laboratorio (recomendación,
    observaciones, descripciones): se muestran como fueron escritos, en
    mayúscula y minúscula, porque un párrafo entero en MAYÚSCULA se lee mal.
    Los títulos que van dentro (<b>...</b>) ya vienen escritos en mayúscula."""

    def __init__(self, text, style=None, *args, **kwargs):
        super().__init__(_primera_mayus(text), style, *args, **kwargs)
