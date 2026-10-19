"""
Paso 2: la voz de cada escena, con las voces neuronales de Microsoft (edge-tts).

Gratis y sin clave. Se sintetiza escena a escena porque la duracion de cada
audio es la que manda: la animacion de cada imagen dura lo que dura su frase.

En modo prueba no se llama a nada: se pone silencio con la duracion que
tendria la frase leida.
"""
import asyncio
import re
import time

import edge_tts

from . import medios, proyecto, voz_gpu

PALABRAS_POR_SEGUNDO = 2.2
FORMATO = re.compile(r"^[a-z]{2}-[A-Z]{2}-[A-Za-z]+Neural$")
FRASE_MUESTRA = "Hola, así va a sonar la narración de tu video. ¿Te gusta cómo suena?"
PAISES = {"AR": "Argentina", "BO": "Bolivia", "CL": "Chile", "CO": "Colombia", "CR": "Costa Rica",
          "CU": "Cuba", "DO": "Rep. Dominicana", "EC": "Ecuador", "ES": "España", "GQ": "Guinea Ecuatorial",
          "GT": "Guatemala", "HN": "Honduras", "MX": "México", "NI": "Nicaragua", "PA": "Panamá",
          "PE": "Perú", "PR": "Puerto Rico", "PY": "Paraguay", "SV": "El Salvador", "US": "Estados Unidos",
          "UY": "Uruguay", "VE": "Venezuela"}
_catalogo = {"hora": 0, "voces": None}


def _ficha(corto, genero):
    _, pais, nombre = corto.split("-", 2)
    return {"id": corto, "nombre": nombre.replace("Neural", ""), "pais": PAISES.get(pais, pais),
            "genero": {"Female": "mujer", "Male": "hombre"}.get(genero, "")}


def catalogo(respaldo):
    """Las voces en español de edge-tts, con nombre, país y si es hombre o mujer.

    Se piden a Microsoft una vez al día; sin red, sale la lista corta de config.
    """
    if _catalogo["voces"] and time.time() - _catalogo["hora"] < 86400:
        return _catalogo["voces"]
    try:
        todas = asyncio.run(edge_tts.list_voices())
        voces = [_ficha(v["ShortName"], v["Gender"]) for v in todas
                 if v["Locale"].startswith("es-") and FORMATO.match(v["ShortName"])]
        _catalogo.update(hora=time.time(), voces=sorted(voces, key=lambda v: (v["pais"], v["nombre"])))
        return _catalogo["voces"]
    except Exception:
        return [_ficha(v, "") for v in respaldo]


def valida(voz_id):
    return bool(FORMATO.match(voz_id or "")) or voz_gpu.es_suya(voz_id)


def muestra(voz_id):
    """Un mp3 corto con esa voz para escucharla antes de elegirla. Se guarda y se reusa."""
    if voz_gpu.es_suya(voz_id):                       # Chatterbox: lo que dijo en la última prueba
        if voz_gpu.ruta_prueba(voz_id).exists():
            return voz_gpu.ruta_prueba(voz_id)
        if voz_id == "chatterbox:clon" and voz_gpu.hay_muestra():
            return voz_gpu.ruta_muestra()             # aún sin prueba: tu grabación
        raise ValueError("Esta voz aún no tiene muestra: pulsa «Probar en mi GPU».")
    if not FORMATO.match(voz_id or ""):
        raise ValueError("Esa voz no existe.")
    carpeta = proyecto.RAIZ / "voces_muestra"
    carpeta.mkdir(exist_ok=True)
    destino = carpeta / f"{voz_id}.mp3"
    if not destino.exists() or destino.stat().st_size == 0:
        asyncio.run(_sintetizar(FRASE_MUESTRA, voz_id, "+0%", destino))
    return destino


async def _sintetizar(texto, voz, velocidad, destino):
    await edge_tts.Communicate(texto, voz, rate=velocidad).save(str(destino))


def _silencio(texto, destino):
    segundos = max(1.5, len(texto.split()) / PALABRAS_POR_SEGUNDO)
    medios.ffmpeg("-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", f"{segundos:.2f}",
                  "-b:a", "64k", destino)


def ejecutar(datos, avisar, solo=None, ejecutor=None):
    cfg = proyecto.config()["voz"]
    elegida = datos.get("voz") or cfg["voz"]          # la del video; si no tiene, la de Ajustes
    carpeta = proyecto.carpeta(datos["id"]) / "voz"
    carpeta.mkdir(exist_ok=True)
    if voz_gpu.es_suya(elegida) and not datos.get("simular"):
        if solo:
            escenas = [e for e in datos["escenas"] if e["n"] in solo]
        else:                                          # las que aún no tienen voz
            escenas = [e for e in datos["escenas"]
                       if not (e["audio"] and proyecto.absoluta(datos, e["audio"]).exists())]
        if escenas:
            voz_gpu.ejecutar(datos, avisar, escenas, elegida, ejecutor)
        else:
            avisar("Voz: todas las escenas ya están narradas.")
        return
    for e in datos["escenas"]:
        if solo and e["n"] not in solo:
            continue
        if e["audio"] and not solo and proyecto.absoluta(datos, e["audio"]).exists():
            continue
        destino = carpeta / f"escena_{e['n']:03d}.mp3"
        if datos.get("simular"):
            _silencio(e["narracion"], destino)
        else:
            for intento in range(3):
                try:
                    asyncio.run(_sintetizar(e["narracion"], elegida, cfg["velocidad"], destino))
                    break
                except Exception as err:      # la red falla a veces: se reintenta
                    if intento == 2:
                        raise
                    avisar(f"voz escena {e['n']}: {err}; reintento")
        e["audio"] = proyecto.relativa(datos, destino)
        e["duracion"] = round(medios.duracion(destino), 2)
        datos["mp4"] = None
        proyecto.guardar(datos)
    total = sum(e["duracion"] or 0 for e in datos["escenas"])
    avisar(f"Voz lista: {total / 60:.1f} min de narracion.")
