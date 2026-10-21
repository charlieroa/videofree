# VideoFree: detalles técnicos

## Cómo funciona

| Paso | Qué hace | Con qué | Coste |
|---|---|---|---|
| 1 · Guion | Parte el material en escenas de ~7 s y escribe el estilo y los personajes. Más de 3 min: por capítulos | **ChatGPT a mano** (pegas el prompt y su respuesta), CLI de Claude (con suscripción) u **Ollama** | 0 $ |
| 2 · Voz | Una locución por escena | **edge-tts**, voces neuronales de Microsoft | 0 $ |
| 3 · Imágenes | Una imagen por escena | **Pollinations** (Flux, automático), **tu GPU de Kaggle** (FLUX.2 [klein], personajes iguales) o **las pegas tú** desde ChatGPT/Gemini/Bing | 0 $ |
| 4 · Animar y montar | Cada imagen se convierte en un plano con movimiento de cámara (acercar, alejar, paneos) que dura lo que su frase. Se pega todo con subtítulos y música opcional | **ffmpeg en tu PC** (motor propio) | 0 $ |

**Por qué las imágenes se parecen entre sí:** el prompt de cada imagen lleva siempre el
mismo estilo, la misma descripción de cada personaje y la misma semilla. Y las escenas
marcadas **«misma imagen que la anterior»** reusan la imagen con otro movimiento de cámara:
da continuidad y no hay que generar nada.

### Imágenes: dos formas gratis

- **Pollinations (automático):** sin clave, una imagen cada ~45 s (límite gratis por IP). Un vídeo de 14 min
  (~120 escenas, ~85 imágenes) tarda ~65 min en imágenes (se deja corriendo). Sin token, Pollinations
  pone una marca de agua pequeña. Con una **clave de enter.pollinations.ai** (funciona con su saldo «pollen»; mira si al registrarte te dan saldo gratis)
  se pega arriba en la pantalla y va sin marca ni espera.
- **A mano (ChatGPT gratis u otro):** elige «Las pego yo». En cada escena pulsa
  **Copiar prompt**, pégalo en ChatGPT, copia la imagen que te dé y pégala en la escena
  con **Ctrl+V** (ratón encima) o con **Subir imagen**. Se puede mezclar: dejar que
  Pollinations haga todas y cambiar a mano las que no te gusten.

OpenAI no da créditos gratis en su API, y automatizar la web de ChatGPT va contra sus
condiciones: por eso la vía ChatGPT es pegando las imágenes, no automática.

### Modo prueba

Sin ninguna IA: trocea tu texto en escenas, pone silencio en la voz y dibuja imágenes
de prueba. Sirve para ver el montaje en segundos.

## GPU gratis (Kaggle, opcional)

Kaggle da **30 horas a la semana** de una GPU de 16 GB a cada cuenta. El asistente la
conecta en 4 pasos: cuenta en kaggle.com, verificar el teléfono, *Generate New Token* en
kaggle.com/settings/api y pegar usuario y token. «Probar la GPU» manda un trabajo de
prueba y confirma que la GPU responde (comprobado con una cuenta real: 2× Tesla T4 de 15 GB).
La GPU es de cada persona: el programa usa su token, nunca uno compartido.

## Vídeo IA en la GPU de Kaggle

Algunas escenas pueden ser **vídeo IA de verdad** en vez de foto con movimiento de cámara.
Se anima la imagen de la escena con un modelo abierto en la GPU gratis de Kaggle de cada persona.

### Flujo

1. Haz las imágenes como siempre (paso 3).
2. En cada escena que quieras animar, marca **«Vídeo IA (GPU)»**. La cabecera del vídeo dice
   cuántas escenas llevan vídeo IA y cuántas horas de GPU costarán, frente a las 30 h semanales.
3. Pulsa **«3b · Clips IA (GPU Kaggle)»**. Si la GPU no está conectada, el botón lo dice y abre
   el Asistente en el paso 5.
4. Por cada tanda (como mucho `max_escenas_por_tanda` escenas), `motor/clips_gpu.py`:
   - recorta cada imagen a 832×480 y escribe un prompt de movimiento: un movimiento de cámara
     alterno, el `visual` de la escena, los personajes y el estilo de la biblia, y «movimiento suave»;
   - calcula los fotogramas: lo que dura la voz más el respiro, con un tope de `tope_s` (5 s).
     LTX pide 8·k+1 fotogramas;
   - **sube las imágenes**:
     - si ocupan ≤ 600 KB en base64 (unas 5 imágenes, por ejemplo al *Rehacer clip*), van **dentro del script**;
     - si ocupan más, van como **dataset privado** de la cuenta, siempre con el mismo slug por proyecto
       (`kaggle datasets create`, y luego `version -d`). El kernel lo monta con `dataset_sources`.

     Kaggle no documenta un tope de tamaño para el código de un kernel, así que el corte de 600 KB es
     por prudencia. Además, `kernels push` solo sube el `code_file`: los demás ficheros de la carpeta no llegan;
   - lanza **un único kernel** por tanda con `gpu.ejecutar_script`, con `machine_shape` y
     `--accelerator NvidiaTeslaT4`, y con tope de sesión `-t` para no gastar cuota si algo se cuelga.
     El kernel:
     0. si no hay GPU, escribe `resultado.json` con «sin GPU: verifica el teléfono…» y termina;
     1. hace `pip install` de las versiones fijadas en `video_gpu.pip` (Kaggle trae Python 3.13 y torch);
     2. carga el codificador de texto T5 **una vez** en la GPU 0, en fp16, codifica todos los prompts y lo libera;
     3. lanza **un trabajador por GPU**: con 2×T4 la tanda se reparte entre las dos. Cada trabajador carga
        el transformer y el VAE una sola vez y genera sus clips seguidos. **Si una escena falla, sigue con la siguiente**;
     4. deja `escena_NNN.mp4` y `resultado.json` en `/kaggle/working`. Ese JSON lleva, por escena, si salió
        bien o el error y cuántos segundos tardó, y además la GPU, la precisión y el tiempo de arranque;
   - baja la salida, copia los clips a `proyectos/<id>/clips/` y guarda en cada escena
     `clip` y `clip_s`. Los tiempos reales sustituyen a la estimación (`video_gpu.medido`).
5. Montaje: una escena con clip, y con «Vídeo IA» marcado, usa el clip escalado y recortado a 1920×1080.
   - Si el clip dura menos que la voz, se ralentiza hasta 1.4× y después se congela el último fotograma (`tpad`).
   - Si dura más, se corta.

   Las demás escenas siguen con el zoompan. Todos los planos se codifican igual, así que la
   concatenación sigue sin recodificar.

Si cambias la imagen de una escena o su «Qué se ve», su clip deja de valer y hay que rehacerlo
con **Rehacer clip** en la tarjeta. El clip se reproduce al pasar el ratón por la tarjeta.

### Modelo elegido: LTX-Video 2B distilled (0.9.6) de Lightricks

| | LTX-Video 2B distilled | Wan 2.2 TI2V-5B | CogVideoX-5B-I2V |
|---|---|---|---|
| Parámetros | 2B | 5B | 5B |
| Pasos | **8**, sin CFG (destilado) | ~50 con CFG | 50 con CFG |
| Velocidad publicada | «tiempo real» a 1216×704 en H100; «15× más rápido» que el no destilado | 5 s a 720p en «menos de 9 min» en una GPU de consumo (RTX 4090) | ~180 s por clip en una A100 |
| VRAM | poca: el transformer ocupa 4 GB en fp16 | **≥ 24 GB** | desde 5 GB, con todas las optimizaciones (muy lento) |
| Precisión | bf16 recomendado; VAE y texto también en fp16/fp32 | bf16 | bf16 recomendado (el 5B se entrenó en bf16) |
| Resolución | múltiplos de 32, hasta 1216×704; 8·k+1 fotogramas | 1280×704, 24 fps | 720×480, 8 fps, 6 s fijos |
| Licencia | LTX Open Weights: gratis, también para uso comercial, salvo empresas con ≥ 10 M$/año | Apache 2.0 | CogVideoX License (lo comercial, vía su plataforma) |

**Por qué LTX 2B distilled:** es el único que cabe con holgura en 16 GB sin bf16 y que va en pocos pasos.
- Wan 2.2 5B tiene mejor licencia, pero pide 24 GB. Una T4 no tiene bf16 y es unas 5 veces más lenta
  que una 4090, así que cada clip costaría del orden de **una hora**: inviable con 30 h a la semana.
- CogVideoX va a 720×480 y 8 fps, y se recomienda en bf16. En una T4 serían decenas de minutos por clip.

La licencia de LTX permite el uso comercial a creadores y a empresas pequeñas.

**Cómo se carga** (diffusers 0.35.2, `LTXConditionPipeline`):
- el transformer y el VAE, del fichero `ltxv-2b-0.9.6-distilled-04-25.safetensors` con `from_single_file`
  (diffusers lo reconoce como arquitectura 0.9.5);
- el scheduler y el T5, de `Lightricks/LTX-Video-0.9.5`.

Los parámetros son los del `ltxv-2b-0.9.6-distilled.yaml` oficial: guidance 1, 8 pasos,
`decode_timestep` 0.05 y `decode_noise_scale` 0.025.

**Precisión en T4/P100 (sin bf16):**
- Con `precision: "auto"` se usa bf16 solo si la GPU lo tiene (Ampere o más nueva). En T4/P100 se usa **fp16**.
- El T5 en fp16 es seguro: transformers deja en fp32 sus capas `wo`, que son las que desbordan.
- Si un clip sale negro o con NaN, el trabajador **pasa todo a fp32** y repite esa escena. El 2B en fp32
  ocupa 8 GB y cabe. También se puede forzar con `"precision": "fp32"`.

**Plan B de modelo (`video_gpu.plan_b`):** si el checkpoint destilado no carga, se usa
`Lightricks/LTX-Video-0.9.5` completo, en formato diffusers y documentado oficialmente, con 30 pasos y
guidance 3. Es unas 7 veces más lento, pero carga seguro.

**Máquina:** `machine_shape: "NvidiaTeslaT4"` son 2×T4 de 15 GB (comprobado en real con «Probar la GPU»).
Para la P100 de 16 GB, pon el nombre que use Kaggle para esa máquina: no está documentado, y lo más
probable es que sea `NvidiaTeslaP100`. En ese caso la estimación cuenta una sola GPU.

### Tiempos medidos en Kaggle (16-10-2026, 2× Tesla T4)

Primera tanda real: 2 clips de 5 s (121 fotogramas, 832×480, 24 fps). **fp16 funcionó a la
primera** en la T4, sin caer a fp32.

| | Por clip | Arranque de cada tanda |
|---|---|---|
| **Medido**, T4 fp16 | **29 s** (28.6 y 29.2 s) | **4.3 min** (pip, bajar los modelos, cargar y codificar) |
| Estimado antes de medir | ~1.5 min | ~12 min |

Con 2×T4 los clips se reparten entre las dos GPU. Por ejemplo, 40 escenas con vídeo IA
en una tanda ≈ 4.3 min + 40 × 0.5 / 2 min = **~15 min de las 30 h semanales**. La cabecera de la
pantalla ya usa estos tiempos medidos (`video_gpu.medido`).

**Calidad:** el clip cuyo texto encajaba con su imagen (un faro en la tormenta) salió estable,
con olas y luz en movimiento. En la prueba, a otro clip se le dio a propósito un texto que no
encajaba con su imagen, y el modelo «metió» lo del texto en la escena. La imagen y el texto de
cada escena tienen que contar lo mismo, que es lo normal cuando salen del mismo guion.

### Límites

- Clips de hasta `tope_s` = 5 s. Si la escena dura más, el clip se ralentiza hasta 1.4× (7 s) y luego
  se congela el último fotograma. Subir `tope_s` alarga el clip, pero gasta más GPU.
- 832×480 (casi 16:9), reescalado a 1080p en el montaje: se ve algo más blando que las fotos.
- Kaggle da 30 h/semana de GPU, con sesiones de 12 h como máximo (el tope de cada tanda es 11.5 h).
  Hace falta el teléfono verificado y el internet activado en el kernel.
- Mientras corre una tanda, el proyecto está ocupado y no se puede editar.

### Probado con una cuenta real (16-10-2026)

Funciona de punta a punta en Kaggle: push con `-t` y `--accelerator` a la vez, `pip install` de
diffusers y transformers sobre el Python 3.13 de Kaggle, carga del checkpoint 0.9.6 destilado con
`from_single_file`, generación en fp16 en las dos T4, descarga, registro de los clips y montaje.

Falta probar:

1. La subida como **dataset privado** (`datasets create`/`version`, la espera hasta `ready` y el
   montaje en `/kaggle/input`). Solo entra con tandas grandes, de más de ~5 escenas; la prueba
   real llevaba las imágenes dentro del script.
2. Una tanda grande (decenas de clips) repartida entre las dos GPU.
3. Si la calidad mejora con los `timesteps` del yaml oficial en vez de los 8 pasos uniformes de
   diffusers (`video_gpu.modelo.timesteps`).

Para probarlo, crea un proyecto nuevo de 2 escenas, marca «Vídeo IA», pulsa **3b** y mira el registro.
El log completo del kernel queda en `gpu_trabajos/video-simple-clips-*/salida/*.log`.

Fuentes: [model card LTX-Video](https://huggingface.co/Lightricks/LTX-Video),
[licencia LTX Open Weights](https://huggingface.co/Lightricks/LTX-Video/blob/main/LTX-Video-Open-Weights-License-0.X.txt),
[repo LTX-Video (configs y notas de versión)](https://github.com/Lightricks/LTX-Video),
[diffusers: LTX-Video](https://huggingface.co/docs/diffusers/main/en/api/pipelines/ltx_video),
[Wan 2.2 TI2V-5B](https://huggingface.co/Wan-AI/Wan2.2-TI2V-5B-Diffusers),
[CogVideoX-5B-I2V](https://huggingface.co/THUDM/CogVideoX-5b-I2V),
[metadatos de kernels](https://github.com/Kaggle/kaggle-cli/blob/main/docs/kernels_metadata.md),
[metadatos de datasets](https://github.com/Kaggle/kaggle-cli/blob/main/docs/datasets_metadata.md).

## Imágenes en la GPU de Kaggle (motor «GPU Kaggle»)

En Ajustes (o en el paso 3 del asistente) elige **«GPU Kaggle (gratis, sin límite, mejor calidad)»**
(`imagen.motor = "kaggle"`). El paso «3 · Imágenes» y «Rehacer imagen» (con nota) mandan las
imágenes a tu GPU de Kaggle (`motor/imagenes_gpu.py`). Si la GPU no está conectada, avisa y
abre el Asistente en el paso 5. Las escenas «misma imagen que la anterior» siguen sin generar nada.

**Modelo: FLUX.2 [klein] 4B** (Black Forest Labs, `Flux2KleinPipeline` de diffusers 0.39.0,
4 pasos, destilado, sin CFG). Por qué:
- **Licencia Apache 2.0**: uso comercial permitido, sin formularios (el repo no está restringido).
- Cabe en una T4: transformer de 4B (7,75 GB en fp16) + VAE; el codificador de texto (Qwen3 4B)
  se usa al principio en un subproceso y se libera, así caben **dos trabajadores, uno por T4**.
- **Admite imágenes de referencia** (edición multi-referencia): es lo que da personajes iguales.
- Alternativa configurada (`imagen_gpu.plan_b`): Z-Image-Turbo (Apache 2.0, 9 pasos). No admite
  referencias y pide offload en una T4; no se ha probado en real.

**Consistencia de personajes:**
1. Primero se genera una **hoja de personajes** del proyecto: los personajes de la biblia de
   cuerpo entero, de frente, en el estilo del vídeo, sobre fondo gris liso → `imagenes/hoja.png`
   (se ve en «Estilo y personajes»).
2. Cada escena con personajes se genera con la hoja **como imagen de referencia** (reducida a
   1024 px), el prompt de siempre (visual + personajes + estilo), la orden de copiar cara, cuerpo
   y ropa de la hoja, y semilla fija por escena. Las escenas sin personajes, sin referencia.
3. La hoja se reusa (va dentro del script, ~100 KB) al rehacer escenas o en tandas siguientes;
   si cambian el estilo o los personajes de la biblia, se rehace sola.

**Precisión:** fp16 en T4 funcionó a la primera (sin imágenes negras). Aun así, si una imagen sale
negra o con NaN, el trabajador pasa el transformer a bf16 (emulado, más lento) y la repite; el
VAE va siempre en fp32 y el codificador de texto repite en bf16 si da NaN.

**Tiempos medidos** (16-10-2026, 2× Tesla T4, fp16, 1344×768, 4 pasos):

| | Tiempo |
|---|---|
| Arranque de la tanda (pip, bajar ~16 GB del modelo, codificar prompts, cargar) | **3,9-4,3 min** (230-259 s en 3 tandas; la carga del modelo, 48 s) |
| Imagen sin referencia | **~10 s** |
| Imagen con la hoja como referencia | **~17 s** (16-18 s) |
| Hoja de personajes | 11,5 s |
| Prueba completa (hoja + 5 escenas), desde que se manda hasta que está en el proyecto | 5,5 min |

Con las dos GPU, un vídeo de 14 min (~85 imágenes) son unos 4 min de arranque + ~12 min de
imágenes: ~16 min de las 30 h semanales. Configuración en `imagen_gpu`: modelo, pasos, guía,
tamaño (múltiplos de 16), semilla, `referencias`, `max_por_tanda`, `machine_shape`, pip.

## Usuarios (sin login)

Desde el mismo PC se entra sin cuenta. Con 0 usuarios se crea `local` (sin contraseña); con
uno, se entra con ese; con varios, con el más antiguo, y arriba sale un selector para cambiar
sin contraseña. Las peticiones de otra máquina (si arrancas con `--host 0.0.0.0`) o que
llegan por un proxy siguen pidiendo usuario y contraseña. `VIDEOFREE_SIN_LOGIN=0` vuelve a
pedir login siempre.

## Claves

Las claves (Pollinations, Kaggle) se guardan en `secretos/<usuario>.json`, que está en
`.gitignore`: **no se suben nunca al repositorio**. `config.json` no lleva ninguna clave.

## Configuración (`config.json`)

- `guion.motor`: `manual` (ChatGPT a mano), `claude` u `ollama` (y `modelo_ollama`).
- `voz.voz`: cualquier voz de edge-tts (`es-MX-JorgeNeural`, `es-ES-ElviraNeural`…).
- `imagen`: motor (`pollinations`, `manual` o `kaggle`), tamaño, semilla, espera entre imágenes.
- `imagen_gpu`: el motor `kaggle` (ver «Imágenes en la GPU de Kaggle»).
- `video_gpu`: modelo y plan B, precisión, resolución, fps, pasos, tope de segundos por clip,
  escenas por tanda, `machine_shape`, versiones de pip y tiempos estimados o medidos.
- `montaje`: resolución, fps, cuánto zoom hace la cámara, subtítulos, música
  (`"musica": "musica/fondo.mp3"`, un fichero tuyo).

## Siguientes pasos posibles (siguen siendo gratis)

- **Profundidad 2.5D:** separar fondo y figura con un modelo de profundidad local para
  que la cámara haga paralaje (parece vídeo de verdad sin generar vídeo).
- **Imágenes en tu PC:** Stable Diffusion local (lento en GPUs de 4 GB).

## Estructura

```
app.py              servidor y rutas (FastAPI)
web/index.html      la pantalla
motor/guion.py      paso 1, Claude CLI u Ollama
motor/voz.py        paso 2, edge-tts
motor/imagenes.py   paso 3, Pollinations, pegadas a mano o de prueba
motor/montaje.py    paso 4, animación y montaje con ffmpeg
motor/gpu.py        GPU gratis de Kaggle: conectar, probar, datasets y mandar trabajos
motor/clips_gpu.py  clips de vídeo IA (LTX-Video) en Kaggle y el script del kernel
motor/imagenes_gpu.py  imágenes con FLUX.2 [klein] en Kaggle, con hoja de personajes
proyectos/<id>/     cada vídeo: proyecto.json y sus ficheros
```
