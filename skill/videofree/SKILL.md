---
name: videofree
description: Instala y arranca VideoFree (de un tema a un vídeo narrado, gratis, con las cuentas gratis de Cloudflare y Gemini de la persona) desde github.com/charlieroa/videofree y guía a la persona hasta su primer vídeo. Úsalo cuando pidan instalar VideoFree, "el programa de videos gratis" o /videofree.
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
2. Abrir **Asistente** (arriba) y llegar al paso 2, «Tu clave de IA».
3. **Imágenes gratis: Cloudflare.** Marcar **Cloudflare** y pulsar **Entrar con Cloudflare**: se
   abre Cloudflare en el navegador, entra con Google (o crea la cuenta gratis, sin tarjeta) y
   pulsa **Allow**. Da unas 60 imágenes al día que copian su imagen de ejemplo. Ese botón usa
   Node.js (`node --version`); si no lo tiene, que lo instale de https://nodejs.org (LTS) o que
   use la opción «a mano» (Account ID + token de Workers AI en dash.cloudflare.com → AI →
   Workers AI → Use REST API).
4. **Guion y voz: clave de Gemini** (gratis):
   - entrar en https://aistudio.google.com/apikey con su cuenta de Google;
   - pulsar **Create API key** y copiarla;
   - en el paso 2, marcar **Gemini**, pegarla **en la app** y pulsar «Probar y guardar».
   Con ella el guion sale mejor y tiene las voces Puck, Charon y Kore. Para los **nichos de
   YouTube**, que habilite «YouTube Data API v3» en el mismo proyecto de console.cloud.google.com:
   sirve la misma clave.

   **No le pidas ninguna clave ni token, no los escribas tú en ningún archivo y dile que no los
   pegue en el chat.** Los pega la persona en VideoFree, que los guarda en `secretos/` (fuera de git).
   Sin nada también funciona: guion gratis automático (Pollinations), 10 voces gratis e imágenes
   sencillas con marca de agua.
5. Hacer un primer vídeo corto, de 1 minuto: botón **+ Crear vídeo** → automático → tema (o
   💡 una idea de los nichos) → línea gráfica (texto y/o imagen de ejemplo, y sus fotos si
   quiere) → voz → **Crear vídeo**. Si una escena no le gusta, en esa escena puede pulsar
   «Subir mi imagen» para poner la suya.

Arriba se ve cuánto queda del cupo gratis de imágenes de hoy. Un vídeo de 15 minutos gasta casi
todo el de un día.

## 6. Si algo falla

- `pip` falla en Windows con Python 3.13+: crea el venv con 3.12 (`py -3.12`).
- El puerto 8031 está ocupado: `python app.py --puerto 8032` y abre ese puerto.
- «Gemini no acepta esa clave»: que cree otra en aistudio.google.com/apikey y la pegue en el asistente.
- «Se acabó la cuota gratis de Gemini»: esperar un rato, o usar una voz gratis.
- No sale «Entrar con Cloudflare»: falta Node.js; instalarlo y volver a abrir VideoFree, o conectarlo «a mano».
- Imágenes simples con marca de agua: Cloudflare sin conectar o cupo del día gastado (se ve arriba).

Termina con un resumen corto: dónde quedó instalado, cómo abrirlo otra vez y qué paso le falta.
