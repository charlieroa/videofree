"""
Lo gastado HOY de cada cupo gratis, para enseñarlo arriba en la pantalla.

Cloudflare no da el gasto del dia a una app como esta, asi que se cuenta aqui con la
tarifa oficial de cada llamada (por eso la pantalla pone «≈»):

  cloudflare  neuronas de FLUX.2 klein 4B: 26,05 por trozo de 512x512 de salida +
              5,37 por imagen de referencia (cada una cabe en un trozo). Cupo
              10.000/dia; se reinicia a las 00:00 UTC.
  youtube     unidades de la YouTube Data API: search = 100, videos/channels/
              videoCategories = 1. Cupo 10.000/dia; se reinicia a medianoche de
              California (hora del Pacifico).

Se guarda por usuario en canal/<usuario>/consumo.json (fuera de git).
"""
import json
import math
import threading
from datetime import datetime, timedelta, timezone

from . import canal

CUPO = {"cloudflare": 10000, "youtube": 10000}
_cerrojo = threading.Lock()


def _dia(servicio):
    ahora = datetime.now(timezone.utc)
    if servicio == "youtube":
        ahora -= timedelta(hours=8)            # medianoche del Pacifico (sin contar el horario de verano)
    return ahora.strftime("%Y-%m-%d")


def _ruta():
    return canal.carpeta() / "consumo.json"


def _leer():
    try:
        return json.loads(_ruta().read_text(encoding="utf-8"))
    except (OSError, ValueError, RuntimeError):
        return {}


def sumar(servicio, cantidad):
    try:
        with _cerrojo:
            datos = _leer()
            d = datos.get(servicio) or {}
            if d.get("dia") != _dia(servicio):
                d = {"dia": _dia(servicio), "gastado": 0}
            d["gastado"] = round(d["gastado"] + cantidad, 2)
            datos[servicio] = d
            _ruta().write_text(json.dumps(datos), encoding="utf-8")
    except RuntimeError:                        # sin usuario no se cuenta
        pass


def neuronas_imagen(ancho, alto, referencias):
    return 26.05 * math.ceil(ancho / 512) * math.ceil(alto / 512) + 5.37 * referencias


def hoy():
    datos = _leer()
    salida = {}
    for servicio, cupo in CUPO.items():
        d = datos.get(servicio) or {}
        gastado = d.get("gastado", 0) if d.get("dia") == _dia(servicio) else 0
        salida[servicio] = {"gastado": round(gastado), "cupo": cupo}
    return salida
