# Pitch deck técnico · Briefly

Material de la presentación final (entrega: 8-oct-2026).

**Demo: la app desplegada** en <https://multimodal-market-briefer-production.up.railway.app/> (Railway, rama `entrega-v1`, versión `v1.0`). Abre en modo demo, sin
claves ni gasto, con un briefing real pregenerado; el modo Real pide una contraseña que el equipo da aparte. No hay
vídeo grabado: la demo se hace en vivo sobre esa URL con [`demo_guion.md`](demo_guion.md).

| Fichero | Qué es |
| --- | --- |
| [`pitch_briefly.pdf`](pitch_briefly.pdf) | Deck técnico exportado: **7 diapositivas** 16:9 (1280 × 720) |
| [`pitch_briefly.html`](pitch_briefly.html) | Fuente del deck (HTML + CSS inline, fuente Source Serif 4 local, logo de `docs/assets/marca/`, captura `docs/assets/capturas/01_portada.png`) |
| [`demo_guion.md`](demo_guion.md) | Guion de la demo en vivo sobre la app desplegada (3:30-4:00 min): checklist previa, pasos con tiempos y locución, plan B |
| `assets/qr_demo.png` | QR de la app desplegada (diapositiva 7); lo genera el script con `--demo-url` |

**Formato.** La mitad de la presentación es la demo en vivo, así que el deck solo acompaña: poco texto, cifras
grandes y un mensaje por diapositiva.

| # | Diapositiva | Contenido |
| --- | --- | --- |
| 1 | Portada | Logo, eslogan, qué es en una línea, MIAX B5-T4 · 8-oct-2026, equipo |
| 2 | Problema | Una frase y tres bloques: titulares dispersos, PDFs de 40 páginas, gráficos sin contexto |
| 3 | Qué es Briefly | Captura real de la app en un portátil; entradas → salidas; por qué multimodal y no un chat |
| 4 | Cadena de modelos | CLIP → Claude visión → Analista Sonnet 5.5 → Guionista Haiku 4.5 → TTS → vídeo + portada; rama Q&A por voz |
| 5 | Números y negocio | 0,034 € y 53 s por briefing (p50, N = 6), 6 s por pregunta de voz; B2B2C, fijo y equilibrio (est.) |
| 6 | Compliance | «Informa, no asesora»: MiFID II, AI Act art. 50, RGPD, fuentes citadas |
| 7 | Demo en vivo y cierre | URL + QR, repo · v1.0, siguientes pasos, lema y aviso legal |

**Regenerar el PDF** (Chrome o Edge del sistema en modo headless):

```bash
.venv/Scripts/python scripts/build_pitch.py --demo-url https://multimodal-market-briefer-production.up.railway.app/
                                                                 # QR en pitch/assets/qr_demo.png (segno) + PDF
.venv/Scripts/python scripts/build_pitch.py                      # solo el PDF (reutiliza el QR existente)
.venv/Scripts/python scripts/build_pitch.py --preview <carpeta>  # + una PNG de 1280 × 720 por diapositiva
```

El QR solo hay que generarlo una vez (o si cambia la URL; entonces cambia también el texto de la diapositiva 7).
Sin `segno` o sin QR, la diapositiva 7 muestra un marcador en su lugar; si falta la captura, la 3 muestra un marco
con su nombre. Inter y JetBrains Mono no van incluidas: si no están instaladas, el deck usa Segoe UI y Consolas.

Fuentes de las cifras: `docs/04_viabilidad_costes_latencia_compliance.md` (§ 3, evaluación N = 6 y Q&A por voz;
§ 6, negocio) y el README. Toda cifra va medida o marcada como estimación («est.»).

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
final (p. ej. «Cada paso con el modelo que basta»), con una línea de contexto en mono gris encima
(`03 · CADENA DE MODELOS`) al estilo de la cabecera de la app. Un mensaje por diapositiva.

**Tono:** el de la marca: serio con los datos, cercano al contarlo. Nada de promesas de rentabilidad ni
lenguaje de recomendación; el aviso legal (con el de voces sintéticas) va al pie de la diapositiva 7
y la 6 resume los controles de compliance. Toro y Osa se pueden presentar como «los locutores» del producto.
