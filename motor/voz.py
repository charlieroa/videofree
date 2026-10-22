"""
Paso 2: la voz de cada escena.

El catalogo, en este orden:
  - Puck (la de serie), Charon y Kore: Gemini TTS, con la clave de Gemini de la
    persona. El tono del video se da con un prefijo corto en el propio texto
    (motor/gemini.py). SIN clave de Gemini se narra con Jorge. Solo si en
    config.json se pone "voz": {"puter": true}, las narra el NAVEGADOR con Puter.js
    (puter.com: cada persona entra con su cuenta gratis de Puter y el gasto va a
    esa cuenta). Este paso no puede llamar a Puter: marca el video con
    'voz_navegador', espera, y la pestaña abierta narra cada escena y la sube
    (POST /api/proyectos/<id>/escena/<n>/audio).
  - Voces gratis y sin clave de edge-tts (Microsoft), de varios paises (GRATIS), y
    Jorge (es-MX-JorgeNeural) al final.

Los proyectos viejos con otra voz de edge-tts siguen funcionando. Se sintetiza escena a escena porque la duracion de cada
audio es la que manda: la animacion de cada imagen dura lo que dura su frase.

En modo prueba no se llama a nada: se pone silencio con la duracion que
tendria la frase leida.
"""
import asyncio
import re
import time

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
    """Primero las 3 de Gemini (Puck es la de serie), luego las gratis y Jorge al final.

    Las de Gemini necesitan la clave de Gemini (gratis); sin ella el video sale con
    Jorge. Con "voz": {"puter": true} en config.json las narra el navegador con Puter.
    """
    con_clave = gemini.hay_clave()
    puter = not con_clave and bool(proyecto.config()["voz"].get("puter"))
    voces = [{"id": vid, "nombre": v["nombre"], "pais": "Gemini", "genero": v["genero"],
              "detalle": v["detalle"], "gemini": True, "lista": con_clave or puter, "puter": puter}
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


ESPERA_MAX_S = 15 * 60          # sin ninguna escena nueva en este tiempo, se corta
ESPERA_PRIMERA_S = 3 * 60       # sin la primera escena en este tiempo, se narra con Jorge
SIN_SALDO = {}                  # pid -> motivo: la pestaña avisa que Puter no tiene saldo


def puter_sin_saldo(pid, motivo):
    SIN_SALDO[pid] = motivo or "sin saldo"


def _esperar_navegador(datos, elegida, avisar, solo):
    """Sin clave de Gemini: la pestaña narra con Puter y sube cada escena; aqui se espera."""
    if solo:
        for e in datos["escenas"]:
            if e["n"] in solo:
                e["audio"], e["duracion"] = None, None
    SIN_SALDO.pop(datos["id"], None)
    datos["voz_navegador"] = elegida
    proyecto.guardar(datos)
    nombre = elegida.split(":", 1)[1]
    avisar(f"Narrando con {nombre} en tu navegador (cuenta gratis de Puter): deja esta "
           f"pestaña abierta. Si te lo pide, pulsa «Conectar Puter».")
    hechas, ultimo = -1, time.time()
    try:
        while True:
            fresco = proyecto.leer(datos["id"])
            faltan = [e for e in fresco["escenas"] if not e.get("audio")]
            listas = len(fresco["escenas"]) - len(faltan)
            if listas != hechas:
                hechas, ultimo = listas, time.time()
            if not faltan:
                break
            if datos["id"] in SIN_SALDO:
                break
            if hechas == 0 and time.time() - ultimo > ESPERA_PRIMERA_S:
                SIN_SALDO[datos["id"]] = "nadie conectó Puter"     # no se queda parado: Jorge
                break
            if time.time() - ultimo > ESPERA_MAX_S:
                raise RuntimeError(f"El navegador no ha narrado ninguna escena en {ESPERA_MAX_S // 60} "
                                   f"min. Abre el vídeo, conecta Puter y vuelve a pulsar «2 · Voz», "
                                   f"o pega tu clave de Gemini, o elige una voz gratis.")
            time.sleep(2)
    finally:
        fresco = proyecto.leer(datos["id"])
        for e, f in zip(datos["escenas"], fresco["escenas"]):   # lo que subio el navegador
            e["audio"], e["duracion"] = f.get("audio"), f.get("duracion")
        datos["voz_navegador"] = None
        proyecto.guardar(datos)
    datos["mp4"] = None
    if SIN_SALDO.pop(datos["id"], None):
        # Sin saldo en Puter: TODO el video con Jorge (no se mezclan dos voces en un video).
        avisar(f"Puter no ha narrado (sin saldo o sin conectar): narro todo el vídeo con Jorge (gratis). "
               f"Para usar {nombre} gratis de verdad, pega tu clave de Gemini en el Asistente.")
        for e in datos["escenas"]:
            e["audio"], e["duracion"] = None, None
        datos["voz"] = JORGE
        proyecto.guardar(datos)
        ejecutar(datos, avisar)
        return
    total = sum(e["duracion"] or 0 for e in datos["escenas"])
    avisar(f"Voz lista: {total / 60:.1f} min de narracion (Puter).")


def guardar_audio(datos, e, crudo):
    """Un audio de escena que manda el navegador (Puter): se pasa a mp3 y se mide."""
    import tempfile
    from pathlib import Path
    carpeta = proyecto.carpeta(datos["id"]) / "voz"
    carpeta.mkdir(exist_ok=True)
    destino = carpeta / f"escena_{e['n']:03d}.mp3"
    with tempfile.TemporaryDirectory() as tmp:
        origen = Path(tmp) / "entrada"
        origen.write_bytes(crudo)
        medios.ffmpeg("-i", origen, "-ac", 1, "-b:a", "128k", destino)
    e["audio"] = proyecto.relativa(datos, destino)
    e["duracion"] = round(medios.duracion(destino), 2)
    datos["mp4"] = None
    proyecto.guardar(datos)


def ejecutar(datos, avisar, solo=None):
    cfg = proyecto.config()["voz"]
    elegida = datos.get("voz") or cfg["voz"]          # la del video; si no tiene, la de Ajustes
    carpeta = proyecto.carpeta(datos["id"]) / "voz"
    carpeta.mkdir(exist_ok=True)
    if gemini.es_suya(elegida) and not datos.get("simular") and not gemini.hay_clave():
        if cfg.get("puter"):
            _esperar_navegador(datos, elegida, avisar, solo)
            return
        # Puter ya no va por defecto: su saldo gratis no da para un video largo.
        avisar(f"Sin clave de Gemini no hay {elegida.split(':')[1]}: narro con Jorge (gratis). "
               f"Pega tu clave de Gemini (gratis) en el Asistente para usar Puck, Charon o Kore.")
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
