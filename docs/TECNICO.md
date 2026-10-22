# VideoFree: detalles técnicos

## Cómo funciona

Das el **tema** y la **línea gráfica** (un texto de estilo y/o una **imagen de ejemplo**) y,
con «Hacerlo todo solo» marcado, al pulsar **Crear** se encadenan los cuatro pasos:

| Paso | Qué hace | Con qué | Sin clave de Gemini |
|---|---|---|---|
| 1 · Guion | Parte el tema en escenas de ~7 s y escribe la «biblia»: estilo visual y personajes. Más de 3 min: por capítulos | **Gemini** (modelo flash de texto más nuevo; ve también la imagen de ejemplo). Alternativas: ChatGPT a mano, CLI de Claude, Ollama | ChatGPT a mano |
| 2 · Voz | Una locución por escena | **Jorge** (edge-tts `es-MX-JorgeNeural`) o **Gemini TTS**: Puck, Charon, Kore | Jorge |
| 3 · Imágenes | Una imagen por escena, con el estilo de la imagen de ejemplo y los mismos personajes | **Gemini imagen** con referencias. Respaldo: **Pollinations**. Y siempre: tu imagen subida o pegada | Pollinations |
| 4 · Animar y montar | Cada imagen se convierte en un plano con **efecto 3D de profundidad** (lo cercano se mueve más que el fondo) que dura lo que su frase; todo se une con subtítulos y música opcional | `motor/profundidad.py` (Depth Anything V2 Small en ONNX, CPU; el modelo, ~95 MB, se baja la primera vez a `modelos/`) + ffmpeg. Modo prueba o `"efecto_3d": false`: zoom plano | igual |

**Manual dentro del mismo vídeo:** en cualquier escena, «Subir mi imagen» o **Ctrl+V** con el
ratón encima pone tu imagen. Queda marcada como **Tu imagen** (`escena.propia = true`) y ni
«3 · Imágenes» ni «Hacer todo» la pisan: solo se cambia si pulsas «Rehacer imagen» en esa
escena (pide confirmación).

## Una sola clave: Gemini

Se crea gratis en [aistudio.google.com/apikey](https://aistudio.google.com/apikey) y se pega en el
Asistente (o en Ajustes → Clave Gemini → Cambiar). «Probar y guardar» solo lista los modelos
(`GET /v1beta/models`), así que no gasta cuota; si la clave no vale, no se guarda. Se guarda en
`secretos/<usuario>.json` (fuera de git), como el resto de secretos de cada persona.

Todo va por la API REST `generativelanguage.googleapis.com/v1beta` con `requests`
(`motor/gemini.py`), sin SDK.

| Uso | Modelo (`config.json → gemini`) | Notas |
|---|---|---|
| Guion | `modelo_texto: "auto"` → el `gemini-X.Y-flash` de versión más alta que liste la API (hoy `gemini-3.8-flash`) | `responseMimeType: application/json`; la imagen de ejemplo va como `inlineData` para que `estilo_visual` la describa |
| Voz | `modelo_voz: "gemini-3.1-flash-tts-preview"` | El 3.8 TTS tiene la cuota gratis mínima |
| Imágenes | `modelo_imagen: "auto"` → el `gemini-X.Y-flash-image` más nuevo (hoy `gemini-3.1-flash-image`) | `responseModalities: ["IMAGE"]`, `aspectRatio: 16:9` |

### Voz con Gemini TTS

- El estilo va con un **prefijo corto en el mismo texto**, según el tono del vídeo, p. ej.
  `"Dilo en español latino, cálido y con humor, como un divulgador de YouTube: " + narración`
  (`gemini.ESTILO_VOZ`). Medido: `systemInstruction` da error en estos modelos, y un prefijo
  largo hace que **lea las instrucciones en voz alta** (la misma frase pasa de ~14 s a ~25 s).
- Devuelve PCM 16 bit mono 24 kHz en base64 (`inlineData`); se pasa a mp3 con ffmpeg.
- Medido (22-10-2026): ~7 s de audio por escena de ~17 palabras, 6-25 s por llamada.

### Imágenes con Gemini: estilo y personajes iguales

1. **Imagen de ejemplo** (opcional, al crear el vídeo o luego en la página del vídeo):
   `imagenes/referencia.*`. Va como primera referencia de **cada** imagen con la orden de copiar
   solo el estilo (técnica, paleta, luz, trazo), no el contenido.
2. **Hoja de personajes**: antes de las escenas se genera una hoja con los personajes de la
   biblia, de cuerpo entero sobre fondo liso, en el estilo del vídeo → `imagenes/hoja.jpg`.
3. Cada escena con personajes lleva la hoja como segunda referencia («same face, hair, body and
   clothes»). Si cambian el estilo, los personajes o la imagen de ejemplo, la hoja se rehace sola
   (`imagenes.firma_hoja`).

### Cuota del plan gratis

- Ante 429/500/503 se reintenta hasta 5 veces esperando lo que pida la API (`RetryInfo`) o
  10-50 s; si el cupo es del día (espera de horas) se corta con un mensaje claro.
- **Medido el 22-10-2026: el plan gratis da `limit: 0` a todos los `gemini-*-image`.** Con una
  clave sin facturación, las imágenes pasan solas a Pollinations y el registro lo dice. Con
  facturación activada en AI Studio, Gemini imagen funciona.
- Si se acaba la cuota de imágenes a mitad de vídeo, el resto sigue con Pollinations. Si se
  acaba la de voz, el paso se para (no se mezclan voces en un vídeo): espera o cambia a Jorge.

## Pollinations (respaldo, sin clave)

Flux por la API pública: una imagen cada ~45 s por IP. Un vídeo de 14 min (~85 imágenes)
tarda ~65 min en imágenes. Sin token pone una marca de agua pequeña; con una clave de
enter.pollinations.ai (Ajustes) va sin marca ni espera.

## Modo prueba

Sin ninguna IA: trocea tu texto en escenas, pone silencio en la voz y dibuja imágenes de
prueba. Sirve para ver el montaje en segundos.

## Usuarios (sin login)

Desde el mismo PC se entra sin cuenta. Con 0 usuarios se crea `local` (sin contraseña); con
uno, se entra con ese; con varios, con el más antiguo, y arriba sale un selector para cambiar
sin contraseña. Las peticiones de otra máquina (si arrancas con `--host 0.0.0.0`) o que
llegan por un proxy siguen pidiendo usuario y contraseña. `VIDEOFREE_SIN_LOGIN=0` vuelve a
pedir login siempre.

## Claves

Las claves (Gemini, Pollinations) se guardan en `secretos/<usuario>.json`, que está en
`.gitignore`: **no se suben nunca al repositorio**. `config.json` no lleva ninguna clave.

## Configuración (`config.json`)

- `guion.motor`: `gemini` (por defecto), `manual` (ChatGPT a mano), `claude` u `ollama`.
- `voz.voz`: `es-MX-JorgeNeural`, `gemini:Puck`, `gemini:Charon` o `gemini:Kore`.
- `imagen`: motor (`gemini`, `pollinations` o `manual`), tamaño, semilla y espera de Pollinations.
- `gemini`: `modelo_texto`, `modelo_voz`, `modelo_imagen` (`auto` = el más nuevo de la API).
- `montaje`: resolución, fps, zoom, subtítulos, música; `efecto_3d` y `planos_a_la_vez` (planos en paralelo; por defecto según los núcleos del PC)
  (`"musica": "musica/fondo.mp3"`, un fichero tuyo).

## Estructura

```
app.py              servidor y rutas (FastAPI)
web/index.html      la pantalla
motor/gemini.py     la clave de Gemini y las llamadas: texto, voz (TTS) e imagen
motor/guion.py      paso 1: Gemini, ChatGPT a mano, Claude CLI u Ollama
motor/voz.py        paso 2: Jorge (edge-tts) o Gemini TTS
motor/imagenes.py   paso 3: Gemini (referencia + hoja de personajes), Pollinations, a mano o de prueba
motor/montaje.py    paso 4: animación y montaje con ffmpeg
proyectos/<id>/     cada vídeo: proyecto.json y sus ficheros
```
