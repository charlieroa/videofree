---
name: videofree
description: Instala y arranca VideoFree (texto a vídeo narrado, gratis, con la GPU de Kaggle de la persona) desde github.com/charlieroa/videofree y guía a la persona hasta su primer vídeo. Úsalo cuando pidan instalar VideoFree, "el programa de videos gratis" o /videofree.
---

# Instalar VideoFree

Habla en español y en frases cortas: quien usa esto puede no ser programador. Ve paso a
paso y di qué haces antes de cada comando.

## 1. Comprobar Python y Git

- Windows: `py -3.12 --version`. Si falla, prueba `python --version`, que debe ser 3.11 o más nuevo.
- Mac/Linux: `python3 --version` (3.11 o más nuevo).
- `git --version`.

Si falta Python, NO lo instales tú. Dile que lo baje de https://www.python.org/downloads/,
que en Windows marque «Add python.exe to PATH», y que te avise cuando termine.
Si falta Git, puedes bajar el ZIP con
`curl -L -o videofree.zip https://github.com/charlieroa/videofree/archive/refs/heads/main.zip`
y descomprimirlo (`tar -xf videofree.zip` funciona en Windows 10+). La carpeta queda como `videofree-main`.

## 2. Descargar

En la carpeta donde está la persona (pregúntale solo si no está claro dónde lo quiere):

```
git clone https://github.com/charlieroa/videofree.git
```

Si la carpeta `videofree` ya existe, no la borres: haz `git -C videofree pull`.
Ahí pueden estar sus vídeos (`proyectos/`) y sus claves (`secretos/`).

## 3. Instalar dependencias

Windows:
```
cd videofree
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```
Mac/Linux:
```
cd videofree
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

## 4. Arrancar

Arranca la app EN SEGUNDO PLANO (no bloquees la conversación):
`.venv\Scripts\python app.py` (Windows) o `.venv/bin/python app.py` (Mac/Linux).

Comprueba que responde: `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8031/` → 200.
Ábrela en el navegador (`start http://127.0.0.1:8031/` en Windows, `open` en Mac,
`xdg-open` en Linux). Dile que la próxima vez basta con doble clic en `iniciar.bat`
(o `./iniciar.sh`).

## 5. Acompañar el asistente

Explícale que en la pantalla tiene que:
1. Nada de cuenta ni contraseña: la app entra directo con un usuario local de su PC.
2. Seguir el asistente. Para el guion, si no tiene la CLI de Claude ni Ollama, que elija
   **ChatGPT (a mano)**.
3. **Kaggle**, para tener GPU gratis:
   - crear una cuenta en kaggle.com;
   - en Settings, verificar el teléfono;
   - en Settings → API, pulsar **Generate New Token**;
   - pegar su usuario y su token **en la app**, y pulsar «Probar la GPU».

   **No le pidas el token ni lo escribas tú en ningún archivo.** Lo pega la persona en la
   app, que lo guarda en `secretos/` (fuera de git).
4. Hacer un primer vídeo corto, de 1 minuto, con **Modo prueba** marcado, para ver que todo
   funciona. Después, uno de verdad.

## 6. Si algo falla

- `pip` falla en Windows con Python 3.13+: crea el venv con 3.12 (`py -3.12`).
- El puerto 8031 está ocupado: `python app.py --puerto 8032` y abre ese puerto.
- «Kaggle ya no acepta tu token»: que genere uno nuevo en kaggle.com/settings y lo pegue en el asistente.
- «Sin GPU»: falta verificar el teléfono en Kaggle.
- El trabajo se queda en `queued`: es la cola de Kaggle. El programa espera y cambia de GPU solo.

Termina con un resumen corto: dónde quedó instalado, cómo abrirlo otra vez y qué paso le falta.
