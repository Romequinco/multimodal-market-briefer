# Pitch deck técnico · Briefly

Material de la presentación final (entrega: 8-oct-2026).

| Fichero | Qué es |
| --- | --- |
| [`pitch_briefly.pdf`](pitch_briefly.pdf) | Deck técnico exportado: 12 diapositivas 16:9 (1280 × 720) |
| [`pitch_briefly.html`](pitch_briefly.html) | Fuente del deck (HTML + CSS inline, fuente Source Serif 4 local, logos de `docs/assets/marca/`, capturas de `docs/assets/capturas/`) |
| [`demo_guion.md`](demo_guion.md) | Guion de la demo grabada (3:30-4:00 min): checklist previa, pasos con tiempos, locución, trucos de edición |
| `assets/` | Fotograma del vídeo 9:16 del pregenerado (lo extrae el script) y, si se genera, el QR de la demo |

**Regenerar el PDF** (Chrome o Edge del sistema en modo headless; sin dependencias nuevas):

```bash
.venv/Scripts/python scripts/build_pitch.py                    # → pitch/pitch_briefly.pdf
.venv/Scripts/python scripts/build_pitch.py --preview <carpeta> # + una PNG por diapositiva para revisar
.venv/Scripts/python scripts/build_pitch.py --demo-url <URL>    # + QR de la demo (requiere pip install segno)
```

**Marcadores por rellenar** en `pitch_briefly.html` (buscar `MARCADOR`): `[tercer integrante]` (diapositivas 1 y
12) y `[enlace a la demo]` (diapositiva 10). Si falta una captura, la diapositiva de producto muestra un marco con
su nombre en vez de romper el diseño. Inter y JetBrains Mono no van incluidas: si no están instaladas, el deck usa
Segoe UI y Consolas.

Contenido original previsto:
- `pitch_briefly.pdf` — deck técnico exportado (10-12 diapositivas):
  problema y usuario, propuesta de valor, demo, arquitectura multimodal (diagrama de flujo
  de datos), modelos encadenados y por qué, costes por briefing y latencias medidas
  (de `StepMetric`), compliance (MiFID II: no es asesoramiento; RGPD: datos de cartera),
  monetización (B2C como cara visible, B2B2C de marca blanca como negocio) y roadmap
  (edición de mañana, recorte automático de capturas de cartera). El vídeo 9:16, el router
  CLIP y la cartera desde captura ya están hechos (06-oct); portada y Telegram, implementados sin
  prueba real: ver `docs/06_estado_actual.md` antes de contarlos como demostrados.
- `capturas/` — capturas de la app para el deck y el README.
- `demo/` — enlace o vídeo corto de la demo (los `.mp4` pesados no se versionan; subir a un
  enlace externo y referenciarlo aquí).
- Guion de la presentación (quién cuenta qué y tiempos).

Fuentes de datos para las cifras: `docs/04_viabilidad_costes_latencia_compliance.md` y las
métricas reales que muestra la app. Toda cifra va medida (y se dice cómo) o marcada como estimación.

## Uso de la marca en el deck

Guía completa en [docs/08_identidad_marca.md](../docs/08_identidad_marca.md). Resumen para montar las
diapositivas:

**Nombre y eslogan.** «Briefly» (siempre con mayúscula inicial en el texto; el logo lo escribe en minúscula) y
«El cierre del día, mientras vuelves a casa». El repo y el paquete se llaman `multimodal-market-briefer` /
`briefer`: en la diapositiva de arquitectura se puede mostrar tal cual, pero no como nombre del producto.

**Logo** (`docs/assets/marca/`):

| Fichero | Dónde usarlo en el deck |
| --- | --- |
| `briefly_logo_oscuro.svg` | Portada y cierre sobre fondo `#12151B` (versión principal) |
| `briefly_logo_claro.svg` | Diapositivas con fondo claro, si alguna lo necesita (p. ej. tablas densas) |
| `briefly_logo_mono.svg` | Pie de página pequeño o impresión en un solo color |
| `briefly_vertical.svg` | Diapositiva de portada con eslogan, formato centrado |
| `briefly_icono.svg` | Marca de agua o esquina de cada diapositiva (≥ 24 px) |

**Paleta** (la de la app, «Noticiero nocturno»): fondo `#12151B`, paneles `#1C2129`, texto `#D6DEE8`, títulos
`#FFFFFF`, secundario `#9A9992`, acento `#C0502A` (rellenos, barras) y `#F0997B` (texto o detalle sobre oscuro),
sube `#5DCAA5`, baja `#F09595`, etiquetas técnicas en ámbar `#EF9F27`. El verde y el rojo solo para datos que
suben o bajan, nunca como decoración; y siempre con ▲/▼ o signo, no solo color.

**Tipografía:** Source Serif 4 seminegrita para títulos de diapositiva; Inter para el cuerpo; JetBrains Mono para
cifras, tickers, costes y latencias. La fuente serif va en `docs/assets/marca/fuentes/` (licencia OFL); Inter y
JetBrains Mono, de Google Fonts.

**Estilo de título de diapositiva:** una afirmación corta en serif, en minúscula salvo la inicial y sin punto
final (p. ej. «Seis modelos, una sola cadena»), con una línea de contexto en mono gris encima (`02 · ARQUITECTURA`)
al estilo de la cabecera de la app. Un mensaje por diapositiva.

**Tono:** el de la marca: serio con los datos, cercano al contarlo. Nada de promesas de rentabilidad ni
lenguaje de recomendación; el disclaimer y el aviso de voces sintéticas aparecen en la diapositiva de
compliance y en la de la demo. Toro y Osa se pueden presentar como «los locutores» del producto.
