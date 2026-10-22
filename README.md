# VideoFree

De un tema a un vídeo narrado, con imágenes en tu estilo y movimiento de cámara, **sin pagar
nada por vídeo**. Corre en tu computador, sin GPU. Con **una clave de Google Gemini u OpenAI**
el guion y las imágenes salen solos (las imágenes de Gemini piden facturación activada en Google);
sin clave también funciona.

```
Tema + línea gráfica  →  1 Guion  →  2 Voz  →  3 Imágenes  →  4 Montaje  →  video_final.mp4
```

Das el **tema** y la **línea gráfica** (un texto de estilo y/o **una imagen de ejemplo**) y
VideoFree hace el resto. Y si una escena no te gusta, **en esa escena subes tu propia imagen**:
el resto del vídeo sigue automático.

| Paso | Con tu clave de Gemini | Sin clave |
|---|---|---|
| Guion (escenas, estilo, personajes) | Gemini, automático | Copias un prompt en ChatGPT y pegas la respuesta |
| Voz | **Puck** (hombre, animado), **Charon** (hombre, narrador), **Kore** (mujer) o **Jorge** | **Jorge** (México), gratis y sin clave |
| Imágenes | Gemini u OpenAI, copiando el estilo de tu imagen de ejemplo y con los mismos personajes en todo el vídeo | Pollinations, gratis y sin cuenta |
| Montaje | **Efecto 3D de profundidad** en tu PC (Depth Anything V2 Small, sin GPU), subtítulos y música opcional | igual |

Alternativas para el guion (en Ajustes): el CLI de Claude (con tu suscripción) u Ollama (local).

---

## Paso a paso (Windows)

### 1. Lo que necesitas (una sola vez)

1. **Python 3.12**: bájalo de [python.org/downloads](https://www.python.org/downloads/).
   Al instalarlo, marca **«Add python.exe to PATH»**.
2. **Git**: desde [git-scm.com](https://git-scm.com/download/win). Si no quieres instalar Git,
   usa el botón verde **Code → Download ZIP** de esta página y descomprime el ZIP.
3. **Una cuenta de Google** para sacar tu clave gratis de Gemini (opcional, pero recomendada).

### 2. Descargar e instalar

Abre una terminal (tecla Windows, escribe `cmd` y pulsa Enter) y pega:

```bat
git clone https://github.com/charlieroa/videofree.git
cd videofree
iniciar.bat
```

La primera vez tarda 1–2 minutos porque instala lo necesario. Después se abre solo
**http://127.0.0.1:8031/** en tu navegador. Las siguientes veces basta con doble clic en `iniciar.bat`.

### 3. El asistente (4 pasos)

No hace falta crear cuenta: la app entra directo con un usuario local de tu PC. La primera vez
se abre el **asistente**:

1. **Tu equipo**: comprueba solo que todo funcione.
2. **Clave de Gemini**: entra en [aistudio.google.com/apikey](https://aistudio.google.com/apikey),
   pulsa **Create API key**, cópiala, pégala en la app y pulsa **Probar y guardar**.
   Si no quieres clave, pulsa **Seguir sin clave**.
3. **Voz**: escucha las 4 voces (▶) y elige una.
4. **Listo.**

La clave se guarda **solo en tu PC**, en `secretos/`, que nunca se sube al repositorio.
Pégala solo en la app, nunca en un chat. Puedes cambiarla cuando quieras en **Ajustes → Clave Gemini**.

### 4. Hacer tu primer vídeo

1. En el panel de la izquierda, en **🎙 Voz**, elige la voz.
2. Llena **Título**, **Tema** (pega un texto, un resumen o tus ideas) y **Minutos**.
3. **Línea gráfica**: escribe el estilo (p. ej. «ilustración acuarela, colores cálidos») y/o
   **sube una imagen de ejemplo**: todas las imágenes copiarán su estilo, no su contenido.
4. Elige el **Tono** (humor, documental, infantil, inspirador, misterio…).
5. Deja marcado **«Hacerlo todo solo al crear»** y pulsa **Crear**. El registro de abajo dice
   en qué va.
6. ¿Una escena no te gusta? Pulsa **Subir mi imagen** (o **Ctrl+V** con el ratón encima) y pon
   la tuya. Queda marcada **Tu imagen** y no se vuelve a generar. Luego pulsa **4 · Animar y montar MP4**.
7. Cuando diga **Listo**, pulsa **Descargar MP4**. Cuando lo subas a YouTube, márcalo como publicado.

Sin clave, el guion se hace con ChatGPT: la app te da el prompt, lo pegas en ChatGPT y pegas su
respuesta. Después pulsa **Hacer todo**.

Si es tu primera vez, marca **Modo prueba**: arma el vídeo en segundos sin IA, para ver el montaje.

### 5. Tu canal: foto de perfil y banner

Arriba, en **📺 Mi canal**, sube una foto cualquiera y sale con las medidas de YouTube:

| | Medida | Cómo se ajusta |
|---|---|---|
| Foto de perfil | **800 × 800** (se ve en círculo de 98 px), máx. 4 MB | Recorte al centro. En fotos verticales, cerca de la cara |
| Banner | **2560 × 1440**, máx. 6 MB. Zona segura **1546 × 423** | Si la foto es ancha, la llena. Si no, la pone entera en la zona segura sobre un fondo desenfocado |

Descárgalas y súbelas en **YouTube Studio → Personalización → Branding**.

---

## Mac o Linux

```bash
git clone https://github.com/charlieroa/videofree.git
cd videofree
./iniciar.sh
```

Necesitas Python 3.11 o más nuevo (`python3 --version`). Lo demás es igual.

---

## Instalarlo con Claude Code

Si usas [Claude Code](https://claude.com/claude-code), abre Claude Code en la carpeta donde lo
quieras y **pega este mensaje**:

```
Instala VideoFree desde https://github.com/charlieroa/videofree siguiendo su skill
en skill/videofree/SKILL.md, déjalo abierto en el navegador y guíame en el asistente.
```

Claude comprueba Python, descarga el repo, instala lo necesario, arranca la app y te acompaña
en el asistente. **Tu clave de Gemini la pegas tú en VideoFree**: Claude no te la pide y no
debes pegarla en el chat.

Para dejar el skill instalado y usarlo cuando quieras con `/videofree`:

```bat
git clone https://github.com/charlieroa/videofree.git
mkdir %USERPROFILE%\.claude\skills\videofree
copy videofree\skill\videofree\SKILL.md %USERPROFILE%\.claude\skills\videofree\
```

(En Mac/Linux: `mkdir -p ~/.claude/skills/videofree && cp videofree/skill/videofree/SKILL.md ~/.claude/skills/videofree/`.)

---

## Qué esperar, sin adornos

- **Cuota gratis de Gemini**: el guion y la voz entran de sobra en el plan gratis para vídeos
  cortos y medianos; si Google pide esperar, la app espera y reintenta sola. **Las imágenes de
  Gemini no tienen cuota gratis** (Google las deja en 0 sin facturación): con una clave gratis
  las imágenes salen de Pollinations y el registro lo avisa. Si activas la facturación en AI
  Studio, salen de Gemini con tu estilo y tus personajes.
- **Pollinations**: una imagen cada ~45 s. Un vídeo de 14 min (~85 imágenes) ≈ 1 hora, solo.
- **Voces**: Jorge es clara pero algo robótica. Las de Gemini suenan más naturales y siguen el
  tono del vídeo (humor, documental, infantil…).

## Problemas comunes

| Síntoma | Solución |
|---|---|
| `py` no se reconoce | Instala Python 3.12 marcando «Add to PATH» y abre otra terminal |
| «Gemini no acepta esa clave» | Crea otra en aistudio.google.com/apikey y pégala en el asistente |
| «Se acabó la cuota gratis de Gemini» | Espera un rato (el cupo por minuto se libera solo; el diario, al día siguiente) o usa Jorge |
| «Tu clave no tiene cuota gratis para imágenes» | Normal en el plan gratis: siguen con Pollinations |
| El puerto 8031 está ocupado | `.venv\Scripts\python app.py --puerto 8032` y abre ese puerto |

Los detalles técnicos (modelos, parámetros y cómo está hecho cada paso) están en
[docs/TECNICO.md](docs/TECNICO.md).

## Estructura

```
iniciar.bat / iniciar.sh   instalar y arrancar
app.py                     servidor (FastAPI)
web/index.html             la pantalla
motor/                     gemini, guion, voz, imágenes, montaje y canal
config.json                ajustes globales (sin claves)
skill/videofree/SKILL.md   el skill para Claude Code
```

Tus vídeos se guardan en `proyectos/` y tus claves en `secretos/`. Ninguna de las dos
carpetas se sube a git.
