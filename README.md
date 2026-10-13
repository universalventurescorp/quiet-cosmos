# Quiet Cosmos — canal de YouTube automatizado

Documentales del espacio largos (≈40 min), calmados, para relajarse y dormir. Todo el pipeline corre gratis en GitHub Actions: guion → voz → imágenes → música → video → miniatura → subida a YouTube, 3 veces por semana, sin que toques nada.

## Por qué este nicho

| Criterio | Por qué gana "espacio para dormir" |
|---|---|
| Retención | El espectador pone el video y se queda; los videos de 40–90 min generan muchísimas horas de visualización, que es justo lo que pide el Programa de Socios (4.000 horas). |
| Materia prima infinita y gratis | La NASA Image Library tiene cientos de miles de imágenes reales, en general de dominio público, con API sin clave. |
| La voz IA encaja | El género pide narración lenta y uniforme, justo donde el TTS suena mejor. |
| Contenido evergreen | "Qué hay dentro de un agujero negro" se busca hoy y dentro de 5 años. |
| Anuncios | Ciencia/educación en inglés tiene RPM por encima del promedio. |

Inglés por defecto (más audiencia y RPM). Para una versión en español basta con `language: es` y `voice.id: ef_dora` en `config.yaml`: es un segundo canal con el mismo pipeline.

## Cómo funciona

```
data/topics.json ─▶ Claude (claude -p, tu plan Pro) ─▶ guion por capítulos
                                                         │
     Kokoro TTS (open source) ◀──────────────────────────┘ voz + subtítulos exactos
     NASA Image API ─▶ imágenes por capítulo (nunca repite una imagen en todo el canal)
     Música ambiental original generada por código (sin derechos, distinta en cada episodio)
     FFmpeg ─▶ Ken Burns lento + fundidos + mezcla + loudnorm ─▶ video 1080p
     Pillow ─▶ miniatura   │   descripción con capítulos y créditos
     YouTube Data API ─▶ video + miniatura + subtítulos
```

Cuando quedan menos de 5 temas en la cola, Claude propone 20 nuevos automáticamente. Si una corrida falla a la mitad, se retoma desde el último paso terminado.

## Lo que tienes que hacer tú (una sola vez, ~30 min)

1. **Repo**: crea un repo privado en GitHub y sube esta carpeta tal cual.
2. **Claude**: en tu computadora con Claude Code instalado, ejecuta `claude setup-token`. Guarda el token como secreto del repo `CLAUDE_CODE_OAUTH_TOKEN` (Settings → Secrets and variables → Actions).
3. **Canal**: crea el canal "Quiet Cosmos" (si el nombre está tomado, cámbialo aquí y en `config.yaml`). **Verifica el canal con tu teléfono** en youtube.com/verify: sin eso YouTube no acepta videos de más de 15 minutos ni miniaturas personalizadas.
4. **Google Cloud** (gratis):
   - Crea un proyecto en console.cloud.google.com y habilita **YouTube Data API v3**.
   - Pantalla de consentimiento OAuth: tipo *External*, agrega tu correo como usuario de prueba y luego pulsa **Publish app / En producción**. Si se queda en "Testing", el token caduca a los 7 días y las subidas dejan de funcionar.
   - Credenciales → OAuth client ID → *Desktop app* → descarga el JSON como `client_secret.json`.
   - En tu computadora: `pip install google-auth-oauthlib` y `python scripts/get_youtube_token.py client_secret.json`. Inicia sesión con la cuenta del canal.
   - Guarda los 3 valores que imprime como secretos: `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN`.
5. **Primera prueba**: Actions → *produce-episode* → *Run workflow*. Tarda 1–3 horas (voz y render en CPU). El video aparece en YouTube Studio como **privado**.

Después corre solo lunes, miércoles y viernes a las 7:17 a. m. (hora de Lima).

## Dos límites reales que debes conocer

- **Los videos suben en privado.** Google bloquea en privado los videos subidos por API desde proyectos nuevos sin auditar. Hay dos caminos: publicarlos tú (un clic por video en Studio) o pedir la auditoría gratuita de la API (formulario "YouTube API Services – Audit and Quota Extension"). Mi recomendación: publica tú los primeros videos, igual conviene revisarlos.
- **Política de "contenido inauténtico".** YouTube desmonetiza canales de videos masivos y repetitivos. Este pipeline la mitiga: guiones únicos por episodio con ciencia verificable, estructura distinta por capítulo, imágenes que nunca se repiten, música original y créditos honestos. Aun así, **mira 2 minutos de cada video antes de publicarlo** al menos el primer mes: eso es lo que más protege la monetización.

## Monetización

- Programa de Socios: 1.000 suscriptores + 4.000 horas de visualización pública en 12 meses. Con 3 videos de 40 min por semana, las horas llegan rápido si el canal despega.
- Después: membresías y un segundo canal en español con el mismo pipeline.

## Ajustes útiles (`config.yaml`)

- `target_minutes`: 40 por defecto. Puedes subir a 60–90 cuando el canal funcione (más horas de visualización, más tiempo de render).
- `voice.id` y `speed`: prueba voces en el demo de Kokoro y elige la que más te guste.
- Horario: `cron` en `.github/workflows/produce.yml`.
- Consumo: cada episodio usa unas 8–10 llamadas a Claude de tu plan Pro, y 60–120 minutos de GitHub Actions (el plan gratis de repos privados trae 2.000 min/mes, suficiente para unos 12–15 episodios al mes).

## Probar en local

```bash
sudo apt install ffmpeg espeak-ng   # (macOS: brew install ffmpeg espeak-ng)
pip install -r requirements.txt
python -m pipeline.run --no-upload                  # siguiente tema de la cola
python -m pipeline.run --topic "Saturn's rings" --no-upload
```
Todo queda en `outputs/<tema>/`: `video.mp4`, `thumbnail.jpg`, `captions.srt`, `metadata.json`, `script.json`.
