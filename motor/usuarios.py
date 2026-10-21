"""
Las cuentas: quien entra, y de quien es cada cosa.

Sin servicios de fuera: las contrasenas se guardan con PBKDF2 (sal propia por
usuario, 200 000 vueltas) en usuarios.json, y las sesiones son un token
aleatorio en una cookie httponly, apuntado en sesiones.json para que reiniciar
el programa no saque a nadie. Los dos ficheros estan en .gitignore.

ACTUAL es el usuario de la peticion o del trabajo en curso. Lo pone el
middleware de app.py en cada peticion y _correr en cada hilo de trabajo; de el
dependen los secretos (proyecto.secretos) y la GPU (gpu.credenciales), que son
de cada persona.

Modo local (el normal): quien abre la app desde el mismo PC entra sin cuenta.
Si no hay usuarios se crea uno llamado "local" sin contrasena; si hay uno, se
entra con ese; si hay varios, con el mas antiguo, y la pantalla deja cambiar de
uno a otro sin contrasena. Las peticiones que llegan de otra maquina (si alguien
arranca con --host 0.0.0.0) siguen pidiendo usuario y contrasena.
"""
import contextvars
import ipaddress
import os
import hashlib
import hmac
import json
import re
import secrets
import threading
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
USUARIOS = RAIZ / "usuarios.json"
SESIONES = RAIZ / "sesiones.json"
COOKIE = "vs_sesion"
VUELTAS = 200_000
DURACION_SESION = 60 * 60 * 24 * 30          # 30 dias

ACTUAL = contextvars.ContextVar("usuario", default=None)

_cerrojo = threading.Lock()


class ErrorUsuario(Exception):
    pass


def _leer(ruta):
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else {}


def _escribir(ruta, datos):
    tmp = ruta.with_suffix(".tmp")
    tmp.write_text(json.dumps(datos, indent=2), encoding="utf-8")
    tmp.replace(ruta)


def _hash(clave, sal):
    return hashlib.pbkdf2_hmac("sha256", clave.encode(), bytes.fromhex(sal), VUELTAS).hex()


def hay_usuarios():
    return bool(_leer(USUARIOS))


def crear(nombre, clave):
    nombre = (nombre or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9_.-]{3,30}", nombre):
        raise ErrorUsuario("El usuario: de 3 a 30 letras, numeros, punto, guion o guion bajo.")
    if len(clave or "") < 8:
        raise ErrorUsuario("La contraseña tiene que tener al menos 8 caracteres.")
    with _cerrojo:
        todos = _leer(USUARIOS)
        if nombre in todos:
            raise ErrorUsuario("Ese usuario ya existe.")
        sal = secrets.token_hex(16)
        todos[nombre] = {"sal": sal, "hash": _hash(clave, sal), "creado": time.strftime("%Y-%m-%d %H:%M:%S")}
        _escribir(USUARIOS, todos)
    return nombre


def cambiar_clave(nombre, clave):
    if len(clave or "") < 8:
        raise ErrorUsuario("La contraseña tiene que tener al menos 8 caracteres.")
    with _cerrojo:
        todos = _leer(USUARIOS)
        if nombre not in todos:
            raise ErrorUsuario("No existe ese usuario.")
        sal = secrets.token_hex(16)
        todos[nombre].update(sal=sal, hash=_hash(clave, sal))
        _escribir(USUARIOS, todos)


def comprobar(nombre, clave):
    nombre = (nombre or "").strip().lower()
    u = _leer(USUARIOS).get(nombre)
    if not u or not u.get("hash"):               # "local" no tiene contrasena: no se entra con una
        _hash(clave or "", "00" * 16)            # mismo tiempo exista o no el usuario
        return None
    return nombre if hmac.compare_digest(u["hash"], _hash(clave or "", u["sal"])) else None


def abrir_sesion(nombre):
    token = secrets.token_urlsafe(32)
    with _cerrojo:
        s = _leer(SESIONES)
        ahora = time.time()
        s = {t: v for t, v in s.items() if v["caduca"] > ahora}   # de paso, limpia las viejas
        s[token] = {"usuario": nombre, "caduca": ahora + DURACION_SESION}
        _escribir(SESIONES, s)
    return token


def cerrar_sesion(token):
    with _cerrojo:
        s = _leer(SESIONES)
        if s.pop(token or "", None):
            _escribir(SESIONES, s)


def de_sesion(token):
    if not token:
        return None
    v = _leer(SESIONES).get(token)
    if not v or v["caduca"] < time.time():
        return None
    return v["usuario"] if v["usuario"] in _leer(USUARIOS) else None


USUARIO_LOCAL = "local"
SIN_LOGIN = os.environ.get("VIDEOFREE_SIN_LOGIN", "1") != "0"


def nombres():
    """Los usuarios, del mas antiguo al mas nuevo."""
    todos = _leer(USUARIOS)
    return sorted(todos, key=lambda n: (todos[n].get("creado", ""), n))


def es_local(scope):
    """La peticion viene de este mismo PC y no pasa por un proxy."""
    if not SIN_LOGIN:
        return False
    cabeceras = dict(scope.get("headers") or [])
    if b"x-forwarded-for" in cabeceras or b"forwarded" in cabeceras:
        return False
    cliente = (scope.get("client") or ("", 0))[0]
    try:
        return ipaddress.ip_address(cliente).is_loopback
    except ValueError:
        return cliente == "testclient"          # el TestClient de FastAPI


def por_defecto():
    """Con quien se entra sin cuenta: el mas antiguo, o "local" recien creado."""
    lista = nombres()
    if lista:
        return lista[0]
    with _cerrojo:
        todos = _leer(USUARIOS)
        if not todos:                            # sin contrasena: solo se entra desde este PC
            todos[USUARIO_LOCAL] = {"sal": "", "hash": "", "creado": time.strftime("%Y-%m-%d %H:%M:%S")}
            _escribir(USUARIOS, todos)
        return sorted(todos)[0] if USUARIO_LOCAL not in todos else USUARIO_LOCAL
