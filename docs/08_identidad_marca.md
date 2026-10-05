# 08 · Identidad de marca

> Guía de marca de **Briefly**, la startup ficticia detrás del MVP. Da contexto al producto en la app, el README,
> el audio y el pitch. Documento vivo: registra las decisiones a medida que se toman; lo pendiente se marca
> **PENDIENTE**.

**Briefly** · *«El cierre del día, mientras vuelves a casa»*. Lo que ha movido tu cartera hoy, contado a dos voces
en unos cuatro minutos.

**Nombres internos.** Solo cambia lo que ve u oye el usuario. El paquete Python sigue siendo `briefer`, el
repositorio `multimodal-market-briefer`, las variables de entorno `BRIEFER_*` y el servicio de Docker conservan su
nombre. Los textos de marca (nombre, eslogan, propuesta de valor, edición, saludo, locutores y lema) viven en
`src/briefer/brand.py` y de ahí los leen la app, el guion, la transcripción, los gráficos, los metadatos del audio
y los envíos: **no se repiten a mano** en ningún otro sitio.

## Índice

1. [Decisiones](#decisiones)
2. [Logo](#logo)
3. [Color](#color)
4. [Tipografía](#tipografía)
5. [Tono de voz](#tono-de-voz)
6. [Locutores: Toro y Osa](#locutores-toro-y-osa)
7. [Formatos](#formatos)
8. [Notas sobre el nombre](#notas-sobre-el-nombre)
9. [Quiénes somos](#quiénes-somos)

## Decisiones

| Ámbito | Decisión | Notas |
| --- | --- | --- |
| Nombre | **Briefly** | El programa (podcast) se llama igual que la marca. Ver [notas sobre el nombre](#notas-sobre-el-nombre) |
| Eslogan | **«El cierre del día, mientras vuelves a casa»** | `brand.TAGLINE` |
| Tono de voz | **Radio nocturna + mezcla**: serio y preciso en los datos, cercano en la conversación entre locutores | Nunca suena a consejo: «Te contamos el mercado; tú decides.» (`brand.COMPLIANCE_MOTTO`) |
| Arquetipo | **Sabio + Explorador**: claridad y conocimiento, con curiosidad por descubrir qué se ha movido | |
| Público | **B2C como cara visible** (inversor minorista que escucha en el trayecto) **y B2B2C como negocio** (neobancos y *brokers* con su marca) | Coherente con [01](01_producto_y_propuesta_valor.md) y [04](04_viabilidad_costes_latencia_compliance.md) |
| Momento | **Edición de noche** (al cierre); saludo «Buenas noches» | Edición de mañana (antes de la apertura) como roadmap |
| Paleta | **Noticiero nocturno** (la actual de la app) | Tokens y contrastes en [Color](#color) |
| Tipografía | **Source Serif 4** (marca y titulares) · **Inter** (texto) · **JetBrains Mono** (datos y rótulos) | Google Fonts, ya cargadas en la app |
| Locutores | **Toro** (voz A, el optimista) y **Osa** (voz B, la prudente, cierra con el aviso legal) | Guiño a *bull & bear*. Voces sintéticas (edge-tts) |
| Logo | **LG1-A · velas-ecualizador** | Ver [Logo](#logo) |
| «Quiénes somos» | Texto de broma corto (misión, valores, equipo) | Página `app/pages/5_Quienes_somos.py`; texto [abajo](#quiénes-somos) |
| Formatos | Ahora: guía de marca, logo SVG y favicon, marca en la app, banner del README. Después: portada, vídeo 9:16, tarjeta de Telegram y pitch | Ver [Formatos](#formatos) |

## Logo

### Concepto

**LG1-A · velas-ecualizador.** Cuatro velas japonesas (mecha + cuerpo) colocadas a alturas de ecualizador, de modo
que el mismo dibujo se lee como **gráfico de mercado** y como **barras de audio**: las dos mitades del producto.
Las velas alternan el acento suave `#F0997B` y el acento `#C0502A`. A la derecha, la palabra **«briefly» en
minúscula**, en Source Serif 4 seminegrita: minúscula para que suene cercano, serif para que suene a periódico.

### Variantes

Todas en `docs/assets/marca/`.

| Fichero | Qué es | Cuándo usarlo |
| --- | --- | --- |
| `briefly_logo_oscuro.svg` | Logo horizontal (velas + palabra) para fondo oscuro | **Versión principal**: app, cabeceras, portada del pitch, todo lo que va sobre `#12151B` o `#1C2129` |
| `briefly_logo_claro.svg` | Logo horizontal para fondo claro | Documentos impresos, diapositivas claras, fondos blancos |
| `briefly_logo_mono.svg` | Logo en un solo color | Impresión a una tinta, marcas de agua, sellos sobre fotografía; cuando el color no está garantizado |
| `briefly_vertical.svg` | Velas encima de la palabra, con el eslogan | Portadas centradas, carteles, diapositiva de cierre, formatos verticales |
| `briefly_icono.svg` | Solo las cuatro velas en un cuadrado | Favicon, avatar de Telegram y redes, icono de app; espacios donde no cabe la palabra |
| `briefly_icono_32.png` · `briefly_icono_192.png` · `briefly_icono_512.png` | El icono rasterizado | 32 px: favicon del navegador · 192 px: icono de PWA / acceso directo · 512 px: avatar y tiendas |
| `briefly_banner.png` | Banner 1280 × 320 con logo y eslogan | Cabecera del README y de la página del repositorio |
| `fuentes/` | Source Serif 4 con su licencia OFL | Para reproducir la palabra o los titulares fuera de la app (deck, vídeo) |

### Área de respeto y tamaño mínimo

- **Área de respeto:** alrededor del logo se deja libre, como mínimo, la altura de la vela más alta. Nada de texto,
  bordes ni otros logos dentro de ese margen.
- **Tamaño mínimo:** logo horizontal a **96 px** de ancho en pantalla (25 mm impreso); por debajo, usar el icono.
  Icono a **16 px** como mínimo (favicon); por debajo de 24 px, las mechas pueden desaparecer y es aceptable.
- Sobre fondos de color o fotografía, la versión mono o el logo oscuro sobre una placa `#12151B`.

### Lo que no se hace

- No cambiar el orden ni el número de velas, ni convertirlas en un gráfico real con datos.
- No usar el verde «sube» ni el rojo «baja» en el logo: el logo no opina sobre el mercado.
- No escribir el nombre en mayúsculas («BRIEFLY») ni con otra tipografía dentro del logo.
- No deformar, rotar, añadir sombras, degradados ni contornos.
- No colocar el logo oscuro sobre fondo claro (ni el claro sobre oscuro): para eso están las dos variantes.
- No acompañar el logo de frases que suenen a recomendación («invierte con…», «gana con…»).

## Color

Paleta **«Noticiero nocturno»**: base oscura de terminal, titulares de periódico y un naranja «en antena». Los
tokens son los de `app/components/theme.py` (`TOKENS`); los colores base se repiten en `.streamlit/config.toml`.

| Token | Hex | Papel |
| --- | --- | --- |
| `bg` | `#12151B` | Fondo general |
| `bg-sidebar` | `#0E1116` | Barra lateral, cinta de cotizaciones |
| `surface` | `#1C2129` | Tarjetas, reproductor, métricas |
| `surface-2` | `#232A34` | Superficie elevada (etiquetas, *hover*) |
| `border` | `#2A313B` | Bordes decorativos (tarjetas, separadores); no apto para controles |
| `border-strong` | `#6B7480` | Borde de controles (campos, selectores, botones secundarios) |
| `text` | `#D6DEE8` | Texto de cuerpo |
| `text-strong` | `#FFFFFF` | Titulares y cifras destacadas |
| `text-muted` | `#9A9992` | Metadatos, fechas, texto secundario, «neutral» |
| `accent` | `#C0502A` | Color de marca: relleno del botón primario, velas del logo, disco del reproductor |
| `accent-hover` | `#B84A26` | Botón primario al pasar el ratón |
| `accent-soft` | `#F0997B` | Acento como **texto** sobre oscuro: «● en antena», enlaces, pestaña activa, anillo de foco, velas del logo |
| `up` | `#5DCAA5` | Sube / sentimiento positivo (solo datos) |
| `down` | `#F09595` | Baja / sentimiento negativo / error (solo datos) |
| `amber` | `#EF9F27` | Etiquetas técnicas en mono, avisos |

Reglas de uso:

- **El color nunca es la única señal**: cada variación lleva ▲/▼/● y signo (`+1,20 %`).
- Verde y rojo son **semánticos**: solo para datos que suben o bajan. Nunca en el logo ni como decoración.
- `accent` (#C0502A) es para rellenos y bordes; para **texto** sobre fondo oscuro se usa `accent-soft`.

### Contrastes validados (WCAG 2.1 AA)

`CONTRAST_PAIRS` en `app/components/theme.py` declara los pares que comprueba `tests/test_app_a11y.py`: **4,5:1**
para texto normal y **3:1** para componentes de interfaz y gráficos. Ratios calculados con la misma fórmula que
`contrast_ratio()` del módulo:

| Primer plano | `bg` | `bg-sidebar` | `surface` | `surface-2` | Mínimo exigido |
| --- | --- | --- | --- | --- | --- |
| `text` | 13,47 | 13,93 | 11,91 | 10,65 | 4,5 (texto) |
| `text-strong` | 18,28 | 18,91 | 16,17 | 14,46 | 4,5 (texto) |
| `text-muted` | 6,39 | 6,62 | 5,66 | 5,06 | 4,5 (texto) |
| `accent-soft` | 8,31 | 8,60 | 7,35 | 6,57 | 4,5 (texto) y 3 (anillo de foco) |
| `up` | 9,10 | 9,42 | 8,05 | 7,20 | 4,5 (texto) |
| `down` | 8,22 | 8,50 | 7,27 | 6,50 | 4,5 (texto) |
| `amber` | 8,41 | 8,70 | 7,44 | 6,65 | 4,5 (texto) |
| `accent` | 3,85 | 3,98 | 3,40 | 3,05 | 3 (relleno/borde de UI; **no** apto para texto) |
| `border-strong` | 3,86 | 3,99 | 3,41 | — | 3 (borde de controles) |

| Par | Ratio | Uso |
| --- | --- | --- |
| Blanco `#FFFFFF` sobre `accent` | 4,75 | Texto del botón primario |
| Blanco `#FFFFFF` sobre `accent-hover` | 5,19 | Texto del botón primario (*hover*) |
| `border` sobre `bg` | 1,39 | Solo decorativo: por eso los controles usan `border-strong` |

Historia del ajuste (en el propio `theme.py`): `text-muted` era `#888780` y `accent` era `#D85A30`; se oscurecieron
o aclararon para pasar AA sin cambiar el carácter de la paleta.

## Tipografía

| Familia | Rol | Pesos | Dónde y tamaño (app) |
| --- | --- | --- | --- |
| **Source Serif 4** | Marca y titulares: la voz de «periódico» | 400 y 600 | Nombre en la cabecera 2,1 rem (1,7 rem en móvil) · titular del episodio 1,5-2,1 rem (fluido) · títulos de puntos clave 18 px · eslogan 1,15 rem en 400 · título del reproductor 1,05 rem |
| **Inter** | Texto de lectura: explicaciones, transcripción, formularios | 400, 500, 600 | Cuerpo 15 px con interlineado 1,5 · fuentes 13 px |
| **JetBrains Mono** | Datos y rótulos: tickers, cifras, fechas, costes, latencias, etiquetas técnicas | 400 y 500 | Cinta de cotizaciones y metadatos 12 px · píldoras y leyendas 11,5 px · etiquetas de métricas 11 px en mayúsculas con espaciado 0,06 em · valor de métrica 1,35 rem |

Reglas:

- Titulares en serif seminegrita, con espaciado ligeramente cerrado (−0,01 em) y en minúscula salvo la inicial.
- **Toda cifra va en mono** (precios, porcentajes, euros, segundos): se alinea y se lee como dato.
- Formato numérico español: `1.234,56`, `+1,20 %`, fechas `LUN · 05/10/2026`.
- Las tres familias se cargan desde Google Fonts en la app; Source Serif 4 va además en
  `docs/assets/marca/fuentes/` con su licencia OFL para usarla fuera de la app.

## Tono de voz

**Radio nocturna.** Serio y preciso con los datos, cercano en la conversación. El oyente vuelve a casa cansado:
frases cortas, una idea por frase, cifras redondeadas cuando se dicen en voz alta y siempre la fuente. Sabio
(explica el porqué) y explorador (curiosidad por lo que se ha movido), nunca vendedor.

Los ejemplos de esta sección y de la siguiente son **ilustrativos**: las cifras y fuentes son inventadas.

| Sí | No | Por qué |
| --- | --- | --- |
| «Inditex ha cerrado con una caída del 2 %, tras publicar sus resultados del trimestre, según Expansión.» | «Inditex se ha desplomado: ¡ojo!» | Dato, causa y fuente; sin dramatismo |
| «Te contamos el mercado; tú decides.» | «Es buen momento para entrar en Santander.» | **Nunca** recomendación de compra o venta (MiFID II) |
| «Para quien tenga NVIDIA en cartera, hoy ha sido un día movido.» | «Si tienes NVIDIA, deberías vender antes de que siga cayendo.» | Se describe el efecto, no se dice qué hacer |
| «La subida coincide con el dato de inflación; no sabemos si irá a más.» | «Esto va a seguir subiendo, seguro.» | Sin predicciones ni certezas sobre precios |
| «Buenas noches. Esto es Briefly, el cierre del día.» | «¡Hola, inversores! ¡Vamos a ganar dinero!» | Saludo de la edición de noche, tono de radio |
| «Somos voces sintéticas; el análisis lo ha hecho una IA a partir de noticias citadas.» | Hacerse pasar por periodistas humanos | Transparencia (AI Act) |

Palabras que no se usan: «recomendamos», «compra», «vende», «oportunidad», «chollo», «seguro», «garantizado»,
«objetivo de precio» (salvo citando literalmente a un analista con su fuente). Los guardarraíles del Agente
Guionista y las puertas deterministas ([ADR-006](decisiones/ADR-006-guionista-haiku-puertas-deterministas.md)) son
la versión automática de esta tabla.

## Locutores: Toro y Osa

| | **Toro** | **Osa** |
| --- | --- | --- |
| Voz | A (`BRIEFER_VOICE_A`, por defecto `es-ES-AlvaroNeural`) | B (`BRIEFER_VOICE_B`, por defecto `es-ES-ElviraNeural`) |
| Papel | El optimista: **abre** el episodio y se fija primero en lo que sube | La prudente: pone el **contexto y los riesgos** y **cierra con el aviso legal** |
| En el Q&A | — | Es la voz que responde a las preguntas |
| Ejemplo | «Buenas noches. Esto es Briefly, y hoy hay verde en la pantalla: Iberdrola ha subido un 1,5 %.» | «Antes de que lo celebres, Toro: el Ibex ha caído en conjunto, así que no todo ha sido verde.» |
| Ejemplo | «Lo de NVIDIA da para un rato: los resultados han superado lo que esperaba el mercado, según Reuters.» | «Y como siempre: esto es información, no una recomendación. Somos voces sintéticas. Buenas noches.» |

- Guiño a *bull & bear* (toro alcista, oso bajista). **Personalidad, nunca opinión**: los dos se ciñen a los hechos
  del análisis y ninguno recomienda comprar ni vender. El optimismo de Toro es de tono, no de contenido.
- **Voces sintéticas**, generadas con edge-tts. Se dice en el audio, en la transcripción y en la app.
- Los nombres por defecto salen de `brand.SPEAKER_A_NAME` / `SPEAKER_B_NAME` y se pueden cambiar con
  `BRIEFER_SPEAKER_A_NAME` / `BRIEFER_SPEAKER_B_NAME` (p. ej. para un cliente de marca blanca).

## Formatos

| Formato | Estado | Notas |
| --- | --- | --- |
| Guía de marca (este documento) | Hecho | |
| Logo SVG, icono y favicon | Hecho | `docs/assets/marca/` |
| Marca en la app (cabecera, tema, «Quiénes somos») | Hecho | `app/components/theme.py`, `app/pages/5_Quienes_somos.py` |
| Banner del README | Hecho | `docs/assets/marca/briefly_banner.png` (1280 × 320) |
| Portada del episodio | **PENDIENTE** | Fondo `bg`, logo oscuro, titular del día en serif, fecha en mono. La portada generada por IA (texto → imagen) va en D2 |
| Vídeo corto 9:16 | **PENDIENTE** | Icono arriba, gráfico del día, subtítulos en Inter sobre placa `surface`, nombre del locutor que habla en mono. Disclaimer en el último plano |
| Tarjeta de Telegram | **PENDIENTE** | Avatar = `briefly_icono_512.png`; mensaje con titular, 3 puntos clave con ▲/▼, audio adjunto y disclaimer |
| Plantilla del pitch | **PENDIENTE** | Reglas de uso en [pitch/README.md](../pitch/README.md) |
| Edición de mañana | Roadmap | Misma identidad; cambia el saludo y el eslogan de la edición |

## Notas sobre el nombre

- «Briefly» es una palabra común en inglés y un nombre **muy usado** en productos digitales. Para un uso real habría
  que revisar disponibilidad en **OEPM** (España) y **EUIPO** (UE) en las clases relevantes (servicios financieros
  de información, software, radiodifusión/podcast) y la del dominio. **No se ha hecho**: este es un proyecto
  académico y el nombre no está registrado.
- Alternativa si hubiera conflicto: **«Briefly Mercados»**.
- En texto se escribe «Briefly» (mayúscula inicial); el logo lo escribe en minúscula como recurso gráfico.
- «Market Briefer» fue el nombre de trabajo del proyecto; sigue en los nombres técnicos y en las entradas
  históricas de la documentación.

## Quiénes somos

Texto de la página «Quiénes somos» de la app. Es **de broma** y así se presenta: la startup es ficticia.

> **Briefly** nació en un atasco de la M-30, cuando tres estudiantes de MIAX se dieron cuenta de que llegaban a
> casa sin saber qué había hecho su cartera. Nuestra misión: que lo sepas antes de quitarte los zapatos.
>
> - **Te contamos el mercado; tú decides.** No damos consejos, ni siquiera de cocina.
> - **Fuente o no ha pasado.** Cada noticia lleva su enlace.
> - **Cuatro minutos.** Si tu cartera necesita más, el problema no es el podcast.
> - **Voces sintéticas, y orgullosas de serlo.**
>
> Equipo: tres personas, seis modelos de IA, un toro y una osa.
