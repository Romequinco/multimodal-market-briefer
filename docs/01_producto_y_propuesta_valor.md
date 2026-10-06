# 01 · Producto y propuesta de valor

## Briefly en una frase

**Briefly** · *«El cierre del día, mientras vuelves a casa»*. Lo que ha movido tu cartera hoy, contado a dos
voces en unos cuatro minutos.

| | |
| --- | --- |
| **Qué es** | Un podcast diario y personalizado por cartera, con transcripción, gráficos y preguntas por voz |
| **Cuándo** | **Edición de noche**, al cierre de la sesión, para escucharla en el trayecto de vuelta. La **edición de mañana** (antes de la apertura) queda en el roadmap |
| **Quién habla** | **Toro** (voz A, el optimista: abre el episodio y se fija primero en lo que sube) y **Osa** (voz B, la prudente: pone el contexto y los riesgos y cierra con el aviso legal). Guiño a *bull & bear*. Las dos voces son **sintéticas** y los dos se ciñen a los hechos: personalidad, nunca opinión de inversión |
| **Para quién** | **B2C como cara visible** (inversor minorista) y **B2B2C como negocio** (neobancos y *brokers* que lo ofrecen con su marca) |
| **Lema** | «Te contamos el mercado; tú decides.» |

La marca visible es Briefly; los nombres técnicos internos (paquete `briefer`, repositorio
`multimodal-market-briefer`, variables `BRIEFER_*`) no cambian. Identidad completa en
[08 · Identidad de marca](08_identidad_marca.md).

## Esquema del producto

```mermaid
flowchart LR
    subgraph DOLOR["Problema"]
        D1["Información dispersa<br/>prensa, PDFs, gráficos"]
        D2["Poco tiempo<br/>para leerla"]
        D3["Resúmenes genéricos<br/>que no hablan de mi cartera"]
        D4["Barrera del inglés<br/>y de la jerga"]
    end

    subgraph PROD["Briefly"]
        P1["Filtra por mi cartera"]
        P2["Interpreta noticias,<br/>PDFs y gráficos"]
        P3["Lo explica en un podcast<br/>a dos voces (Toro y Osa)"]
        P4["Responde mis dudas<br/>por voz"]
    end

    subgraph VALOR["Resultado para el usuario"]
        V1["5 minutos al día<br/>en lugar de 1 hora"]
        V2["Entiende el porqué,<br/>no solo el titular"]
        V3["Lo consume donde quiera:<br/>oír, leer, ver"]
    end

    D1 --> P2
    D2 --> P3
    D3 --> P1
    D4 --> P3
    P1 --> V2
    P2 --> V2
    P3 --> V1
    P3 --> V3
    P4 --> V2
```

## Problema

El inversor minorista que gestiona su propia cartera tiene un problema de **tiempo y de formato**, no de
acceso a la información:

- Las noticias relevantes para *sus* valores están mezcladas con cientos de titulares irrelevantes.
- Las fuentes primarias (resultados trimestrales en PDF, gráficos técnicos) exigen tiempo y formación.
- Buena parte de la información de calidad está en inglés y con jerga.
- Los formatos que sí consume a diario (podcasts, vídeo corto) son genéricos y no conocen su cartera.

## Público objetivo

| Segmento | Tipo | Descripción | Papel en el MVP |
| --- | --- | --- | --- |
| Inversor minorista hispanohablante | **B2C (cara visible)** | 25-55 años, cartera propia en broker online (acciones y ETFs, 5-20 posiciones), sin tiempo para seguir el mercado a diario; escucha el resumen de vuelta a casa | Usuario de la app web |
| Neobancos y *brokers* | **B2B2C (negocio)** | Quieren aumentar el engagement diario de sus clientes con contenido propio | Cliente de marca blanca: el briefing con su marca dentro de su app |
| Newsletters y medios financieros | B2B2C (canal) | Quieren convertir su contenido escrito en audio/vídeo sin estudio de grabación | Cliente de la API de generación |

**Posicionamiento:** la marca Briefly se presenta al público como producto B2C (es lo que se ve en la demo y en
la app), pero el negocio con más recorrido es el B2B2C: un neobanco o *broker* que ofrece «su» edición de noche a
sus clientes, con su marca y su lista de valores. El MVP se diseña para el **B2C**; el B2B2C es el canal de
escalado que justifica la arquitectura por proveedores, la marca centralizada en un único módulo y la generación
compartida por ticker (ver [04](04_viabilidad_costes_latencia_compliance.md)).

## Propuesta de valor diferencial

La multimodalidad no es decorativa: cada modalidad resuelve una fricción concreta.

| Fricción | Modalidad | Qué aporta |
| --- | --- | --- |
| «No tengo tiempo de leer» | Texto → audio (podcast a 2 voces) | Se consume mientras se hace otra cosa; dos voces hacen el contenido más didáctico que una locución plana |
| «No entiendo este PDF de resultados» | Documento → texto (visión) | Extrae cifras clave y las lleva al análisis del día |
| «¿Qué significa este gráfico?» | Imagen → texto (visión) | El usuario sube la captura de su broker y entra en el briefing |
| «Tengo una duda concreta» | Audio → texto → texto → audio | Pregunta hablando, responde hablando: experiencia de asistente de voz |
| «Quiero verlo de un vistazo» | Datos → imagen, imagen + audio → vídeo | Gráficos del día y vídeo corto compartible |
| «Quiero leerlo después» | Transcripción + SRT | Accesibilidad y consulta rápida |

**Diferencial frente a un chat financiero:** el usuario no tiene que saber qué preguntar. El producto es
*push* (llega solo cada tarde, al cierre; la edición de mañana está en el roadmap), personalizado por cartera, y el chat por voz es un complemento, no el núcleo.

## Casos de uso

| ID | Caso | Modalidades | Flujo |
| --- | --- | --- | --- |
| CU1 | Edición de noche de mi cartera | texto → texto → audio, datos → imagen | Cartera → noticias filtradas → análisis → guion → podcast + gráficos |
| CU2 | Briefing enriquecido con un PDF de resultados | documento → texto | Sube el PDF de la empresa → cifras clave entran en el análisis |
| CU3 | «Explícame este gráfico» | imagen → texto | Sube captura de velas → descripción entra en el análisis |
| CU4 | Pregunta por voz sobre el briefing | audio → texto → texto → audio | «¿Por qué ha caído Inditex hoy?» → respuesta hablada con fuentes |
| CU5 | Recibirlo sin abrir la app | entrega | Telegram con el audio, el resumen y el vídeo (además de la web) |
| CU6 | Compartir un resumen visual | imagen + audio → vídeo | Vídeo corto con gráficos, subtítulos y audio |
| CU7 | Consultar días anteriores | — | Histórico de briefings guardados |

## Competencia y alternativas

| Alternativa | Qué hace bien | Qué le falta frente a Briefly |
| --- | --- | --- |
| Podcasts de mercado generalistas | Calidad editorial, voz humana | No conocen tu cartera; horario fijo; no puedes preguntar |
| Newsletters financieras | Curación, análisis | Texto; genéricas; en inglés muchas de las buenas |
| Apps de broker (noticias por valor) | Integradas con la cartera | Titulares sueltos sin interpretación ni audio |
| Chat generalista con IA | Responde lo que preguntes | Hay que saber preguntar; no es *push*; no genera podcast ni lee tu PDF en un flujo |
| Herramientas de «texto a podcast» | Convierten documentos en audio | No son financieras, no filtran por cartera, no tienen compliance |

**Hueco:** contenido financiero *push*, personalizado por cartera, en español, multiformato y con capa de
compliance desde el diseño.

## Monetización

| Modelo | Precio orientativo | Incluye |
| --- | --- | --- |
| Freemium | 0 € | Briefing diario de hasta 3 tickers, voces gratuitas, sin Q&A por voz o con cupo bajo |
| Suscripción Pro | 4,99-7,99 €/mes *(a validar)* | Cartera completa, Q&A por voz, PDFs y gráficos propios, vídeo, entrega por Telegram, voces premium |
| Marca blanca B2B2C | Licencia + por usuario activo *(a negociar)* | Briefing con la marca del broker/neobanco (logo, nombre y locutores propios), integración vía API |

Números y supuestos detallados en [04](04_viabilidad_costes_latencia_compliance.md#monetización).

## Métricas de producto

Métricas que se medirían en un piloto. **Ninguna está medida en el MVP.**

| Métrica | Qué indica | Objetivo orientativo |
| --- | --- | --- |
| % de usuarios que escuchan el briefing ≥ 3 días/semana | Hábito | > 40 % |
| % de escucha completa del episodio | Calidad y duración del guion | > 60 % |
| Preguntas por voz por usuario activo y semana | Valor del Q&A | ≥ 2 |
| Conversión free → Pro | Monetización | 3-5 % |
| Coste de generación por usuario activo y mes | Viabilidad | < 15 % del ingreso por usuario |
| Latencia de respuesta del Q&A | UX | < 10 s |
| Errores factuales detectados por cada 100 briefings | Confianza | Tendencia a 0 |
