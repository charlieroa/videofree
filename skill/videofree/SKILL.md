---
name: videofree
description: Instala y arranca VideoFree (de un tema a un vídeo narrado, gratis, con una sola clave de Gemini de la persona) desde github.com/charlieroa/videofree y guía a la persona hasta su primer vídeo. Úsalo cuando pidan instalar VideoFree, "el programa de videos gratis" o /videofree.
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
Ahí pueden estar sus vídeos (`proyectos/`) y su clave (`secretos/`).

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
2. Seguir el asistente, que tiene 4 pasos: equipo → clave de Gemini → voz → listo.
3. **Clave de Gemini** (gratis, una sola para guion, voz e imágenes):
   - entrar en https://aistudio.google.com/apikey con su cuenta de Google;
   - pulsar **Create API key** y copiarla;
   - pegarla **en la app** y pulsar «Probar y guardar».

   **No le pidas la clave, no la escribas tú en ningún archivo y dile que no la pegue en el
   chat.** La pega la persona en VideoFree, que la guarda en `secretos/` (fuera de git).
   Si no quiere clave, que pulse «Seguir sin clave»: funciona con la voz Jorge, imágenes de
   Pollinations y el guion pegado de ChatGPT.
4. Elegir la voz escuchando las 4 (Jorge, Puck, Charon, Kore).
5. Hacer un primer vídeo corto, de 1 minuto: tema, línea gráfica (texto y/o una imagen de
   ejemplo) y «Hacerlo todo solo al crear» marcado. Si una escena no le gusta, en esa escena
   puede pulsar «Subir mi imagen» para poner la suya.

Avísale de algo normal: con una clave gratis, Google no da cuota para imágenes de Gemini, así
que las imágenes salen de Pollinations (el registro lo dice). No es un fallo de la instalación.

## 6. Si algo falla

- `pip` falla en Windows con Python 3.13+: crea el venv con 3.12 (`py -3.12`).
- El puerto 8031 está ocupado: `python app.py --puerto 8032` y abre ese puerto.
- «Gemini no acepta esa clave»: que cree otra en aistudio.google.com/apikey y la pegue en el asistente.
- «Se acabó la cuota gratis de Gemini»: esperar un rato, o usar la voz Jorge.

Termina con un resumen corto: dónde quedó instalado, cómo abrirlo otra vez y qué paso le falta.
