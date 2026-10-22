"""
Paso 1: el guion, partido en escenas.

Lo escribe Gemini (por defecto, con la clave gratis de la persona; ve tambien
la imagen de ejemplo del estilo si la hay), Claude por su CLI (va contra tu
suscripcion), un modelo local de Ollama (gratis, mas flojo) o, a mano, ChatGPT:
se copia el prompt y se pega la respuesta. Gemini sin clave = a mano.
Ademas de la narracion devuelve la «biblia» del video: el estilo y como es
cada personaje, en ingles. Esa biblia se repite en el prompt de cada imagen
y es lo que hace que las imagenes se parezcan entre si.

'continua' marca las escenas que siguen en el mismo sitio y momento: esas no
generan imagen nueva, reusan la anterior con otro movimiento de camara. Da
continuidad y ahorra tiempo.
"""
import json
import re
import shutil
import subprocess
import tempfile

import requests

from . import gemini, imagenes, openai_img, proyecto

PLANTILLA = """Eres guionista y director de un canal de YouTube de videos narrados.
Convierte el MATERIAL en un video de unos {minutos} minutos, narrado en espanol.

Reglas:
- Unas {escenas} escenas. Cada escena dura unos {segundos} segundos de voz: su narracion tiene unas {palabras} palabras (nunca mas de {max_palabras}).
- La narracion es para escuchar: frases claras, gancho fuerte al principio, cierre con llamada a la accion.
- TONO de la narracion (muy importante, respetalo en cada frase): {tono}
- Estilo visual pedido por el usuario: {estilo}
- "estilo_visual": UNA frase corta en ingles con el estilo (tecnica, paleta, luz). Se repetira en cada imagen.
- "personajes": los personajes o elementos recurrentes, con "descripcion_visual" en ingles muy concreta y corta (edad, pelo, ropa, colores) para que salgan siempre parecidos. Maximo 3.
- En cada escena:
  - "narracion": el texto que se lee (espanol).
  - "visual": prompt en ingles de la imagen: sujeto, accion, lugar, encuadre. Sin texto escrito en la imagen.
  - "personajes": lista de nombres de personajes que aparecen (puede estar vacia).
  - "continua": true si la escena sigue en el MISMO sitio y momento que la anterior (reusara su imagen). La primera siempre false. Nunca mas de 2 seguidas.

Responde SOLO con un JSON valido, sin texto alrededor, con esta forma:
{{"titulo": "...", "estilo_visual": "...", "personajes": [{{"nombre": "...", "descripcion_visual": "..."}}],
 "escenas": [{{"narracion": "...", "visual": "...", "personajes": [], "continua": false}}]}}

MATERIAL:
{texto}
"""


class ErrorGuion(Exception):
    pass


TONOS = {
    "humor": (
        "Divulgacion con humor, al estilo de los canales de historia animada tipo 'Ancient Life': "
        "habla al espectador de tu ('imagina que te despiertas en...'), cuenta 'un dia en la vida de' "
        "con detalles cotidianos concretos y sorprendentes, compara con la vida moderna de forma "
        "ironica, mete un chiste o una exageracion graciosa cada pocas frases sin perder el rigor de "
        "los datos, y deja remates cortos al final de las frases. Nada de solemnidad."),
    "documental": (
        "Documental serio y epico: narrador en tercera persona, ritmo pausado, datos precisos, "
        "tension narrativa y frases con peso. Sin chistes."),
    "infantil": (
        "Para ninos de 6 a 10 anos: frases muy cortas, palabras sencillas, preguntas al nino, "
        "entusiasmo y comparaciones con cosas que conocen. Nada que asuste."),
    "inspirador": (
        "Devocional e inspirador, al estilo de los canales cristianos de habitos tipo 'BibleFix': "
        "formato lista ('el habito numero uno es...'), hablale al espectador de tu con calma y "
        "calidez, une cada consejo practico a un versiculo de la Biblia (cita libro, capitulo y "
        "versiculo y parafrasea el texto con tus palabras), pon un ejemplo cotidiano de cada habito, "
        "frases cortas con pausas, esperanza sin sermonear, y cierra con una invitacion suave a "
        "ponerlo en practica manana mismo."),
    "misterio": (
        "Misterio e intriga: empieza con una pregunta inquietante, dosifica las revelaciones, "
        "deja cliffhangers al final de cada bloque y no cuentes la respuesta hasta el final."),
}


def tono_de(datos):
    t = (datos.get("tono") or "").strip()
    return TONOS.get(t.lower(), t) or "divulgativo y ameno"


def _claude(prompt, modelo):
    exe = shutil.which("claude")
    if not exe:
        raise ErrorGuion("No encuentro el CLI de Claude (claude). Instalalo e inicia sesion, "
                         "o pon \"motor\": \"ollama\" en config.json.")
    # En una carpeta vacia: asi no carga instrucciones de ningun proyecto.
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run(
            [exe, "-p", "--output-format", "json", "--model", modelo],
            input=prompt, capture_output=True, text=True, encoding="utf-8",
            cwd=tmp, timeout=900)
    if r.returncode != 0:
        raise ErrorGuion(f"Claude fallo: {(r.stderr or r.stdout)[:500]}")
    sobre = json.loads(r.stdout)
    if sobre.get("is_error"):
        raise ErrorGuion(f"Claude fallo: {sobre.get('result', '')[:500]}")
    return sobre.get("result", "")


def _ollama(prompt, modelo):
    try:
        r = requests.post("http://127.0.0.1:11434/api/generate",
                          json={"model": modelo, "prompt": prompt, "stream": False, "format": "json"},
                          timeout=1800)
    except requests.ConnectionError:
        raise ErrorGuion("Ollama no esta abierto (http://127.0.0.1:11434).")
    if r.status_code >= 400:
        raise ErrorGuion(f"Ollama fallo: {r.text[:300]}")
    return r.json().get("response", "")


def _extraer_json(texto):
    texto = texto.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", texto, re.S)
    if m:
        texto = m.group(1)
    ini, fin = texto.find("{"), texto.rfind("}")
    if ini < 0 or fin < 0:
        raise ErrorGuion("El modelo no ha devuelto un JSON.")
    return json.loads(texto[ini:fin + 1])


def _troceado(datos, palabras):
    """Modo prueba: el material tal cual, cortado en frases, sin llamar a nadie."""
    frases = re.split(r"(?<=[.!?;:])\s+", datos["texto"].strip())
    trozos, actual = [], ""
    for f in frases:
        if actual and len((actual + " " + f).split()) > palabras * 1.3:
            trozos.append(actual)
            actual = f
        else:
            actual = f"{actual} {f}".strip()
    if actual:
        trozos.append(actual)
    return {"titulo": datos["titulo"], "estilo_visual": datos.get("estilo") or "illustration",
            "personajes": [],
            "escenas": [{"narracion": t, "visual": t, "personajes": [], "continua": i % 3 == 2}
                        for i, t in enumerate(trozos)]}


# Por encima de esto el guion se escribe por capitulos: pedir 120 escenas de una
# vez hace que el modelo se quede corto (entrega 9 minutos en vez de 14).
MINUTOS_DE_UNA_VEZ = 3
MINUTOS_POR_CAPITULO = 2

PLANTILLA_INDICE = """Eres guionista de un canal de YouTube de videos narrados en espanol.
Vas a convertir el MATERIAL en un video de {minutos} minutos. Primero, solo el plan.

Devuelve SOLO un JSON valido con esta forma:
{{"titulo": "...",
 "estilo_visual": "UNA frase corta en ingles con el estilo visual (tecnica, paleta, luz). Estilo pedido: {estilo}",
 "personajes": [{{"nombre": "...", "descripcion_visual": "en ingles, concreta y corta: edad, pelo, ropa, colores"}}],
 "capitulos": [{{"titulo": "...", "resumen": "que se cuenta, 2-3 frases", "minutos": 2}}]}}

Reglas: {capitulos} capitulos cuyos minutos sumen {minutos}. Maximo 3 personajes.
El primer capitulo abre con un gancho fuerte; el ultimo cierra con una llamada a la accion.
Tono de todo el video: {tono}

MATERIAL:
{texto}
"""

PLANTILLA_CAPITULO = """Eres guionista de un canal de YouTube de videos narrados en espanol.
Escribe las escenas del CAPITULO {n} de {total} del video "{titulo}".

Capitulo: {cap_titulo}
De que va: {cap_resumen}
Lo que se conto en el capitulo anterior: {anterior}
Personajes del video: {personajes}

Reglas:
- Exactamente {escenas} escenas. Cada una dura unos {segundos} segundos de voz: su narracion tiene unas {palabras} palabras (nunca mas de {max_palabras}).
- La narracion sigue el hilo del capitulo anterior sin repetirlo. Frases claras, para escuchar.
- TONO (muy importante, respetalo en cada frase): {tono}
- En cada escena: "narracion" (espanol), "visual" (prompt en ingles de la imagen: sujeto, accion, lugar, encuadre; sin texto en la imagen), "personajes" (nombres que aparecen), "continua" (true si sigue en el MISMO sitio y momento que la anterior; nunca mas de 2 seguidas).

Devuelve SOLO un JSON valido: {{"escenas": [{{"narracion": "...", "visual": "...", "personajes": [], "continua": false}}]}}

MATERIAL DE REFERENCIA:
{texto}
"""


def _por_capitulos(datos, cfg, llamar, nombre, avisar):
    segundos = cfg["segundos_por_escena"]
    palabras = round(segundos * cfg["palabras_por_minuto"] / 60)
    n_caps = max(2, round(datos["minutos"] / MINUTOS_POR_CAPITULO))
    avisar(f"{nombre} escribe el indice ({n_caps} capitulos)...")
    indice = llamar(PLANTILLA_INDICE.format(
        minutos=datos["minutos"], capitulos=n_caps,
        estilo=datos.get("estilo") or "el que mejor encaje con el tema", tono=tono_de(datos), texto=datos["texto"]))
    caps = indice.get("capitulos") or []
    if not caps:
        raise ErrorGuion("El indice ha salido sin capitulos.")
    # Los minutos de cada capitulo se reescalan para que sumen lo pedido.
    suma = sum(float(c.get("minutos") or 1) for c in caps)
    personajes = "; ".join(f"{p.get('nombre')}: {p.get('descripcion_visual')}"
                           for p in indice.get("personajes", [])) or "ninguno fijo"
    escenas, anterior = [], "nada, es el primero"
    for i, c in enumerate(caps, 1):
        minutos = float(c.get("minutos") or 1) * datos["minutos"] / suma
        n = max(2, round(minutos * 60 / segundos))
        avisar(f"{nombre} escribe el capitulo {i}/{len(caps)}: {c.get('titulo', '')} ({n} escenas)")
        r = llamar(PLANTILLA_CAPITULO.format(
            n=i, total=len(caps), titulo=indice.get("titulo") or datos["titulo"],
            cap_titulo=c.get("titulo", ""), cap_resumen=c.get("resumen", ""), anterior=anterior,
            personajes=personajes, escenas=n, segundos=segundos, palabras=palabras,
            max_palabras=round(palabras * 1.5), texto=datos["texto"], tono=tono_de(datos)))
        nuevas = r.get("escenas") or []
        if nuevas:
            nuevas[0]["continua"] = False          # un capitulo nuevo abre plano nuevo
        escenas.extend(nuevas)
        anterior = f"{c.get('titulo', '')}: {c.get('resumen', '')}"
    return {"titulo": indice.get("titulo"), "estilo_visual": indice.get("estilo_visual", ""),
            "personajes": indice.get("personajes", []), "escenas": escenas}


def motor_efectivo(datos=None):
    """El motor que de verdad se usa: Gemini sin clave pasa a OpenAI si hay su clave,
    y si no, a «a mano». OpenAI sin clave, a mano."""
    if datos and datos.get("simular"):
        return "prueba"
    motor = proyecto.config()["guion"]["motor"]
    if motor == "gemini" and not gemini.hay_clave():
        return "openai" if openai_img.hay_clave() else "manual"
    if motor == "openai" and not openai_img.hay_clave():
        return "manual"
    return motor


NOTA_REFERENCIA = ("Se adjunta una IMAGEN DE EJEMPLO del estilo visual que quiere el usuario: "
                   "\"estilo_visual\" debe describir con precision su estilo (tecnica, paleta, luz, "
                   "trazo), no su contenido.\n\n")


def ejecutar(datos, avisar):
    cfg = proyecto.config()["guion"]
    motor = motor_efectivo(datos)
    segundos = cfg["segundos_por_escena"]
    escenas = max(3, round(datos["minutos"] * 60 / segundos))
    palabras = round(segundos * cfg["palabras_por_minuto"] / 60)

    if motor == "prueba":
        g = _troceado(datos, palabras)
    elif motor == "manual":
        avisar("Guion a mano: copia el prompt, pegalo en ChatGPT y pega aqui su respuesta."
               + (" (Con tu clave de Gemini u OpenAI se escribe solo.)"
                  if cfg["motor"] in ("gemini", "openai") else ""))
        return
    else:
        if motor == "gemini":
            nombre = f"Gemini ({gemini.modelo_texto()})"
            ref = imagenes.referencia(datos)
            extra = NOTA_REFERENCIA if ref else ""
            llamar = lambda p: _extraer_json(gemini.texto(extra + p, avisar,
                                                          imagenes=[ref] if ref else []))
        elif motor == "openai":
            nombre = f"OpenAI ({openai_img.modelo_texto()})"
            ref = imagenes.referencia(datos)
            extra = NOTA_REFERENCIA if ref else ""
            llamar = lambda p: _extraer_json(openai_img.texto(extra + p, avisar,
                                                              imagenes=[ref] if ref else []))
        elif motor == "ollama":
            nombre = f"Ollama ({cfg['modelo_ollama']})"
            llamar = lambda p: _extraer_json(_ollama(p, cfg["modelo_ollama"]))
        else:
            nombre = "Claude"
            llamar = lambda p: _extraer_json(_claude(p, cfg["modelo_claude"]))
        if datos["minutos"] > MINUTOS_DE_UNA_VEZ:
            g = _por_capitulos(datos, cfg, llamar, nombre, avisar)
        else:
            prompt = PLANTILLA.format(
                minutos=datos["minutos"], escenas=escenas, segundos=segundos,
                palabras=palabras, max_palabras=round(palabras * 1.5),
                estilo=datos.get("estilo") or "el que mejor encaje con el tema", tono=tono_de(datos),
                texto=datos["texto"])
            avisar(f"{nombre} escribe el guion ({escenas} escenas)...")
            g = llamar(prompt)
    aplicar(datos, g)
    avisar(f"Guion listo: {len(datos['escenas'])} escenas.")


def prompt_manual(datos):
    """El prompt para pegar en ChatGPT (o cualquier chat gratis) cuando el guion es a mano."""
    cfg = proyecto.config()["guion"]
    segundos = cfg["segundos_por_escena"]
    palabras = round(segundos * cfg["palabras_por_minuto"] / 60)
    return PLANTILLA.format(
        minutos=datos["minutos"], escenas=max(3, round(datos["minutos"] * 60 / segundos)),
        segundos=segundos, palabras=palabras, max_palabras=round(palabras * 1.5),
        estilo=datos.get("estilo") or "el que mejor encaje con el tema", tono=tono_de(datos), texto=datos["texto"])


def pegar(datos, texto):
    """La respuesta del chat, pegada en la pantalla."""
    try:
        g = _extraer_json(texto)
    except (ValueError, ErrorGuion) as err:
        raise ErrorGuion(f"No reconozco un JSON en lo pegado: {err}")
    aplicar(datos, g)


def aplicar(datos, g):
    if not g.get("escenas"):
        raise ErrorGuion("El guion ha salido sin escenas.")

    datos["biblia"] = {
        "titulo": g.get("titulo") or datos["titulo"],
        "estilo_visual": g.get("estilo_visual", ""),
        "personajes": g.get("personajes", []),
    }
    datos["escenas"] = []
    for i, e in enumerate(g["escenas"]):
        datos["escenas"].append({
            "n": i + 1,
            "narracion": e.get("narracion", "").strip(),
            "visual": e.get("visual", "").strip(),
            "personajes": e.get("personajes") or [],
            "continua": bool(e.get("continua")) and i > 0,
            "audio": None, "duracion": None, "imagen": None,
        })
    datos["mp4"] = None
