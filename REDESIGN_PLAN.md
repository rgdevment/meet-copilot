# Plan de rediseño — meet-copilot

> Origen: auditoría + exploración + council (4 lentes). Resuelve los 4 síntomas reportados:
> transcripción que pierde/confunde/duplica palabras (sobre todo spanglish), prompts débiles,
> IA que se confunde, y minutas tipo "resúmenes de frases sueltas".

## Diagnóstico raíz (consenso del council)

El defecto estructural es **comprometerse temprano sobre datos incompletos**, repetido en tres capas:

1. **Captura** commitea una línea antes de saber si estaba corregida a medias, y descarta datos en la frontera equivocada (`get_caption` devuelve solo el último nodo; la caché se invalida en cada silencio).
2. **Segmentación/minuta** corta a 350 palabras antes de saber dónde acaba el tema, y genera mini-minutas incrementales que luego se concatenan → incoherencia estructural inevitable.
3. **Idioma/error** fuerza un idioma y encadena el string `"AI Error"` como si fuera transcripción.

El arreglo no es afinar umbrales ni temperaturas: es **persistir el transcript crudo como fuente de verdad** y volver derivaciones recomputables (dedup, minuta) todo lo que hoy es destructivo e irreversible.

## Decisiones cerradas

- **Fuente = captions de Teams/Zoom vía UI Automation.** Whisper sobre audio se midió meses atrás: más complejo y **pierde más** que los captions de Teams (que son malos pero menos malos), y además sacrifica la diarización por nombre. **Descartado.** No reabrir sin nueva evidencia.
- **Minuta en vivo NO es requisito de calidad.** Durante la reunión se muestra un feed crudo simple (sin LLM); la minuta de calidad se genera **single-pass al final** sobre el transcript completo.
- **Spanglish = Camino A (mitigación).** Idioma mayoritario en Teams + glosario como contexto pasivo + LLM. El techo de calidad lo pone el ASR de Teams; lo aceptamos y maximizamos recuperación de términos conocidos.
- **Reuniones de ~1h NO necesitan chunking.** ~12-16k tokens entran holgados en cualquier proveedor, y single-pass cuesta *menos* tokens que el incremental actual. El chunking (map-reduce semántico) se deja **implementado pero inactivo**, se activa solo para workshops de 2h+.

---

## Regla de oro del rollout

**Nada irreversible toca una reunión en vivo hasta que exista el crudo persistente (Fase 0).**
Con el crudo, cada cambio posterior deja de ser apuesta a ciegas y pasa a ser comparación reproducible contra reuniones reales ya capturadas. Cada fase aguas abajo va detrás de un flag en `config.py`, default = comportamiento actual, y se valida **offline regenerando crudos guardados** antes de activarse en vivo.

---

## Fase 0 — Red de seguridad y observabilidad

**Objetivo:** dejar de ser ciegos. Hoy "perdí palabras" es indiagnosticable porque cada capa puede comerse texto sin dejar rastro. Riesgo **Bajo** (puramente aditivo, no cambia comportamiento).

- **`raw_uia.jsonl` append-only**, una línea por lectura UIA cruda, escrita **antes** del dedup (en `manager.update()` / `get_caption`). Campos: `ts` monotónico, `speaker`, `text`, y `decision` (`accepted` | `dup_exact` | `dup_substring` | `dup_ratio_X` | `excluded_speaker` | `no_alnum`). Es la caja negra: permite ver si el texto llegó de UIA y, si llegó, qué regla lo descartó.
- **Transcript crudo persistente** (líneas committeadas con `ts`, speaker, texto), flush frecuente, independiente del path de la minuta y del LLM. Habilita re-generar minutas offline sin re-grabar.
- **Logs reales en los `except` mudos**: `manager.py:114`, `teams_windows.py:127,149,167`, `pipeline.py:257`. Mínimo `logger.debug(..., exc_info=True)` + contador. Cuando algo falla, el log debe decir *qué*.
- **Métrica de salud por bloque**: nodos UIA leídos / descartados por dedup / palabras committeadas. Si lees 400 frames y commiteas 12 palabras, se ve de un vistazo.
- **Dump UIA integrado en la app** (botón "Diagnosticar captura") basado en `debug_teams_tree.py`, + health-check: si tras N s hay ventana pero cero captions parseados, avisar en UI ("ventana encontrada pero sin subtítulos — ¿activados? ¿cambió la estructura?").

**Criterio de validación:** capturar una reunión real y poder reconstruir desde el `.jsonl` dónde y por qué se perdió texto.

**Archivos:** `capture/manager.py`, `capture/teams_windows.py`, `capture/zoom_windows.py`, `processing/pipeline.py`, `debug_teams_tree.py`, GUI.

---

## Fase 1 — Single-pass al final + vista en vivo desacoplada

**Objetivo:** eliminar las minutas "frases sueltas", que son inevitables por diseño del incremental. Riesgo **Medio**, detrás de flag `pipeline_mode = "incremental" | "single_pass"`.

- **Vista en vivo = feed crudo** (dedup, sin LLM): instantáneo, gratis, sin pretensión de estructura final.
- **Minuta = single-pass** sobre el transcript completo al cerrar la reunión. Una sola decisión de estructura sobre todo el documento → coherencia garantizada.
- **Eliminar** como unidad de síntesis: `word_threshold=350`, mini-minutas por bloque, `previous_context` de 150 palabras, topic-extraction incremental, concatenación de N mini-minutas.
- **Chunking map-reduce semántico**: implementado pero **inactivo por defecto**. Se activa solo si el transcript supera un umbral de tokens. Corta en fronteras naturales (cambio de tema, pausa larga) con solapamiento controlado, resume cada trozo, y una pasada "reduce" teje la minuta. Clave: corta conociendo el documento completo, no a ciegas en caliente.

**Criterio de validación:** regenerar la minuta de un crudo guardado de Fase 0 y comparar coherencia contra la salida del modo incremental.

**Archivos:** `processing/pipeline.py`, `config.py`, `prompts.py`, GUI (panel en vivo).

---

## Fase 2 — Canal de error separado + saneo de prompts/parámetros

**Objetivo:** que un fallo no contamine la minuta y que la IA deje de inventar. Riesgo **Bajo**.

- **Canal de error separado**: `_call_ai` debe **lanzar excepción**, no devolver `"AI Error (Final): ..."` como string (`pipeline.py:254`). La capa superior degrada a crudo, nunca incrusta el error como contenido. Un fallo de red no debe envenenar el documento.
- **Colapsar temperaturas**: con single-pass desaparece el zoológico 0.1/0.2/0.4. Una temperatura de síntesis baja-media (~0.3, fidelidad sobre creatividad) + opcional una de naming.
- **Quitar la instrucción especulativa** (`prompts.py:104-105`, "riesgos que el equipo pasó por alto" / "contradicciones implícitas"): induce a inventar sobre transcripción incompleta. Reemplazar por registro fiel de lo dicho; marcar lo inferido como inferido.
- **Resolver la ambigüedad** del prompt de corrección ("no cambies el significado" vs "infiere con el contexto del proyecto"): el LLM corrige y sintetiza en la misma pasada, con el glosario como *hints*, no como mandato de reescritura.

**Archivos:** `processing/pipeline.py`, `prompts.py`, `providers/*`.

---

## Fase 3 — Captura: reconciliación por identidad de línea

**Objetivo:** dejar de perder/duplicar palabras en la captura. Riesgo **Medio**, detrás de flag `capture_all_nodes`. Validar offline contra crudos de Fase 0 antes de activar en vivo.

- **`get_caption` devuelve TODAS las candidatas**, no `candidates[-1]` (`teams_windows.py:64`, `zoom_windows.py:65`). Las líneas intermedias de otros speakers entre polls hoy se pierden irreversiblemente.
- **No invalidar la caché del web-area por silencio** (`teams_windows.py:67`): un silencio es fin de turno, no caché inválida. Invalidar solo si `Exists()` falla. Hoy se come el arranque de cada intervención.
- **Reconciliación por prefijo común con identidad de línea por hablante**, en vez de `SequenceMatcher` ratio fijo 0.65 sobre la cadena completa (`manager.py:79-97`):
  - Buffer de "líneas en vuelo" por speaker, no una sola `active_line`.
  - Test de casamiento = **prefijo común** (la línea crece/se auto-corrige) → reemplaza; si diverge de raíz → línea nueva.
  - **Commit diferido (debounce)**: una línea pasa a committed cuando lleva N ms estable, o cambia el speaker, o desaparece del DOM. Elimina el problema A→B→A.
  - El cierre de bloque **solo toca líneas estabilizadas**, nunca corta un track abierto.
- **Distinguir tres estados de la fuente**: `HAY_CAPTIONS` | `SILENCIO_CONFIRMADO` | `FUENTE_NO_DISPONIBLE`. El timer de silencio solo avanza en `SILENCIO_CONFIRMADO`; en `FUENTE_NO_DISPONIBLE` (ventana perdida, minimizada, re-discovery) se **pausa**. Hoy los tres colapsan a `(None, None)`.
- **Parseo tolerante**: no exigir exactamente 2 TextControl en Teams (`teams_windows.py:185-199`) ni formato fijo de regex en Zoom (`zoom_windows.py:180`); heurística con fallback.

**Riesgo conocido:** UIA no garantiza `RuntimeId` estable; el orden de `GetChildren` sí es estable entre polls cercanos. Identidad híbrida (slot + speaker + relación prefijo) con tolerancia de un slot. Validar con grabaciones reales multi-speaker.

**Archivos:** `capture/manager.py`, `capture/teams_windows.py`, `capture/zoom_windows.py`.

---

## Fase 4 — Spanglish (Camino A)

**Objetivo:** maximizar recuperación de términos mixtos sin reescribir la fuente. Riesgo **Bajo**.

- **`source="auto"`** en `translator.py` (hoy `GoogleTranslator(source="es")` cableado, `config.py:75`) para que el panel de traducción en vivo no rompa frases en inglés.
- **Prompt bilingüe explícito** en la síntesis: "la transcripción mezcla español e inglés técnico; genera la minuta en español preservando los términos técnicos en inglés". El idioma pasa de problema de detección a instrucción.
- **Glosario a contexto pasivo**: eliminar `apply_live_corrections` (regex destructivo previo) y `generate_ai_suggestions` (hints especulativos). El glosario se entrega al LLM como lista de términos de dominio para que **él** decida, no como reemplazo a ciegas. Quitar el límite de 100 palabras del fuzzy.
- **Recordatorio del techo**: el ASR de Teams es el límite; el inglés arbitrario no técnico seguirá deformándose. Medir con el crudo de Fase 0 cuánto se pierde realmente, para tener evidencia objetiva del impacto.

**Archivos:** `processing/translator.py`, `processing/glossary.py`, `prompts.py`, `config.py`.

---

## Resumen de orden y riesgo

| Fase | Qué | Riesgo | Síntoma que resuelve |
|------|-----|--------|----------------------|
| 0 | Crudo persistente + `raw_uia.jsonl` + logs + dump UIA | Bajo | Habilita todo; hace diagnosticable "perdí palabras" |
| 1 | Single-pass al final + vista en vivo sin LLM (chunking inactivo) | Medio | Minutas "frases sueltas" |
| 2 | Canal de error + temperatura única + quitar especulación | Bajo | IA que inventa / errores encadenados |
| 3 | Captura por prefijo + todos los nodos + no invalidar caché | Medio | Pérdida/duplicación de palabras |
| 4 | `source="auto"` + prompt bilingüe + glosario pasivo | Bajo | Spanglish (dentro del techo de Teams) |

**Riesgo principal del plan:** workshops de 2h+ que excedan contexto → mitigado por el chunking map-reduce de Fase 1 (inactivo hasta que haga falta). Confirmado que 1h no lo necesita.

---

## Estado de implementación (todas las fases aplicadas)

Las 5 fases están implementadas y la auditoría + revisión finales corrieron sobre los cambios. Bugs reales detectados y corregidos:

- **Pérdida silenciosa por fusión**: `merge_similarity` subido de 0.55 → 0.80 y la decisión de fusión usa **prefijo común** (no solo ratio global), para que una corrección con crecimiento simultáneo ("bakloc"→"backlog grooming...") no se parta en dos líneas ni dos frases distintas se fusionen.
- **Duplicación de historial**: leer todos los nodos re-emite líneas ya scrolladas; se agregó dedup contra lo recién commiteado (`recent_committed`).
- **Pérdida de minuta en rename**: `_apply_rename` solo adopta los paths nuevos si el rename existe en disco.
- **map-reduce**: cada tramo degrada a su texto crudo (`_safe_ai`) si falla; no se descarta el trabajo parcial.
- **Persistencia aislada**: el transcript se acumula en memoria antes de escribir a disco; un fallo de disco no lo borra de la minuta.

Validación: todos los archivos compilan; smoke test del reconciliador cubre crecimiento+corrección, A→B→A, dedup de historial y no-fusión de frases distintas (4/4 OK).

### Flags (en `config.py` / `meets_config.json`) para revertir por capa
- `pipeline_mode`: `"single_pass"` (default) | `"incremental"` (legacy).
- `capture_all_nodes`: `true` (default) | `false` (solo último nodo, comportamiento viejo).
- `glossary_passive`: `true` (default, glosario como contexto) | `false` (reemplazo regex viejo).

### Observabilidad (Fase 0)
- `{output_dir}/_diag/raw_uia_<ts>.jsonl`: caja negra de cada lectura UIA con su decisión.
- `{output_dir}/_diag/meetcopilot.log`: log (DEBUG si `MEETCOPILOT_DEBUG=1`).
- Botón 🩺 en la GUI: dump del árbol UIA cuando Teams/Zoom cambien su estructura.

### Pendientes deliberados (no bloqueantes)
- Speaker vacío agrupa anónimos en un track (mitigado por umbral alto + dedup).
- Parser de Teams asume orden speaker/caption (frágil ante cambios de DOM; el dump 🩺 + logs facilitan el re-mapeo).
- `dispatch_thread.join(timeout=2)`: riesgo bajo en single_pass (encolar es O(1)).
