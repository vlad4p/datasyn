# DataSyn

![status](https://img.shields.io/badge/status-active%20development-orange) ![license](https://img.shields.io/badge/license-TBD-lightgrey) ![approach](https://img.shields.io/badge/approach-AI--driven-success) ![focus](https://img.shields.io/badge/focus-public%20data-blue) ![locale](https://img.shields.io/badge/docs-es-informational) [![en](https://img.shields.io/badge/README-EN-lightgrey)](README.en.md)

**Análisis de datos asistido por IA.**

DataSyn es una sistema para **ingestar, descubrir, estructurar y analizar información** mediante agentes que operan sobre el warehouse, asegurando el correcto Gobierno de cada Agente y cada fuente de datos, disminuyendo el gap tecnico que representa mantener y procesar diversas fuentes de infomacion, tales como datos estrucutrados como no estructurados.

[Cómo correrlo →](INSTALL.md) · [Reglas del agente →](AGENTS.md) · [Skills →](skills/) · [Pipelines incluidos →](infra/dagster/mcp/dagster-code/projects/datasyn/src/datasyn/assets/) · [Diagramas →](docs/diagrams/)

---

## Por qué existe

> Un sistema que entregue **insight de la sociedad en tiempo real** para informar mejor decisiones, y que **no necesita ser privado**: las políticas públicas no necesitan información desagrupada — necesitan información comprensible y revisable.

Hoy, el analisis de datos, al igual que muchas otras areas, se ha visto atravesado y potenciado por la IA, permitiendo a cientificos, analistas politicos, economistas, entre otros;  trabajar mediante *lenguajenatural* sobre la informacion, manteniendo las buenas practicas de un sistema de alto nivel.
A diferencia de otras soluciones, donde la informacion es **subida a un tercero**: tu archivo viaja a un proveedor, la respuesta vuelve sin trazabilidad, y el conocimiento operativo queda dentro del producto.

DataSyn toma una posición distinta:

- **Datos públicos como bien común.** El código que los procesa también es público. Si un análisis aparece en una nota o un informe, el lector puede reproducirlo.
- **IA como amplificador del análisis ciudadano**, no como caja negra que centraliza el control. Tu eliges el modelo (incluso uno local) y el sistema corre en tu infraestructura.
- **El conocimiento de dominio se versiona.** Lo que un analista sabe hacer "a mano" se escribe una vez como **skill** y queda disponible para todos los demás. Ejemplo: El analisis de un dataset, o como realizar una ingesta especifica.

---

## El planteo: AI-driven, no AI-assisted

En este ultimo tiempo los agentes ya no "ayudan" puntualmente — **operan** el stack, mientras la persona aporta dirección, contexto y juicio. DataSyn aplica esa idea al **análisis** de datos.

El agente hace el trabajo rutinario:

| Vos hacés | El agente hace |
|---|---|
| Formulás la pregunta en lenguaje natural | Resuelve a qué tabla y columnas corresponde |
| Aportás conocimiento de dominio una sola vez (en una skill) | Ejecuta los pasos del playbook cada vez que matchea |
| Decidís qué interpretar y qué reportar | Lista esquemas, valida tipos, normaliza decimales, aplica `TRY_CAST`, elige la ponderación correcta |
| Revisás el SQL devuelto | Escribe **un** `SELECT` por llamada, lo corre, devuelve filas + supuestos |
| Pedís otro corte | Reutiliza contexto, no vuelve a empezar |

Lo que se evita: scripts ad-hoc por archivo, notebooks que sólo entiende quien los escribió, y promptear *"escribime una SQL para…"* sin saber si la columna existe o si el tipo es correcto.

---

## Cómo se ve usarlo

![Ciclo de una pregunta](docs/diagrams/question-lifecycle.svg)

> Editable: [`docs/diagrams/question-lifecycle.drawio`](docs/diagrams/question-lifecycle.drawio) · [PNG](docs/diagrams/question-lifecycle.png).

```text
Vos:     ¿Qué porcentaje de hogares en NOA tuvo IPCF bajo la línea
         de pobreza en T3-2025? Mostrame la SQL.

Agente:  · Lee el catálogo (descripciones de IPCF, REGION, PONDIH).
         · Confirma tipos (IPCF llega como VARCHAR → TRY_CAST).
         · Ejecuta UN SELECT con la ponderación correcta.
         · Devuelve tabla + bloque SQL + supuestos + cobertura.

UI:      Markdown renderizado, gráfico opcional, SQL copiable.
Trazas:  request_id cruza brain ↔ MCP ↔ Langfuse.
```

---

## Skills: tu conocimiento de dominio se vuelve capacidad del sistema

Una **skill** es un `SKILL.md` versionado. El Brain las descubre al arrancar y el agente las sigue como *playbooks ejecutables* cuando reconoce el dominio.

> Una skill bien escrita le enseña al sistema a **ingerir un dataset**, **derivar tablas nuevas**, **correr un análisis recurrente** o **producir un reporte** — sin tocar código del brain ni de la UI.


Quién las escribe: **analistas, periodistas de datos, investigadores académicos, etc...**. Lo único que se necesita es Markdown + saber qué `WHERE`, qué `GROUP BY`, qué ponderación corresponde para tu dataset.

### Anatomía mínima, ejemplo de una SKILL.md
```markdown
---
name: analyze-presupuesto-municipio-x
description: Ejecución presupuestaria del municipio X — gasto por función y partida.
---

## Tabla y columnas
- `gold.presupuesto_muni_x` (`ejercicio`, `mes`, `funcion`, `partida`, `monto_devengado`)
- `monto_devengado` llega como VARCHAR → `TRY_CAST(... AS DOUBLE)`

## Reglas
- Excluir `partida = '00 - No imputable'`
- Para series interanuales: deflactar por `silver.ipc_base_2016`

## SQL canónica
SELECT funcion, SUM(TRY_CAST(monto_devengado AS DOUBLE)) AS total
FROM gold.presupuesto_muni_x
WHERE ejercicio = $year
GROUP BY 1 ORDER BY 2 DESC;

## Salida esperada
- Tabla Markdown ordenada por total descendente
- Bloque SQL ejecutado
- Nota si faltan meses en el ejercicio consultado
```

A partir de ese archivo, *"gasto por función del municipio X en 2024"* hace que el agente cargue la skill, ejecute la SQL canónica, y devuelva la respuesta en el formato pedido — sin que vos vuelvas a escribir nada de eso.

### Lo que las skills habilitan

| Caso | Lo que escribe el analista | Lo que hace el agente |
|---|---|---|
| **Ingesta de dataset nuevo** | Skill + asset Dagster bronze (clonado de un ejemplo) | Materializa, valida tipos, registra |
| **Tabla derivada (silver/gold)** | Skill con SQL canónica y columnas finales | Crea/actualiza la tabla |
| **Análisis recurrente** | Skill con filtros, ponderaciones, breakdowns | Ejecuta on-demand, devuelve tabla + SQL |
| **Reporte periódico** | Skill con secciones esperadas y formato | Produce Markdown, guarda en `reports/` |

---

## Pipelines incluidos

Datasets que el sistema ya sabe ingerir (`infra/dagster/.../assets/bronze/`):

| Dataset | Fuente | Granularidad |
|---|---|---|
| INDEC EPH (microdatos) | `usu_hogar_*.txt`, `usu_individual_*.txt` | Trimestral, append por quarter |
| INDEC Censo 2022 | Radios censales + indicadores UCA | Por radio / departamento / provincia |
| Elecciones 2023 — Generales | argentina.gob.ar (ZIP oficial) | Por mesa / circuito |
| Boletín Oficial — 3ª Sección | boletinoficial.gob.ar | Daily partition (PDF + HTML + manifest) |
| Prensa | Infobae · Clarín · La Nación | Daily partition por sección |

Cada pipeline es un asset Dagster reproducible. Para sumar el tuyo: clonás uno y adaptás la lectura. La lógica de análisis se documenta como skill, no como notebook personal.

---

## Soberanía

| Pieza | Dónde corre |
|---|---|
| Datos crudos y warehouse | `data-local/` + MinIO + DuckDB **en tu host** |
| Pipelines, brain, UI | Containers en tu red `infra-datasynk` |
| LLM | A elección: local (Ollama/vLLM vía LiteLLM), OpenRouter o Gemini |
| Trazas | Langfuse self-hosted (opcional) |

Único egress posible: la llamada al modelo. Apuntando LiteLLM a un modelo on-prem el sistema queda offline. Lo que viaja al modelo son resúmenes, SQL y nombres de columnas — **no archivos**.

---

## Bajo el capó (resumen)

![Arquitectura](docs/diagrams/architecture.svg)

> Editable: [`docs/diagrams/architecture.drawio`](docs/diagrams/architecture.drawio) · [PNG](docs/diagrams/architecture.png) · Detalle de despliegue: [`INSTALL.md`](INSTALL.md).

Cuatro piezas, cada una estándar y reemplazable:

- **DuckDB** como warehouse local (`bronze` / `silver` / `gold`).
- **MinIO** como zona de aterrizaje S3-compatible.
- **Dagster** para los pipelines de ingesta (assets reproducibles, partitions, schedules).
- **Servidores MCP HTTP** (`duckdb-mcp`, `storage-mcp`, `dagster-mcp`) que exponen un contrato chico y auditable al agente.

Sobre eso, un brain (FastAPI + Deep Agents + LangChain) y una UI (React/Vite). La elección del LLM es del operador. Reglas duras del agente y antipatrones, en [`AGENTS.md`](AGENTS.md).

---

## Estado

| Componente | Estado |
|---|---|
| Brain + UI | Operativo |
| MCP servers (`duckdb`, `storage`, `dagster`) | Operativos |
| Pipelines bronze (INDEC, BOA, elecciones, prensa) | Operativos |
| Capas `silver` / `gold` | Mínimas (sólo `gold.indec_eph_*`) |
| Catálogo de metadatos | Opcional, contrato definido |
| Iceberg REST | Implementado, opt-in |
| Licencia opensource | A definir (MIT / Apache-2.0 sugeridos) |

Roadmap corto: ampliar `silver`/`gold`, sumar pipelines provinciales / municipales / sectoriales, formalizar gobernanza opensource.

---

## Comunidad

La forma más alta de leverage es **escribir skills**: cada skill convierte conocimiento de dominio en una capacidad nueva del sistema, accesible para todos los demás analistas que lo desplieguen.

Aportes esperados, en orden de menor a mayor esfuerzo técnico:

- **Skill `SKILL.md`** sobre un dataset que ya está en el warehouse — Markdown puro.
- **Skill + asset Dagster bronze** para sumar un dataset público nuevo (provincia, municipio, organismo, sectorial).
- **Reportar discrepancias** entre lo que responde el agente y un análisis manual — son los bugs más valiosos del proyecto.
- **Componentes reutilizables** (`utils/`, `components/`) cuando una transformación se repite en varios assets.

Issues y PRs bienvenidos. PRs chicos, una pieza por PR.

---

## Estructura

```
agent/                Brain (FastAPI + Deep Agents + clientes MCP)
ui/                   Frontend Vite/React
skills/               Playbooks SKILL.md
infra/                MinIO · DuckDB · Dagster · MCP servers · registry
data-local/           Mirror local para DuckDB (gitignored)
docs/diagrams/        Diagramas .drawio + SVG/PNG
mcp.json              URLs MCP que carga el brain
AGENTS.md             Reglas autoritativas del agente
INSTALL.md            Despliegue, troubleshooting, backends de modelo
Makefile              Targets de operación (make help)
```

---

## Referencias

- [`AGENTS.md`](AGENTS.md) — contrato del agente y reglas operativas.
- [`INSTALL.md`](INSTALL.md) — despliegue completo, backends de modelo, troubleshooting.
- [`docs/diagrams/`](docs/diagrams/) — `.drawio` editables (arquitectura, flujo de datos, ciclo de pregunta).
- [`Makefile`](Makefile) — `make help` para operar el stack.
- [`skills/`](skills/) — playbooks ejecutables.
- [`mcp.json`](mcp.json) — URLs MCP.

Inspiraciones explícitas:

- Dagster — [AI-Driven Data Engineering](https://dagster.io/blog/announcing-ai-driven-data-engineering) (marzo 2026).
- DuckDB — motor analítico embebido, columnar, sobre archivos locales.
- Model Context Protocol — contrato chico y verificable entre agente y herramientas.

---

> Si algo del README no coincide con el código, abrí un issue. Las discrepancias documentales son tan importantes como los bugs de código.
