# DataSyn

![status](https://img.shields.io/badge/status-active%20development-orange) ![license](https://img.shields.io/badge/license-TBD-lightgrey) ![approach](https://img.shields.io/badge/approach-AI--driven-success) ![focus](https://img.shields.io/badge/focus-public%20data-blue) ![locale](https://img.shields.io/badge/docs-es-informational) [![en](https://img.shields.io/badge/README-EN-lightgrey)](README.en.md)

## 🎯 ¿Qué es DataSyn?

**DataSyn** es un sistema para **buscar, organizar y analizar datos públicos** con ayuda de inteligencia artificial.

No necesitas saber programar ni escribir consultas SQL: puedes hacerle preguntas en **lenguaje natural** a tu asistente de IA (Cursor, VS Code, Claude, etc.) y el sistema responde con tablas, gráficos y el detalle de cómo llegó a ese resultado.

Todo el código y los datos que procesa son **públicos y reproducibles**: si un análisis aparece en una nota o informe, cualquiera puede verificarlo.

---

## 🚀 ¿Cómo empiezo?

Hay dos caminos según lo que quieras hacer:

| Quiero… | Qué hacer |
|---|---|
| **Consultar y analizar** datos que ya están en DataSyn | Conectar el asistente de IA vía MCP (abajo) |
| **Instalar** DataSyn en mi computadora o servidor | Seguir la guía [`INSTALL.md`](INSTALL.md) |
| **Agregar** una fuente de datos nueva | Pedírselo al asistente de IA (ver más abajo) |

### 💡 Opción recomendada: conectar tu asistente de IA (MCP)

Es la forma más simple de usar DataSyn **sin instalar nada**.

1. **Elige un asistente** que soporte MCP: [Cursor](https://cursor.com), VS Code con [Kilo Code](https://kilocode.ai) (tiene modelos gratuitos), Claude Desktop, etc.
2. **Configura los servidores MCP** apuntando a una instancia de DataSyn. El archivo [`mcp.json`](mcp.json) del repo muestra el formato; tu administrador te dará las URLs (por ejemplo `http://tu-servidor:8040/mcp`).
3. **Pregunta en español**, por ejemplo:
   - *"¿Qué datasets hay disponibles?"*
   - *"¿Cuántos hogares en NOA estuvieron bajo la línea de pobreza en el último trimestre?"*
   - *"Muéstrame la consulta SQL que usaste."*

> **Nota sobre costos:** las consultas las ejecuta tu asistente de IA, por lo que consumen tokens de tu cuenta. Con Kilo Code + VS Code puedes usar modelos free.

### 🖥️ Instalación completa

Si quieres ejecutar DataSyn en tu propia máquina (datos, pipelines, interfaz web), sigue la guía paso a paso en **[`INSTALL.md`](INSTALL.md)**. Resumen en dos comandos:

```bash
make bootstrap      # prepara la red y los volúmenes
make stack-up       # levanta todo el sistema
```

Luego abre la interfaz web en `http://localhost:8003`.

---

## 💬 ¿Cómo se ve usarlo?

![Ciclo de una pregunta](docs/diagrams/question-lifecycle.svg)

> Diagrama editable: [`docs/diagrams/question-lifecycle.drawio`](docs/diagrams/question-lifecycle.drawio) · [PNG](docs/diagrams/question-lifecycle.png)

**Ejemplo de conversación:**

```text
Usuario: ¿Qué porcentaje de hogares en NOA tuvo IPCF bajo la línea
         de pobreza en T3-2025? Muéstrame la SQL.

Agente:  · Busca en el catálogo qué significan IPCF, REGION y PONDIH.
         · Verifica los tipos de datos y aplica la ponderación correcta.
         · Ejecuta la consulta y devuelve una tabla con resultados.
         · Incluye el SQL usado y los supuestos que tomó.

Resultado: tabla en Markdown, SQL copiable, y notas sobre la cobertura de datos.
```

---

## 🌍 ¿Por qué existe?

> Un sistema que entregue **información comprensible sobre la sociedad**, en tiempo real, para tomar mejores decisiones — y que **no necesita ser privado**: las políticas públicas no requieren datos desagregados, sino información clara y verificable.

DataSyn parte de tres ideas:

- 📂 **Datos públicos como bien común.** El código que los procesa también es público.
- 🤖 **IA como amplificador**, no como caja negra. Puedes elegir el modelo (incluso uno local) y el sistema corre en tu infraestructura.
- 📝 **El conocimiento se versiona.** Lo que un analista sabe hacer "a mano" se escribe una vez como **skill** y queda disponible para todos.

---

## 📚 Skills: tu conocimiento, reutilizable por todos

Una **skill** es un archivo Markdown (`SKILL.md`) que le enseña al agente **cómo analizar un dataset**, **cómo ingerir una fuente** o **cómo generar un reporte**.

Quién las escribe: analistas, periodistas de datos, investigadores. Solo hace falta Markdown y conocer el dominio (qué columnas usar, qué filtros aplicar, etc.).

| Caso | Lo que escribes | Lo que hace el agente |
|---|---|---|
| **Análisis recurrente** | Filtros, ponderaciones, columnas clave | Ejecuta la consulta y devuelve tabla + SQL |
| **Ingesta de dataset nuevo** | Pasos para leer y guardar la fuente | Crea el pipeline y valida los datos |
| **Reporte periódico** | Secciones y formato esperado | Produce Markdown y lo guarda en `reports/` |

Ejemplos en la carpeta [`skills/`](skills/).

---

## 📊 Datos disponibles

Fuentes que el sistema ya sabe procesar:

| Dataset | Fuente | Frecuencia |
|---|---|---|
| INDEC EPH (microdatos) | Encuesta Permanente de Hogares | Trimestral |
| INDEC Censo 2022 | Radios censales + indicadores UCA | Por radio / departamento |
| Elecciones 2023 — Generales | argentina.gob.ar (ZIP oficial) | Por mesa / circuito |
| Boletín Oficial — 3ª Sección | boletinoficial.gob.ar | Diaria |
| Prensa | Infobae · Clarín · La Nación | Diaria por sección |
| OECD AI Incidents | oecd.ai | Por fecha de incidente |

Para sumar una fuente nueva, pídele al asistente que cree el job de ingesta (ver ejemplo abajo).

---

## ➕ Ejemplo: agregar una fuente de datos nueva

Supongamos que quieres sumar **incidentes de IA de la OECD** al sistema.

### Paso 1 — Pídele al agente

Describe la fuente, qué guardar y cómo debe funcionar:

```text
Crear un nuevo job para ingestar incidentes de OECD AI:

- Fuente: https://oecd.ai/en/incidents?countries=ARG&...
- Para cada incidente, extraer toda la información y estructurar un JSON.
- Guardar cada JSON en object storage.
- Crear una tabla DuckDB en schema bronze.
- El job debe recibir una fecha de scrape como input.
- Tomar como referencia el estilo de otros jobs Dagster del repo.
```

### Paso 2 — Revisión y publicación

El agente crea el código, lo valida y prepara un **Pull Request** a la rama `main`. Un revisor interno lo aprueba y la fuente queda disponible para todos.

> **Para operadores técnicos:** los pasos de build de imagen Docker, push al registry y redeploy en servidor están documentados en [`INSTALL.md`](INSTALL.md) (secciones *Publicar imágenes* y *Redeploy*).

---

## 🔒 Privacidad y control

| Qué | Dónde vive |
|---|---|
| Datos y warehouse | En **tu** computadora o servidor |
| Pipelines y asistente | Contenedores en tu red local |
| Modelo de IA | A tu elección: local, OpenRouter, Gemini, etc. |
| Trazas de uso | Langfuse self-hosted (opcional) |

Lo único que puede salir de tu red es la llamada al modelo de IA — y solo viajan resúmenes, SQL y nombres de columnas, **nunca archivos completos**. Con un modelo local, el sistema funciona sin conexión a internet.

---

## 🛠️ Para desarrolladores

### Arquitectura

![Arquitectura](docs/diagrams/architecture.svg)

> Editable: [`docs/diagrams/architecture.drawio`](docs/diagrams/architecture.drawio) · [PNG](docs/diagrams/architecture.png)

Cuatro piezas principales:

- **DuckDB** — base de datos analítica local (`bronze` / `silver` / `gold`).
- **MinIO** — almacenamiento de archivos compatible con S3.
- **Dagster** — orquestación de pipelines de ingesta.
- **Servidores MCP** — interfaz entre el agente de IA y el sistema (`duckdb`, `storage`, `dagster`).

Sobre eso: un brain (FastAPI + Deep Agents) y una UI (React/Vite). Reglas del agente en [`AGENTS.md`](AGENTS.md).

### AI-driven, no solo AI-assisted

El agente **opera** el stack; tú aportas dirección y criterio:

| Tú haces | El agente hace |
|---|---|
| Formulas la pregunta en lenguaje natural | Resuelve a qué tabla y columnas corresponde |
| Escribes una skill con el conocimiento de dominio | Ejecuta el playbook cada vez que aplica |
| Revisas el SQL devuelto | Escribe y corre la consulta, devuelve filas + supuestos |

### Estado del proyecto

| Componente | Estado |
|---|---|
| Brain + UI | ✅ Operativo |
| Servidores MCP | ✅ Operativos |
| Pipelines bronze (INDEC, BOA, elecciones, prensa) | ✅ Operativos |
| Capas silver / gold | 🟡 Mínimas |
| Catálogo de metadatos | 🟡 Opcional |
| Licencia open source | 🔲 A definir |

### Estructura del repositorio

```
agent/                Brain (FastAPI + Deep Agents + clientes MCP)
ui/                   Frontend Vite/React
skills/               Playbooks SKILL.md
infra/                MinIO · DuckDB · Dagster · MCP servers · registry
data-local/           Datos locales para DuckDB (gitignored)
docs/diagrams/        Diagramas .drawio + SVG/PNG
mcp.json              URLs MCP que carga el brain
AGENTS.md             Reglas del agente
INSTALL.md            Instalación, despliegue y troubleshooting
Makefile              Comandos de operación (make help)
```

---

## 🤝 Comunidad

La forma más valiosa de contribuir es **escribir skills**: cada una convierte conocimiento de dominio en una capacidad nueva para todos.

| Esfuerzo | Contribución |
|---|---|
| 🟢 Bajo | Skill `SKILL.md` sobre un dataset existente |
| 🟡 Medio | Skill + pipeline Dagster para una fuente pública nueva |
| 🔴 Alto | Componentes reutilizables cuando una transformación se repite |

Issues y PRs bienvenidos. PRs pequeños, una pieza por PR.

---

## 📎 Referencias

- [`INSTALL.md`](INSTALL.md) — instalación, despliegue y solución de problemas.
- [`AGENTS.md`](AGENTS.md) — reglas operativas del agente.
- [`skills/`](skills/) — playbooks ejecutables.
- [`docs/diagrams/`](docs/diagrams/) — diagramas editables.
- [`Makefile`](Makefile) — `make help` para operar el stack.
- [`mcp.json`](mcp.json) — configuración de servidores MCP.

Inspiraciones:

- [Dagster — AI-Driven Data Engineering](https://dagster.io/blog/announcing-ai-driven-data-engineering) (marzo 2026).
- [DuckDB](https://duckdb.org/) — motor analítico embebido sobre archivos locales.
- [Model Context Protocol](https://modelcontextprotocol.io/) — contrato entre agente y herramientas.

---

> 🐛 Si algo del README no coincide con el código, abre un issue. Las discrepancias documentales son tan importantes como los bugs de código.
