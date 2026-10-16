# Quiet Cosmos v3: canal de YouTube automatizado

> **Novedad v3 — escenas cinematográficas con IA.** Además de las fotos y videos reales de la NASA, cada
> episodio lleva escenas generadas por IA para mostrar lo que ninguna cámara puede captar (la vista desde
> la superficie de otro mundo, el disco de un agujero negro, la Tierra hace 4.000 millones de años).
> Se pintan gratis en la GPU de **Kaggle**, se animan con un **efecto 2.5D por mapa de profundidad** y en
> los momentos clave se convierten en **clips de video IA**. Cada escena cae justo en la frase que la
> narra, lleva un rótulo discreto *"AI artist's impression"* y el video se marca en YouTube como
> contenido sintético. Si Kaggle falla o no hay cuota, el episodio sale igual con imágenes de la NASA.

Quiet Cosmos publica documentales del espacio de 60 minutos, cinematográficos, calmados y con ciencia revisada, pensados para relajarse y dormir. Cada episodio sale con 2 Shorts verticales para atraer audiencia nueva. Todo el proceso es automático y usa solo código abierto: guion, revisión científica, voz, imágenes y video reales de la NASA, música original, edición, miniaturas, Shorts, control de calidad y subida a YouTube.

## Por qué este canal

| Criterio | Por qué gana "documentales del espacio para dormir" |
|---|---|
| Retención y horas | El espectador pone el video y lo deja correr. Un episodio de 60 minutos genera muchas horas de visualización, que es lo que pide el Programa de Socios (4.000 horas). |
| Materia prima inagotable y gratis | La NASA Image and Video Library tiene cientos de miles de fotos **y videos** reales, en general de dominio público, con una API que no requiere clave. |
| Producción 100% automatizable | La voz IA encaja con el género (narración lenta y pareja), y la edición se puede programar. |
| Contenido evergreen | "Qué hay dentro de un agujero negro" se busca hoy y se seguirá buscando en 5 años. |
| Anuncios | Ciencia y educación en inglés tiene un RPM alto. |

## Qué hace en cada episodio

```
Tema (cola que se rellena sola con Claude)
 └─ Claude: esquema → capítulos → gancho inicial → revisión científica y de pronunciación → 2 guiones de Shorts
     └─ Kokoro TTS (open source): narración pausada + subtítulos sincronizados
         └─ NASA: fotos por capítulo + clips de video reales (time-lapses, observatorios, visualizaciones)
             └─ Música ambiental original (acordes que evolucionan + reverb estéreo, sin derechos)
                 └─ Mezcla: voz ecualizada y comprimida, la música baja sola cuando habla la voz, normalización de volumen
                     └─ Motor de edición propio: movimientos de cámara suaves, fundidos cruzados, clips reales,
                        viaje 3D entre estrellas, título de apertura, tarjetas de capítulo, acabado de cine
                         └─ 3 miniaturas · Shorts verticales con subtítulos grandes · control de calidad
                             └─ Subida a YouTube: video + miniatura + subtítulos + capítulos + Shorts enlazados
```

### Lo que cuida la retención

- **Gancho de 30 segundos:** el video abre con un dato real impactante y con la mejor toma en movimiento del episodio, antes del título.
- **Estructura con progresión** (cerca → lejos, pequeño → inmenso), con curiosidades que se plantean al inicio y se resuelven más adelante.
- **Revisión científica automática:** una segunda pasada de Claude corrige datos, números y repeticiones antes de narrar.
- **Variedad visual:** cada capítulo tiene sus propias imágenes, entra un clip real cada 3 tomas, ninguna imagen se repite en todo el canal y el movimiento de cámara cambia en cada toma.
- **Capítulos en la línea de tiempo** de YouTube, más subtítulos.

### Control de calidad automático

Antes de subir, el sistema revisa varias cosas:
- que la duración coincida con la narración,
- que el volumen esté en un rango seguro,
- que no haya títulos leídos en voz alta,
- que no haya capítulos demasiado cortos,
- que no haya pantallas negras.

Si algo falla, **no sube nada** y el informe queda en `qa.json`.

## Configuración (una sola vez)

1. **Repo:** sube esta carpeta a tu repo privado de GitHub.
2. **Claude:** ejecuta `claude setup-token` en tu computadora y guarda el token como secreto `CLAUDE_CODE_OAUTH_TOKEN` (en Settings → Secrets and variables → Actions).
3. **Canal:** crea el canal y **verifícalo con tu teléfono** en youtube.com/verify. Sin verificación, YouTube no acepta videos de más de 15 minutos ni miniaturas personalizadas.
4. **Google Cloud** (gratis):
   - Crea un proyecto y habilita **YouTube Data API v3**.
   - En la pantalla de consentimiento OAuth, elige *External*, agrega tu correo como usuario de prueba y pulsa **Publish app**. Si se queda en modo de prueba, el token caduca a los 7 días.
   - Crea credenciales de tipo *OAuth client ID* → *Desktop app* y descárgalas como `client_secret.json`.
   - En tu computadora ejecuta `pip install google-auth-oauthlib` y luego `python scripts/get_youtube_token.py client_secret.json`. Inicia sesión con la cuenta del canal.
   - Guarda los 3 valores que imprime como secretos: `YT_CLIENT_ID`, `YT_CLIENT_SECRET` y `YT_REFRESH_TOKEN`.
5. **Kaggle (GPU gratis para las escenas IA):**
   - En kaggle.com → *Settings*, **verifica tu teléfono** (sin esto Kaggle no da GPU ni internet a los scripts).
   - En la misma página, *API → Create New Token* descarga `kaggle.json`. Guarda sus dos valores como
     secretos de GitHub: `KAGGLE_USERNAME` y `KAGGLE_KEY`.
   - Nada más. El sistema crea solo un script privado `quiet-cosmos-gen` en tu cuenta y lo vuelve a correr
     en cada episodio. Ahí puedes ver el registro de cada corrida.
6. **Auditoría de la API (importante):** Google deja en **privado** los videos que se suben desde proyectos de API nuevos. Pide la auditoría gratuita con el formulario *YouTube API Services – Audit and Quota Extension*. Mientras llega la aprobación, publicar es un clic por video en YouTube Studio.

Una vez configurado, corre solo **todos los días a las 7:17 a. m.** (hora de Lima). Cada corrida produce 1 episodio de unos 60 minutos y 2 Shorts.

## Cómo funcionan las escenas IA (v3)

```
Guion listo
 └─ Claude diseña ~140 escenas: para cada una, la frase exacta que ilustra + el prompt + el movimiento
     └─ Kaggle (2 GPU T4, gratis, en paralelo con la narración y la música):
          GPU 1: imágenes fotorrealistas (RealVisXL / SDXL, o FLUX) + Real-ESRGAN x2 → 2688×1536
          GPU 2: clips de video imagen→video (LTX-Video) de los momentos clave, también ampliados x2
     └─ GitHub Actions: mapas de profundidad (Depth Anything V2) → cámara 2.5D con paralaje real
        (el primer plano se mueve distinto del fondo), clips ralentizados con interpolación de movimiento
         └─ Edición: cada escena IA entra en el segundo exacto en que la voz la describe;
            la NASA llena el resto; el gancho inicial abre con el mejor clip IA
```

- **Tope de GPU:** `kaggle.gpu_budget_minutes` (120 por defecto). Lo que no alcance se reemplaza por NASA.
  Diario son unas 15 horas por semana, dentro de la cuota gratis de Kaggle (que se ve en tu perfil y puede cambiar).
- **Si algo falla** (sin cuota, cola larga, modelo que no carga): el episodio se publica igual con el aspecto v2
  y `qa.json` explica por qué (`ai_status`). Puedes forzar el modo v2 con la casilla *Escenas IA* en
  *Run workflow* o con `--no-ai`.
- **Honestidad:** las escenas son reconstrucciones artísticas basadas en la ciencia actual, rotuladas en
  pantalla y en la descripción, y el video se marca como contenido sintético en YouTube.

## Ver los resultados

En **Actions**, abre una corrida y baja hasta **Artifacts** para descargar **episode-files**. Contiene:
- `preview-10min.mp4`: los primeros 10 minutos del episodio,
- `short.mp4`: los Shorts,
- `thumbnail_1/2/3.jpg`: las tres miniaturas,
- `qa.json`: el informe de calidad (incluye cuántas escenas IA entraron y el estado de Kaggle),
- `scenes.json`, `ai_media.json`, `ai/log.txt`: el plan de escenas y el registro de la GPU,
- `script.json`: el guion completo.

Se sube la miniatura 1. Las otras dos sirven para la prueba A/B de YouTube Studio (*Test & compare*).

## Tiempos y costos

- **Por episodio:** unas 3 a 5 horas en las máquinas gratis de GitHub (la GPU de Kaggle trabaja en paralelo), sin que tengas que estar presente.
- **Minutos de GitHub Actions:** el repo es **público**, así que los minutos son ilimitados. Tus claves siguen protegidas como secretos. Para ir más rápido puedes registrar una PC propia como *self-hosted runner* (Settings → Actions → Runners) y crear la variable de repositorio `RUNNER` con el valor `self-hosted`.
- **Kaggle:** hasta 2 horas de GPU por episodio, gratis.
- **Claude:** unas 18 a 21 llamadas por episodio (3 más para diseñar las escenas IA), que entran en tu plan.

## Ajustes (`config.yaml`)

- `target_minutes`: 60 por defecto. Con 90 o más se juntan más horas de visualización, a cambio de más tiempo de render.
- `voice.speed`: 0.75 por defecto. Más bajo es más lento.
- `voice.id`: cambia la voz.
- `shorts.count`: Shorts por episodio. Con 0 se desactivan.
- `mix.music_volume`: volumen de la música.
- `clip_every`: frecuencia de los clips de video.
- **Horario:** se cambia en el `cron` de `.github/workflows/produce.yml`.
- **Idioma:** con `language: es` y `voice.id: ef_dora` el mismo sistema produce un canal en español.

## Probar en tu computadora

```bash
sudo apt install ffmpeg espeak-ng fonts-inter
pip install -r requirements.txt
python -m pipeline.run --topic "Saturn's rings" --no-upload
```

Todo queda en `outputs/<tema>/`.
