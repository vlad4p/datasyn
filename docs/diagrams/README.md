# Diagramas — datasyn

SVG hand-crafted con la paleta datasyn (fondo `#fffceb`, tinta `#49443b`, acentos rojo / amarillo / azul / verde / naranja). Referencia y mapeo de roles: [`../colors/`](../colors/).

## Inventario (README)

| Diagrama | SVG |
|---|---|
| Arquitectura de plataforma | [`architecture.svg`](architecture.svg) |
| Layout repo datasyn | [`repo-layout.svg`](repo-layout.svg) |
| Despliegue distribuido | [`distributed-layout.svg`](distributed-layout.svg) |
| Patrón medalla | [`medallion.svg`](medallion.svg) |
| Ciclo de consulta | [`query-flow.svg`](query-flow.svg) |
| Ejemplo chat (EPH) | [`query-example-chat.svg`](query-example-chat.svg) |

El README embebe estos **SVG** directamente. Fondo a sangre: `style="background-color:#fffceb"` + `<rect width="100%" height="100%" fill="#fffceb"/>` (sin `rx` en el canvas — evita esquinas transparentes).

## Editar

XML editable (viewBox, `rect`, `text`, gradientes en `<defs>`).

- Fondo `#fffceb` (ivory)
- Tipografía Arial/Helvetica; labels de sección `#585d5e` en mayúsculas con `letter-spacing="2"`
- Strokes `#49443b` (ink), gruesos (2px+)
- Validar: `xmllint --noout docs/diagrams/<nombre>.svg`
- Paleta (hex + roles): [`../colors/`](../colors/)

Tras editar, commitear el `.svg` junto al README.
