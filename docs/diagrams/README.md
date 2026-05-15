# Diagramas — DataSyn

Diagramas técnicos del proyecto en formato **drawio** (XML mxGraph) con sus exportaciones SVG y PNG. Editables en:

- **draw.io desktop** — `/Applications/draw.io.app` en macOS, equivalente en Linux/Windows.
- **app.diagrams.net** — abrí el `.drawio` directamente en el navegador.
- **VS Code / Cursor** — extensión [Draw.io Integration](https://marketplace.visualstudio.com/items?itemName=hediet.vscode-drawio).

## Inventario

| Diagrama | Editable | SVG (README) | PNG |
|---|---|---|---|
| Arquitectura general | [`architecture.drawio`](architecture.drawio) | [`architecture.svg`](architecture.svg) | [`architecture.png`](architecture.png) |
| Flujo de datos (medallón) | [`data-flow.drawio`](data-flow.drawio) | [`data-flow.svg`](data-flow.svg) | [`data-flow.png`](data-flow.png) |
| Ciclo de vida de una pregunta | [`question-lifecycle.drawio`](question-lifecycle.drawio) | [`question-lifecycle.svg`](question-lifecycle.svg) | [`question-lifecycle.png`](question-lifecycle.png) |

## Re-exportar tras editar un `.drawio`

Cualquiera de estos métodos sirve. Tras correr, **commiteá** los `.svg` / `.png` actualizados.

### macOS — draw.io desktop CLI

```bash
cd docs/diagrams
for f in architecture data-flow question-lifecycle; do
  /Applications/draw.io.app/Contents/MacOS/draw.io --no-sandbox --export \
    --format svg --output "$f.svg" "$f.drawio"
  /Applications/draw.io.app/Contents/MacOS/draw.io --no-sandbox --export \
    --format png --scale 1.5 --output "$f.png" "$f.drawio"
done
```

### Linux — drawio-desktop AppImage

```bash
./drawio-x86_64.AppImage --no-sandbox --export --format svg --output "$f.svg" "$f.drawio"
```

(Headless server: prefijar con `xvfb-run -a`.)

### Sin CLI — app.diagrams.net

`File → Export as → SVG / PNG → Selection: Diagram → Embed Images: on`. Guardar al lado del `.drawio`.

## Cuándo agregar un diagrama nuevo

- Cuando una pieza estructural (componente nuevo, lane nuevo, contrato MCP nuevo) cambie y la prosa del README ya no alcance.
- Cuando una secuencia operativa (un flujo de pregunta, un pipeline complejo) sea más clara visualmente que en pasos.

Convención: `kebab-case.drawio` + mismas dos exportaciones (`.svg` para embeber, `.png` para previews y compatibilidad). Referenciar desde el README principal con `![Título](docs/diagrams/<nombre>.svg)`.
