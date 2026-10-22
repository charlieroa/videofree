"""El canal de YouTube: foto de perfil y banner a la medida, desde una foto cualquiera.

Medidas de YouTube (ayuda oficial, «Cambiar el banner y la foto de perfil del canal»):
- Perfil: 800x800, se ve como círculo de 98x98. JPG/PNG/GIF/BMP, hasta 4 MB.
- Banner: 2560x1440 (mínimo 2048x1152, relación 16:9), hasta 6 MB. La TV lo enseña
  entero; el ordenador, una franja de 2560x423; el móvil y la zona segura, 1546x423
  en el centro. Lo importante (nombre, cara, logo) tiene que caer en esa zona.
"""
import io

from PIL import Image, ImageFilter, ImageOps

from . import proyecto, usuarios

PERFIL = (800, 800)
BANNER = (2560, 1440)
ESCRITORIO = (2560, 423)
SEGURA = (1546, 423)
TOPE = {"perfil": 4 * 1024 * 1024, "banner": 6 * 1024 * 1024}
ARCHIVO = {"perfil": "perfil.jpg", "banner": "banner.jpg"}


def carpeta():
    nombre = usuarios.ACTUAL.get()
    if not nombre:
        raise RuntimeError("No hay usuario.")
    c = proyecto.RAIZ / "canal" / nombre
    c.mkdir(parents=True, exist_ok=True)
    return c


def _abrir(crudo):
    img = Image.open(io.BytesIO(crudo))
    img = ImageOps.exif_transpose(img)          # las fotos del móvil vienen giradas
    if img.mode in ("RGBA", "LA", "P"):
        fondo = Image.new("RGB", img.size, (255, 255, 255))
        img = img.convert("RGBA")
        fondo.paste(img, mask=img.split()[-1])
        return fondo
    return img.convert("RGB")


def _recortar(img, ancho, alto, foco_y=0.5):
    """Llena ancho x alto sin deformar; foco_y decide qué parte vertical se queda."""
    escala = max(ancho / img.width, alto / img.height)
    img = img.resize((round(img.width * escala), round(img.height * escala)), Image.LANCZOS)
    x = (img.width - ancho) // 2
    y = round((img.height - alto) * foco_y)
    return img.crop((x, y, x + ancho, y + alto))


def perfil(img):
    # En un retrato la cara suele estar en el tercio de arriba: si sobra alto, se
    # recorta más por abajo que por arriba.
    return _recortar(img, *PERFIL, foco_y=0.3 if img.height > img.width else 0.5)


def banner(img):
    """Foto ancha: llena el banner. Foto cuadrada o vertical: entera dentro de la
    zona segura, sobre la misma foto ampliada y desenfocada (no hay franjas vacías)."""
    if img.width / img.height >= 1.5:
        return _recortar(img, *BANNER), "recortada"
    fondo = _recortar(img, *BANNER).filter(ImageFilter.GaussianBlur(40))
    fondo = Image.blend(fondo, Image.new("RGB", BANNER, (0, 0, 0)), 0.35)
    frente = ImageOps.contain(img, SEGURA, Image.LANCZOS)
    fondo.paste(frente, ((BANNER[0] - frente.width) // 2, (BANNER[1] - frente.height) // 2))
    return fondo, "centrada en la zona segura"


def encuadrar(img, tipo, recorte):
    """El encuadre que eligio la persona en la pantalla.

    recorte = {x, y, w, h} en FRACCIONES de la foto (0-1), con la proporcion final
    (1:1 o 16:9). Puede salirse de la foto (al alejar): lo que queda fuera se llena
    con la misma foto ampliada y desenfocada, como en el banner automatico.
    """
    ancho, alto = PERFIL if tipo == "perfil" else BANNER
    try:
        rx, ry = float(recorte["x"]) * img.width, float(recorte["y"]) * img.height
        rw, rh = float(recorte["w"]) * img.width, float(recorte["h"]) * img.height
    except (KeyError, TypeError, ValueError):
        raise ValueError("Encuadre no válido.")
    if rw < 8 or rh < 8:
        raise ValueError("El encuadre es demasiado pequeño.")
    escala = ancho / rw
    # Solo se amplia el trozo de foto que cae dentro del encuadre (una foto de 4000
    # px con zoom 3 no se reescala entera).
    x0, y0 = max(rx, 0), max(ry, 0)
    x1, y1 = min(rx + rw, img.width), min(ry + rh, img.height)
    dentro = x0 < x1 and y0 < y1
    if dentro and x0 <= rx + 0.5 and y0 <= ry + 0.5 and x1 >= rx + rw - 0.5 and y1 >= ry + rh - 0.5:
        return img.crop((round(rx), round(ry), round(rx + rw), round(ry + rh))).resize((ancho, alto), Image.LANCZOS)
    lienzo = _recortar(img, ancho, alto).filter(ImageFilter.GaussianBlur(40))
    lienzo = Image.blend(lienzo, Image.new("RGB", (ancho, alto), (0, 0, 0)), 0.35)
    if dentro:
        trozo = img.crop((round(x0), round(y0), round(x1), round(y1)))
        trozo = trozo.resize((max(1, round(trozo.width * escala)), max(1, round(trozo.height * escala))),
                             Image.LANCZOS)
        lienzo.paste(trozo, (round((x0 - rx) * escala), round((y0 - ry) * escala)))
    return lienzo


def guardar(tipo, crudo, recorte=None):
    """Prepara y guarda la imagen; devuelve lo que se hizo.

    Sin 'recorte' se encuadra sola (centro / zona segura); con él, como lo dejó la persona.
    """
    try:
        img = _abrir(crudo)
    except Exception:
        raise ValueError("No he podido leer esa imagen. Prueba con un JPG o PNG.")
    if recorte:
        final, como = encuadrar(img, tipo, recorte), "encuadrada a mano"
    elif tipo == "perfil":
        final, como = perfil(img), "recortada al centro"
    else:
        final, como = banner(img)
    aviso = ""
    minimo = PERFIL if tipo == "perfil" else (2048, 1152)
    if img.width < minimo[0] // 2 or img.height < minimo[1] // 4:
        aviso = "La foto es pequeña: se verá algo borrosa. Si puedes, usa una más grande."
    ruta = carpeta() / ARCHIVO[tipo]
    for calidad in (92, 85, 75, 65):           # bajo el tope de peso de YouTube
        buf = io.BytesIO()
        final.save(buf, "JPEG", quality=calidad, optimize=True)
        if buf.tell() <= TOPE[tipo]:
            break
    ruta.write_bytes(buf.getvalue())
    return {"ancho": final.width, "alto": final.height, "kb": buf.tell() // 1024,
            "como": como, "aviso": aviso}


def estado():
    c = carpeta()
    return {t: (int((c / a).stat().st_mtime) if (c / a).exists() else None)
            for t, a in ARCHIVO.items()}
