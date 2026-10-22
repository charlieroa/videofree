"""
Nichos de YouTube: qué temas están dando vistas AHORA, para elegir de qué hacer videos.

Usa la YouTube Data API v3 con la clave de Google de la persona (gratis:
console.cloud.google.com -> «YouTube Data API v3» -> Habilitar -> Credenciales ->
Clave de API). Puede ser la MISMA clave que la de Gemini si se habilita la API en
su proyecto; si no hay clave de YouTube, se prueba con la de Gemini.

Cuota gratis: 10.000 unidades al día. Cada nicho cuesta ~102 (search = 100,
videos y channels = 1 cada uno), asi que el resultado se guarda un dia en
canal/<usuario>/nichos/ y volver a mirarlo no gasta nada.

Para cada nicho se miran los videos LARGOS (mas de 3 min: VideoFree hace 16:9,
no Shorts) mas vistos del ultimo mes en espanol y se calcula:

  demanda       mediana de vistas por dia desde que se publico
  competencia   mediana de suscriptores de los canales que salen
  oportunidad   % de esos videos que son de canales pequenos (< 50.000
                suscriptores) y aun asi tienen mas vistas que suscriptores:
                si pasa a menudo, el nicho premia el contenido y no el tamano
"""
import json
import re
import statistics
import time
from datetime import datetime, timedelta, timezone

import requests

from . import canal, gemini, proyecto

BASE = "https://www.googleapis.com/youtube/v3"
CLAVE_SECRETO = "youtube_clave"
CANAL_PEQUENO = 50_000
MIN_SEGUNDOS = 180

# Nichos que encajan con videos narrados con imagenes (lo que hace VideoFree).
# 'tono' es el de la pantalla de nuevo video, para que «Usar este tema» lo deje puesto.
NICHOS = [
    {"id": "historia", "nombre": "Historia antigua", "consulta": "historia antigua documental", "tono": "humor"},
    {"id": "vida-pasado", "nombre": "Cómo se vivía en el pasado", "consulta": "un día en la vida de un romano", "tono": "humor"},
    {"id": "misterios", "nombre": "Misterios sin resolver", "consulta": "misterios sin resolver", "tono": "misterio"},
    {"id": "terror", "nombre": "Historias de terror", "consulta": "historias de terror narradas", "tono": "misterio"},
    {"id": "curiosidades", "nombre": "Curiosidades y datos", "consulta": "curiosidades que no sabías", "tono": "humor"},
    {"id": "biblia", "nombre": "Devocional cristiano", "consulta": "hábitos cristianos biblia", "tono": "inspirador"},
    {"id": "estoicismo", "nombre": "Estoicismo y motivación", "consulta": "estoicismo lecciones de vida", "tono": "inspirador"},
    {"id": "finanzas", "nombre": "Finanzas personales", "consulta": "finanzas personales ahorrar dinero", "tono": ""},
    {"id": "cuentos", "nombre": "Cuentos infantiles", "consulta": "cuentos infantiles para dormir", "tono": "infantil"},
    {"id": "espacio", "nombre": "Ciencia y espacio", "consulta": "universo espacio documental", "tono": "documental"},
    {"id": "animales", "nombre": "Animales increíbles", "consulta": "animales increíbles datos", "tono": "documental"},
    {"id": "biografias", "nombre": "Biografías", "consulta": "biografía la historia de", "tono": "documental"},
    {"id": "guerras", "nombre": "Guerras y batallas", "consulta": "batallas de la historia documental", "tono": "documental"},
    {"id": "ia", "nombre": "Tecnología e IA", "consulta": "inteligencia artificial explicado", "tono": ""},
    {"id": "salud", "nombre": "Salud y hábitos", "consulta": "hábitos saludables cuerpo humano", "tono": ""},
]


class ErrorNichos(Exception):
    pass


# --------------------------------------------------------------- la clave

def clave():
    try:
        propia = (proyecto.secretos().get(CLAVE_SECRETO) or "").strip()
    except RuntimeError:
        return ""
    return propia or gemini.clave()


def tiene_clave_propia():
    try:
        return bool((proyecto.secretos().get(CLAVE_SECRETO) or "").strip())
    except RuntimeError:
        return False


def guardar_clave(valor):
    proyecto.guardar_secreto(CLAVE_SECRETO, (valor or "").strip())


def _get(ruta, k=None, **params):
    k = k or clave()
    if not k:
        raise ErrorNichos("Falta la clave de YouTube. Créala gratis en console.cloud.google.com "
                          "(YouTube Data API v3) y pégala aquí.")
    try:
        r = requests.get(f"{BASE}/{ruta}", params={**params, "key": k}, timeout=30)
    except requests.RequestException as err:
        raise ErrorNichos(f"Sin conexión con YouTube: {err}")
    if r.status_code == 200:
        return r.json()
    try:
        err = r.json().get("error", {})
        motivo = (err.get("errors") or [{}])[0].get("reason", "")
        texto = err.get("message", r.text)
    except ValueError:
        motivo, texto = "", r.text
    if motivo in ("quotaExceeded", "dailyLimitExceeded"):
        raise ErrorNichos("Se acabó la cuota de YouTube de hoy (10.000 unidades). Vuelve mañana: "
                          "lo ya mirado sigue guardado.")
    if motivo in ("accessNotConfigured", "SERVICE_DISABLED") or "has not been used" in texto:
        raise ErrorNichos("Esa clave no tiene activada la «YouTube Data API v3». Actívala en "
                          "console.cloud.google.com → APIs y servicios → Biblioteca.")
    if r.status_code in (400, 403) and re.search(r"API key|keyInvalid|API_KEY", texto + motivo, re.I):
        raise ErrorNichos("YouTube no acepta esa clave. Revisa que la copiaste entera.")
    raise ErrorNichos(f"YouTube ({r.status_code}): {texto[:300]}")


def probar(k):
    """Una llamada de 1 unidad para ver si la clave sirve con YouTube."""
    try:
        _get("videoCategories", k, part="snippet", regionCode="US", hl="es")
    except ErrorNichos as err:
        return False, str(err)
    return True, "Clave válida."


# ------------------------------------------------------------------ cache

def _cache(nombre):
    c = canal.carpeta() / "nichos"
    c.mkdir(exist_ok=True)
    return c / f"{re.sub(r'[^a-z0-9-]+', '-', nombre.lower())[:60]}.json"


def _de_cache(nombre):
    ruta = _cache(nombre)
    if ruta.exists():
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        if datos.get("dia") == time.strftime("%Y-%m-%d"):
            return datos
    return None


def _a_cache(nombre, datos):
    datos["dia"] = time.strftime("%Y-%m-%d")
    _cache(nombre).write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    return datos


# ---------------------------------------------------------------- calculo

def _segundos(iso):
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def _dias_desde(fecha):
    t = datetime.fromisoformat(fecha.replace("Z", "+00:00"))
    return max((datetime.now(timezone.utc) - t).total_seconds() / 86400, 1.0)


def _videos(ids):
    if not ids:
        return []
    return _get("videos", part="snippet,statistics,contentDetails", id=",".join(ids)).get("items", [])


def _suscriptores(ids_canal):
    subs = {}
    ids = list(dict.fromkeys(ids_canal))
    for i in range(0, len(ids), 50):
        for c in _get("channels", part="statistics", id=",".join(ids[i:i + 50])).get("items", []):
            st = c.get("statistics", {})
            subs[c["id"]] = None if st.get("hiddenSubscriberCount") else int(st.get("subscriberCount", 0))
    return subs


def _ficha(v, subs):
    st, sn = v.get("statistics", {}), v["snippet"]
    vistas = int(st.get("viewCount", 0))
    s = subs.get(sn["channelId"])
    return {"id": v["id"], "titulo": sn["title"], "canal": sn["channelTitle"],
            "url": f"https://www.youtube.com/watch?v={v['id']}",
            "miniatura": (sn.get("thumbnails", {}).get("medium") or {}).get("url", ""),
            "publicado": sn["publishedAt"][:10], "vistas": vistas,
            "vistas_dia": round(vistas / _dias_desde(sn["publishedAt"])),
            "likes": int(st.get("likeCount", 0)), "suscriptores": s,
            "minutos": round(_segundos(v["contentDetails"].get("duration")) / 60, 1),
            "sorpresa": bool(s is not None and s < CANAL_PEQUENO and vistas > max(s, 1))}


def analizar(consulta, dias=30, idioma="es", forzar=False):
    """Los videos largos mas vistos del ultimo mes para una busqueda, con sus numeros."""
    consulta = consulta.strip()
    if not consulta:
        raise ErrorNichos("Escribe un tema para buscar.")
    clave_cache = f"busqueda-{idioma}-{dias}-{consulta}"
    if not forzar and (hecho := _de_cache(clave_cache)):
        return hecho
    desde = (datetime.now(timezone.utc) - timedelta(days=dias)).strftime("%Y-%m-%dT%H:%M:%SZ")
    encontrados = _get("search", part="id", q=consulta, type="video", order="viewCount",
                       publishedAfter=desde, relevanceLanguage=idioma, maxResults=50)
    ids = [i["id"]["videoId"] for i in encontrados.get("items", []) if i.get("id", {}).get("videoId")]
    videos = [v for v in _videos(ids) if _segundos(v["contentDetails"].get("duration")) > MIN_SEGUNDOS]
    subs = _suscriptores(v["snippet"]["channelId"] for v in videos)
    fichas = sorted((_ficha(v, subs) for v in videos), key=lambda f: f["vistas"], reverse=True)[:25]
    conocidos = [f["suscriptores"] for f in fichas if f["suscriptores"] is not None]
    resumen = {
        "consulta": consulta, "dias": dias, "videos": len(fichas),
        "demanda": round(statistics.median(f["vistas_dia"] for f in fichas)) if fichas else 0,
        "competencia": round(statistics.median(conocidos)) if conocidos else 0,
        "oportunidad": round(100 * sum(f["sorpresa"] for f in fichas) / len(fichas)) if fichas else 0,
        "minutos_tipicos": round(statistics.median(f["minutos"] for f in fichas), 1) if fichas else 0,
        "top": fichas[:12],
    }
    return _a_cache(clave_cache, resumen)


def catalogo():
    """Los nichos de la lista, con sus numeros si ya se miraron hoy (no gasta cuota)."""
    salida = []
    for n in NICHOS:
        hecho = _de_cache(f"busqueda-es-30-{n['consulta']}")
        salida.append({**n, "datos": hecho})
    return salida


def nicho(nid, forzar=False):
    n = next((x for x in NICHOS if x["id"] == nid), None)
    if not n:
        raise ErrorNichos("Ese nicho no existe.")
    return {**n, "datos": analizar(n["consulta"], forzar=forzar)}


def tendencias(region="CO", forzar=False):
    """Lo mas visto HOY en un pais (la lista de tendencias de YouTube), por categoria. ~2 unidades."""
    region = (region or "CO").upper()[:2]
    clave_cache = f"tendencias-{region}"
    if not forzar and (hecho := _de_cache(clave_cache)):
        return hecho
    cats = {c["id"]: c["snippet"]["title"] for c in
            _get("videoCategories", part="snippet", regionCode=region, hl="es").get("items", [])}
    items = _get("videos", part="snippet,statistics,contentDetails", chart="mostPopular",
                 regionCode=region, maxResults=50).get("items", [])
    grupos = {}
    for v in items:
        cid = v["snippet"].get("categoryId", "")
        g = grupos.setdefault(cid, {"categoria": cats.get(cid, "Otros"), "videos": 0, "vistas": 0, "ejemplos": []})
        g["videos"] += 1
        g["vistas"] += int(v.get("statistics", {}).get("viewCount", 0))
        if len(g["ejemplos"]) < 3:
            g["ejemplos"].append({"titulo": v["snippet"]["title"], "canal": v["snippet"]["channelTitle"],
                                  "url": f"https://www.youtube.com/watch?v={v['id']}"})
    lista = sorted(grupos.values(), key=lambda g: g["videos"], reverse=True)
    return _a_cache(clave_cache, {"region": region, "categorias": lista})
