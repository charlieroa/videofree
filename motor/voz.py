"""
Paso 2: la voz de cada escena.

El catalogo, en este orden:
  - Puck (la de serie), Charon y Kore: Gemini TTS, con la clave de Gemini de la
    persona. El tono del video se da con un prefijo corto en el propio texto
    (motor/gemini.py). Sin clave de Gemini se narra con Jorge y el registro lo dice.
  - Voces gratis y sin clave de edge-tts (Microsoft), de varios paises (GRATIS), y
    Jorge (es-MX-JorgeNeural) al final.

Los proyectos viejos con otra voz de edge-tts siguen funcionando. Se sintetiza escena a escena porque la duracion de cada
audio es la que manda: la animacion de cada imagen dura lo que dura su frase.

En modo prueba no se llama a nada: se pone silencio con la duracion que
tendria la frase leida.
"""
import asyncio
import re

import edge_tts

from . import gemini, medios, proyecto

PALABRAS_POR_SEGUNDO = 2.2
FORMATO = re.compile(r"^[a-z]{2}-[A-Z]{2}-[A-Za-z]+Neural$")
JORGE = "es-MX-JorgeNeural"
# Voces de edge-tts (gratis, sin clave) que se ofrecen ademas de Jorge.
GRATIS = [
    ("es-CO-GonzaloNeural", "Gonzalo", "Colombia", "hombre"),
    ("es-CO-SalomeNeural", "Salomé", "Colombia", "mujer"),
    ("es-MX-DaliaNeural", "Dalia", "México", "mujer"),
    ("es-US-AlonsoNeural", "Alonso", "Latino (EE. UU.)", "hombre"),
    ("es-US-PalomaNeural", "Paloma", "Latino (EE. UU.)", "mujer"),
    ("es-AR-TomasNeural", "Tomás", "Argentina", "hombre"),
    ("es-AR-ElenaNeural", "Elena", "Argentina", "mujer"),
    ("es-ES-AlvaroNeural", "Álvaro", "España", "hombre"),
    ("es-ES-ElviraNeural", "Elvira", "España", "mujer"),
]
FRASE_MUESTRA = "Hola, así va a sonar la narración de tu video. ¿Te gusta cómo suena?"
def catalogo():
    """Primero las 3 de Gemini (Puck es la de serie), luego las gratis y Jorge al final."""
    con_clave = gemini.hay_clave()
    voces = [{"id": vid, "nombre": v["nombre"], "pais": "Gemini", "genero": v["genero"],
              "detalle": v["detalle"], "gemini": True, "lista": con_clave}
             for vid, v in gemini.VOCES.items()]
    voces += [{"id": vid, "nombre": nombre, "pais": pais, "genero": genero,
               "detalle": "gratis, sin clave", "gemini": False, "lista": True}
              for vid, nombre, pais, genero in GRATIS]
    voces.append({"id": JORGE, "nombre": "Jorge", "pais": "México", "genero": "hombre",
                  "detalle": "gratis, sin clave", "gemini": False, "lista": True})
    return voces


def valida(voz_id):
    return bool(FORMATO.match(voz_id or "")) or gemini.es_suya(voz_id)


def muestra(voz_id):
    """Un mp3 corto con esa voz para escucharla antes de elegirla. Se guarda y se reusa."""
    if not valida(voz_id):
        raise ValueError("Esa voz no existe.")
    carpeta = proyecto.RAIZ / "voces_muestra"
    carpeta.mkdir(exist_ok=True)
    destino = carpeta / f"{voz_id.replace(':', '_')}.mp3"
    if destino.exists() and destino.stat().st_size > 0:
        return destino
    if gemini.es_suya(voz_id):
        if not gemini.hay_clave():
            raise ValueError("Esta voz es de Gemini: pega tu clave en el Asistente para escucharla.")
        gemini.voz(FRASE_MUESTRA, voz_id, destino)
    else:
        asyncio.run(_sintetizar(FRASE_MUESTRA, voz_id, "+0%", destino))
    return destino


async def _sintetizar(texto, voz, velocidad, destino):
    await edge_tts.Communicate(texto, voz, rate=velocidad).save(str(destino))


def _silencio(texto, destino):
    segundos = max(1.5, len(texto.split()) / PALABRAS_POR_SEGUNDO)
    medios.ffmpeg("-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", f"{segundos:.2f}",
                  "-b:a", "64k", destino)


def ejecutar(datos, avisar, solo=None):
    cfg = proyecto.config()["voz"]
    elegida = datos.get("voz") or cfg["voz"]          # la del video; si no tiene, la de Ajustes
    carpeta = proyecto.carpeta(datos["id"]) / "voz"
    carpeta.mkdir(exist_ok=True)
    if gemini.es_suya(elegida) and not datos.get("simular") and not gemini.hay_clave():
        # Puck es la de serie: sin clave de Gemini el video no se queda parado, sale con Jorge.
        avisar(f"Sin clave de Gemini no se puede usar {elegida.split(':')[1]}: narro con Jorge "
               f"(gratis). Pega tu clave de Gemini en el Asistente para usar Puck, Charon o Kore.")
        elegida = JORGE
    for e in datos["escenas"]:
        if solo and e["n"] not in solo:
            continue
        if e["audio"] and not solo and proyecto.absoluta(datos, e["audio"]).exists():
            continue
        destino = carpeta / f"escena_{e['n']:03d}.mp3"
        if datos.get("simular"):
            _silencio(e["narracion"], destino)
        elif gemini.es_suya(elegida):
            # Sin reintento propio: gemini._post ya espera ante 429 y corta con un
            # mensaje claro si se acaba la cuota (no se mezclan voces en un video).
            avisar(f"Voz escena {e['n']} con Gemini ({elegida.split(':')[1]})")
            gemini.voz(e["narracion"], elegida, destino, datos.get("tono", ""), avisar)
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
