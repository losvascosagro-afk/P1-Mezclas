"""Todo el texto de los informes PDF en MAYÚSCULA.

Paragraph de reportlab con el texto pasado a mayúscula, sin tocar las
etiquetas (<b>, <font color="...">, <br/>) ni las entidades (&amp;).
En pantalla lo mismo se hace con CSS (text-transform en style.css).
"""
import copy
import re

from reportlab.platypus import Paragraph as _Paragraph

_MARCAS = re.compile(r'(<[^>]*>|&[#\w]+;)')


def mayus(texto):
    if not isinstance(texto, str):
        return texto
    partes = _MARCAS.split(texto)
    # Las partes impares son etiquetas/entidades; µ queda igual (su
    # mayúscula es la letra griega, que Helvetica no tiene).
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
