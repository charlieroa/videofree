# VideoFree

De un tema a un vídeo narrado, con imágenes en tu estilo y movimiento de cámara, **sin pagar
nada por vídeo**. Corre en tu computador, sin GPU. Las imágenes salen de tu **cuenta gratis de
Cloudflare** (unas 60 al día) y el guion y la voz de tu **clave gratis de Gemini**; sin nada
también funciona, más sencillo.

> **La forma fácil: que lo instale Claude.** Abre la app de Claude en tu PC, entra en la pestaña
> **Code** con una carpeta de tu PC (no en el chat ni en claude.ai/code) y pega el mensaje de [Instalarlo con Claude Code](#instalarlo-con-claude-code).
> Claude descarga, instala, lo abre en tu navegador y te guía. Si te contesta que no puede
> instalarlo, estás en la nube: vuelve a la app instalada.

```
Tema + línea gráfica  →  1 Guion  →  2 Voz  →  3 Imágenes  →  4 Montaje  →  video_final.mp4
```

Das el **tema** y la **línea gráfica** (un texto de estilo y/o **una imagen de ejemplo**) y
VideoFree hace el resto. Y si una escena no te gusta, **en esa escena subes tu propia imagen**:
el resto del vídeo sigue automático.

| Paso | Con tu clave de Gemini | Sin clave |
|---|---|---|
| Guion (escenas, estilo, personajes) | Gemini, automático | Pollinations, automático y sin cuenta |
| Voz | **Puck** (hombre, animado), **Charon** (hombre, narrador), **Kore** (mujer) o **Jorge** | **Jorge** (México), gratis y sin clave |
| Imágenes | **Cloudflare** (gratis, ~60 al día) u OpenAI (de pago), copiando el estilo de tu imagen de ejemplo y con los mismos personajes en todo el vídeo | Pollinations: sencillas y con marca de agua |
| Montaje | **Efecto 3D de profundidad** en tu PC (Depth Anything V2 Small, sin GPU), subtítulos y música opcional | igual |

Alternativas para el guion (en Ajustes): el CLI de Claude (con tu suscripción) u Ollama (local).

---

## Paso a paso (Windows)

### 1. Lo que necesitas (una sola vez)

1. **Python 3.12**: bájalo de [python.org/downloads](https://www.python.org/downloads/).
   Al instalarlo, marca **«Add python.exe to PATH»**.
2. **Git**: desde [git-scm.com](https://git-scm.com/download/win). Si no quieres instalar Git,
   usa el botón verde **Code → Download ZIP** de esta página y descomprime el ZIP.
3. **Node.js** (recomendado): desde [nodejs.org](https://nodejs.org) (botón LTS). Con él conectas
   Cloudflare con un solo botón.
4. **Una cuenta de Google** para sacar tu clave gratis de Gemini (opcional, pero recomendada).

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
2. **Tu clave de IA** (puedes guardar varias):
   - **Cloudflare** (imágenes): pulsa **Entrar con Cloudflare**, entra con Google (o crea la
     cuenta gratis, sin tarjeta) y pulsa **Allow**. Sin Node.js, hazlo «a mano»: en
     dash.cloudflare.com → AI → Workers AI → Use REST API copias el Account ID, creas el token
     y pegas los dos.
   - **Gemini** (guion y voz): entra en [aistudio.google.com/apikey](https://aistudio.google.com/apikey),
     pulsa **Create API key**, cópiala, pégala en la app y pulsa **Probar y guardar**.

   Si no quieres nada de esto, pulsa **Seguir sin clave**.
3. **Voz**: escucha las 4 voces (▶) y elige una.
4. **Listo.**

La clave se guarda **solo en tu PC**, en `secretos/`, que nunca se sube al repositorio.
Pégala solo en la app, nunca en un chat. Puedes cambiarla cuando quieras en **Ajustes → Claves de IA**.

### 4. Hacer tu primer vídeo

Pulsa **+ Crear vídeo**: un asistente de 5 pasos te lleva de la mano.

1. **¿Cómo?** ⚡ **Automático** (la IA hace todo y al final tienes el MP4) o ✋ **Manual** (tú
   revisas el guion y lanzas cada paso).
2. **¿De qué trata?** Escribe el tema, o pulsa **💡 Buscar ideas en los nichos de YouTube** y
   elige uno con **Usar este tema**. La IA escribe el guion.
3. **Tu línea gráfica**: estilo en palabras, imagen de ejemplo y tus fotos (todo opcional).
4. **La voz**: escúchalas y elige.
5. **Todo listo**: te dice qué IA hará cada cosa. Pulsa **Crear vídeo**.

**Sin ninguna clave también funciona, gratis:** el guion lo escribe Pollinations (sin cuenta),
las imágenes salen de Pollinations (sencillas y con marca de agua) y la voz de una de las gratis.
Para mejor calidad, gratis: **Cloudflare** (imágenes) + **clave de Gemini** (guion y voces Puck,
Charon y Kore).

**Imágenes gratis de calidad cada día: Cloudflare.** En el Asistente (paso 2) elige
**Cloudflare**: con una cuenta gratis (sin tarjeta) y un token de Workers AI salen unas 55-90
imágenes FLUX.2 al día con tu estilo y los mismos personajes (acepta tu imagen de ejemplo, la
hoja de personajes y tus fotos como referencia). El cupo se renueva cada día a las 00:00 UTC.

Los detalles de cada paso:

1. En el panel de la izquierda, en **🎙 Voz**, elige la voz.
2. Llena **Título**, **Tema** (pega un texto, un resumen o tus ideas) y **Minutos**.
3. **Línea gráfica**: escribe el estilo (p. ej. «ilustración acuarela, colores cálidos») y/o
   **sube una imagen de ejemplo**: todas las imágenes copiarán su estilo, no su contenido.
   **Tus fotos** (opcional, varias a la vez: tu producto, tu cara, tu local…). Elige cómo se usan:
   - **La IA crea las imágenes a partir de ellas**: Gemini u OpenAI las ven en cada escena y sacan
     tu producto o tu cara tal cual, en la situación que pida el guion.
   - **Usar mis fotos tal cual**: no se genera ninguna imagen; tus fotos se reparten en orden entre
     las escenas y el efecto 3D las anima.
4. Elige el **Tono** (humor, documental, infantil, inspirador, misterio…).
5. Deja marcado **«Hacerlo todo solo al crear»** y pulsa **Crear**. El registro de abajo dice
   en qué va.
6. ¿Una escena no te gusta? Pulsa **Subir mi imagen** (o **Ctrl+V** con el ratón encima) y pon
   la tuya. Queda marcada **Tu imagen** y no se vuelve a generar. Luego pulsa **4 · Animar y montar MP4**.
7. Cuando diga **Listo**, pulsa **Descargar MP4**. Cuando lo subas a YouTube, márcalo como publicado.

¿No sabes de qué hacer el vídeo? Mira **🔥 Nichos** (abajo) y pulsa **Usar este tema**: rellena
el vídeo nuevo y la IA escribe un guion propio sobre ese tema.

Si es tu primera vez, marca **Modo prueba**: arma el vídeo en segundos sin IA, para ver el montaje.

### 5. Tu canal: foto de perfil y banner

Arriba, en **📺 Mi canal**, sube una foto cualquiera y **encuádrala**: arrástrala y usa el zoom
(o la rueda del ratón). En el banner ves la zona del ordenador y la zona segura del móvil, para
que tu nombre o tu cara queden dentro. **Automático** la ajusta sola. Sale con las medidas de YouTube:

| | Medida | Cómo se ajusta |
|---|---|---|
| Foto de perfil | **800 × 800** (se ve en círculo de 98 px), máx. 4 MB | Recorte al centro. En fotos verticales, cerca de la cara |
| Banner | **2560 × 1440**, máx. 6 MB. Zona segura **1546 × 423** | Si la foto es ancha, la llena. Si no, la pone entera en la zona segura sobre un fondo desenfocado |

Descárgalas y súbelas en **YouTube Studio → Personalización → Branding**.

### 6. Nichos: de qué hacer vídeos

Arriba, en **🔥 Nichos**, ves qué temas están dando vistas **ahora** en YouTube en español: 15
nichos que encajan con vídeos narrados (historia, misterio, devocional, finanzas, cuentos…) y un
buscador para cualquier tema. Para cada uno mira los vídeos largos más vistos del último mes:

| Dato | Qué significa |
|---|---|
| **Vistas/día** | Cuánta gente lo busca (demanda) |
| **Subs típicos** | Tamaño de los canales que salen (competencia) |
| **Sorpresas** | % de vídeos de canales pequeños (< 50 mil subs) con más vistas que suscriptores. Alto = el nicho premia el contenido, no el tamaño del canal |

Abajo, **Tendencias de hoy**: lo más visto hoy en tu país, por categoría.

Necesita una clave **gratis** de la YouTube Data API: en
[console.cloud.google.com](https://console.cloud.google.com/apis/library/youtube.googleapis.com)
pulsa **Habilitar**, luego **Credenciales → Crear credenciales → Clave de API**, y pégala en la
pantalla de Nichos. Da 10.000 unidades al día; mirar un nicho gasta ~100 y queda guardado todo el día.

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

Necesitas la app de Claude en tu PC ([claude.ai/download](https://claude.ai/download)) con un plan
de pago. Entra en la pestaña **Code**, elige la carpeta donde lo quieras (por ejemplo
Documentos) y **pega este mensaje**:

```
Clona https://github.com/charlieroa/videofree aquí (si no hay Git, baja el ZIP del repo), lee el archivo skill/videofree/SKILL.md que viene dentro y síguelo: instala VideoFree, déjalo abierto en el navegador y guíame en el asistente.
```

Pulsa **Permitir** cada vez que te lo pida. **Tiene que ser la app instalada, en Code y con una
carpeta de tu PC**: el chat y **claude.ai/code** en el navegador corren en un servidor de
Anthropic, no en tu computador. Si te dice que no puede instalarlo, que no tiene internet o que
corre en un «contenedor», estás en uno de esos.

Claude comprueba Python, descarga el repo, instala lo necesario, arranca la app y te acompaña
en el asistente. **Tus claves (Gemini, Cloudflare) las pegas tú en VideoFree**: Claude no te la pide y no
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

- **Cupo de Cloudflare**: unas 55-90 imágenes al día (arriba en la app ves cuánto te queda).
  Un vídeo de 15 minutos gasta casi todo el de un día; si se acaba a mitad, el resto sale de
  Pollinations. Se renueva a las 00:00 UTC.
- **Cuota gratis de Gemini**: el guion y la voz entran de sobra en el plan gratis para vídeos
  cortos y medianos; si Google pide esperar, la app espera y reintenta sola. Las imágenes de
  Gemini no tienen cuota gratis (piden facturación): para eso está Cloudflare.
- **Pollinations**: lento y con marca de agua. Es el respaldo, no el camino recomendado.
- **Voces**: Jorge es clara pero algo robótica. Las de Gemini suenan más naturales y siguen el
  tono del vídeo (humor, documental, infantil…).

## Problemas comunes

| Síntoma | Solución |
|---|---|
| `py` no se reconoce | Instala Python 3.12 marcando «Add to PATH» y abre otra terminal |
| «Gemini no acepta esa clave» | Crea otra en aistudio.google.com/apikey y pégala en el asistente |
| «Se acabó la cuota gratis de Gemini» | Espera un rato (el cupo por minuto se libera solo; el diario, al día siguiente) o usa Jorge |
| No sale «Entrar con Cloudflare» | Falta Node.js: instálalo y vuelve a abrir VideoFree, o conéctalo «a mano» |
| Imágenes simples con marca de agua | Cloudflare sin conectar o cupo del día gastado (se ve arriba) |
| Claude dice que no puede instalarlo o que corre en un «contenedor» | Estás en el chat o en claude.ai/code (nube): abre la app instalada, **Code**, carpeta de tu PC |
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
