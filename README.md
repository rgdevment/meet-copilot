# Meet Copilot Pro — Asistente de minutas con IA

Aplicación de escritorio (Windows) que captura los **subtítulos en vivo de Microsoft Teams y Zoom** mediante automatización de UI (`uiautomation`), los muestra y traduce en tiempo real, y genera una **minuta técnica coherente con IA al cerrar la reunión**.

## Cómo funciona (arquitectura)

La tubería separa captura, persistencia y síntesis:

1. **Captura** (`capture/`): lee todos los nodos de subtítulo visibles y reconcilia el stream volátil (líneas que crecen y se reescriben) en un transcript estable, por hablante, con deduplicación de historial.
2. **Persistencia** (fuente de verdad): el transcript crudo se guarda siempre en disco antes de tocar la IA, así un fallo de IA o de red nunca pierde la reunión.
3. **Síntesis** (`processing/pipeline.py`): al cerrar la reunión se genera la minuta **en una sola pasada** sobre el transcript completo (coherencia de principio a fin, no fragmentos). Para reuniones muy largas hay un modo map-reduce que se activa solo por encima de un umbral de palabras.

La vista en vivo (captions + traducción) es un feed directo sin IA; la minuta de calidad se genera al final.

## Características

* **Plataformas:** Microsoft Teams y Zoom (auto-detección o selección manual).
* **Proveedores de IA:** OpenAI, Anthropic (Claude), Google Gemini y LM Studio (local). Configurable.
* **Spanglish:** la minuta se genera en español preservando los términos técnicos en inglés; el glosario del proyecto se entrega como contexto al modelo. La traducción en vivo auto-detecta el idioma de origen.
* **Traducción** en vivo en hilo dedicado.
* **Observabilidad:** caja negra de cada lectura de subtítulo y dump del árbol UI bajo demanda (ver abajo).
* **Salida:** Markdown con la minuta + la transcripción completa, en `reuniones_logs/`.

## Requisitos

1. **SO:** Windows 10/11 (obligatorio para `uiautomation`).
2. **Python:** 3.10 o superior.
3. **Subtítulos en vivo activados** en Teams/Zoom durante la reunión.
4. **Clave de IA:** según el proveedor (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`) o un servidor LM Studio local en `http://localhost:1234`.

## Instalación

```bash
git clone <tu-repo>
cd meet-copilot
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Verifica el entorno con el doctor:

```bash
python doctor.py
```

## Ejecución

```bash
python main.py
```

Al iniciar se abre el diálogo de configuración (proveedor, modelo, plataforma, idiomas). La configuración se guarda en `meets_config.json`.

## Configuración

`meets_config.json` (se crea desde la GUI). Campos relevantes:

| Campo | Valores | Descripción |
|---|---|---|
| `ai_provider` | `openai` / `anthropic` / `gemini` / `lmstudio` | Proveedor de IA. |
| `model_name` | (según proveedor) | Modelo a usar. |
| `platform` | `auto` / `teams` / `zoom` | Fuente de captura. |
| `source_lang` / `target_lang` | `es` / `en` / `pt` / `fr` | Idioma de escucha (etiqueta) y de traducción. |
| `pipeline_mode` | `single_pass` (default) / `incremental` | Minuta al final vs. modo incremental antiguo. |
| `capture_all_nodes` | `true` (default) / `false` | Leer todos los nodos de subtítulo vs. solo el último. |
| `glossary_passive` | `true` (default) / `false` | Glosario como contexto vs. reemplazo de texto. |

## Diagnóstico

Cuando "se pierden palabras" o Teams/Zoom cambian su estructura interna:

* **`reuniones_logs/_diag/raw_uia_<fecha>.jsonl`**: una línea por lectura de subtítulo con la decisión tomada (caja negra para rastrear pérdidas).
* **`reuniones_logs/_diag/meetcopilot.log`**: log de la app (pon `MEETCOPILOT_DEBUG=1` para nivel DEBUG).
* **Botón 🩺 en la GUI**: vuelca el árbol UI Automation a `_diag/uia_tree_<fecha>.txt` para re-mapear el parser si Teams/Zoom cambiaron su DOM.

## Estructura del proyecto

* `main.py` — entry point: configura logging, hilos de captura e IA, y la GUI.
* `capture/` — fuentes de captura (`teams_windows.py`, `zoom_windows.py`), `manager.py` (reconciliación), `recorder.py` (caja negra), `diagnostics.py` (dump UIA).
* `processing/` — `pipeline.py` (síntesis), `glossary.py`, `translator.py`.
* `providers/` — adaptadores de OpenAI/Anthropic/Gemini/LM Studio.
* `prompts.py` — prompts de síntesis.
* `ui/` — GUI (`customtkinter`).
* `reuniones_logs/` — salida (minutas + transcript + `_diag/`).
* `REDESIGN_PLAN.md` — diseño de la tubería y decisiones de arquitectura.
