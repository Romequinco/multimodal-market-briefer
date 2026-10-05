# Decisiones de arquitectura (ADR)

Cada decisión que condiciona varios módulos o que sería cara de revertir se documenta como un ADR. Los ADR no
se reescriben: si una decisión cambia, se crea uno nuevo que **sustituye** al anterior y se actualiza el estado
de ambos.

## Índice

| ADR | Título | Estado | Fecha |
| --- | --- | --- | --- |
| [ADR-001](ADR-001-stack-mvp.md) | Stack del MVP | Aceptado | 05-oct-2026 |
| [ADR-002](ADR-002-proveedores-intercambiables.md) | Proveedores de IA intercambiables y modo mock | Aceptado | 05-oct-2026 |
| [ADR-003](ADR-003-tolerancia-fallos-y-contratos-v02.md) | Tolerancia a fallos por paso y contratos v0.2 | Aceptado | 05-oct-2026 |
| [ADR-004](ADR-004-salida-estructurada-json-schema.md) | Salida estructurada con `output_config` JSON Schema y pares para los diccionarios | Aceptado | 05-oct-2026 |
| [ADR-005](ADR-005-privacidad-cartera-no-persistida.md) | Privacidad: la cartera no se persiste | Aceptado | 05-oct-2026 |
| [ADR-006](ADR-006-guionista-haiku-puertas-deterministas.md) | Guionista en Haiku con puertas deterministas | Aceptado | 05-oct-2026 |

Estados posibles: **Propuesto** · **Aceptado** · **Sustituido por ADR-XXX** · **Descartado**.

## Plantilla

Copiar en `ADR-NNN-titulo-corto.md`:

```markdown
# ADR-NNN · Título

- **Estado:** Propuesto | Aceptado | Sustituido por ADR-XXX | Descartado
- **Fecha:** DD-mmm-AAAA
- **Ámbito:** módulos o carriles afectados

## Contexto

Qué problema hay y qué restricciones aplican (plazo, coste, rúbrica, equipo).

## Decisión

Qué se decide, en una o dos frases claras. Luego el detalle.

## Alternativas consideradas

| Opción | A favor | En contra |
| --- | --- | --- |

## Consecuencias

- Positivas:
- Negativas / deuda que se asume:
- Qué habría que hacer para revertirla:
```

Ver también: [índice de documentación](../README.md) · [material de clase](../clase/00_indice.md).
