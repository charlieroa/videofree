# VideoFree

De un texto a un vídeo narrado, con imágenes y movimiento, **sin pagar nada por vídeo**.
Corre en tu computador, y lo pesado (imágenes, voz natural y movimiento IA) va a la
**GPU gratis de Kaggle de cada persona**: 30 horas a la semana por cuenta.

```
Tu texto  →  1 Guion  →  2 Voz  →  3 Imágenes  →  4 Movimiento IA  →  5 Montaje  →  video_final.mp4
```

| Paso | Con qué | Dónde corre |
|---|---|---|
| Guion (escenas, estilo, personajes) | ChatGPT pegado a mano, CLI de Claude u Ollama | tu PC / tu cuenta |
| Voz | 45 voces edge-tts en español (Colombia, México, España…) o **Chatterbox**, una voz más natural que además puede clonar **tu** voz | tu PC / tu Kaggle |
| Imágenes | FLUX.2 [klein] con personajes iguales en todo el vídeo, Pollinations, o pegadas a mano | tu Kaggle / internet |
| Movimiento | LTX-Video: la escena se anima con la cámara quieta | tu Kaggle |
| Montaje | ffmpeg, con subtítulos y música opcional | tu PC |

---

## Paso a paso (Windows)

### 1. Lo que necesitas (una sola vez)

1. **Python 3.12**: bájalo de [python.org/downloads](https://www.python.org/downloads/).
   Al instalarlo, marca **«Add python.exe to PATH»**.
2. **Git**: desde [git-scm.com](https://git-scm.com/download/win). Si no quieres instalar Git,
   puedes usar el botón verde **Code → Download ZIP** de esta página y descomprimir el ZIP.
3. **Una cuenta de Kaggle** (gratis) en [kaggle.com](https://www.kaggle.com). Es opcional,
   pero sin ella no hay voz natural, imágenes con personajes iguales ni movimiento IA.

### 2. Descargar e instalar

Abre una terminal (tecla Windows, escribe `cmd` y pulsa Enter) y pega:

```bat
git clone https://github.com/charlieroa/videofree.git
cd videofree
iniciar.bat
```

La primera vez tarda 1–2 minutos porque instala lo necesario. Después se abre solo
**http://127.0.0.1:8031/** en tu navegador. Las siguientes veces basta con doble clic en `iniciar.bat`.

### 3. Crear tu usuario y seguir el asistente

Al entrar, pulsa **Crear cuenta** (usuario y contraseña de mínimo 8 caracteres; se guarda
solo en tu PC). Después se abre el **asistente** de 7 pasos (cada usuario nuevo lo ve al entrar):

1. **Bienvenida.**
2. **Equipo**: comprueba solo que todo esté instalado.
3. **Quién escribe el guion**: si no tienes nada instalado, elige **ChatGPT (a mano)**.
4. **De dónde salen las imágenes**: «GPU Kaggle» si vas a conectar Kaggle, si no Pollinations.
5. **GPU de Kaggle**: pegas tu usuario y token y pulsas **Probar la GPU** (ver el paso 4).
6. **Voz**: eliges país y voz, y la escuchas antes de decidir.
7. **Listo.**

Puedes volver a abrir el asistente cuando quieras con el botón **Asistente**.

### 4. Conectar tu GPU gratis de Kaggle

1. En kaggle.com, entra a **Settings** y **verifica tu teléfono**. Sin teléfono verificado, Kaggle no da GPU.
2. En la misma página, sección **API**, pulsa **Generate New Token** y copia el token.
3. Pega tu **usuario de Kaggle** y el **token** en el asistente, y pulsa **Probar la GPU**.

La GPU es **tuya**: el programa usa tu token y nunca uno compartido. El token se guarda
solo en tu PC, en `secretos/`, que nunca se sube al repositorio. Si un día Kaggle dice
«ya no acepta tu token», genera otro y pégalo de nuevo en el asistente.

### 5. Hacer tu primer vídeo

1. En el panel de la izquierda, en **🎙 Voz**, elige la voz.
2. Debajo, llena **Título**, **Material** (pega el texto, un resumen o las ideas), **Minutos**,
   y si quieres el **Estilo visual** y el **Tono**.
3. Deja marcado **«Movimiento IA en todas las escenas»** si quieres que las escenas se muevan.
4. Pulsa **Crear** y, dentro del vídeo, **Hacer todo**. El registro de abajo dice en qué va,
   y el tablero (la portada) muestra el estado de todos tus vídeos.
5. Cuando diga **Listo**, pulsa **Descargar MP4**. Cuando lo subas a YouTube, márcalo como publicado.

Si es tu primera vez, marca **Modo prueba**: arma el vídeo en segundos sin IA,
para que veas cómo queda el montaje.

### 6. Tu propia voz (opcional)

En **🎙 Voz → Tu voz clonada**, graba 15 segundos hablando normal o sube un audio, y marca
la casilla de permiso. Chatterbox habla con tu voz y tu acento, y lo hace en tu GPU de Kaggle.
**Clona solo tu voz o la de alguien que te haya dado permiso.**

---

## Mac o Linux

```bash
git clone https://github.com/charlieroa/videofree.git
cd videofree
./iniciar.sh
```

Necesitas Python 3.11 o más nuevo (`python3 --version`). Lo demás es igual.

---

## Instalarlo con Claude Code (el skill)

Si usas [Claude Code](https://claude.com/claude-code), puede instalarlo por ti:

**Opción A, en un solo mensaje.** Abre Claude Code en la carpeta donde lo quieras y escribe:

```
Instala VideoFree desde https://github.com/charlieroa/videofree siguiendo su skill
en skill/videofree/SKILL.md, déjalo abierto en el navegador y guíame en el asistente.
```

**Opción B, dejar el skill instalado** para usarlo cuando quieras con `/videofree`:

```bat
git clone https://github.com/charlieroa/videofree.git
mkdir %USERPROFILE%\.claude\skills\videofree
copy videofree\skill\videofree\SKILL.md %USERPROFILE%\.claude\skills\videofree\
```

(En Mac/Linux: `mkdir -p ~/.claude/skills/videofree && cp videofree/skill/videofree/SKILL.md ~/.claude/skills/videofree/`.)

El skill comprueba Python, descarga el repo, instala lo necesario, arranca la app y te
acompaña en el paso de Kaggle. **Tu token de Kaggle lo pegas tú en la app**: el skill no te lo pide.

---

## Qué esperar, sin adornos

- **Tiempos**, medidos en una cuenta real con 2× T4: cada imagen tarda unos 15 s y cada clip con
  movimiento unos 30 s. Cada trabajo de Kaggle tarda además unos 4–5 minutos en arrancar.
  Un vídeo de 15 minutos gasta 1–2 horas de las 30 semanales.
- **Cola de Kaggle**: en horas pico, Kaggle puede tardar en darte la GPU. El programa espera,
  avisa cada 5 minutos y, si una GPU no sale, pide la otra (T4 ↔ P100). Kaggle deja como
  máximo **2 trabajos de GPU a la vez** por cuenta.
- **Movimiento**: el modelo que cabe gratis (LTX-Video 2B) hace un movimiento **suave**
  (respirar, gestos, humo, luz). En objetos pequeños a veces se deforma. No es Sora ni Kling.
- **Voces**: las de edge-tts son claras, pero algo robóticas. La más natural es **Chatterbox
  clonando tu voz**.

## Problemas comunes

| Síntoma | Solución |
|---|---|
| `py` no se reconoce | Instala Python 3.12 marcando «Add to PATH» y abre otra terminal |
| «Kaggle ya no acepta tu token» | Genera uno nuevo en kaggle.com/settings y pégalo en el asistente |
| «Sin GPU: verifica el teléfono» | Verifica tu teléfono en Kaggle → Settings |
| «2 trabajos de GPU (su máximo)» | Espera: el programa reintenta solo cuando se libera un hueco |
| Se queda en `queued` | Es la cola de Kaggle. Si pasan 10 min, el programa cambia de GPU solo |

Los detalles técnicos (modelos, parámetros, tiempos y cómo está hecho cada paso)
están en [docs/TECNICO.md](docs/TECNICO.md).

## Estructura

```
iniciar.bat / iniciar.sh   instalar y arrancar
app.py                     servidor (FastAPI)
web/index.html             la pantalla
motor/                     guion, voz, imágenes, clips, montaje y la conexión con Kaggle
config.json                ajustes globales (sin claves)
skill/videofree/SKILL.md   el skill para Claude Code
```

Tus vídeos se guardan en `proyectos/` y tus claves en `secretos/`. Ninguna de las dos
carpetas se sube a git.
