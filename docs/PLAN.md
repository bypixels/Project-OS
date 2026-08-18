# cabina — plan de implementación: de inspector a torre de control (v0.3)

**Esta versión incorpora las revisiones R1–R14 del brief ("REVISIONS after adversarial review",
2026-08-18) que SOBRESCRIBEN el texto original.** Donde la v0.2 de este plan decía algo distinto,
gana esta versión — no queda ninguna tarea de la v0.2 que contradiga R1–R14.

Este documento traduce el brief en tareas chicas, ejecutables una por una, con TDD (test que falla
primero, código mínimo después). Está escrito para que lo ejecute un desconocido — o un agente sin
memoria de esta conversación — sin tener que adivinar nada.

Analogía general: este plan es como los planos de una remodelación de oficina, cuarto por cuarto.
No se derrumba toda la pared de una vez — se cierra un cuarto (una tarea), se revisa que la
estructura sigue en pie (se corren los tests), y recién entonces se pasa al siguiente.

Convención: **prosa en español (Costa Rica), código/identificadores/mensajes de commit en inglés**.

## Cómo ejecutar este plan

**(a) Con subagentes, uno por tarea, en secuencia (recomendado).** Un ejecutor hace Paso 1–4 de UNA
tarea; un verificador independiente lee el diff y corre la suite antes de dar luz verde a la
siguiente. Es como tener un inspector de obra que no es el mismo albañil que puso el ladrillo — con
Fable como orquestador (`~/.claude/skills/orquestar/SKILL.md`), esto es directo.

**(b) Inline, una sesión larga.** Más simple de arrancar, pero productor == verificador (más riesgo
de que un error se cuele), y Fase 2/Fase 3 (independientes entre sí una vez cerrada 1b) no se
pueden paralelizar.

Cualquiera de las dos: **nunca saltar el Paso 1 (test en rojo)**.

---

# Fase 0 — Higiene de código abierto

Siete tareas sin "comportamiento" testeable con `unittest` — documentación y configuración. Cada
una usa una **verificación** (algo que hoy falla y después de la tarea pasa) en vez de un test.

### Tarea 1: Sincronizar el conteo de tests en README.md
**Archivos:** Modificar `README.md`

- [ ] Paso 1: verificación que falla — `grep -n "68 tests" README.md` (imprime la línea vieja).
- [ ] Paso 2: `python3 -m unittest discover -s tests -v 2>&1 | tail -3` → hoy `Ran 126 tests in
      ...s` / `OK` (este número se moverá con cada tarea nueva de las Fases 1/1b — normal, no hace
      falta perseguirlo, solo dejarlo razonable al cierre de cada fase).
- [ ] Paso 3: en la línea `python -m unittest discover -s tests -v      # 68 tests, stdlib only`
      cambiar `68` por `126`.
- [ ] Paso 4: `grep -n "126 tests" README.md` imprime la línea corregida.
- [ ] Paso 5: `git commit -am "docs: sync README test count with the actual suite (68 -> 126)"`

### Tarea 2: Placeholder de screenshots/GIF en README.md
**Archivos:** Modificar `README.md`

- [ ] Paso 1: verificación — `grep -n "## Screenshots" README.md` (no existe).
- [ ] Paso 3: agregar después de `## Why`:
  ```markdown
  ## Screenshots

  <!-- TODO(danny): recorded GIF/PNG of the Agents tab with real (but non-sensitive) data,
       before tagging v0.1.0. Suggested: one GIF showing archive-with-references-check,
       one static shot of the health check output. -->
  ```
- [ ] Paso 4: `grep -n "## Screenshots" README.md` imprime la línea.
- [ ] Paso 5: `git commit -am "docs: add a screenshots placeholder section ahead of v0.1.0"`

### Tarea 3: Config de ruff en pyproject.toml (solo desarrollo)
**Archivos:** Modificar `pyproject.toml`

Analogía: es la regla de estilo que un editor le pasa a un corrector — no cambia el libro, solo
marca faltas de forma antes de imprimir. `dependencies = []` no se toca.

- [ ] Paso 1: verificación — `grep -n "\[tool.ruff\]" pyproject.toml` (no existe).
- [ ] Paso 3: agregar al final:
  ```toml
  [tool.ruff]
  line-length = 140
  target-version = "py311"

  [tool.ruff.lint]
  select = ["E", "F", "I"]
  ignore = ["E501"]
  ```
- [ ] Paso 4: `python3 -c "import tomllib; tomllib.load(open('pyproject.toml','rb')); print('valid toml')"` → `valid toml`.
- [ ] Paso 5: `git commit -am "chore: add ruff config for local linting (dev-only, no runtime dep)"`

### Tarea 4: CONTRIBUTING.md
**Archivos:** Crear `CONTRIBUTING.md`

- [ ] Paso 1: `test -f CONTRIBUTING.md && echo exists || echo missing` → `missing`.
- [ ] Paso 3: crear con: cómo correr la suite, la regla de guards+break-tests, cómo se agregan
      strings (`i18n.py`, siempre `en`+`es`), que no hay linter obligatorio en CI (ruff es local).
- [ ] Paso 4: `test -f CONTRIBUTING.md && echo exists` → `exists`.
- [ ] Paso 5: `git add CONTRIBUTING.md && git commit -m "docs: add CONTRIBUTING.md"`

### Tarea 5: CHANGELOG.md
**Archivos:** Crear `CHANGELOG.md`

- [ ] Paso 1: `test -f CHANGELOG.md && echo exists || echo missing` → `missing`.
- [ ] Paso 3: Keep a Changelog, `## [Unreleased]` vacío + `## [0.1.0]` con lo que ya existe hoy
      (roster con contrato, skills, harness, docs con hash+backup, health check, live/herdr, MCP
      read-only, export/compare, hooks guard+brief).
- [ ] Paso 4: `test -f CHANGELOG.md && head -3 CHANGELOG.md`.
- [ ] Paso 5: `git add CHANGELOG.md && git commit -m "docs: add CHANGELOG.md, seed the 0.1.0 entry"`

### Tarea 6: Decidir el nombre de distribución — "cabina" está TOMADO en PyPI (R14)
**Archivos:** Modificar `README.md`

Confirmado (no "a verificar" — ya se comprobó): `https://pypi.org/project/cabina/` pertenece a otro
paquete (`tsv1/cabina`). Es como llegar a poner el rótulo en la vidriera y encontrar que el nombre
del local ya lo usa el negocio de al lado — hay que decidir el nombre nuevo ANTES de imprimir
tarjetas de presentación (las líneas de instalación del README). Esta es una decisión del dueño, no
de un agente: candidatos sugeridos `cabina-cc`, `claude-cabina`, `cabina-tower`.

- [ ] Paso 1: verificación — `grep -n "pip install cabina" README.md` (hoy existe, línea 92:
      `pipx install cabina          # or: pip install cabina`).
- [ ] Paso 3: marcar el bloque de instalación como bloqueado hasta la decisión — en `README.md`,
      justo antes del bloque `## Install`, agregar:
  ```markdown
  > **Blocked on a name decision** (2026-08-18): the PyPI name `cabina` is taken by an unrelated
  > package (`tsv1/cabina`). Install instructions below use the placeholder `cabina` until a real
  > distribution name is chosen — candidates: `cabina-cc`, `claude-cabina`, `cabina-tower`. Do not
  > `pip install` from these instructions until this note is gone.
  ```
  (No se cambia `pyproject.toml` `[project] name` todavía — eso es parte de la MISMA decisión y se
  hace en un solo commit cuando Danny elija el nombre; cambiarlo a medias generaría un estado
  inconsistente entre el nombre publicado y el que usan los ejemplos.)
- [ ] Paso 4: `grep -n "Blocked on a name decision" README.md` imprime la línea.
- [ ] Paso 5: `git commit -am "docs: flag the PyPI name collision (cabina is taken) — blocks install instructions until renamed"`

### Tarea 7: Instrucciones de release (lo corre Danny)
**Archivos:** Modificar `CONTRIBUTING.md`

- [ ] Paso 1: verificación — `grep -n "## Releasing" CONTRIBUTING.md` (no existe).
- [ ] Paso 3: agregar sección `## Releasing` con el comando exacto (usando el nombre final una vez
      resuelta la Tarea 6):
  ```sh
  git tag -a v0.1.0 -m "cabina v0.1.0 — agents, skills, harness, docs, health check, live, MCP"
  git push origin v0.1.0
  ```
  y una nota: "no publicar en PyPI hasta cerrar la Tarea 6 (nombre de distribución)".
- [ ] Paso 4: — (sin verificación automática; el tag lo corre Danny).
- [ ] Paso 5: `git commit -am "docs: document the release process (CONTRIBUTING.md)"`

---

# Fase 1 — `sessions.py`: leer la actividad real de Claude Code

Analogía: cada transcripción `.jsonl` es la cinta de una caja registradora — un renglón por
movimiento. `sessions.py` es quien al final del día resume esa cinta: cuánto duró, cuántos
clientes, qué se vendió — nunca lo que cada cliente dijo. Ese resumen es lo único que se guarda.

**Cambio de arquitectura clave (R2): el parser ya no relee el archivo entero cada vez.** El
registro guarda, por archivo, el BYTE en el que se quedó (`offset`) más un "estado a medio
terminar" (`partial_state`: los contadores acumulados hasta ese byte). Un `refresh()` solo lee los
bytes nuevos desde `offset`, los mezcla con `partial_state`, y recalcula el resumen final. Es como
un cajero que anota "hasta la línea 40 ya sumé" en vez de volver a sumar el ticket completo cada
vez que llega un cliente nuevo.

### Tarea 8: Fixture — una transcripción sintética completa (sidechain, cambio de cwd, subagente con tokens, mtimes "frías" por defecto)
**Archivos:** Modificar `tests/_env.py` · Crear `tests/test_sessions.py`

La transcripción de mentira necesita, además de lo básico, una línea `isSidechain:true` (para
probar R6: se excluye de turnos/tool_calls/tokens) y una línea con un `cwd` distinto (para probar
R5: mayoría + `cwd_changed`). Usa nombres de agente/skill nuevos (`sessions-demo-agent`,
`sessions-demo-skill`) para no alterar los conteos que `test_usage.py`/`test_server.py` ya verifican
sobre `reviewer`/`deploy`.

**Hallazgo de la revisión adversarial (crítico):** `Env` ya escribe hoy `<claude>/projects/-x/s.jsonl`
(con `cwd` = alpha) y esta tarea agrega `sess-1.jsonl` + `agent-1.jsonl`, todos con la fecha de
"ahora mismo" en el momento en que el test los crea. Si se dejaran así, `live.TranscriptProvider`
(Tarea 20) marcaría "alpha" como activo en TODOS los tests que usan `Env` — y la Tarea 21, que hace
que `App.working()` incluya esa señal, bloquearía silenciosamente el guardado de documentos en
`tests/test_server.py::test_doc_read_save_conflict` y
`::test_commit_endpoint_requires_repo_and_only_that_path` (ambos guardan un doc en `alpha` y esperan
`ok: True`). Es como dejar la luz del cuarto de al lado prendida por error y que la alarma de
movimiento del cuarto equivocado suene. Por eso esta tarea deja **todas** las transcripciones de la
fixture "frías" (mtime = ahora − 3600 s) por defecto, y agrega un método `touch_session(fresh=True)`
que un test llama EXPLÍCITAMENTE cuando de verdad necesita simular actividad reciente.

- [ ] Paso 1: test que falla (`tests/test_sessions.py`, nuevo):
  ```python
  import os, unittest
  import _helpers  # noqa
  from _env import Env

  class TestSessionsFixture(unittest.TestCase):
      def setUp(self):
          self.env = Env()
      def tearDown(self):
          self.env.cleanup()

      def test_fixture_has_a_session_file_and_a_subagent_file(self):
          self.assertTrue(os.path.isfile(self.env.session_file))
          sub_dir = os.path.join(os.path.dirname(self.env.session_file), self.env.session_id, "subagents")
          self.assertEqual(len([f for f in os.listdir(sub_dir) if f.endswith(".jsonl")]), 1)

  if __name__ == "__main__":
      unittest.main()
  ```
  Falla hoy: `Env` no tiene `session_file`/`session_id`.
- [ ] Paso 2: `python3 -m unittest discover -s tests -p "test_sessions.py" -v` → `AttributeError`.
- [ ] Paso 3a: en `tests/_env.py`, cambiar la primera línea `import os, json, tempfile` por
      `import os, json, tempfile, time`.
- [ ] Paso 3b: en `Env.__init__`, después del bloque de Codex y antes de `self.cfg = ...`:
  ```python
          # sessions fixture: one real-shaped transcript for project alpha + one subagent file.
          # Uses names ("sessions-demo-agent"/"sessions-demo-skill") that do NOT collide with
          # "reviewer"/"deploy" above, so usage.py-based assertions elsewhere stay unaffected.
          self.session_id = "sess-1"
          sdir = os.path.join(self.claude, "projects", "-work-alpha")
          os.makedirs(os.path.join(sdir, self.session_id, "subagents"))
          self.session_file = os.path.join(sdir, self.session_id + ".jsonl")
          open(self.session_file, "w").write(
              f'{{"type":"user","timestamp":"2026-08-10T09:00:00Z","cwd":"{a}","gitBranch":"main","sessionId":"{self.session_id}","version":"1.2.3","message":{{"role":"user","content":[{{"type":"text","text":"PROMPT_MARKER_DO_NOT_LEAK please refactor the widget loader"}}]}}}}\n'
              f'{{"type":"assistant","timestamp":"2026-08-10T09:01:00Z","cwd":"{a}","gitBranch":"main","sessionId":"{self.session_id}","message":{{"role":"assistant","content":[{{"type":"text","text":"On it."}},{{"type":"tool_use","name":"Edit","input":{{"file_path":"{a}/src/widget.py"}}}}],"usage":{{"input_tokens":120,"output_tokens":340,"cache_read_input_tokens":50,"cache_creation_input_tokens":10}}}}}}\n'
              f'{{"type":"assistant","timestamp":"2026-08-10T09:01:30Z","cwd":"{a}/apps","gitBranch":"main","sessionId":"{self.session_id}","message":{{"role":"assistant","content":[{{"type":"tool_use","name":"Agent","input":{{"subagent_type":"sessions-demo-agent"}}}},{{"type":"tool_use","name":"Skill","input":{{"skill":"sessions-demo-skill"}}}}],"usage":{{"input_tokens":80,"output_tokens":60,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}}}}\n'
              f'{{"type":"assistant","timestamp":"2026-08-10T09:02:00Z","cwd":"{a}","isSidechain":true,"sessionId":"{self.session_id}","message":{{"role":"assistant","content":[{{"type":"tool_use","name":"Read","input":{{"file_path":"{a}/src/secret.py"}}}}],"usage":{{"input_tokens":999,"output_tokens":999,"cache_read_input_tokens":999,"cache_creation_input_tokens":999}}}}}}\n'
              f'{{"type":"assistant","timestamp":"2026-08-10T09:03:00Z","cwd":"{a}","gitBranch":"main","sessionId":"{self.session_id}","message":{{"role":"assistant","content":[{{"type":"tool_use","name":"Bash","input":{{"command":"git commit -m done"}}}}],"usage":{{"input_tokens":30,"output_tokens":20,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}}}}\n'
              f'{{"type":"ai-title","aiTitle":"Refactor the widget loader","sessionId":"{self.session_id}"}}\n'
          )
          open(os.path.join(sdir, self.session_id, "subagents", "agent-1.jsonl"), "w").write(
              '{"type":"assistant","timestamp":"2026-08-10T09:01:35Z","message":{"role":"assistant","content":[{"type":"tool_use","name":"Grep","input":{"pattern":"x"}}],"usage":{"input_tokens":15,"output_tokens":25,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}\n')
          # CRITICAL fix from adversarial review: default every transcript fixture (the pre-existing
          # -x/s.jsonl included) to a STALE mtime, so live.TranscriptProvider (Tarea 20) never marks
          # "alpha" active by accident in an ordinary Env-based test. Tests that need "active"
          # call env.touch_session(fresh=True) explicitly (see the method below).
          old = time.time() - 3600
          for p in (os.path.join(self.claude, "projects", "-x", "s.jsonl"), self.session_file,
                    os.path.join(sdir, self.session_id, "subagents", "agent-1.jsonl")):
              os.utime(p, (old, old))
  ```
- [ ] Paso 3c: agregar un método a la clase `Env` (junto a `cleanup`):
  ```python
      def touch_session(self, fresh=True):
          """Set the mtime of the sessions fixture (session file + its subagent file) to 'now'
          (fresh=True, looks active to live.TranscriptProvider) or back to stale (fresh=False).
          Tests call this explicitly — the fixture defaults to stale (see Env.__init__ above)."""
          t = time.time() if fresh else time.time() - 3600
          sub = os.path.join(os.path.dirname(self.session_file), self.session_id, "subagents", "agent-1.jsonl")
          for p in (self.session_file, sub):
              os.utime(p, (t, t))
  ```
- [ ] Paso 4: `python3 -m unittest discover -s tests -p "test_sessions.py" -v` → `Ran 1 test ... OK`.
- [x] Paso 5: `git add tests/_env.py tests/test_sessions.py && git commit -m "test: add a real-shaped synthetic transcript fixture for sessions.py, defaulting to stale mtimes (sidechain, cwd change, subagent tokens)"`

### Tarea 9: `usage._project_of` — resolver symlinks (fix compartido, R5)
**Archivos:** Modificar `src/cabina/usage.py`, `tests/test_usage.py`

`sessions.py` va a reusar esta función para atribuir cada sesión a un proyecto; el brief pide
resolver symlinks en ambos lados de la comparación primero, como fix compartido.

- [ ] Paso 1: test que falla:
  ```python
  # tests/test_usage.py, agregar a TestUsage
  import unittest
  @unittest.skipIf(os.name == "nt", "symlinks need admin rights on Windows")
  def test_project_of_resolves_symlinks(self):
      with tempfile.TemporaryDirectory() as d:
          real = os.path.join(d, "real"); os.makedirs(real)
          link = os.path.join(d, "link"); os.symlink(real, link)
          self.assertEqual(U._project_of(os.path.join(link, "sub"), {"p": real}), "p")
  ```
- [ ] Paso 2: `python3 -m unittest discover -s tests -p "test_usage.py" -v -k symlink` → falla
      (`assertEqual(None, "p")`) porque `link` nunca calza con `real` sin resolver.
- [ ] Paso 3: en `src/cabina/usage.py`, reemplazar `_project_of` por:
  ```python
  def _project_of(cwd, roots):
      """roots: {project_name: abs_root}. Longest matching root wins. Both sides go through
      os.path.realpath first, so a symlinked root or a symlinked cwd still matches."""
      if not cwd:
          return None
      cwd = os.path.realpath(cwd)
      best, best_len = None, -1
      for name, root in roots.items():
          r = os.path.realpath(root)
          if (cwd == r or cwd.startswith(r.rstrip("/") + "/")) and len(r) > best_len:
              best, best_len = name, len(r)
      return best
  ```
- [ ] Paso 4: `python3 -m unittest discover -s tests -p "test_usage.py" -v` → todos en verde
      (incluye los tests existentes de atribución, que usan rutas ficticias sin symlinks —
      `realpath` no les cambia el resultado).
- [x] Paso 5: `git commit -am "fix: usage._project_of resolves symlinks on both sides (shared fix, needed by sessions.py)"`

### Tarea 10: `_read_new_lines` — lectura incremental por byte-offset
**Archivos:** Crear `src/cabina/sessions.py` · Modificar `tests/test_sessions.py`

El primer bloque del módulo, y la pieza que hace posible R2: leer SOLO lo que se agregó desde la
última vez, no el archivo entero.

- [ ] Paso 1: test que falla:
  ```python
  # tests/test_sessions.py, nueva clase
  import tempfile
  from cabina import sessions as S

  class TestReadNewLines(unittest.TestCase):
      def test_only_returns_bytes_after_offset(self):
          with tempfile.TemporaryDirectory() as d:
              p = os.path.join(d, "f.jsonl")
              open(p, "w").write('{"a":1}\n{"a":2}\n')
              lines1, off1 = S._read_new_lines(p, 0)
              self.assertEqual(len(lines1), 2)
              open(p, "a").write('{"a":3}\n')
              lines2, off2 = S._read_new_lines(p, off1)
              self.assertEqual(lines2, ['{"a":3}'])
              self.assertGreater(off2, off1)
  ```
- [ ] Paso 2: `python3 -m unittest discover -s tests -p "test_sessions.py" -v` →
      `ModuleNotFoundError: No module named 'cabina.sessions'`.
- [ ] Paso 3: crear `src/cabina/sessions.py`:
  ```python
  """Session activity, read from Claude Code's own transcripts. Read-only: never edits or
  deletes a transcript. Parses each .jsonl into a per-session SUMMARY — counts and metadata
  only, never prompt/response text (the one exception is `title`, the AI-generated one-line
  title Claude Code itself already writes to the transcript as an `ai-title` line).

  Incremental by BYTE OFFSET: <state_dir>/sessions.json keyed by source_path -> {offset, size,
  mtime, partial_state, summary}. A refresh() only reads the bytes appended after `offset`; if
  the file is now shorter than `offset` (rotated/rewritten) it is re-parsed from scratch. The
  transcript format is internal and undocumented: parsing is best-effort per line — a bad line
  is skipped, never fatal.

  Retention: summaries survive their source file disappearing (rotation is normal; history is
  the point, same as usage.py). They are pruned only once `ended` is older than
  cfg.activity.retention_days (default 365).
  """
  import json, os


  def _read_new_lines(path, offset):
      """Bytes after `offset` -> (list of non-empty line strings, new_offset)."""
      with open(path, "rb") as f:
          f.seek(offset)
          data = f.read()
      new_offset = offset + len(data)
      lines = [l for l in data.decode("utf-8", "replace").splitlines() if l.strip()]
      return lines, new_offset
  ```
- [ ] Paso 4: `python3 -m unittest discover -s tests -p "test_sessions.py" -v` → `Ran 2 tests ... OK`.
- [x] Paso 5: `git add src/cabina/sessions.py tests/test_sessions.py && git commit -m "feat: sessions.py — byte-offset incremental line reader"`

### Tarea 11: `_merge_lines`/`_new_state` — turnos, tokens, exclusión de sidechain (R6)
**Archivos:** Modificar `src/cabina/sessions.py`, `tests/test_sessions.py`

`_new_state()` es el acumulador vacío; `_merge_lines(state, lines)` lo actualiza con líneas nuevas.
Una línea `isSidechain:true` suma a `sidechain_lines` y no toca nada más — ni turnos, ni tokens, y
(decisión R6, confirmada) tampoco `started`/`ended`/`duration_s`: el chequeo de `isSidechain` va
ANTES de leer el `timestamp`, no después, precisamente para que una línea sidechain nunca corra la
hora de fin de la sesión.

- [ ] Paso 1: tests que fallan:
  ```python
  class TestMergeLinesCore(unittest.TestCase):
      def setUp(self):
          self.env = Env()
      def tearDown(self):
          self.env.cleanup()

      def test_turns_tokens_and_sidechain_exclusion(self):
          lines, _ = S._read_new_lines(self.env.session_file, 0)
          state = S._merge_lines(S._new_state(), lines)
          self.assertEqual(state["turns"], 1)                     # only the one real human text message
          self.assertEqual(state["tokens"], {"in": 230, "out": 420, "cache_read": 50, "cache_write": 10})
          self.assertEqual(state["sidechain_lines"], 1)           # the isSidechain:true line, excluded above
          self.assertEqual(state["branch"], "main")
          self.assertEqual(state["title"], "Refactor the widget loader")

      def test_sidechain_excluded_from_started_ended_too(self):
          # a standalone, minimal pair of lines (not the shared fixture): the sidechain line's
          # timestamp is LATER than the real one, so if it leaked into `ended` this would catch it.
          lines = [
              '{"type":"user","timestamp":"2026-08-10T09:00:00Z","message":{"role":"user","content":[{"type":"text","text":"hi"}]}}',
              '{"type":"assistant","timestamp":"2026-08-10T09:05:00Z","isSidechain":true,"message":{"role":"assistant","content":[{"type":"tool_use","name":"Read","input":{}}],"usage":{"input_tokens":1,"output_tokens":1,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}',
          ]
          state = S._merge_lines(S._new_state(), lines)
          self.assertEqual(state["ended"], "2026-08-10T09:00:00Z")     # the sidechain line's later timestamp never counts
  ```
- [ ] Paso 2: `python3 -m unittest discover -s tests -p "test_sessions.py" -v` → `AttributeError:
      module 'cabina.sessions' has no attribute '_new_state'`.
- [ ] Paso 3: en `src/cabina/sessions.py` agregar:
  ```python
  def _empty_tokens():
      return {"in": 0, "out": 0, "cache_read": 0, "cache_write": 0}


  def _new_state():
      return {"session_id": None, "cwd_counts": {}, "branch": None, "version": None, "title": None,
              "started": None, "ended": None, "turns": 0, "tool_calls": {}, "files_touched": [],
              "agents": {}, "skills": {}, "commits": 0, "tokens": _empty_tokens(), "sidechain_lines": 0}


  def _merge_lines(state, lines):
      """Parse new raw JSON lines into `state` (mutated in place, also returned)."""
      for raw in lines:
          try:
              d = json.loads(raw)
          except Exception:
              continue
          if not state["session_id"] and d.get("sessionId"):
              state["session_id"] = d["sessionId"]
          if d.get("version"):
              state["version"] = d["version"]
          if d.get("type") == "ai-title" and d.get("aiTitle"):
              state["title"] = d["aiTitle"]
          if d.get("isSidechain"):
              state["sidechain_lines"] += 1
              continue                                  # R6: excluded from started/ended/cwd/turns/tool_calls/tokens
          ts = d.get("timestamp")
          if ts:
              state["started"] = state["started"] or ts
              state["ended"] = ts
          if d.get("cwd"):
              cw = d["cwd"]; state["cwd_counts"][cw] = state["cwd_counts"].get(cw, 0) + 1
          if d.get("gitBranch") and not state["branch"]:
              state["branch"] = d["gitBranch"]
          msg = d.get("message") or {}
          content = msg.get("content")
          if d.get("type") == "user" and msg.get("role") == "user" and isinstance(content, list):
              if any(isinstance(b, dict) and b.get("type") == "text" for b in content):
                  state["turns"] += 1
          if d.get("type") == "assistant" and isinstance(content, list):
              usg = msg.get("usage") or {}
              state["tokens"]["in"] += usg.get("input_tokens", 0) or 0
              state["tokens"]["out"] += usg.get("output_tokens", 0) or 0
              state["tokens"]["cache_read"] += usg.get("cache_read_input_tokens", 0) or 0
              state["tokens"]["cache_write"] += usg.get("cache_creation_input_tokens", 0) or 0
      return state
  ```
- [ ] Paso 4: `python3 -m unittest discover -s tests -p "test_sessions.py" -v` → `Ran 4 tests ... OK`.
- [x] Paso 5: `git commit -am "feat: sessions.py — turns/tokens accumulator, excluding sidechain lines from started/ended too (R6)"`

### Tarea 12: extracción de herramientas — `tool_calls`, `files_touched`, `agents`, `skills`, `commits`
**Archivos:** Modificar `src/cabina/sessions.py`, `tests/test_sessions.py`

- [ ] Paso 1: test que falla:
  ```python
      def test_tool_extraction_excludes_sidechain(self):
          lines, _ = S._read_new_lines(self.env.session_file, 0)
          state = S._merge_lines(S._new_state(), lines)
          self.assertEqual(state["tool_calls"], {"Edit": 1, "Agent": 1, "Skill": 1, "Bash": 1})   # no "Read" (sidechain)
          self.assertEqual(state["files_touched"], [f"{self.env.alpha}/src/widget.py"])           # absolute here; relpath happens at _finalize
          self.assertEqual(state["agents"], {"sessions-demo-agent": 1})
          self.assertEqual(state["skills"], {"sessions-demo-skill": 1})
          self.assertEqual(state["commits"], 1)
  ```
- [ ] Paso 2: falla — `state["tool_calls"]` queda vacío (`{}`).
- [ ] Paso 3: en `src/cabina/sessions.py`, al tope agregar `import re` y las constantes
      `_COMMIT = re.compile(r"\bgit\s+commit\b")` / `FILE_TOOLS = ("Edit", "Write", "MultiEdit",
      "NotebookEdit")`; dentro de `_merge_lines`, dentro del `if d.get("type") == "assistant" ...`,
      después de sumar `state["tokens"]`, agregar:
  ```python
              for b in content:
                  if not isinstance(b, dict) or b.get("type") != "tool_use":
                      continue
                  name = b.get("name", "?")
                  state["tool_calls"][name] = state["tool_calls"].get(name, 0) + 1
                  inp = b.get("input") or {}
                  if name == "Agent" and inp.get("subagent_type"):
                      k = inp["subagent_type"]; state["agents"][k] = state["agents"].get(k, 0) + 1
                  if name == "Skill" and inp.get("skill"):
                      k = inp["skill"]; state["skills"][k] = state["skills"].get(k, 0) + 1
                  if name in FILE_TOOLS and inp.get("file_path") and inp["file_path"] not in state["files_touched"]:
                      state["files_touched"].append(inp["file_path"])
                  if name == "Bash" and _COMMIT.search(inp.get("command") or ""):
                      state["commits"] += 1
  ```
- [ ] Paso 4: `python3 -m unittest discover -s tests -p "test_sessions.py" -v` → `Ran 5 tests ... OK`.
- [x] Paso 5: `git commit -am "feat: sessions.py — extract tool_calls/files_touched/agents/skills/commits (excludes sidechain)"`

### Tarea 13: `_finalize` — mayoría de cwd, `cwd_changed`, atribución, hora local (R5, R7)
**Archivos:** Modificar `src/cabina/sessions.py`, `tests/test_sessions.py`

`_finalize` convierte el `state` acumulado en el resumen final: elige el `cwd` que más veces
apareció (mayoría, no "el primero"), marca `cwd_changed` si hubo más de uno, atribuye el proyecto, y
convierte fechas a hora LOCAL con offset (no UTC crudo).

- [ ] Paso 1: test que falla:
  ```python
      def test_finalize_majority_cwd_and_local_time(self):
          lines, off = S._read_new_lines(self.env.session_file, 0)
          state = S._merge_lines(S._new_state(), lines)
          roots = {"alpha": self.env.alpha}
          summary = S._finalize(state, self.env.session_file, roots, off)
          self.assertEqual(summary["cwd"], self.env.alpha)          # 3 lines with alpha vs 1 with alpha/apps
          self.assertTrue(summary["cwd_changed"])
          self.assertEqual(summary["project"], "alpha")
          self.assertEqual(summary["started"], S._to_local_iso("2026-08-10T09:00:00Z"))
          self.assertEqual(summary["ended"], S._to_local_iso("2026-08-10T09:03:00Z"))
          self.assertEqual(summary["duration_s"], 180)
          self.assertEqual(summary["files_touched"], ["src/widget.py"])   # relative to the project root now

      def test_finalize_unknown_project_when_no_cwd_lines(self):
          state = S._merge_lines(S._new_state(), ['{"type":"ai-title","aiTitle":"x"}'])
          summary = S._finalize(state, "/tmp/fake/-nowhere/s.jsonl", {}, 0)
          self.assertEqual(summary["project"], "unknown")
          self.assertIsNone(summary["cwd"])
          self.assertFalse(summary["cwd_changed"])
  ```
- [ ] Paso 2: falla — `AttributeError: module 'cabina.sessions' has no attribute '_finalize'`.
- [ ] Paso 3: en `src/cabina/sessions.py` agregar `from . import scan, usage` a los imports, y:
  ```python
  def _guess_project_from_encoded_dir(source_path, roots):
      """Best-effort fallback when a session has no cwd-bearing lines at all: Claude Code encodes
      the cwd into the directory name by replacing '/' with '-'. Lossy (a real '-' in a path looks
      the same as an encoded '/'), so this is a guess, never treated as fact elsewhere."""
      enc = os.path.basename(os.path.dirname(source_path))
      return usage._project_of(enc.replace("-", "/"), roots) or "unknown"


  def _to_local_iso(ts):
      if not ts:
          return None
      try:
          from datetime import datetime
          return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().isoformat()
      except Exception:
          return None


  def _finalize(state, source_path, roots, offset):
      from datetime import datetime
      roots = roots or {}
      counts = state["cwd_counts"]
      if counts:
          cwd = max(counts, key=counts.get)
          cwd_changed = len(counts) > 1
          project = usage._project_of(cwd, roots)
      else:
          cwd, cwd_changed = None, False
          project = _guess_project_from_encoded_dir(source_path, roots)
      started, ended = _to_local_iso(state["started"]), _to_local_iso(state["ended"])
      duration_s = 0
      try:
          if started and ended:
              duration_s = max(0, int((datetime.fromisoformat(ended) - datetime.fromisoformat(started)).total_seconds()))
      except Exception:
          pass
      files = state["files_touched"]
      base = roots.get(project) if project else None
      if base:
          files = [os.path.relpath(f, base) if os.path.isabs(f) and (f == base or f.startswith(base + os.sep)) else f for f in files]
      st = os.stat(source_path)
      return {
          "session_id": state["session_id"] or os.path.splitext(os.path.basename(source_path))[0],
          "project": project, "cwd_changed": cwd_changed, "cwd": cwd, "branch": state["branch"],
          "tool": "claude", "title": state["title"], "started": started, "ended": ended,
          "duration_s": duration_s, "turns": state["turns"], "tool_calls": state["tool_calls"],
          "files_touched": files, "agents": state["agents"], "skills": state["skills"],
          "commits": state["commits"], "tokens": state["tokens"], "version": state["version"],
          "sidechain_lines": state["sidechain_lines"], "source_path": source_path,
          "size": st.st_size, "mtime": st.st_mtime, "offset": offset,
      }
  ```
  (Los campos `subagent_tokens` y `subagents` se agregan en la Tarea 14 — por ahora el dict que
  arma `_finalize` no los tiene, y eso está bien: la Tarea 14 los suma antes de que la Tarea 15
  aplique la lista blanca de campos.)
- [ ] Paso 4: `python3 -m unittest discover -s tests -p "test_sessions.py" -v` → `Ran 7 tests ... OK`.
- [x] Paso 5: `git commit -am "feat: sessions.py — _finalize: majority-cwd attribution, cwd_changed, local-time timestamps (R5, R7)"`

### Tarea 14: subagentes — conteo y tokens SIN sumar al total (R3)
**Archivos:** Modificar `src/cabina/sessions.py`, `tests/test_sessions.py`

`subagents` es un conteo de archivos; `subagent_tokens` es la suma de tokens de ESOS archivos, pero
guardada APARTE — nunca mezclada con `tokens` de la sesión principal.

- [ ] Paso 1: test que falla:
  ```python
      def test_subagents_count_and_unsummed_tokens(self):
          lines, off = S._read_new_lines(self.env.session_file, 0)
          state = S._merge_lines(S._new_state(), lines)
          summary = S._finalize(state, self.env.session_file, {"alpha": self.env.alpha}, off)
          self.assertEqual(summary["subagents"], 1)
          self.assertEqual(summary["subagent_tokens"], {"in": 15, "out": 25, "cache_read": 0, "cache_write": 0})
          self.assertEqual(summary["tokens"]["in"], 230)             # unchanged: subagent tokens NOT added in
  ```
- [ ] Paso 2: falla — `KeyError: 'subagents'`.
- [ ] Paso 3: en `src/cabina/sessions.py` agregar:
  ```python
  def _subagents_count(source_path):
      sid = os.path.splitext(os.path.basename(source_path))[0]
      d = os.path.join(os.path.dirname(source_path), sid, "subagents")
      if not os.path.isdir(d):
          return 0
      return sum(1 for f in os.listdir(d) if f.endswith(".jsonl"))


  def _subagent_tokens(source_path):
      """Tokens spent by subagents of this session — read in full each refresh (these files are
      small), kept SEPARATE from the session's own `tokens` (R3: never summed together)."""
      sid = os.path.splitext(os.path.basename(source_path))[0]
      d = os.path.join(os.path.dirname(source_path), sid, "subagents")
      tokens = _empty_tokens()
      if not os.path.isdir(d):
          return tokens
      for f in os.listdir(d):
          if not f.endswith(".jsonl"):
              continue
          try:
              with open(os.path.join(d, f), encoding="utf-8", errors="replace") as fh:
                  for raw in fh:
                      raw = raw.strip()
                      if not raw:
                          continue
                      try:
                          d2 = json.loads(raw)
                      except Exception:
                          continue
                      if d2.get("isSidechain"):
                          continue
                      usg = ((d2.get("message") or {}).get("usage")) or {}
                      tokens["in"] += usg.get("input_tokens", 0) or 0
                      tokens["out"] += usg.get("output_tokens", 0) or 0
                      tokens["cache_read"] += usg.get("cache_read_input_tokens", 0) or 0
                      tokens["cache_write"] += usg.get("cache_creation_input_tokens", 0) or 0
          except Exception:
              pass
      return tokens
  ```
  y en `_finalize`, en el `return {...}`, agregar dos claves:
  `"subagent_tokens": _subagent_tokens(source_path), "subagents": _subagents_count(source_path),`
- [ ] Paso 4: `python3 -m unittest discover -s tests -p "test_sessions.py" -v` → `Ran 8 tests ... OK`.
- [x] Paso 5: `git commit -am "feat: sessions.py — count subagents and sum their tokens separately, unsummed (R3)"`

### Tarea 15: guardia de privacidad — lista blanca exacta de campos, en el resumen Y en el estado a medio terminar (R8)
**Archivos:** Modificar `src/cabina/sessions.py` · `tests/test_sessions.py` · `tests/test_breaks.py`

Este es el guard que el brief pide explícitamente, con la lista de campos EXACTA de R8. Cualquier
clave que no esté en la lista se cae en silencio antes de tocar disco — es el error seguro (perder
un campo nuevo por accidente, nunca filtrar texto crudo).

**Hallazgo de la revisión adversarial (crítico):** el resumen final (`summary`) SÍ pasa por
`_redact_unknown_fields`, pero el `partial_state` que la Tarea 17 va a guardar tal cual en
`sessions.json` (para poder retomar el parseo incremental) NO pasaba por ningún filtro — quedaba
persistido en disco sin lista blanca. Hoy `_merge_lines` nunca copia texto crudo dentro de `state`
(todos sus campos son contadores, rutas o el título ya resumido por Claude Code), así que no hay una
fuga real todavía — pero el guard existía solo "por construcción", no por un filtro explícito, y
`SUMMARY_FIELDS` no cubría ese archivo. Por eso esta tarea agrega una lista blanca GEMELA,
`PARTIAL_STATE_FIELDS`, definida junto a `SUMMARY_FIELDS` — para que si algún día alguien agrega a
`_merge_lines` una línea que copie texto (por ejemplo, para debug), esa clave nueva se caiga sola
antes de tocar disco, en vez de que el guard dependa para siempre de que nadie cometa ese error.

- [ ] Paso 1: tres tests que fallan:
  ```python
  # tests/test_sessions.py
  import json
      def test_never_stores_prompt_text_and_matches_allowlist(self):
          lines, off = S._read_new_lines(self.env.session_file, 0)
          state = S._merge_lines(S._new_state(), lines)
          summary = S._redact_unknown_fields(S._finalize(state, self.env.session_file, {"alpha": self.env.alpha}, off))
          dumped = json.dumps(summary)
          self.assertNotIn("PROMPT_MARKER_DO_NOT_LEAK", dumped)
          self.assertEqual(set(summary), set(S.SUMMARY_FIELDS))
  ```
  ```python
  # tests/test_breaks.py, agregar a TestBreaks (imports: agregar "sessions as SESS" a la línea
  # "from cabina import contract as C, docs as D, harness as H, usage as U")
      def test_sessions_no_text_leak_guard(self):
          leak = {"session_id": "s1", "prompt_text": "the secret prompt string XYZ123"}
          self.assertNotIn("prompt_text", SESS._redact_unknown_fields(leak))                     # guard present
          with mock.patch.object(SESS, "SUMMARY_FIELDS", SESS.SUMMARY_FIELDS + ("prompt_text",)):
              self.assertIn("prompt_text", SESS._redact_unknown_fields(leak))                     # guard removed -> leaks

      def test_sessions_partial_state_allowlist_guard(self):
          leak_state = dict(SESS._new_state())
          leak_state["prompt_text"] = "the secret prompt string XYZ123"
          self.assertNotIn("prompt_text", SESS._redact_partial_state(leak_state))                # guard present
          with mock.patch.object(SESS, "PARTIAL_STATE_FIELDS", SESS.PARTIAL_STATE_FIELDS + ("prompt_text",)):
              self.assertIn("prompt_text", SESS._redact_partial_state(leak_state))                # guard removed -> leaks
  ```
- [ ] Paso 2: `python3 -m unittest discover -s tests -p "test_sessions.py" -v` y
      `python3 -m unittest discover -s tests -p "test_breaks.py" -v` → ambos
      `AttributeError: module 'cabina.sessions' has no attribute 'SUMMARY_FIELDS'`
      (y luego `'PARTIAL_STATE_FIELDS'` al arreglar la primera).
- [ ] Paso 3: en `src/cabina/sessions.py`, agregar cerca del tope (después de los imports):
  ```python
  SUMMARY_FIELDS = ("session_id", "project", "cwd_changed", "cwd", "branch", "tool", "title",
                     "started", "ended", "duration_s", "turns", "tool_calls", "files_touched",
                     "agents", "skills", "commits", "tokens", "subagent_tokens", "subagents",
                     "sidechain_lines", "version", "source_path", "size", "mtime", "offset")

  PARTIAL_STATE_FIELDS = ("session_id", "cwd_counts", "branch", "version", "title", "started",
                          "ended", "turns", "tool_calls", "files_touched", "agents", "skills",
                          "commits", "tokens", "sidechain_lines")


  def _redact_unknown_fields(summary):
      """Guard: keep only keys in SUMMARY_FIELDS — an allowlist, not a denylist of 'known-bad'
      names. Any accidental new field (e.g. raw text) is dropped, not exposed. `cwd` and
      `source_path` are LOCAL-ONLY: they stay in this local registry but must never leave the
      machine — export.py and mcp.py filter them out separately (Fase 1b / Fase 2)."""
      return {k: v for k, v in summary.items() if k in SUMMARY_FIELDS}


  def _redact_partial_state(state):
      """Same idea as _redact_unknown_fields, but for `partial_state` — the accumulator that
      Tarea 17 persists into sessions.json as-is (to resume incremental parsing). Without this,
      an accidental future addition to _merge_lines that captured raw text would land on disk
      unfiltered, even though the final `summary` was already safe."""
      return {k: v for k, v in state.items() if k in PARTIAL_STATE_FIELDS}
  ```
- [ ] Paso 4: `python3 -m unittest discover -s tests -p "test_sessions.py" -v` → `Ran 9 tests ... OK`;
      `python3 -m unittest discover -s tests -p "test_breaks.py" -v` → `Ran 9 tests ... OK` (los 7
      break-tests existentes + estos 2).
- [x] Paso 5: `git commit -am "feat: sessions.py — exact field allowlist guard on both the summary AND the persisted partial_state (R8), break-tested"`

### Tarea 16: registro en disco (`sessions.json`) — cargar y guardar
**Archivos:** Modificar `src/cabina/sessions.py`, `tests/test_sessions.py`

- [ ] Paso 1: test que falla:
  ```python
  class TestSessionsRegistry(unittest.TestCase):
      def test_save_load_roundtrip_and_missing(self):
          with tempfile.TemporaryDirectory() as d:
              p = os.path.join(d, "sessions.json")
              S._save_registry(p, {"a.jsonl": {"offset": 10, "size": 10, "mtime": 1.0, "partial_state": {}, "summary": {"session_id": "a"}}})
              self.assertEqual(S._load_registry(p)["a.jsonl"]["summary"]["session_id"], "a")
          self.assertEqual(S._load_registry("/no/such/file.json"), {})
  ```
- [ ] Paso 2: `AttributeError: module 'cabina.sessions' has no attribute '_save_registry'`.
- [ ] Paso 3: agregar:
  ```python
  def registry_path(cfg):
      return os.path.join(cfg["state_dir"], "sessions.json")


  def _load_registry(path):
      try:
          with open(path, encoding="utf-8") as f:
              return json.load(f)
      except Exception:
          return {}


  def _save_registry(path, reg):
      os.makedirs(os.path.dirname(path), exist_ok=True)
      tmp = path + ".tmp"
      with open(tmp, "w", encoding="utf-8") as f:
          json.dump(reg, f, ensure_ascii=False, indent=1, sort_keys=True)
      os.replace(tmp, path)
  ```
- [ ] Paso 4: `python3 -m unittest discover -s tests -p "test_sessions.py" -v` → `Ran 10 tests ... OK`.
- [x] Paso 5: `git commit -am "feat: sessions.py — atomic save/load for the sessions.json registry"`

### Tarea 17: `refresh(cfg, days=30)` — orquesta el parseo incremental + retención (R2, R4)
**Archivos:** Modificar `src/cabina/sessions.py`, `src/cabina/config.py`, `tests/test_sessions.py`, `tests/test_breaks.py`

Dos reglas nuevas importantes: (1) si el archivo creció, se leen solo los bytes nuevos desde
`offset`; si es MÁS CHICO que `offset` (se reescribió/rotó), se reparsea desde cero. (2) la
retención se mide por la antigüedad de `ended`, **nunca** por si el archivo fuente sigue existiendo
— un resumen sobrevive a la rotación del transcript (R4), igual que `usage.py` acumula fechas de
uso aunque la historia rote cada ~30 días. La poda por retención se separa en dos funciones chicas
(`_age_days`, `_prune_by_retention`) precisamente para poder break-testearla como el resto del
archivo: desactivar el cálculo de edad con `mock.patch.object` y ver que un registro vencido
sobrevive cuando no debería.

- [ ] Paso 1: cuatro tests que fallan en `tests/test_sessions.py`, más un break-test en
      `tests/test_breaks.py`:
  ```python
  # tests/test_sessions.py
  class TestSessionsRefresh(unittest.TestCase):
      def setUp(self):
          self.env = Env()
      def tearDown(self):
          self.env.cleanup()

      def test_refresh_finds_the_session(self):
          items = S.refresh(self.env.cfg, days=30)
          self.assertTrue(any(s["session_id"] == "sess-1" for s in items))

      def test_refresh_is_truly_incremental_on_appended_bytes(self):
          S.refresh(self.env.cfg, days=30)
          reg = S._load_registry(S.registry_path(self.env.cfg))
          off1 = reg[self.env.session_file]["offset"]
          open(self.env.session_file, "a").write(
              '{"type":"assistant","timestamp":"2026-08-10T09:04:00Z","cwd":"%s","message":{"role":"assistant","content":[{"type":"tool_use","name":"Write","input":{"file_path":"%s/src/new.py"}}],"usage":{"input_tokens":5,"output_tokens":5,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}\n'
              % (self.env.alpha, self.env.alpha))
          items = S.refresh(self.env.cfg, days=30)
          reg2 = S._load_registry(S.registry_path(self.env.cfg))
          self.assertGreater(reg2[self.env.session_file]["offset"], off1)
          s = next(s for s in items if s["session_id"] == "sess-1")
          self.assertIn("Write", s["tool_calls"])

      def test_refresh_survives_source_deletion_but_prunes_by_retention_age(self):
          S.refresh(self.env.cfg, days=30)
          os.remove(self.env.session_file)
          items = S.refresh(self.env.cfg, days=30)
          self.assertTrue(any(s["session_id"] == "sess-1" for s in items))     # R4: NOT pruned just because deleted
          cfg2 = dict(self.env.cfg, activity={"retention_days": 0})            # everything is "too old" now
          items2 = S.refresh(cfg2, days=30)
          self.assertFalse(any(s["session_id"] == "sess-1" for s in items2))   # pruned by age, not by existence

      def test_refresh_writes_a_registry_file_that_never_contains_prompt_text(self):
          # CRITICAL finding from adversarial review: Tarea 15 only checked the in-memory
          # summary dict. This checks the ACTUAL bytes written to sessions.json on disk — the
          # full registry, partial_state included, not just the redacted summary copy.
          S.refresh(self.env.cfg, days=30)
          raw = open(S.registry_path(self.env.cfg), encoding="utf-8").read()
          self.assertNotIn("PROMPT_MARKER_DO_NOT_LEAK", raw)
  ```
  ```python
  # tests/test_breaks.py, agregar a TestBreaks (imports: agregar "from datetime import datetime, timedelta")
      def test_sessions_retention_prune_guard(self):
          now_local = datetime.now().astimezone()
          old_ended = (now_local - timedelta(days=400)).isoformat()
          reg = {"old.jsonl": {"summary": {"ended": old_ended}}}
          self.assertEqual(SESS._prune_by_retention(reg, 365, now_local), {})                     # guard present: pruned
          with mock.patch.object(SESS, "_age_days", return_value=0):                              # guard disabled: "everything is fresh"
              self.assertIn("old.jsonl", SESS._prune_by_retention(reg, 365, now_local))            # over-age entry survives -> canary red
          # R4: existence is irrelevant to this guard — a deleted file's cached summary survives
          # as long as it is within retention (no os.path.exists check anywhere in here)
          fresh_reg = {"/no/such/file/deleted.jsonl": {"summary": {"ended": now_local.isoformat()}}}
          self.assertIn("/no/such/file/deleted.jsonl", SESS._prune_by_retention(fresh_reg, 365, now_local))
  ```
- [ ] Paso 2: `python3 -m unittest discover -s tests -p "test_sessions.py" -v` →
      `AttributeError: module 'cabina.sessions' has no attribute 'refresh'`;
      `python3 -m unittest discover -s tests -p "test_breaks.py" -v -k retention` →
      `AttributeError: module 'cabina.sessions' has no attribute '_prune_by_retention'`.
- [ ] Paso 3a: en `src/cabina/config.py`, en `DEFAULTS`, agregar una clave nueva (junto a `"live"`):
      `"activity": {"retention_days": 365},`
- [ ] Paso 3b: en `src/cabina/sessions.py`, agregar `import time` a los imports y:
  ```python
  def _iter_session_files(claude_home):
      """Every <claude_home>/projects/<encoded-cwd>/<sessionId>.jsonl — flat, NOT the
      subagents/ ones (R3: subagent transcripts are never sessions on their own)."""
      pdir = os.path.join(claude_home, "projects")
      if not os.path.isdir(pdir):
          return
      for enc in os.listdir(pdir):
          edir = os.path.join(pdir, enc)
          if not os.path.isdir(edir):
              continue
          for f in os.listdir(edir):
              if f.endswith(".jsonl"):
                  yield os.path.join(edir, f)


  def _age_days(ended, now_local):
      """Days between `ended` (a local-aware ISO string) and `now_local`. 0 if `ended` is
      missing or unparsable — never ages out something we cannot date."""
      if not ended:
          return 0
      try:
          from datetime import datetime
          return (now_local - datetime.fromisoformat(ended)).days
      except Exception:
          return 0


  def _prune_by_retention(reg, retention_days, now_local):
      """Guard (R4): keep an entry unless its summary's `ended` is older than retention_days.
      Whether the SOURCE FILE still exists on disk is never part of this decision — rotation is
      normal, history is the point (same spirit as usage.py's accumulating registry)."""
      return {k: v for k, v in reg.items()
              if _age_days((v.get("summary") or {}).get("ended"), now_local) <= retention_days}


  def refresh(cfg, days=30):
      """Parse new/changed bytes of every session file (bounded to `days` for files never seen
      before), merge into the registry, prune by retention, save, return every kept summary —
      newest first. Never call this on an HTTP request thread (see server.py, Fase 1b Tarea 22)."""
      path = registry_path(cfg)
      reg = _load_registry(path)
      roots = scan.project_roots(cfg)
      cutoff = time.time() - days * 86400
      retention_days = (cfg.get("activity") or {}).get("retention_days", 365)
      for fp in _iter_session_files(cfg["claude_home"]):
          try:
              st = os.stat(fp)
          except Exception:
              continue
          cached = reg.get(fp)
          if cached is None:
              if st.st_mtime < cutoff:
                  continue
              offset, state = 0, _new_state()
          elif st.st_mtime == cached.get("mtime") and st.st_size == cached.get("size"):
              continue
          elif st.st_size < cached.get("offset", 0):
              offset, state = 0, _new_state()             # rotated/rewritten: reparse from scratch
          else:
              offset, state = cached["offset"], cached["partial_state"]
          new_lines, new_offset = _read_new_lines(fp, offset)
          state = _redact_partial_state(_merge_lines(state, new_lines))
          summary = _redact_unknown_fields(_finalize(state, fp, roots, new_offset))
          reg[fp] = {"offset": new_offset, "size": st.st_size, "mtime": st.st_mtime,
                     "partial_state": state, "summary": summary}
      from datetime import datetime
      now_local = datetime.now().astimezone()
      kept = _prune_by_retention(reg, retention_days, now_local)
      _save_registry(path, kept)
      return sorted((e["summary"] for e in kept.values()), key=lambda s: s.get("started") or "", reverse=True)
  ```
- [ ] Paso 4: `python3 -m unittest discover -s tests -p "test_sessions.py" -v` → `Ran 14 tests ... OK`;
      `python3 -m unittest discover -s tests -p "test_breaks.py" -v` → `Ran 10 tests ... OK`.
- [x] Paso 5: `git commit -am "feat: sessions.py — refresh() with byte-offset incremental parsing and existence-independent retention (R2, R4), retention prune break-tested"`

### Tarea 18: `load(cfg)` — leer el caché sin tocar disco de nuevo
**Archivos:** Modificar `src/cabina/sessions.py`, `tests/test_sessions.py`

- [ ] Paso 1: test que falla:
  ```python
      def test_load_reads_cache_without_touching_source_files(self):
          S.refresh(self.env.cfg, days=30)
          os.remove(self.env.session_file)
          items = S.load(self.env.cfg)
          self.assertTrue(any(s["session_id"] == "sess-1" for s in items))
  ```
- [ ] Paso 2: `AttributeError: module 'cabina.sessions' has no attribute 'load'`.
- [ ] Paso 3:
  ```python
  def load(cfg):
      """Read the cached registry only — never opens a transcript. Used where a request must not
      pay parsing cost (server GET handler, MCP tool)."""
      reg = _load_registry(registry_path(cfg))
      return sorted((e["summary"] for e in reg.values()), key=lambda s: s.get("started") or "", reverse=True)
  ```
- [ ] Paso 4: `python3 -m unittest discover -s tests -p "test_sessions.py" -v` → `Ran 15 tests ... OK`.
- [x] Paso 5: `git commit -am "feat: sessions.py — load() reads the cached registry only, no re-parse"`

---

# Fase 1b — superficies: CLI, live provider aditivo, servidor, MCP, brief, UI

### Tarea 19: CLI `cabina activity [--project P] [--days N] [--json]`
**Archivos:** Modificar `src/cabina/cli.py` · Crear `tests/test_cli.py`

El CLI SÍ puede bloquear (no es un hilo de servidor HTTP) — llama `sessions.refresh()` directo,
igual que `cabina agents`/`cabina check` ya bloquean mientras trabajan.

- [ ] Paso 1: test que falla (nuevo archivo, patrón de subproceso de
      `tests/test_mcp.py::TestMcpSubprocess`):
  ```python
  import json, os, subprocess, sys, tempfile, unittest
  import _helpers  # noqa
  from _env import Env
  from cabina import scan

  class TestActivityCommand(unittest.TestCase):
      def test_activity_json_lists_sessions(self):
          env = Env(); scan.save(env.cfg, scan.run(env.cfg))
          with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as f:
              f.write(f'claude_home = "{env.claude}"\ncodex_home = "{env.codex}"\nroots = ["{env.projects}"]\nstate_dir = "{env.state}"\n[live]\nprovider = "none"\n[scan]\nmeasure_worktrees = false\ncheck_mcp = false\n')
              cfgp = f.name
          src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
          r = subprocess.run([sys.executable, "-m", "cabina", "--config", cfgp, "activity", "--json"],
                              capture_output=True, text=True, env={**os.environ, "PYTHONPATH": src}, timeout=60)
          self.assertEqual(r.returncode, 0, r.stderr)
          items = json.loads(r.stdout)
          self.assertTrue(any(s["project"] == "alpha" for s in items))
          os.unlink(cfgp); env.cleanup()

  if __name__ == "__main__":
      unittest.main()
  ```
- [ ] Paso 2: `python3 -m unittest discover -s tests -p "test_cli.py" -v` → falla:
      `invalid choice: 'activity'`.
- [ ] Paso 3: en `src/cabina/cli.py`, agregar el subparser junto a los demás:
  ```python
      ac = sub.add_parser("activity", help="session activity read from Claude Code transcripts")
      ac.add_argument("--project"); ac.add_argument("--days", type=int, default=30); ac.add_argument("--json", action="store_true")
  ```
  y el handler (junto a los otros `if a.cmd == ...:`):
  ```python
      if a.cmd == "activity":
          from . import sessions
          items = sessions.refresh(cfg, days=a.days)
          if a.project:
              items = [s for s in items if (s.get("project") or "").lower() == a.project.lower()]
          if a.json:
              print(json.dumps(items, ensure_ascii=False, indent=1)); return 0
          print(f"\n{'project':<20} {'started':<25} {'dur':>6} {'turns':>5} {'files':>5}  title")
          print("─" * 100)
          for s in items[:60]:
              dur = f"{(s['duration_s'] or 0) // 60}m"
              print(f"{(s['project'] or '—')[:20]:<20} {(s['started'] or '—')[:24]:<25} {dur:>6} {s['turns']:>5} {len(s['files_touched']):>5}  {(s['title'] or '—')[:50]}")
          print("─" * 100)
          print(f"  {len(items)} sessions\n")
          return 0
  ```
- [ ] Paso 4: `python3 -m unittest discover -s tests -p "test_cli.py" -v` → `Ran 1 test ... OK`.
- [x] Paso 5: `git commit -am "feat: cabina activity — CLI surface for session history"`

### Tarea 20: `live.TranscriptProvider` — señal ADITIVA de "activo", nunca reemplaza a herdr (R1)
**Archivos:** Modificar `src/cabina/live.py`, `src/cabina/config.py` · Crear `tests/test_live.py`

Importante: esto **no** entra en la cadena `live.get()` que elige el proveedor de la pestaña Live
(esa sigue siendo herdr-o-nada, sin cambios). `TranscriptProvider` es una fuente de información
APARTE, que la Tarea 21 usa para ampliar (nunca angostar) el conjunto de proyectos "trabajando" que
bloquea el guardado de documentos — "activo" es un estado propio, distinto de "working" de herdr, y
se calcula mirando tanto el archivo de sesión como cualquier archivo bajo `<sid>/subagents/`.

- [ ] Paso 1: test que falla. Nota (hallazgo de la revisión adversarial): la fixture de la Tarea 8
      ahora es "fría" por defecto — estos tests usan `env.touch_session(fresh=True)` cuando
      necesitan simular actividad reciente, en vez de asumirla:
  ```python
  import os, time, unittest
  import _helpers  # noqa
  from _env import Env
  from cabina import live as LIVE, scan

  class TestTranscriptProvider(unittest.TestCase):
      def setUp(self):
          self.env = Env()
      def tearDown(self):
          self.env.cleanup()

      def test_active_from_fresh_session_file(self):
          self.env.touch_session(fresh=True)
          roots = scan.project_roots(self.env.cfg, scan.run(self.env.cfg))
          out = LIVE.TranscriptProvider(self.env.cfg).active_projects(roots)
          self.assertIn("alpha", out)

      def test_fixture_is_stale_by_default(self):
          # guards the CRITICAL fix from Tarea 8: an ordinary Env, untouched, must NOT look active
          roots = scan.project_roots(self.env.cfg, scan.run(self.env.cfg))
          out = LIVE.TranscriptProvider(self.env.cfg).active_projects(roots)
          self.assertNotIn("alpha", out)

      def test_active_from_fresh_subagent_alone(self):
          old = time.time() - 3600
          os.utime(self.env.session_file, (old, old))         # main file stays stale
          sub = os.path.join(os.path.dirname(self.env.session_file), self.env.session_id, "subagents", "agent-1.jsonl")
          os.utime(sub, (time.time(), time.time()))            # only the subagent file is fresh
          roots = scan.project_roots(self.env.cfg, scan.run(self.env.cfg))
          out = LIVE.TranscriptProvider(self.env.cfg).active_projects(roots)
          self.assertIn("alpha", out)

  if __name__ == "__main__":
      unittest.main()
  ```
- [ ] Paso 2: `python3 -m unittest discover -s tests -p "test_live.py" -v` → `AttributeError:
      module 'cabina.live' has no attribute 'TranscriptProvider'`.
- [ ] Paso 3a: en `src/cabina/config.py`, `DEFAULTS`, cambiar
      `"live": {"provider": "auto"},` por `"live": {"provider": "auto", "active_seconds": 600},`
      (default 600s = 10 minutos, per R1 — antes se había considerado 120s en un borrador previo
      de este plan; R1 lo fija en 600 explícitamente).
- [ ] Paso 3b: en `src/cabina/live.py`, cambiar el import de cabecera a
      `import json, os, re, shutil, time` y agregar `from . import host, usage` (el `usage` es
      nuevo), y agregar antes de `def get(cfg):`:
  ```python
  class TranscriptProvider:
      """Reads Claude Code's own transcripts to find projects with very recent activity.
      ADDITIVE only (R1): used to extend the 'working' set that blocks doc saves — never
      replaces herdr, never downgrades a herdr 'working' status to idle, and is NOT part of the
      live.get() provider chain (the Live tab's provider selection is unchanged). Looks at BOTH
      the session file and any file under its sibling <sid>/subagents/ dir, so a busy subagent
      alone still counts as 'active'."""
      name = "transcript"

      def __init__(self, cfg):
          self.cfg = cfg

      @staticmethod
      def _peek_cwd(path, limit=40):
          try:
              with open(path, encoding="utf-8", errors="replace") as fh:
                  for _ in range(limit):
                      line = fh.readline()
                      if not line:
                          break
                      m = re.search(r'"cwd":"([^"]+)"', line)
                      if m:
                          return m.group(1)
          except Exception:
              pass
          return None

      def active_projects(self, roots):
          """{project names} with a session or subagent file whose mtime is under
          cfg.live.active_seconds (default 600)."""
          pdir = os.path.join(self.cfg["claude_home"], "projects")
          if not os.path.isdir(pdir):
              return set()
          active = (self.cfg.get("live") or {}).get("active_seconds", 600)
          now = time.time()
          out = set()
          for e in os.listdir(pdir):
              edir = os.path.join(pdir, e)
              if not os.path.isdir(edir):
                  continue
              top = [f for f in os.listdir(edir) if f.endswith(".jsonl")]
              if not top:
                  continue
              fresh = any(now - os.path.getmtime(os.path.join(edir, f)) < active for f in top)
              if not fresh:
                  for name in os.listdir(edir):
                      sub = os.path.join(edir, name, "subagents")
                      if os.path.isdir(sub) and any(
                          f.endswith(".jsonl") and now - os.path.getmtime(os.path.join(sub, f)) < active
                          for f in os.listdir(sub)
                      ):
                          fresh = True
                          break
              if not fresh:
                  continue
              newest = max((os.path.join(edir, f) for f in top), key=os.path.getmtime)
              cwd = self._peek_cwd(newest)
              proj = usage._project_of(cwd, roots) if cwd else None
              if proj:
                  out.add(proj)
          return out
  ```
- [ ] Paso 4: `python3 -m unittest discover -s tests -p "test_live.py" -v` → `Ran 3 tests ... OK`.
      Correr la suite completa una vez para confirmar que nada existente se rompió.
- [x] Paso 5: `git commit -am "feat: live.TranscriptProvider — additive 'active' signal from transcript mtimes, never replacing herdr (R1)"`

### Tarea 21: `server.App.working()` se amplía con la señal de transcripciones — guard + break-test (R1)
**Archivos:** Modificar `src/cabina/server.py`, `tests/test_breaks.py`

Este es el punto real donde R1 pega: el conjunto de proyectos "trabajando" que bloquea
`docs.save()` pasa de ser solo lo que dice herdr, a ser esa unión CON lo que dice
`TranscriptProvider` — sin tocar `docs.py` en absoluto (ya acepta `working=<iterable>` desde
afuera; el guard vive en quién arma ese iterable).

**Corrección sobre una afirmación equivocada de una versión anterior de este plan:** un borrador
previo decía que ampliar `working()` "no debería romper nada" porque ningún test de
`test_server.py` verifica el CONTENIDO de `working`. Eso era **incorrecto** — la revisión
adversarial lo encontró: `test_doc_read_save_conflict` y
`test_commit_endpoint_requires_repo_and_only_that_path` (`tests/test_server.py`) SÍ dependen del
contenido de `working`, aunque no lo lean directamente: ambos guardan un documento en el proyecto
`alpha` con `docs().save(..., working=self.working())` (indirectamente, vía el endpoint
`/api/save-doc`) y esperan `ok: True`. Antes de la Tarea 8, la transcripción de la fixture quedaba
con mtime "de ahora" — así que, sin el fix de la Tarea 8, `working()` habría incluido "alpha" en
CADA test que usa `Env`, y esos dos tests habrían empezado a fallar con "an agent is working in
alpha right now" apenas se ampliara `working()`. La Tarea 8 ya resolvió esto (fixture fría por
defecto); por eso el test de esta tarea puede ejercer el camino real de guardado sin miedo a romper
esos dos tests — de hecho, ESTE test es la prueba de que el fix de la Tarea 8 alcanza.

Además, el break-test de esta tarea ya no se queda en `App.working()`: ejercita el camino real,
`app.docs().save(...)`, que es lo que de verdad protege al usuario.

- [ ] Paso 1: test que falla (en `tests/test_breaks.py`; `sessions as SESS` ya se agregó en la
      Tarea 15 — agregar además `server as SRV` a esa misma línea de import
      `from cabina import contract as C, docs as D, harness as H, usage as U`, y agregar
      `from _env import Env`):
  ```python
      def test_transcript_activity_blocks_the_real_save_path(self):
          env = Env()
          try:
              env.touch_session(fresh=True)                        # simulate recent activity
              app = SRV.App(env.cfg)                                # herdr absent (Env forces live.provider="none")
              d = app.docs().read("alpha", "CLAUDE.md")
              r = app.docs().save("alpha", "CLAUDE.md", d["content"], d["hash"], working=app.working())
              self.assertFalse(r["ok"])                             # fresh transcript -> blocked, even without herdr
              env.touch_session(fresh=False)                        # backdate past active_seconds
              app2 = SRV.App(env.cfg)
              r2 = app2.docs().save("alpha", "CLAUDE.md", d["content"], d["hash"], working=app2.working())
              self.assertTrue(r2["ok"], r2)                          # stale -> allowed
          finally:
              env.cleanup()
  ```
- [ ] Paso 2: `python3 -m unittest discover -s tests -p "test_breaks.py" -v -k transcript_activity`
      → falla en el primer `assertFalse` (`working()` hoy no sabe nada de transcripciones, así que
      `save()` de hecho tiene éxito cuando no debería).
- [ ] Paso 3: en `src/cabina/server.py`, agregar `sessions as SESS` a la línea de import del tope
      (`from . import scan, skills as SK, projects as PROJ, harness as HAR, usage, live as LIVE,
      host, drift as DR, gitops as GO, sessions as SESS`), y reemplazar:
  ```python
      def working(self):
          return LIVE.working_projects(self.live, self.roots())
  ```
  por:
  ```python
      def working(self):
          base = set(LIVE.working_projects(self.live, self.roots()))
          try:
              base |= LIVE.TranscriptProvider(self.cfg).active_projects(self.roots())
          except Exception:
              pass                                                 # never let this signal break the guard itself
          return sorted(base)
  ```
- [ ] Paso 4: `python3 -m unittest discover -s tests -p "test_breaks.py" -v` → `Ran 11 tests ... OK`
      (los 10 anteriores + este). Correr también `test_server.py` completo —
      `test_doc_read_save_conflict` y `test_commit_endpoint_requires_repo_and_only_that_path` deben
      seguir en verde (ver la nota de arriba: la fixture llega fría por defecto desde la Tarea 8, así
      que `working()` no incluye "alpha" a menos que un test llame `env.touch_session(fresh=True)`
      explícitamente).
- [x] Paso 5: `git commit -am "feat: server — App.working() unions in transcript-active projects, additively (R1); break-test exercises the real docs().save() path"`

### Tarea 22: `GET /api/activity` — sirve el último snapshot, refresca en segundo plano (R2)
**Archivos:** Modificar `src/cabina/server.py`, `tests/test_server.py`

**Nunca parsear en el hilo de la petición.** El patrón es el mismo que ya usa `api_rescan`:
disparar un hilo de fondo y responder de inmediato con lo último que hay en caché.

- [ ] Paso 1: test que falla:
  ```python
  # tests/test_server.py, agregar a TestServer
      def test_activity_endpoint_serves_cache(self):
          from cabina import sessions as SESS
          SESS.refresh(self.env.cfg)                      # populate the cache once, synchronously, for the test
          d = self.get("/api/activity?days=30")
          self.assertTrue(any(s["project"] == "alpha" for s in d["sessions"]))
          self.assertIn("active_seconds", d)
          d2 = self.get("/api/activity?project=alpha&days=30")
          self.assertTrue(d2["sessions"]); self.assertTrue(all(s["project"] == "alpha" for s in d2["sessions"]))
  ```
- [ ] Paso 2: `python3 -m unittest discover -s tests -p "test_server.py" -v -k activity` →
      `HTTPError: HTTP Error 404: Not Found`.
- [ ] Paso 3: en `src/cabina/server.py` (el import de `sessions as SESS` ya se agregó en la Tarea
      21), agregar el método a `class App`:
  ```python
      def api_activity(self, q):
          days = int((q.get("days") or ["30"])[0])
          proj = (q.get("project") or [""])[0]
          def go():
              SESS.refresh(self.cfg, days=days)
          threading.Thread(target=go, daemon=True).start()          # never parse on the request thread
          items = SESS.load(self.cfg)
          if proj:
              items = [s for s in items if s.get("project") == proj]
          return {"sessions": items, "days": days, "active_seconds": (self.cfg.get("live") or {}).get("active_seconds", 600)}
  ```
  y en `make_handler`, agregar al diccionario `GETS`: `"/api/activity": app.api_activity,`
- [ ] Paso 4: `python3 -m unittest discover -s tests -p "test_server.py" -v` → todos en verde.
- [x] Paso 5: `git commit -am "feat: server — GET /api/activity serves the cached snapshot, refreshes off the request thread (R2)"`

### Tarea 23: MCP — `cabina_activity(project, days)`, `project` obligatorio, sin títulos/rutas (R11)
**Archivos:** Modificar `src/cabina/mcp.py`, `tests/test_mcp.py`

Sin `project` no hay respuesta — nada de listar actividad cruzando todos los proyectos desde un
agente externo. Y el resultado nunca lleva título, `cwd` ni ruta de archivo: solo agregados y una
lista de sesiones con forma fija `{started, ended, duration_s, turns, commits, agents, skills}`.

- [ ] Paso 1: tests que fallan (agregar a `TestMcpInProcess` en `tests/test_mcp.py`; también
      ajustar el set esperado en `test_initialize_and_list`):
  ```python
      def test_activity_tool_requires_project_and_hides_titles_paths(self):
          from cabina import sessions as SESS
          SESS.refresh(self.env.cfg)
          r = self.call("cabina_activity", project="alpha")
          self.assertEqual(r["project"], "alpha")
          self.assertGreaterEqual(r["aggregate"]["sessions"], 1)
          dumped = json.dumps(r)
          self.assertNotIn("title", dumped); self.assertNotIn("source_path", dumped); self.assertNotIn('"cwd"', dumped)
          resp = self.srv.handle({"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": "cabina_activity", "arguments": {}}})
          self.assertTrue(resp["result"]["isError"])                # project omitted -> bad arguments
  ```
  y en `test_initialize_and_list`, agregar `"cabina_activity"` al set esperado.
- [ ] Paso 2: `python3 -m unittest discover -s tests -p "test_mcp.py" -v` → falla (herramienta no
      existe / set de nombres no calza).
- [ ] Paso 3: en `src/cabina/mcp.py`:
  - en `tools_spec()`, agregar:
    ```python
            {"name": "cabina_activity", "description": "Session activity from Claude Code transcripts, aggregated for ONE project — no titles, no paths, no cwd (R11 of the design contract). Read-only; reads the cached registry (a `cabina activity` run or a UI visit may be needed first to populate it).",
             "inputSchema": {"type": "object", "properties": {"project": {"type": "string"}, "days": {"type": "integer", "description": "lookback window in days (default 30)"}}, "required": ["project"], "additionalProperties": False}},
    ```
  - en `class Server`, agregar:
    ```python
        def t_activity(self, project, days=30, **_):
            from . import sessions
            items = [s for s in sessions.load(self.cfg) if s.get("project") == project]
            agg = {"sessions": len(items), "tokens": {"in": 0, "out": 0}, "commits": 0}
            out = []
            for s in items:
                agg["tokens"]["in"] += (s.get("tokens") or {}).get("in", 0)
                agg["tokens"]["out"] += (s.get("tokens") or {}).get("out", 0)
                agg["commits"] += s.get("commits", 0)
                out.append({"started": s.get("started"), "ended": s.get("ended"), "duration_s": s.get("duration_s"),
                            "turns": s.get("turns"), "commits": s.get("commits"), "agents": s.get("agents"), "skills": s.get("skills")})
            return {"project": project, "aggregate": agg, "sessions": out}
    ```
  - en `handle()`, agregar al diccionario de despacho: `"cabina_activity": self.t_activity,`
- [ ] Paso 4: `python3 -m unittest discover -s tests -p "test_mcp.py" -v` → todos en verde.
- [x] Paso 5: `git commit -am "feat: MCP — cabina_activity requires project, never returns titles/cwd/paths (R11)"`

### Tarea 24: `cabina brief` gana una línea — "última sesión aquí"
**Archivos:** Modificar `src/cabina/guard.py`, `src/cabina/i18n.py`, `tests/test_guard.py`

- [ ] Paso 1: test que falla:
  ```python
      def test_brief_mentions_last_session(self):
          from cabina import sessions as SESS
          SESS.refresh(self.env.cfg)
          out = G.brief(self.env.cfg, cwd=self.env.alpha)
          self.assertIn("Refactor the widget loader", out)
  ```
- [ ] Paso 2: `python3 -m unittest discover -s tests -p "test_guard.py" -v -k last_session` → falla.
- [ ] Paso 3a: en `src/cabina/i18n.py`, agregar en `en` y `es` (junto a `"fix.worktree"`):
  ```python
      # en:
      "brief.last_session": "last session here: {title} ({ago} ago)",
      # es:
      "brief.last_session": "última sesión aquí: {title} (hace {ago})",
  ```
- [ ] Paso 3b: en `src/cabina/guard.py`, agregar cerca de `read_stdin_briefly`:
  ```python
  def _ago(ts):
      """Local-aware ISO timestamp -> compact 'x minutes/hours/days ago' string. Best-effort.
      sessions.py already stores started/ended converted to local time with an offset (R7), so
      this parses it directly — no 'Z' stripping needed here."""
      if not ts:
          return "?"
      try:
          t0 = datetime.fromisoformat(ts)
          now = datetime.now(t0.tzinfo) if t0.tzinfo else datetime.now()
          secs = (now - t0).total_seconds()
      except Exception:
          return "?"
      mins = int(secs // 60)
      if mins < 60:
          return f"{mins}m"
      hours = mins // 60
      return f"{hours}h" if hours < 24 else f"{hours // 24}d"
  ```
  y dentro de `brief()`, en el `try:` que ya calcula `here` y la línea de `MEMORY.md`, agregar al
  final de ese mismo bloque `try`:
  ```python
          from . import sessions
          from .i18n import t as _t
          sess = [s for s in sessions.load(cfg) if s.get("project") == here]
          if sess:
              last = sess[0]
              lines.append("[cabina] " + _t(cfg["language"], "brief.last_session",
                                             title=last.get("title") or "(untitled)", ago=_ago(last.get("ended") or last.get("started"))))
  ```
- [ ] Paso 4: `python3 -m unittest discover -s tests -p "test_guard.py" -v` → todos en verde.
- [x] Paso 5: `git commit -am "feat: brief() — one line with the last session recorded in this project"`

### Tarea 25: UI — pestaña "Actividad" (lista + detalle + timeline de 14 días + "activo hace Ns")
**Archivos:** Modificar `src/cabina/static/index.html`, `tests/test_server.py`

Mismo patrón lista/detalle que Agents/Skills/Docs. Cada fila muestra un chip "activo hace Ns"
cuando `mtime` está dentro de `active_seconds` (el mismo umbral de R1, servido en la respuesta del
endpoint) — es la traducción visual de la señal ADITIVA de la Tarea 20/21: "esta sesión sigue
caliente ahora mismo", no un estado nuevo del contrato herdr.

Decisión (R7): `--days`/la retención de la Tarea 17 pueden seguir siendo una ventana corrediza
("últimas 720 horas"), pero el timeline de 14 días de esta pestaña agrupa por DÍA CALENDARIO local
(límites de medianoche local, no "últimas 24 h desde ahora") — dos sesiones a las 23:50 y las 00:10
del día siguiente van en barras distintas, no en la misma.

- [ ] Paso 1: test que falla:
  ```python
      def test_index_has_activity_tab(self):
          with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
          self.assertIn('"activity"', html); self.assertIn("/api/activity", html)
  ```
- [ ] Paso 2: `python3 -m unittest discover -s tests -p "test_server.py" -v -k activity_tab` →
      falla, ninguna de las dos cadenas está en el HTML.
- [ ] Paso 3: en `src/cabina/static/index.html`:
  1. `I18N.en.tabs`: agregar `activity:"Activity"`; `I18N.es.tabs`: agregar `activity:"Actividad"`.
  2. `I18N.en` (nivel raíz): agregar
     `pickSession:"Select a session.",noSessions:"No sessions in this window.",untitled:"(untitled)",
     sessStarted:"started",sessDuration:"duration",sessTurns:"turns",sessFiles:"files touched",
     sessAgents:"agents used",sessSkills:"skills used",sessCommits:"commits",sessSubagents:"subagents",
     sessTokens:"tokens (in/out)",sessBranch:"branch",sessionsFoot:"{n} sessions",activeNow:"active {n}s ago",`
     `I18N.es`: `pickSession:"Seleccioná una sesión.",noSessions:"No hay sesiones en esta ventana.",
     untitled:"(sin título)",sessStarted:"inicio",sessDuration:"duración",sessTurns:"turnos",
     sessFiles:"archivos tocados",sessAgents:"agentes usados",sessSkills:"skills usados",
     sessCommits:"commits",sessSubagents:"subagentes",sessTokens:"tokens (in/out)",sessBranch:"rama",
     sessionsFoot:"{n} sesiones",activeNow:"activo hace {n}s",`
  3. `const VIEWS=["agents","live","skills","projects","harness","docs"];` → agregar `"activity"`
     al final del arreglo.
  4. En `S={...}`, agregar `activity:null,`.
  5. Junto a `loadDocs`, agregar:
     ```js
     async function loadActivity(){S.activity=await GET("/api/activity?days=30");if(S.view==="activity")render();}
     ```
  6. En `render()`, agregar `activity:renderActivity,` al objeto de despacho; en el `onclick` de
     las pestañas, agregar la carga condicional `if(S.view==="activity"&&!S.activity)loadActivity();`
     junto a las de `docs`/`harness`.
  7. Agregar la sección nueva (junto a `// ---------- SKILLS ----------`):
     ```js
     // ---------- ACTIVITY ----------
     function actTimeline(sessions){const days=14;const today=new Date();today.setHours(0,0,0,0);const buckets=Array(days).fill(0);
      sessions.forEach(s=>{if(!s.started)return;const dt=new Date(s.started);dt.setHours(0,0,0,0);const d=Math.round((today-dt)/86400000);if(d>=0&&d<days)buckets[days-1-d]++;});   // local calendar day, not a rolling 24h window (R7)
      const max=Math.max(1,...buckets),w=140,h=28,bw=w/days;
      const bars=buckets.map((v,i)=>{const bh=Math.round((v/max)*h);return `<rect x="${i*bw+1}" y="${h-bh}" width="${bw-2}" height="${Math.max(bh,1)}" rx="1"></rect>`;}).join("");
      return `<svg width="${w}" height="${h}" style="color:var(--moss);fill:currentColor;vertical-align:middle" role="img" aria-label="14-day session count">${bars}</svg>`;}
     function renderActivity(){if(!S.activity){$("rows").innerHTML=`<div class="empty">${T("loading")}</div>`;$("filters").innerHTML="";return;}
      const a=S.activity.sessions,activeSecs=S.activity.active_seconds||600,now=Date.now()/1000;
      $("filters").innerHTML=actTimeline(a)+`<input id="q" placeholder="${T("search")}" value="${esc(S.q)}">`+chipFocus();
      bindFocus();$("q").oninput=e=>{S.q=e.target.value;renderActivity();};
      const q=S.q.toLowerCase();let sel=a.filter(x=>{if(S.focus&&x.project!==S.focus)return false;if(q&&!((x.project||"")+" "+(x.title||"")).toLowerCase().includes(q))return false;return true;});
      $("rows").innerHTML=sel.length?sel.map(x=>{const key=x.source_path;const active=x.mtime&&(now-x.mtime)<activeSecs;
       return `<button class="row ${S.sel===key?"sel":""}" data-k="${esc(key)}"><span class="dot d-${active?"working":"valid"}"></span><span class="n">${esc(x.title||T("untitled"))}${active?` <span class="tl">${T("activeNow",{n:Math.round(now-x.mtime)})}</span>`:""}</span><span class="w">${esc(x.project||"—")} · ${Math.round((x.duration_s||0)/60)}m</span></button>`;}).join(""):`<div class="empty">${T("noSessions")}</div>`;
      document.querySelectorAll(".row").forEach(r=>r.onclick=()=>{S.sel=r.dataset.k;renderActivity();});
      $("foot").textContent=T("sessionsFoot",{n:sel.length});
      if(!S.sel)$("detail").innerHTML=`<div class="muted">${T("pickSession")}</div>`;else renderSessionDetail();}
     function renderSessionDetail(){const x=(S.activity?.sessions||[]).find(y=>y.source_path===S.sel);if(!x){$("detail").innerHTML=`<div class="muted">${T("pickSession")}</div>`;return;}
      const tc=Object.entries(x.tool_calls||{}).map(([k,v])=>`${k}:${v}`).join(", ")||"—";
      const ag=Object.keys(x.agents||{}).join(", ")||"—",sk=Object.keys(x.skills||{}).join(", ")||"—";
      let h=`<div class="h">${esc(x.title||T("untitled"))}</div><div class="meta"><span>${T("where")}</span><b>${esc(x.project||"—")}</b><span>${T("sessBranch")}</span><b>${esc(x.branch||"—")}</b>`+
       `<span>${T("sessStarted")}</span><b>${esc(x.started||"—")}</b><span>${T("sessDuration")}</span><b>${Math.round((x.duration_s||0)/60)}m</b>`+
       `<span>${T("sessTurns")}</span><b>${x.turns}</b><span>${T("sessFiles")}</span><b>${(x.files_touched||[]).length}</b>`+
       `<span>${T("sessAgents")}</span><b>${esc(ag)}</b><span>${T("sessSkills")}</span><b>${esc(sk)}</b>`+
       `<span>${T("sessCommits")}</span><b>${x.commits||0}</b><span>${T("sessSubagents")}</span><b>${x.subagents||0}</b>`+
       `<span>${T("sessTokens")}</span><b>${(x.tokens&&x.tokens.in)||0} / ${(x.tokens&&x.tokens.out)||0}</b></div>`+
       `<div class="muted">${esc(tc)}</div>`+((x.files_touched||[]).length?`<pre class="doc">${(x.files_touched||[]).map(esc).join("\n")}</pre>`:"");
      $("detail").innerHTML=h;}
     ```
     Nota: `x.title` se interpola SIEMPRE a través de `esc()` — esto es lo que la Fase 2 (`hub`)
     va a depender de que siga siendo cierto (Tarea de `hub` sobre XSS, R10).
- [ ] Paso 4: `python3 -m unittest discover -s tests -p "test_server.py" -v` → todos en verde.
      Verificación manual complementaria (no automatizada): `PYTHONPATH=src python3 -m cabina ui`
      con datos reales, click en "Actividad" (skill `run`).
- [x] Paso 5: `git commit -am "feat: UI — Activity tab (session list, detail, 14-day timeline, 'active Ns ago' badge)"`

---

## Enmiendas aplicadas durante la ejecución (Fase 1/1b)

Durante la ejecución de Fase 1/1b, además de las tareas planeadas, se aplicaron las siguientes
correcciones (algunas durante la implementación original, otras a partir de una revisión de código
independiente posterior). Se documentan aquí, con el hash del commit que las introdujo, para que no
queden implícitas:

- **Lector de línea parcial** (`_read_new_lines` nunca consume una línea final sin `\n`, porque una
  transcripción viva se sigue escribiendo mientras cabina la lee): `fa09866`.
- **Atribución por repositorio git de respaldo + nombre determinístico**: primero, atribuir una
  sesión a su repo git aunque no tenga `.claude/` (`ac7198f`); después, al detectar que el nombre
  dependía del orden de escaneo, se corrigió para que sea SIEMPRE la ruta relativa a la raíz
  contenedora — determinístico sin importar qué más se haya escaneado antes — y para que
  `files_touched` de esos repos también quede relativizado (`76cea45`).
- **Un solo centinela `"unknown"`** para sesiones sin proyecto atribuible, nunca `None`: `b2ad476`.
- **Tokens de subagentes leídos incrementalmente por offset**, igual que el archivo de sesión
  propio, en vez de releer la transcripción completa en cada refresh: `7c1ba71`.
- **`TranscriptProvider` lee la cola de la transcripción, no la cabeza**: una sesión que cambia de
  proyecto a mitad de camino (un `cd` a otro repo) quedaba mal atribuida al cwd de arranque; ahora
  se lee el último ~64 KB del archivo y se usa la ÚLTIMA coincidencia de `cwd`, con la cabeza como
  respaldo solo si la cola no tiene ninguna: `99fdaab`.
- **Strings TOML literales para rutas en configs de subproceso** (una ruta de Windows con backslash
  rompe `tomllib` si va entre comillas dobles): `41e93c8`.
- **Canario R8 hecho real**: el canario que probaba "el registro en disco nunca contiene texto de
  prompt" seguía en verde aunque se desactivara la guarda de redacción, porque `_merge_lines` nunca
  copiaba texto crudo al estado — no había nada que la guarda pudiera atrapar. Se reemplazó por un
  canario que envuelve el `_merge_lines` real e inyecta el marcador, así la guarda del punto de
  escritura queda genuinamente ejercida: `7bd7fab`.
- **Test de resiliencia por archivo**: `refresh()` ya toleraba que una transcripción individual
  fallara al leerse (no abortaba las demás), pero nada lo ejercitaba de punta a punta; se agregó un
  segundo archivo de sesión forzado a fallar y se verificó que el resto de las sesiones y el
  registro en disco sobreviven: `eab174b`.

---

# Fase 2 — equipos: export --activity, hub, compare (tareas granulares, R9/R10/P1-P5)

Analogía: si Fase 1/1b es el medidor de electricidad de una casa, Fase 2 junta la lectura de varias
casas en una sola hoja — sin que ninguna casa le dé permiso de escritura a las demás. Cada casa
sigue midiendo lo suyo (`sessions.json` local, nunca se toca); lo único nuevo es una hoja de cálculo
de solo lectura que junta varias lecturas ya hechas.

### Tarea 26: Fixtures para Fase 2 — sesiones reales pobladas + un export sintético de "otra máquina"
**Archivos:** Modificar `tests/_env.py` · Crear `tests/test_hub.py`

Dos piezas chicas de infraestructura que van a usar casi todas las tareas siguientes: (1) un método
en `Env` que corre `sessions.refresh()` de verdad (para tener `activity` poblada antes de exportar),
y (2) una función que arma el JSON de un export de OTRA máquina sin tener que levantar un segundo
entorno sintético completo — como tener una segunda hoja de cálculo ya llena a mano, en vez de
montar una segunda oficina entera solo para sacarle una foto.

- [ ] Paso 1: test que falla:
  ```python
  import unittest
  import _helpers  # noqa
  from _env import Env, sample_export

  class TestHubFixtures(unittest.TestCase):
      def test_refresh_sessions_and_sample_export_shape(self):
          env = Env()
          try:
              items = env.refresh_sessions()
              self.assertTrue(any(s["session_id"] == "sess-1" for s in items))
          finally:
              env.cleanup()
          ex = sample_export("mac-mini")
          self.assertEqual(ex["machine"], "mac-mini")
          self.assertEqual(ex["activity"]["aggregated"][0]["project"], "alpha")

  if __name__ == "__main__":
      unittest.main()
  ```
- [ ] Paso 2: `python3 -m unittest discover -s tests -p "test_hub.py" -v` →
      `ImportError: cannot import name 'sample_export'` (y luego, arreglado eso,
      `AttributeError: 'Env' object has no attribute 'refresh_sessions'`).
- [ ] Paso 3: en `tests/_env.py`, agregar el método a la clase `Env` (junto a `touch_session`):
  ```python
      def refresh_sessions(self):
          """Conveniencia para tests que necesitan `activity` poblada antes de llamar a
          snapshot.export_activity o de golpear el hub: corre sessions.refresh() de verdad
          contra el cfg de este Env, devuelve la lista de resúmenes."""
          from cabina import sessions as SESS
          return SESS.refresh(self.cfg)
  ```
  y, al final del archivo (fuera de la clase), la función de nivel de módulo:
  ```python
  def sample_export(machine, project="alpha", sessions=1, hours=1.0):
      """Un payload de `cabina export --activity` mínimo pero realista — para tests de hub que
      necesitan DOS O MÁS máquinas sin levantar un segundo Env sintético completo por cada una."""
      return {"cabina": 1, "machine": machine, "os": "Linux", "when": "2026-08-18T10:00",
              "agents": [], "skills": [], "harness": [], "projects": [project],
              "activity": {"aggregated": [{"project": project, "sessions": sessions, "hours": hours,
                                            "tokens": {"in": 100, "out": 200}, "commits": 1,
                                            "files_touched": 3, "tool_calls": {"Edit": 2},
                                            "agents": {}, "skills": {}}]}}
  ```
- [ ] Paso 4: `python3 -m unittest discover -s tests -p "test_hub.py" -v` → `Ran 1 test ... OK`.
- [x] Paso 5: `git commit -am "test: Env.refresh_sessions() + sample_export() — Fase 2 fixtures for export/hub tests"`

### Tarea 27: `snapshot.export_activity` — agregados por proyecto, guardia de campos locales (R9/P1)
**Archivos:** Modificar `src/cabina/snapshot.py` · Crear `tests/test_snapshot.py`

Analogía: es el resumen que un jefe de sucursal manda a la oficina central — cuántas horas se
trabajó y cuánto se facturó en cada proyecto, nunca la agenda con el detalle de quién estaba en cada
escritorio (eso es `cwd`/`source_path`, que se quedan en la máquina). `--detail` agrega una fila por
sesión (sigue sin nombres de escritorio); `--titles` agrega el título, y solo tiene sentido si ya
pediste el detalle — pedirlo sin detalle es un error de uso, no algo que se ignore en silencio.

- [ ] Paso 1: test que falla (archivo nuevo):
  ```python
  import json, unittest
  import _helpers  # noqa
  from _env import Env
  from cabina import snapshot as SNAP

  class TestExportActivity(unittest.TestCase):
      def setUp(self):
          self.env = Env(); self.env.refresh_sessions()
      def tearDown(self):
          self.env.cleanup()

      def test_export_activity_aggregated_by_default(self):
          out = SNAP.export_activity(self.env.cfg)
          self.assertNotIn("sessions", out)
          row = next(a for a in out["aggregated"] if a["project"] == "alpha")
          self.assertEqual(row["sessions"], 1)
          self.assertIn("tokens", row); self.assertIn("tool_calls", row)

      def test_export_activity_detail_adds_per_session_rows(self):
          out = SNAP.export_activity(self.env.cfg, detail=True)
          row = next(s for s in out["sessions"] if s["project"] == "alpha")
          self.assertIn("branch", row); self.assertNotIn("title", row)
          self.assertEqual(row["files_touched"], ["src/widget.py"])

      def test_export_activity_titles_requires_detail(self):
          with self.assertRaises(ValueError):
              SNAP.export_activity(self.env.cfg, titles=True)

      def test_export_activity_never_includes_cwd_or_source_path(self):
          out = SNAP.export_activity(self.env.cfg, detail=True, titles=True)
          dumped = json.dumps(out)
          self.assertNotIn("source_path", dumped)
          self.assertNotIn('"cwd"', dumped)

  if __name__ == "__main__":
      unittest.main()
  ```
- [ ] Paso 2: `python3 -m unittest discover -s tests -p "test_snapshot.py" -v` →
      `AttributeError: module 'cabina.snapshot' has no attribute 'export_activity'`.
- [ ] Paso 3: en `src/cabina/snapshot.py`, agregar (después de los imports, antes de `export`):
  ```python
  _LOCAL_ONLY_FIELDS = ("cwd", "source_path", "mtime", "size", "offset")


  def _strip_local_only(row):
      """R9 (cwd/source_path) + P1 (también mtime/size/offset): campos que nunca deben salir de
      esta máquina, sin importar cómo se haya construido la fila. Se aplica en el límite mismo de
      la exportación — no confía en que quien construye la fila nunca los vuelva a agregar."""
      return {k: v for k, v in row.items() if k not in _LOCAL_ONLY_FIELDS}


  def _detail_row(s, titles):
      """Una fila de `export --activity --detail`, como lista blanca explícita a partir de un
      resumen de sesión completo `s` (que SÍ trae cwd/source_path/mtime/size/offset — sessions.py
      los guarda solo localmente, no para exportar). titles=True agrega el título."""
      row = {"project": s.get("project"), "started": s.get("started"), "ended": s.get("ended"),
             "duration_s": s.get("duration_s"), "turns": s.get("turns"), "commits": s.get("commits"),
             "branch": s.get("branch"), "files_touched": s.get("files_touched") or [],
             "agents": s.get("agents") or {}, "skills": s.get("skills") or {},
             "tokens": s.get("tokens") or {"in": 0, "out": 0}, "subagents": s.get("subagents", 0)}
      if titles:
          row["title"] = s.get("title")
      return row


  def export_activity(cfg, projects=None, detail=False, titles=False):
      """R9/P1: agregado por proyecto por default; detail=True agrega filas por sesión; titles=True
      requiere detail=True (error de uso si no, nunca un flag ignorado en silencio). cwd y
      source_path (más mtime/size/offset) nunca salen de acá — _strip_local_only corre sobre CADA
      fila, agregada o por sesión, justo antes de devolverla."""
      if titles and not detail:
          raise ValueError("--titles requires --detail")
      from . import sessions
      items = sessions.load(cfg)
      if projects:
          want = {p.lower() for p in projects}
          items = [s for s in items if (s.get("project") or "").lower() in want]
      agg = {}
      for s in items:
          p = s.get("project") or "unknown"
          a = agg.setdefault(p, {"project": p, "sessions": 0, "hours": 0.0, "tokens": {"in": 0, "out": 0},
                                 "commits": 0, "files_touched": 0, "tool_calls": {}, "agents": {}, "skills": {}})
          a["sessions"] += 1
          a["hours"] += (s.get("duration_s") or 0) / 3600.0
          a["tokens"]["in"] += (s.get("tokens") or {}).get("in", 0)
          a["tokens"]["out"] += (s.get("tokens") or {}).get("out", 0)
          a["commits"] += s.get("commits", 0)
          a["files_touched"] += len(s.get("files_touched") or [])
          for k, v in (s.get("tool_calls") or {}).items(): a["tool_calls"][k] = a["tool_calls"].get(k, 0) + v
          for k, v in (s.get("agents") or {}).items(): a["agents"][k] = a["agents"].get(k, 0) + v
          for k, v in (s.get("skills") or {}).items(): a["skills"][k] = a["skills"].get(k, 0) + v
      aggregated = []
      for p in sorted(agg):
          a = agg[p]; a["hours"] = round(a["hours"], 2)
          aggregated.append(_strip_local_only(a))
      out = {"aggregated": aggregated}
      if detail:
          out["sessions"] = [_strip_local_only(_detail_row(s, titles)) for s in items]
      return out
  ```
- [ ] Paso 4: `python3 -m unittest discover -s tests -p "test_snapshot.py" -v` → `Ran 4 tests ... OK`.
- [x] Paso 5: `git commit -am "feat: snapshot.export_activity — aggregated-by-default session activity export, local-only fields stripped (R9/P1)"`

### Tarea 28: `snapshot.export(cfg, activity=None)` + CLI `cabina export --activity`
**Archivos:** Modificar `src/cabina/snapshot.py`, `src/cabina/cli.py` · Modificar `tests/test_cli.py`

- [ ] Paso 1: test que falla (agregar a `tests/test_cli.py`, imports: agregar `from unittest import mock`):
  ```python
  class TestExportActivity(unittest.TestCase):
      def test_export_activity_flag_and_project_filter(self):
          env = Env(); scan.save(env.cfg, scan.run(env.cfg)); env.refresh_sessions()
          with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as f:
              f.write(f"claude_home = '{env.claude}'\ncodex_home = '{env.codex}'\nroots = ['{env.projects}']\nstate_dir = '{env.state}'\n[live]\nprovider = \"none\"\n[scan]\nmeasure_worktrees = false\ncheck_mcp = false\n")
              cfgp = f.name
          outdir = tempfile.mkdtemp(); outp = os.path.join(outdir, "export.json")
          src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
          r = subprocess.run([sys.executable, "-m", "cabina", "--config", cfgp, "export", "--activity", "--detail", "--project", "alpha", "-o", outp],
                              capture_output=True, text=True, env={**os.environ, "PYTHONPATH": src}, timeout=60)
          self.assertEqual(r.returncode, 0, r.stderr)
          data = json.load(open(outp))
          self.assertIn("activity", data)
          self.assertTrue(data["activity"]["sessions"])
          self.assertTrue(all(s["project"] == "alpha" for s in data["activity"]["sessions"]))
          os.unlink(cfgp); env.cleanup()
  ```
- [ ] Paso 2: `python3 -m unittest discover -s tests -p "test_cli.py" -v -k export_activity` →
      falla: `error: unrecognized arguments: --activity` (exit code 2).
- [ ] Paso 3a: en `src/cabina/snapshot.py`, cambiar la firma y el cuerpo de `export`:
  ```python
  def export(cfg, activity=None):
      data = scan.ensure(cfg)
      R = Roster(cfg, data); rows, items = R.load(refresh_usage=False)
      agents = [{"name": r.name, "project": p, "tool": t, "category": r.category, "model": r.fields.get("model", ""),
                 "uses": items.get(r.name, {}).get("n_total", 0)} for p, r, path, t in rows if r.is_agent]
      sk = [{"name": s["name"], "project": s["project"], "state": s["state"], "symlink": s["symlink"]} for s in SK.load(cfg, data)]
      hs = [{"project": e["name"], "level": e["level"], "hooks_dead": e["hooks_dead"], "hooks_broken": e["hooks_broken"]} for e in HAR.states(data)]
      out = {"cabina": 1, "machine": socket.gethostname(), "os": platform.system(), "when": datetime.now().isoformat(timespec="minutes"),
             "agents": agents, "skills": sk, "harness": hs, "projects": sorted(p["name"] for p in data.get("projects", []))}
      if activity is not None:
          out["activity"] = activity
      return out
  ```
- [ ] Paso 3b: en `src/cabina/cli.py`, en el subparser `export`, agregar:
  ```python
      ex.add_argument("--activity", action="store_true", help="also export session activity (aggregated per project by default)")
      ex.add_argument("--detail", action="store_true", help="with --activity: add per-session rows")
      ex.add_argument("--titles", action="store_true", help="with --activity --detail: add session titles")
      ex.add_argument("--project", action="append", help="with --activity: restrict to this project (repeatable)")
  ```
  y reemplazar el bloque `if a.cmd == "export":` por:
  ```python
      if a.cmd == "export":
          from . import snapshot
          activity = None
          if a.activity:
              try:
                  activity = snapshot.export_activity(cfg, projects=a.project, detail=a.detail, titles=a.titles)
              except ValueError as e:
                  print(f"usage: {e}", file=sys.stderr); return 2
          d = snapshot.export(cfg, activity=activity); txt = json.dumps(d, indent=1, ensure_ascii=False)
          if a.out:
              open(a.out, "w", encoding="utf-8").write(txt)
              print(f"exported {len(d['agents'])} agents, {len(d['skills'])} skills, {len(d['projects'])} projects"
                    + (" + activity" if activity else "") + f" -> {a.out}")
          else:
              print(txt)
          return 0
  ```
- [ ] Paso 4: `python3 -m unittest discover -s tests -p "test_cli.py" -v` → todos en verde.
- [x] Paso 5: `git commit -am "feat: export() embeds activity when given; CLI cabina export --activity/--detail/--titles/--project"`

### Tarea 29: Break-test — `export --activity` nunca filtra cwd/source_path/mtime/size/offset (P1)
**Archivos:** Modificar `tests/test_breaks.py`

Igual que la Tarea 15/17 de Fase 1: el canario tiene que inyectar de verdad un campo local en una
fila y demostrar que `_strip_local_only` lo atrapa — no basta con confirmar que hoy no aparece
(eso solo probaría que nadie lo puso ahí, no que la guardia funciona).

- [ ] Paso 1: test que falla:
  ```python
      def test_export_activity_never_leaks_local_only_guard(self):
          from cabina import snapshot as SNAP
          import json as _json
          env = Env()
          try:
              env.refresh_sessions()
              real_row = SNAP._detail_row
              def leaky_row(s, titles):
                  r = real_row(s, titles)
                  r["cwd"] = s.get("cwd"); r["source_path"] = s.get("source_path")
                  return r
              with mock.patch.object(SNAP, "_detail_row", leaky_row):
                  out = SNAP.export_activity(env.cfg, detail=True)
              self.assertNotIn("cwd", _json.dumps(out))                              # guard present: caught
              with mock.patch.object(SNAP, "_detail_row", leaky_row), \
                   mock.patch.object(SNAP, "_strip_local_only", lambda row: row):
                  out2 = SNAP.export_activity(env.cfg, detail=True)
              self.assertIn(env.alpha, _json.dumps(out2))                            # guard removed -> cwd leaks -> canary red
          finally:
              env.cleanup()
  ```
- [ ] Paso 2: `python3 -m unittest discover -s tests -p "test_breaks.py" -v -k export_activity` →
      `AttributeError: module 'cabina.snapshot' has no attribute '_detail_row'` (ya la resuelve la
      Tarea 27; si se ejecuta en orden, este paso solo confirma que el primer `assertNotIn` pasa
      pero el segundo `assertIn` falla porque `_strip_local_only` real seguía activo por error de
      copy-paste — verificar que el `with` interno de verdad reemplaza ambos).
- [ ] Paso 3: sin cambios de producción — el guard ya existe desde la Tarea 27; este test solo lo
      ejercita de punta a punta con una inyección real (mismo patrón que el canario R8 de Fase 1).
- [ ] Paso 4: `python3 -m unittest discover -s tests -p "test_breaks.py" -v` → todos en verde
      (los 12 anteriores + este).
- [x] Paso 5: `git commit -am "test: break-test — export_activity local-only guard genuinely exercised via injected leak"`

### Tarea 30: `snapshot.compare`/`render_compare` — deltas de actividad entre dos exports (P4)
**Archivos:** Modificar `src/cabina/snapshot.py` · Modificar `tests/test_snapshot.py`

Solo cuando AMBOS exports traen `activity` agregada — si uno de los dos no la tiene (una máquina
corrió `cabina export` sin `--activity`), el comparador simplemente no dice nada de actividad, en
vez de asumir ceros que serían un delta falso.

- [ ] Paso 1: test que falla:
  ```python
  class TestCompareActivity(unittest.TestCase):
      def test_compare_activity_deltas(self):
          a = {"machine": "m1", "agents": [], "skills": [], "projects": [],
               "activity": {"aggregated": [{"project": "alpha", "sessions": 2, "hours": 1.5, "commits": 1}]}}
          b = {"machine": "m2", "agents": [], "skills": [], "projects": [],
               "activity": {"aggregated": [{"project": "alpha", "sessions": 5, "hours": 4.0, "commits": 3}]}}
          r = SNAP.compare(a, b)
          self.assertEqual(r["activity"][0]["sessions"], {"a": 2, "b": 5})
          txt = SNAP.render_compare(r, "m1", "m2")
          self.assertIn("alpha", txt)
  ```
- [ ] Paso 2: `python3 -m unittest discover -s tests -p "test_snapshot.py" -v -k compare_activity` →
      `KeyError: 'activity'`.
- [ ] Paso 3: en `src/cabina/snapshot.py`, en `compare`, agregar antes del `return out` (cambiando
      `return {...}` por `out = {...}` primero):
  ```python
      aa, ab = (a.get("activity") or {}).get("aggregated"), (b.get("activity") or {}).get("aggregated")
      if aa and ab:
          pa2 = {x["project"]: x for x in aa}; pb2 = {x["project"]: x for x in ab}
          out["activity"] = [{"project": p,
                              "sessions": {"a": pa2.get(p, {}).get("sessions", 0), "b": pb2.get(p, {}).get("sessions", 0)},
                              "hours": {"a": pa2.get(p, {}).get("hours", 0), "b": pb2.get(p, {}).get("hours", 0)},
                              "commits": {"a": pa2.get(p, {}).get("commits", 0), "b": pb2.get(p, {}).get("commits", 0)}}
                             for p in sorted(set(pa2) | set(pb2))]
      return out
  ```
  y en `render_compare`, antes del `return "\n".join(out)` final:
  ```python
      if r.get("activity"):
          out.append(f"  activity: sessions/hours/commits, {la} → {lb}")
          for x in r["activity"]:
              out.append(f"     {x['project']:<20} sessions {x['sessions']['a']:>3}→{x['sessions']['b']:<3}  "
                         f"hours {x['hours']['a']:.1f}→{x['hours']['b']:.1f}  commits {x['commits']['a']}→{x['commits']['b']}")
  ```
- [ ] Paso 4: `python3 -m unittest discover -s tests -p "test_snapshot.py" -v` → todos en verde.
- [x] Paso 5: `git commit -am "feat: snapshot.compare/render_compare — activity deltas between two exports when both carry it (P4)"`

### Tarea 31: `hub.py` — `load_dir()`: mezclar N exports con confinamiento y límite de tamaño (P2)
**Archivos:** Modificar `src/cabina/config.py` · Crear `src/cabina/hub.py` · Modificar `tests/test_hub.py`

Analogía: es el archivero que junta las carpetas que cada sucursal mandó por correo — antes de
meter una carpeta al archivero, revisa que de verdad vino de la bandeja de entrada (no de un atajo
que apunta a otro lado), que no pesa más de la cuenta, y que se puede abrir. Una carpeta rota se
marca "ilegible" y se sigue con las demás; no se cierra el archivero entero por una carpeta mala.

- [ ] Paso 1: cuatro tests que fallan (agregar a `tests/test_hub.py`, creado en la Tarea 26):
  ```python
  import json, os, tempfile, unittest
  from cabina import hub as HUB

  class TestHubLoadDir(unittest.TestCase):
      def test_hub_lists_sessions_from_multiple_exports(self):
          with tempfile.TemporaryDirectory() as d:
              open(os.path.join(d, "m1.json"), "w").write(json.dumps({"cabina": 1, "machine": "m1", "os": "macOS", "when": "x",
                  "agents": [], "skills": [], "harness": [], "projects": ["alpha"],
                  "activity": {"aggregated": [{"project": "alpha", "sessions": 2, "hours": 1.0}]}}))
              open(os.path.join(d, "m2.json"), "w").write(json.dumps({"cabina": 1, "machine": "m2", "os": "Linux", "when": "y",
                  "agents": [], "skills": [], "harness": [], "projects": ["alpha"],
                  "activity": {"aggregated": [{"project": "alpha", "sessions": 3, "hours": 2.0}]}}))
              out = HUB.load_dir(d, 5)
              self.assertEqual(len(out["files"]), 2)
              self.assertTrue(all(f["status"] == "ok" for f in out["files"]))
              machines = {row["machine"] for row in out["merged"]["activity"]["aggregated"]}
              self.assertEqual(machines, {"m1", "m2"})

      def test_hub_rejects_symlink_escaping_dir(self):
          with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as outside:
              secret = os.path.join(outside, "secret.json")
              open(secret, "w").write(json.dumps({"machine": "evil", "agents": [{"name": "leaked"}], "skills": [], "harness": [], "projects": []}))
              os.symlink(secret, os.path.join(d, "escape.json"))
              out = HUB.load_dir(d, 5)
              self.assertEqual(out["files"][0]["status"], "outside")
              self.assertEqual(out["merged"]["agents"], [])

      def test_hub_skips_oversized_file(self):
          with tempfile.TemporaryDirectory() as d:
              open(os.path.join(d, "big.json"), "w").write(json.dumps({"machine": "m1", "agents": [], "skills": [], "harness": [], "projects": [], "pad": "x" * 2000}))
              out = HUB.load_dir(d, max_mb=0.001)          # ~1 KB cap, file is bigger
              self.assertEqual(out["files"][0]["status"], "too-large")

      def test_hub_marks_corrupt_json_as_unreadable_without_crashing(self):
          with tempfile.TemporaryDirectory() as d:
              open(os.path.join(d, "bad.json"), "w").write("{not valid json")
              open(os.path.join(d, "good.json"), "w").write(json.dumps({"machine": "m1",
                  "agents": [{"name": "x", "project": "p", "tool": "claude", "category": "valid", "model": "sonnet", "uses": 1}],
                  "skills": [], "harness": [], "projects": ["p"]}))
              out = HUB.load_dir(d, 5)
              statuses = {f["name"]: f["status"] for f in out["files"]}
              self.assertEqual(statuses["bad.json"], "unreadable")
              self.assertEqual(statuses["good.json"], "ok")
              self.assertEqual(out["merged"]["agents"][0]["machine"], "m1")

  if __name__ == "__main__":
      unittest.main()
  ```
- [ ] Paso 2: `python3 -m unittest discover -s tests -p "test_hub.py" -v` →
      `ModuleNotFoundError: No module named 'cabina.hub'`.
- [ ] Paso 3a: en `src/cabina/config.py`, en `DEFAULTS`, agregar (junto a `"activity"`):
      `"hub": {"max_file_mb": 5},`
- [ ] Paso 3b: crear `src/cabina/hub.py`:
  ```python
  """cabina hub — lee N archivos de `cabina export --activity` de una carpeta compartida y sirve
  la MISMA UI (static/index.html) sobre su mezcla. Read-only por diseño (R10): HubApp (definida
  aquí también) no tiene NINGUNA ruta de escritura."""
  import json, os


  def _confined(real_path, real_dir):
      """Guard (R10): una ruta resuelta cuenta como 'adentro' de real_dir solo si es igual o cae
      bajo él. Aislado como función propia (no inline) para que un break-test pueda desactivarlo
      sin tocar os.path.realpath en sí."""
      return real_path == real_dir or real_path.startswith(real_dir + os.sep)


  def load_dir(dir_, max_mb=5):
      """Archivos *.json DIRECTAMENTE bajo dir_ (no recursivo). Cada archivo: confinado por
      realpath a dir_ (un symlink que escapa -> status "outside"), tope de tamaño max_mb MB (->
      "too-large"), json.loads envuelto por archivo (-> "unreadable"). Un archivo malo nunca
      aborta a los demás. Devuelve {files: [...], merged: {agents, skills, projects, harness,
      activity}}."""
      real_dir = os.path.realpath(dir_)
      files, agents, skills, harness = [], [], [], []
      projects_set, agg_by_key, detail_rows, has_detail = set(), {}, [], False
      if os.path.isdir(dir_):
          for name in sorted(os.listdir(dir_)):
              if not name.endswith(".json"):
                  continue
              path = os.path.join(dir_, name)
              entry = {"name": name, "machine": None, "os": None, "when": None, "status": "ok"}
              real_path = os.path.realpath(path)
              if not _confined(real_path, real_dir):
                  entry["status"] = "outside"; files.append(entry); continue
              try:
                  size = os.path.getsize(real_path)
              except OSError as e:
                  entry["status"] = "unreadable"; entry["error"] = str(e); files.append(entry); continue
              if size > max_mb * 1024 * 1024:
                  entry["status"] = "too-large"; files.append(entry); continue
              try:
                  with open(real_path, encoding="utf-8") as f:
                      d = json.load(f)
              except Exception as e:
                  entry["status"] = "unreadable"; entry["error"] = str(e); files.append(entry); continue
              machine = d.get("machine") or name
              entry["machine"], entry["os"], entry["when"] = machine, d.get("os"), d.get("when")
              files.append(entry)
              for a in d.get("agents") or []: agents.append({**a, "machine": machine})
              for s in d.get("skills") or []: skills.append({**s, "machine": machine})
              for h in d.get("harness") or []: harness.append({**h, "machine": machine})
              for p in d.get("projects") or []: projects_set.add(p)
              act = d.get("activity") or {}
              for row in act.get("aggregated") or []:
                  agg_by_key[(row.get("project"), machine)] = {**row, "machine": machine}
              if act.get("sessions"):
                  has_detail = True
                  for row in act["sessions"]: detail_rows.append({**row, "machine": machine})
      activity = {"sessions": detail_rows} if has_detail else {"aggregated": list(agg_by_key.values())}
      merged = {"agents": agents, "skills": skills, "projects": sorted(projects_set), "harness": harness, "activity": activity}
      return {"files": files, "merged": merged}
  ```
- [ ] Paso 4: `python3 -m unittest discover -s tests -p "test_hub.py" -v` → `Ran 5 tests ... OK`
      (los 4 nuevos + el de la Tarea 26).
- [x] Paso 5: `git commit -am "feat: hub.py — load_dir() merges N exports with realpath confinement and a per-file size cap (P2)"`

### Tarea 32: `hub.HubApp` — servidor de solo lectura + placeholder `__HUB__` (P2, R10)
**Archivos:** Modificar `src/cabina/hub.py`, `src/cabina/server.py`, `src/cabina/static/index.html` · Modificar `tests/test_hub.py`, `tests/test_server.py`

`HubApp` es una clase SEPARADA de `App` — no "`App` con `POSTS` vacío" (R10): no tiene ningún
diccionario `POSTS`, ni ningún método `api_archive`/`api_create`/`api_save_doc`/`api_commit`/
`api_open`/`api_focus`/`api_rescan`. `do_POST` responde 405 siempre, sin mirar nada. El placeholder
`__HUB__` en `index.html` es el mismo mecanismo que `__TOKEN__`/`__LANG__` (Tarea 25 de Fase 1b): el
servidor normal (`App`) lo sustituye por `"0"`, `HubApp` por `"1"` — el JS lo lee más adelante
(Tarea 35) para decidir qué esconder.

- [ ] Paso 1: tests que fallan:
  ```python
  # tests/test_server.py, agregar a TestServer
      def test_index_marks_hub_false(self):
          with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
          self.assertNotIn("__HUB__", html)
          self.assertIn('HUB="0"==="1"', html)
  ```
  ```python
  # tests/test_hub.py, nueva clase
  import threading, urllib.request, urllib.error
  from http.server import ThreadingHTTPServer
  from cabina import config as CFG

  class TestHubServer(unittest.TestCase):
      @classmethod
      def setUpClass(cls):
          cls.dir = tempfile.mkdtemp()
          open(os.path.join(cls.dir, "m1.json"), "w").write(json.dumps({
              "cabina": 1, "machine": "m1", "os": "macOS", "when": "x",
              "agents": [{"name": "rev", "project": "alpha", "tool": "claude", "category": "valid", "model": "sonnet", "uses": 1}],
              "skills": [], "harness": [{"project": "alpha", "level": "partial", "hooks_dead": [], "hooks_broken": []}],
              "projects": ["alpha"],
              "activity": {"aggregated": [{"project": "alpha", "sessions": 1, "hours": 0.5, "tokens": {"in": 1, "out": 1},
                                            "commits": 0, "files_touched": 0, "tool_calls": {}, "agents": {}, "skills": {}}]}}))
          cls.cfg = CFG.load(None)
          cls.app = HUB.HubApp(cls.dir, cls.cfg)
          cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), HUB.make_hub_handler(cls.app))
          cls.port = cls.srv.server_address[1]
          threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
      @classmethod
      def tearDownClass(cls): cls.srv.shutdown()

      def get(self, path):
          with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}") as r: return json.loads(r.read())

      def test_index_marks_hub_true(self):
          with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
          self.assertIn('HUB="1"==="1"', html)

      def test_endpoints_and_404s(self):
          self.assertEqual(len(self.get("/api/hub")["files"]), 1)
          self.assertEqual(self.get("/api/agents")["agents"][0]["machine"], "m1")
          self.assertTrue(self.get("/api/activity")["aggregated"])
          for p in ("/api/live", "/api/docs", "/api/doc", "/api/references", "/api/in-repo"):
              with self.assertRaises(urllib.error.HTTPError):
                  self.get(p)

      def test_post_is_always_405(self):
          req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/rescan", data=b"{}", method="POST")
          try:
              urllib.request.urlopen(req); self.fail("expected 405")
          except urllib.error.HTTPError as e:
              self.assertEqual(e.code, 405)
  ```
- [ ] Paso 2: `python3 -m unittest discover -s tests -p "test_hub.py" -v` →
      `AttributeError: module 'cabina.hub' has no attribute 'HubApp'`; y
      `python3 -m unittest discover -s tests -p "test_server.py" -v -k hub_false` → falla porque
      `__HUB__` no existe todavía en `index.html`.
- [ ] Paso 3a: en `src/cabina/static/index.html`, cambiar
      `const TOKEN="__TOKEN__", LANG="__LANG__";` por
      `const TOKEN="__TOKEN__", LANG="__LANG__", HUB="__HUB__"==="1";`
- [ ] Paso 3b: en `src/cabina/server.py`, en `do_GET`, cambiar
      `html = html.replace("__TOKEN__", app.token).replace("__LANG__", lang)` por
      `html = html.replace("__TOKEN__", app.token).replace("__LANG__", lang).replace("__HUB__", "0")`
- [ ] Paso 3c: en `src/cabina/hub.py`, agregar `import threading, webbrowser` a los imports y,
      al final del archivo:
  ```python
  from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
  from urllib.parse import urlparse, parse_qs
  from .i18n import STRINGS

  STATIC = os.path.join(os.path.dirname(__file__), "static")


  class HubApp:
      """Sin diccionario POSTS, sin métodos api_archive/api_create/api_save_doc/api_commit/
      api_open/api_focus/api_rescan en ninguna parte de esta clase — la AUSENCIA es la guardia (R10)."""
      def __init__(self, dir_, cfg):
          self.dir = dir_
          self.max_mb = (cfg.get("hub") or {}).get("max_file_mb", 5)
          self.lang = cfg["language"] if cfg.get("language") in STRINGS else "en"

      def _merged(self):
          return load_dir(self.dir, self.max_mb)

      def api_hub(self, q=None):
          return {"files": self._merged()["files"]}

      def api_agents(self, q=None):
          m = self._merged()["merged"]
          return {"agents": m["agents"], "projects": m["projects"], "window": None, "codex_present": False}

      def api_skills(self, q=None):
          return {"skills": self._merged()["merged"]["skills"], "window": None}

      def api_projects(self, q=None):
          return {"projects": [{"name": p} for p in self._merged()["merged"]["projects"]]}

      def api_harness(self, q=None):
          m = self._merged()["merged"]
          return {"states": m["harness"], "runlogs": [], "drift": {"codex_present": False}}

      def api_activity(self, q=None):
          act = self._merged()["merged"]["activity"]
          return {"aggregated": act.get("aggregated") or [], "sessions": act.get("sessions") or [], "active_seconds": None}


  def make_hub_handler(app):
      GETS = {"/api/hub": app.api_hub, "/api/agents": app.api_agents, "/api/skills": app.api_skills,
              "/api/projects": app.api_projects, "/api/harness": app.api_harness, "/api/activity": app.api_activity}

      class H(BaseHTTPRequestHandler):
          def log_message(self, *a): pass
          def _json(self, obj, code=200):
              b = json.dumps(obj, ensure_ascii=False).encode()
              self.send_response(code); self.send_header("Content-Type", "application/json; charset=utf-8")
              self.send_header("Content-Length", str(len(b))); self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(b)
          def do_GET(self):
              u = urlparse(self.path)
              if u.path in ("/", "/index.html"):
                  html = open(os.path.join(STATIC, "index.html"), encoding="utf-8").read()
                  html = html.replace("__TOKEN__", "").replace("__LANG__", app.lang).replace("__HUB__", "1")
                  b = html.encode(); self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
                  self.send_header("Content-Length", str(len(b))); self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(b); return
              fn = GETS.get(u.path)
              if not fn: return self._json({"error": "not found"}, 404)
              try: return self._json(fn(parse_qs(u.query)))
              except Exception as e: return self._json({"ok": False, "message": str(e)}, 500)
          def do_POST(self):
              return self._json({"ok": False, "message": "cabina hub is read-only: no write route exists"}, 405)
      return H


  def serve_hub(dir_, cfg, port=None, open_browser=True):
      app = HubApp(dir_, cfg)
      port = port or cfg["server"]["port"]
      srv = ThreadingHTTPServer(("127.0.0.1", port), make_hub_handler(app))   # 127.0.0.1 fijo (R10) — nunca cfg["server"]["host"]
      url = f"http://127.0.0.1:{srv.server_address[1]}/"
      print(f"cabina hub (read-only) at {url}  — {dir_}  (Ctrl-C to stop)")
      if open_browser:
          threading.Timer(0.6, lambda: webbrowser.open(url)).start()
      try:
          srv.serve_forever()
      except KeyboardInterrupt:
          print("\nstopped.")
      return srv
  ```
- [ ] Paso 4: `python3 -m unittest discover -s tests -p "test_hub.py" -v` → `Ran 8 tests ... OK`;
      `python3 -m unittest discover -s tests -p "test_server.py" -v` → todos en verde.
- [x] Paso 5: `git commit -am "feat: hub.HubApp — read-only server over merged exports; __HUB__ placeholder (App=0, HubApp=1) (P2, R10)"`

### Tarea 33: CLI `cabina hub DIR [--port] [--no-open]`
**Archivos:** Modificar `src/cabina/cli.py` · Modificar `tests/test_cli.py`

- [ ] Paso 1: test que falla (imports: agregar `from unittest import mock` si no se agregó ya en
      la Tarea 28):
  ```python
  class TestHubCommand(unittest.TestCase):
      def test_hub_command_calls_serve_hub_with_dir_and_port(self):
          from cabina import cli as CLI
          called = {}
          def fake(dir_, cfg, port=None, open_browser=True):
              called.update(dir=dir_, port=port, open_browser=open_browser)
          with tempfile.TemporaryDirectory() as d:
              with mock.patch("cabina.hub.serve_hub", fake):
                  CLI.main(["hub", d, "--port", "9999", "--no-open"])
          self.assertEqual(called["dir"], d); self.assertEqual(called["port"], 9999); self.assertFalse(called["open_browser"])
  ```
- [ ] Paso 2: `python3 -m unittest discover -s tests -p "test_cli.py" -v -k hub_command` → falla:
      `invalid choice: 'hub'`.
- [ ] Paso 3: en `src/cabina/cli.py`, agregar el subparser junto a los demás:
  ```python
      hb = sub.add_parser("hub", help="serve the UI, read-only, over N `cabina export --activity` files in DIR")
      hb.add_argument("dir"); hb.add_argument("--port", type=int); hb.add_argument("--no-open", action="store_true")
  ```
  y el handler (junto a los otros `if a.cmd == ...:`):
  ```python
      if a.cmd == "hub":
          from . import hub
          hub.serve_hub(a.dir, cfg, port=a.port, open_browser=not a.no_open); return 0
  ```
- [ ] Paso 4: `python3 -m unittest discover -s tests -p "test_cli.py" -v` → todos en verde.
- [x] Paso 5: `git commit -am "feat: cabina hub DIR — CLI entrypoint for the read-only hub server"`

### Tarea 34: Break-tests — el hub nunca escribe, el hub nunca sale de su carpeta (P5)
**Archivos:** Modificar `tests/test_breaks.py`

Dos guardias distintas de R10, cada una con su canario real. La primera prueba que `do_POST` es
INCONDICIONAL (nunca llega a mirar una tabla de rutas), no que hoy nadie definió esa tabla — para
eso, el canario cambia `do_POST` mismo por una versión "como `App`" (que sí consulta una tabla) y
confirma que ESA versión sí dejaría pasar una escritura. La segunda ya se diseñó en la Tarea 31
(`_confined` como función aislada) — acá solo se ejercita como break-test.

- [ ] Paso 1: dos tests que fallan:
  ```python
      def test_hub_no_write_path_guard(self):
          from cabina import hub as HUB, config as CFG
          self.assertFalse(hasattr(HUB.HubApp, "POSTS"))
          for m in ("api_archive", "api_create", "api_archive_skill", "api_save_doc", "api_commit", "api_open", "api_focus", "api_rescan"):
              self.assertFalse(hasattr(HUB.HubApp, m))
          import threading, urllib.request, urllib.error
          from http.server import ThreadingHTTPServer
          with tempfile.TemporaryDirectory() as d:
              app = HUB.HubApp(d, CFG.load(None))
              H = HUB.make_hub_handler(app)
              def run_posts():
                  srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
                  port = srv.server_address[1]
                  threading.Thread(target=srv.serve_forever, daemon=True).start()
                  try:
                      codes = []
                      for path in ("/api/archive", "/api/create", "/api/archive-skill", "/api/save-doc",
                                   "/api/open", "/api/focus", "/api/rescan", "/api/commit"):
                          req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=b"{}", method="POST")
                          try:
                              urllib.request.urlopen(req); codes.append(200)
                          except urllib.error.HTTPError as e:
                              codes.append(e.code)
                      return codes
                  finally:
                      srv.shutdown()
              self.assertEqual(run_posts(), [405] * 8)                                  # guard present: every write route blocked
              leaky_do_post = lambda self: self._json({"ok": True, "message": "SHOULD NEVER HAPPEN"}, 200)
              with mock.patch.object(H, "do_POST", leaky_do_post):
                  self.assertEqual(run_posts(), [200] * 8)                              # guard removed -> canary red

      def test_hub_path_confinement_guard(self):
          from cabina import hub as HUB
          with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as outside:
              secret = os.path.join(outside, "secret.json")
              open(secret, "w").write('{"machine": "evil", "agents": [{"name": "leaked"}], "skills": [], "harness": [], "projects": []}')
              os.symlink(secret, os.path.join(d, "escape.json"))
              out = HUB.load_dir(d, 5)
              self.assertEqual(out["files"][0]["status"], "outside")                     # guard present: rejected
              self.assertEqual(out["merged"]["agents"], [])
              with mock.patch.object(HUB, "_confined", return_value=True):               # guard disabled
                  out2 = HUB.load_dir(d, 5)
              self.assertEqual(out2["files"][0]["status"], "ok")                          # confinement bypassed -> canary red
              self.assertEqual(out2["merged"]["agents"][0]["name"], "leaked")
  ```
- [ ] Paso 2: `python3 -m unittest discover -s tests -p "test_breaks.py" -v -k hub` → falla en el
      `assertFalse(hasattr(...))` o en `ModuleNotFoundError` según el orden de ejecución de tareas
      (si Tareas 31/32 ya están hechas, este paso solo confirma que ambos canarios se ponen rojos
      como se espera).
- [ ] Paso 3: sin cambios de producción — ambas guardias ya existen desde las Tareas 31/32; este
      test las ejercita de punta a punta.
- [ ] Paso 4: `python3 -m unittest discover -s tests -p "test_breaks.py" -v` → todos en verde
      (los 13 anteriores + estos 2 = 15).
- [x] Paso 5: `git commit -am "test: break-tests — hub do_POST is unconditional (P5), hub path confinement genuinely exercised"`

### Tarea 35: UI — modo hub esconde Live/Docs y los botones de crear/reescanear (P3)
**Archivos:** Modificar `src/cabina/static/index.html` · Modificar `tests/test_server.py`

Como no hay corredor de navegador en este repo, la verificación es **estructural** (lee el HTML
servido y confirma con texto/patrones que el código está ahí) — igual que la Tarea 25 de Fase 1b.

- [ ] Paso 1: test que falla:
  ```python
      def test_hub_mode_hides_live_docs_and_write_buttons(self):
          with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
          self.assertIn('["agents","skills","projects","harness","activity"]', html)   # hub-mode VIEWS, sin live/docs
          self.assertIn('HUB?"":', html)                                               # al menos un control de escritura condicionado
  ```
- [ ] Paso 2: `python3 -m unittest discover -s tests -p "test_server.py" -v -k hub_mode_hides` →
      falla, ninguna de las dos cadenas está en el HTML.
- [ ] Paso 3a: en `src/cabina/static/index.html`, cambiar
      `const VIEWS=["agents","live","skills","projects","harness","docs","activity"];` por
      `const VIEWS=HUB?["agents","skills","projects","harness","activity"]:["agents","live","skills","projects","harness","docs","activity"];`
- [ ] Paso 3b: en `renderAgents`, cambiar la línea de `$("filters").innerHTML=...` para que el
      botón "+ Crear" sea condicional:
  ```js
   $("filters").innerHTML=`<input id="q" placeholder="${T("search")}" value="${esc(S.q)}">`+chips.map(([k,l])=>`<button class="chip ${S.chips.has(k)?"on":""}" data-c="${k}">${l}</button>`).join("")+chipFocus()+(HUB?"":`<button class="btn primary" id="btnCreate" style="margin-left:auto">${T("create")}</button>`);
   bindFocus();$("q").oninput=e=>{S.q=e.target.value;renderAgents();};document.querySelectorAll(".chip[data-c]").forEach(c=>c.onclick=()=>{const k=c.dataset.c;S.chips.has(k)?S.chips.delete(k):S.chips.add(k);renderAgents();});
   if(!HUB)$("btnCreate").onclick=()=>{S.mode="create";S.sel=null;renderAgents();renderCreate();};
  ```
- [ ] Paso 3c: en `renderProjects`, hacer lo mismo con "Reescanear":
  ```js
   $("filters").innerHTML=`<span class="muted">${T("projHint")}</span>`+chipFocus()+(HUB?"":`<button class="btn" id="bRescan" style="margin-left:auto" title="${T("rescanT")}">${T("rescan")}</button>`);bindFocus();
   if(!HUB)$("bRescan").onclick=async()=>{toast((await POST("/api/rescan",{})).message);setTimeout(()=>{loadAgents();loadSkills();loadProjs();loadHar();loadDocs();},45000);};
  ```
- [ ] Paso 4: `python3 -m unittest discover -s tests -p "test_server.py" -v` → todos en verde.
- [x] Paso 5: `git commit -am "feat: UI — hub mode hides Live/Docs tabs and the create/rescan buttons (P3)"`

### Tarea 36: UI — esconder el resto de controles de escritura + chip de máquina + banner del hub (P3)
**Archivos:** Modificar `src/cabina/static/index.html` · Modificar `tests/test_server.py`

Los botones "Abrir"/"Archivar"/"Referencias" de Agentes y Skills, y "Abrir carpeta" de Proyectos,
llaman rutas POST que en el hub siempre dan 405 — se esconden también en la UI para no ofrecer un
botón que sabe de antemano que va a fallar. "Enfocar" NO se esconde: es un filtro solo del lado del
cliente (`S.focus`), nunca llama al servidor. Tarea más grande que el resto de Fase 2 por la
cantidad de puntos que toca — ver Concern al final de la sección.

- [ ] Paso 1: test que falla:
  ```python
      def test_hub_mode_hides_remaining_write_buttons_and_has_machine_chip(self):
          with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
          self.assertIn("function mchip", html)
          self.assertIn("function renderHubBanner", html)
  ```
- [ ] Paso 2: `python3 -m unittest discover -s tests -p "test_server.py" -v -k hub_mode_hides_remaining`
      → falla, ninguna de las dos funciones existe.
- [ ] Paso 3a: en `src/cabina/static/index.html`, agregar cerca de `chipFocus()`/`bindFocus()`:
  ```js
  function mchip(x){return x.machine?` <span class="tl">${esc(x.machine)}</span>`:"";}
  ```
- [ ] Paso 3b: en el objeto `S`, agregar `hub:null,` (junto a `activity:null,`).
- [ ] Paso 3c: en `renderAgents`, agregar `${mchip(x)}` al final del `<span class="w">` de cada
      fila (después de `${u}`); en `renderAgentDetail`, cambiar el bloque de acciones:
  ```js
   h+=`<div id="refs"></div><div class="actions">`+(HUB?"":`<button class="btn primary" id="bOpen">${T("openFile")}</button><button class="btn" id="bRefs">${T("refs")}</button><button class="btn danger" id="bArch">${T("archive")}</button>`)+`</div>`;
   $("detail").innerHTML=h;
   if(!HUB){$("bOpen").onclick=async()=>{toast((await POST("/api/open",{path:x.path})).message);};
    $("bRefs").onclick=async()=>{$("refs").innerHTML=`<div class="muted">${T("searching")}</div>`;const r=await GET("/api/references?name="+encodeURIComponent(x.name));$("refs").innerHTML=r.references.length?`<div class="box warn"><b>${T("refsFound",{n:r.references.length,name:esc(x.name)})}</b><ul>${r.references.map(f=>`<li><code>${esc(f)}</code></li>`).join("")}</ul></div>`:`<div class="box info">${T("refsNone")}</div>`;};
    $("bArch").onclick=()=>renderArchive(x,"/api/archive",{name:x.name,project:x.project,tool:x.tool},"agents/"+x.project,renderAgentDetail,loadAgents);}
  ```
- [ ] Paso 3d: en `renderSkillDetail`, el mismo patrón:
  ```js
   h+=`<div id="refs"></div>`+(HUB?"":`<div class="actions"><button class="btn primary" id="bOpen">${T("openFolder")}</button><button class="btn" id="bRefs">${T("refs")}</button><button class="btn danger" id="bArch">${T("archive")}</button></div>`);$("detail").innerHTML=h;
   if(!HUB){$("bOpen").onclick=async()=>{toast((await POST("/api/open",{path:x.path})).message);};
    $("bRefs").onclick=async()=>{$("refs").innerHTML=`<div class="muted">${T("searching")}</div>`;const r=await GET("/api/references?name="+encodeURIComponent(x.name));$("refs").innerHTML=r.references.length?`<div class="box warn"><b>${T("refsFound",{n:r.references.length,name:esc(x.name)})}</b><ul>${r.references.map(f=>`<li><code>${esc(f)}</code></li>`).join("")}</ul></div>`:`<div class="box info">${T("refsNone")}</div>`;};
    $("bArch").onclick=()=>renderArchive(x,"/api/archive-skill",{name:x.name,project:x.project,path:x.path},"skills/"+x.project,renderSkillDetail,loadSkills,x.symlink?T("skArchLink"):T("skArch")+` <code>_archive/&lt;today&gt;/skills/${esc(x.project)}/</code>.`);}
  ```
- [ ] Paso 3e: en `renderProjDetail`, esconder solo "Abrir carpeta" (Enfocar queda):
  ```js
   h+=`<div class="actions"><button class="btn primary" id="bFocus">${S.focus===x.name?T("focusOff"):T("focusOn")}</button>`+(HUB?"":`<button class="btn" id="bFolder">${T("openFolder")}</button>`)+`</div>`;$("detail").innerHTML=h;
   $("bFocus").onclick=()=>{S.focus=S.focus===x.name?null:x.name;renderProjects();renderProjDetail();toast(S.focus?T("focused",{p:S.focus}):T("unfocused"));};
   if(!HUB)$("bFolder").onclick=async()=>{toast((await POST("/api/open",{path:x.path})).message);};
  ```
- [ ] Paso 3f: en `renderHarness`, agregar `${mchip(e)}` dentro del `<span class="w">` de cada fila
      de proyecto (después de la parte de MEM).
- [ ] Paso 3g: agregar el banner del hub, junto a `loadActivity`:
  ```js
  async function loadHub(){if(!HUB)return;S.hub=await GET("/api/hub");renderHubBanner();}
  function renderHubBanner(){if(!HUB||!S.hub)return;let el=$("hubBanner");if(!el){el=document.createElement("div");el.id="hubBanner";
   el.style.cssText="padding:8px 18px;background:var(--slate-soft);color:var(--slate);font-size:12px;border-bottom:1px solid var(--line)";
   document.querySelector(".top").after(el);}
   el.innerHTML=S.hub.files.map(f=>`<span>${esc(f.name)} (${esc(f.machine||"?")}) · ${esc(f.status)}</span>`).join("  ·  ");}
  ```
- [ ] Paso 3h: al final del archivo, cambiar la línea de arranque
      `loadAgents();loadLive();loadSkills();loadProjs();loadHar();loadDocs();loadActivity();setInterval(loadLive,1000);`
      por:
  ```js
  loadAgents();loadSkills();loadProjs();loadHar();loadActivity();loadHub();
  if(!HUB){loadLive();loadDocs();setInterval(loadLive,1000);}
  ```
      (evita que el hub llame `/api/live` y `/api/docs`, que dan 404 ahí — ver "no console errors"
      en la Tarea 39).
- [ ] Paso 4: `python3 -m unittest discover -s tests -p "test_server.py" -v` → todos en verde.
- [x] Paso 5: `git commit -am "feat: UI — hide remaining write buttons in hub mode, machine chip on agent/harness rows, hub banner (P3)"`

### Tarea 37: UI — pestaña Actividad soporta filas agregadas y filas por sesión (P3)
**Archivos:** Modificar `src/cabina/static/index.html` · Modificar `tests/test_server.py`

Cuando el hub mezcla exports sin `--detail`, `/api/activity` no trae `sessions` (solo `aggregated`)
— la pestaña Actividad tiene que poder mostrar ESO también, no asumir siempre que hay filas por
sesión.

- [ ] Paso 1: test que falla:
  ```python
      def test_activity_supports_aggregated_shape(self):
          with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
          self.assertIn("function renderActivityAggregated", html)
  ```
- [ ] Paso 2: `python3 -m unittest discover -s tests -p "test_server.py" -v -k activity_supports` →
      falla, la función no existe.
- [ ] Paso 3: en `src/cabina/static/index.html`, reemplazar `renderActivity` completo por:
  ```js
  function renderActivity(){if(!S.activity){$("rows").innerHTML=`<div class="empty">${T("loading")}</div>`;$("filters").innerHTML="";return;}
   const detail=(S.activity.sessions||[]).length>0;
   if(!detail){renderActivityAggregated();return;}
   const a=S.activity.sessions,activeSecs=S.activity.active_seconds||600,now=Date.now()/1000;
   $("filters").innerHTML=actTimeline(a)+`<input id="q" placeholder="${T("search")}" value="${esc(S.q)}">`+chipFocus();
   bindFocus();$("q").oninput=e=>{S.q=e.target.value;renderActivity();};
   const q=S.q.toLowerCase();let sel=a.filter(x=>{if(S.focus&&x.project!==S.focus)return false;if(q&&!((x.project||"")+" "+(x.title||"")+" "+(x.machine||"")).toLowerCase().includes(q))return false;return true;});
   $("rows").innerHTML=sel.length?sel.map(x=>{const key=x.source_path||(x.project+"|"+x.started+"|"+(x.machine||""));const active=x.mtime&&(now-x.mtime)<activeSecs;
    return `<button class="row ${S.sel===key?"sel":""}" data-k="${esc(key)}"><span class="dot d-${active?"working":"valid"}"></span><span class="n">${esc(x.title||T("untitled"))}${active?` <span class="tl">${T("activeNow",{n:Math.round(now-x.mtime)})}</span>`:""}${mchip(x)}</span><span class="w">${esc(x.project||"—")} · ${Math.round((x.duration_s||0)/60)}m</span></button>`;}).join(""):`<div class="empty">${T("noSessions")}</div>`;
   document.querySelectorAll(".row").forEach(r=>r.onclick=()=>{S.sel=r.dataset.k;renderActivity();});
   $("foot").textContent=T("sessionsFoot",{n:sel.length});
   if(!S.sel)$("detail").innerHTML=`<div class="muted">${T("pickSession")}</div>`;else renderSessionDetail();}
  function renderActivityAggregated(){const a=S.activity.aggregated||[];
   $("filters").innerHTML=`<input id="q" placeholder="${T("search")}" value="${esc(S.q)}">`+chipFocus();bindFocus();
   $("q").oninput=e=>{S.q=e.target.value;renderActivityAggregated();};
   const q=S.q.toLowerCase();let sel=a.filter(x=>{if(S.focus&&x.project!==S.focus)return false;if(q&&!((x.project||"")+" "+(x.machine||"")).toLowerCase().includes(q))return false;return true;});
   $("rows").innerHTML=sel.length?sel.map(x=>{const key=(x.project||"")+"|"+(x.machine||"");
    return `<button class="row ${S.sel===key?"sel":""}" data-k="${esc(key)}"><span class="dot d-valid"></span><span class="n">${esc(x.project||"—")}${mchip(x)}</span><span class="w">${x.sessions||0} · ${(x.hours||0).toFixed(1)}h</span></button>`;}).join(""):`<div class="empty">${T("noSessions")}</div>`;
   document.querySelectorAll(".row").forEach(r=>r.onclick=()=>{S.sel=r.dataset.k;renderActivityAggregated();});
   $("foot").textContent=T("sessionsFoot",{n:sel.length});
   if(!S.sel){$("detail").innerHTML=`<div class="muted">${T("pickSession")}</div>`;return;}
   const x=a.find(y=>(y.project||"")+"|"+(y.machine||"")===S.sel);if(!x)return;
   $("detail").innerHTML=`<div class="h">${esc(x.project||"—")}${mchip(x)}</div><div class="meta"><span>${T("sessCommits")}</span><b>${x.commits||0}</b><span>${T("sessDuration")}</span><b>${(x.hours||0).toFixed(1)}h</b><span>${T("sessTokens")}</span><b>${(x.tokens&&x.tokens.in)||0} / ${(x.tokens&&x.tokens.out)||0}</b></div>`;}
  ```
  y en `renderSessionDetail`, agregar `${mchip(x)}` junto al título:
  `let h=`<div class="h">${esc(x.title||T("untitled"))}${mchip(x)}</div>...`
- [ ] Paso 4: `python3 -m unittest discover -s tests -p "test_server.py" -v` → todos en verde.
- [x] Paso 5: `git commit -am "feat: UI — Activity tab renders aggregated (project x machine) rows when no per-session detail exists (P3)"`

### Tarea 38: Test estructural — los campos de Actividad/hub siempre pasan por `esc()` (R10, XSS)
**Archivos:** Modificar `tests/test_server.py`

No hay corredor de navegador en este repo (sin dependencias de test nuevas — ver Concern), así que
la prueba práctica es de código fuente: una expresión regular que agarra cada bloque `${...}` de la
sección de Actividad y confirma que, si menciona `x.title`/`x.project`/`x.machine`/`x.branch`,
`esc(` aparece dentro de ESE mismo bloque. Distingue interpolación real (riesgo de XSS) de un
simple `if(x.machine?...)` de JS plano, que no se renderiza como HTML y no necesita `esc()`.

- [ ] Paso 1: test que falla:
  ```python
      def test_activity_and_hub_fields_always_escaped(self):
          with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
          import re
          start = html.index("// ---------- ACTIVITY ----------")
          end = html.index("// ---------- PROJECTS ----------")
          body = html[start:end]
          pattern = re.compile(r"\$\{([^{}]*\bx\.(?:title|project|machine|branch)\b[^{}]*)\}")
          hits = list(pattern.finditer(body))
          self.assertGreater(len(hits), 0)                    # sanity: the section actually interpolates these fields
          for m in hits:
              self.assertIn("esc(", m.group(1), f"unescaped interpolation: ${{{m.group(1)}}}")
  ```
- [ ] Paso 2: `python3 -m unittest discover -s tests -p "test_server.py" -v -k always_escaped` →
      pasa o falla según si Tareas 36/37 ya dejaron todo envuelto en `esc()` — si falla, es una
      interpolación real sin escapar que hay que corregir antes de seguir (no se toca este test
      para hacerlo pasar; se corrige `index.html`).
- [ ] Paso 3: sin cambios de producción esperados si las Tareas 36/37 se siguieron al pie de la
      letra; si el test encuentra un caso sin `esc()`, envolverlo ahí mismo en `index.html`.
- [ ] Paso 4: `python3 -m unittest discover -s tests -p "test_server.py" -v` → todos en verde.
- [x] Paso 5: `git commit -am "test: structural esc() guard over the Activity/hub section of index.html (R10, XSS)"`

### Tarea 39: Verificación manual — export real + hub sobre dos archivos
**Archivos:** ninguno (verificación, no código)

- [ ] Paso 1: `PYTHONPATH=src python3 -m cabina export --activity --detail -o /tmp/m1.json` en esta
      máquina (después de haber usado Claude Code acá al menos una vez, para que `sessions.json`
      tenga algo real).
- [ ] Paso 2: copiar `/tmp/m1.json` a `/tmp/m2.json` y editarle a mano el campo `"machine"` (simula
      una segunda máquina sin necesitar una de verdad).
- [ ] Paso 3: `PYTHONPATH=src python3 -m cabina hub /tmp` — abre el navegador; confirmar: no aparecen
      las pestañas Live/Docs, aparece un chip de máquina en las filas de Agentes/Actividad, el
      banner del hub lista los dos archivos como "ok", la pestaña Actividad muestra filas por sesión
      (porque el export se hizo con `--detail`).
- [ ] Paso 4: abrir la consola del navegador (skill `run` si hace falta) — confirmar CERO errores
      (en particular, que no se llame `/api/live` ni `/api/docs`, que darían 404 en el hub).
- [ ] Paso 5: — (verificación manual, sin commit).

---

## Enmiendas aplicadas durante la ejecución (Fase 2)

Registro de lo que cambió respecto al texto original de las Tareas 26-39, con su commit:

- `5ae57b5` — `export()` incluye `projects_detail` (P6; resuelve Concern 2 de esta fase).
- `4ed2b0e` — `export --detail` nunca lleva rutas absolutas en `files_touched`; las cuenta como `files_outside` (P7).
- `979ce74` — `export_activity` refresca el registro de sesiones antes de leerlo (una máquina nueva exportaba vacío).
- `7bdebfe` — el hub conserva agregados Y filas por sesión de todas las máquinas; fusiona `projects_detail`.
- `c68859d` — `sessKey` compartido entre lista y detalle de Actividad (el detalle buscaba por `source_path`, que el export no lleva); máquinas solo-agregado se muestran como filas no clicables.
- `d1e1766` — break-tests extra: tope de tamaño y aislamiento por archivo del hub.
- `11b7355` — el hub ignora archivos no regulares (`not-a-file`): un FIFO en la carpeta compartida colgaba todos los endpoints.
- `6132ce2` — limitación declarada: los hardlinks escapan al confinamiento por `realpath`.
- `84d0904` — caché del hub hasta que cambie algún archivo de DIR.
- `4fe2f80` — el detalle de agente en modo hub no revienta; el export lleva `critical`/`warnings`/`desc`.
- `cbaae03` — detalle de proyecto en hub indexado por nombre+máquina.
- Tarea 39 (verificación manual) ejecutada por el orquestador en Chrome con dos máquinas, un archivo corrupto, un symlink que escapa y título/rama envenenados con `<img onerror>`: sin XSS, sin errores de consola.

# Concerns (Fase 2)

1. **Tarea 36 es más grande que el resto.** Toca seis puntos distintos de `index.html`
   (Agentes, Skills, Proyectos, Harness, banner nuevo, arranque). Se mantuvo como una sola tarea
   por cohesión (todo es "esconder controles de escritura + mostrar de dónde vino cada fila"), pero
   si al ejecutarla resulta pesada, se puede partir en 2-3 sub-tareas por vista sin perder nada.
2. **`HubApp.api_projects` es deliberadamente pobre.** `export()` solo guarda una lista de NOMBRES
   de proyecto (`data.get("projects", [])` → strings), no el detalle rico que sirve `App.api_projects`
   (rama, dirty, worktrees, docs...). El hub no puede mostrar eso porque el export nunca lo llevó.
   La pestaña Proyectos en modo hub queda utilizable pero visualmente más pobre que en modo normal
   — no se resolvió porque el brief no pidió enriquecer `export()` con esos campos, y hacerlo sería
   ampliar el alcance de Fase 2 sin que se haya pedido.
3. **El test de XSS (Tarea 38) sigue siendo estructural, no ejecución real de navegador**, igual que
   ya advertía R10/Concern 5 de Fase 1b — ver "Preguntas abiertas" más abajo.
4. **`--titles` sin `--detail` en el CLI (Tarea 28) no tiene un test dedicado a nivel CLI** — solo
   se prueba a nivel de `snapshot.export_activity` (Tarea 27). El CLI reusa el mismo `ValueError`
   como única fuente de verdad (evita duplicar la regla en dos lugares), así que cubrirlo en
   `snapshot.py` cubre la lógica real; falta solo el "cableado" (exit code 2, mensaje a stderr).
5. **El banner del hub (Tarea 36) no tiene test de contenido**, solo se confirma que la función
   existe en el HTML servido (estructural, como el resto de esta fase). Su comportamiento real solo
   se confirma en la Tarea 39 (verificación manual).
6. **`HubApp` no valida que `cfg["hub"]["max_file_mb"]` sea un número positivo** — un valor negativo
   o cero en un `.cabina.toml` a mano haría que TODO archivo cuente como "too-large". No se agregó
   validación porque `config.py` hoy no valida ningún otro valor numérico (mismo criterio que el
   resto del archivo).

# Preguntas abiertas (Fase 2)

- ¿El test estructural de XSS (Tarea 38) alcanza, o el equipo quiere sumar un runner de navegador
  real (Playwright) — la primera dependencia de solo-test del proyecto? Sigue siendo la misma
  pregunta que R10/Concern 5 de Fase 1b dejó abierta; Fase 2 no la resuelve, solo la hereda.
- ¿Vale la pena enriquecer `export()` (agregar rama/dirty/worktrees por proyecto) para que
  `HubApp.api_projects` deje de ser tan pobre (Concern 2), o el hub se queda deliberadamente
  centrado en agentes/skills/harness/actividad y Proyectos es una vista secundaria ahí?
- ¿El banner del hub (Tarea 36) debería poder colapsarse/cerrarse, o para el tamaño típico (2-5
  máquinas de equipo) una línea fija alcanza?

# Fase 3 — salud en el tiempo: health.jsonl, sparkline, tablero de proyectos (checklist, R12/R13)

- [ ] **`healthlog.py` (nuevo módulo)**: `append(cfg, findings)` — **un solo `write()` por línea**
      (R12: nunca reconstruir el archivo entero para agregar una línea), con
      `{when, crit, warn, info}`. Se agrega una línea solo si `(crit, warn, info)` difiere de la
      última línea guardada **O** la última línea tiene más de 24 h — así un `cabina check` corrido
      dos veces seguidas con el mismo resultado no duplica renglones, pero tampoco deja pasar más
      de un día sin dejar constancia aunque nada haya cambiado. Poda a
      `cfg["check"]["history_days"]` (default 180) con `tmp+os.replace`, mismo patrón que
      `docs.py::_prune`. Tests: `tests/test_healthlog.py::test_append_writes_first_line`,
      `::test_append_skips_when_unchanged_and_recent`, `::test_append_writes_even_if_unchanged_after_24h`,
      `::test_prune_keeps_newest_lines_via_tmp_replace`.
- [ ] **`check.py`**: `run()` (o `cli.py` después de imprimir — decidir en la tarea real cuál capa
      es dueña) llama `healthlog.append(cfg, F)`.
- [ ] **Break-test** (`tests/test_breaks.py`) — "health.jsonl append-only / no rewrite" (R12): con
      `mock.patch.object` desactivar la condición "solo si cambió o pasaron 24h" y confirmar que
      dos llamadas seguidas con los MISMOS conteos producen dos líneas en vez de una; por separado,
      desactivar la poda por `history_days` y confirmar que el archivo crece sin límite en vez de
      recortarse.
- [ ] **`server.py`**: `GET /api/health-history` — lee `health.jsonl`, devuelve la serie para la
      sparkline.
- [ ] **UI**: sparkline (mismo patrón SVG que la Tarea 25 de Fase 1b) en la pestaña Projects,
      leyendo `/api/health-history`.
- [ ] **"Tablero de proyectos" (R13, ahora definido)**: TILES de solo lectura por proyecto —
      `{last_session, health (crit/warn/info), active/idle (misma señal aditiva de la Tarea 20/21),
      open_findings_count}`. Explícitamente NADA de estados tipo tarea, asignados, ni texto de
      tareas — no es un Kanban, es un resumen de una sola mirada. Vive como una vista dentro de la
      pestaña Projects existente (tiles arriba de la lista actual), no como pestaña nueva. Tests:
      `tests/test_server.py::test_project_tiles_shape`, y un test de UI estructural (mismo estilo
      que el de XSS de Fase 2) confirmando que ningún campo de texto libre tipo "tarea" se agregó
      por error.

---

# Fase 4 — usage incremental: dejar de releer 1.4 GB por cada "cabina agents" (H2 raíz)

## Contexto y medición

`src/cabina/usage.py` responde "¿qué tanto se usó este agente/skill?" cada vez que alguien corre
`cabina agents`, abre la UI (`server.py::api_skills`, `App.roster()`), o consulta por MCP. Para
responder, `extract()`/`refresh()` no llevan ninguna cuenta de lo que ya leyeron: cada llamada
grepea (`grep -rhF <needle> --include=*.jsonl`, con un fallback en Python puro para Windows) **todo**
`~/.claude/projects` de arriba a abajo, de nuevo, sin memoria de la corrida anterior. Es como si cada
vez que alguien preguntara "¿cuántas veces se usó el archivero X?" la respuesta fuera ir a la bodega
y releer expediente por expediente desde la primera página — en vez de mirar el separador de
página (el "bookmark") que se dejó la última vez y leer solo lo que se agregó después. Medido sobre
el entorno real de Danny (1.4 GB, 2 044 archivos `.jsonl`): 8.6-11 segundos por llamada.

`sessions.py` (Fase 1, Tarea 10/17) ya resolvió exactamente este problema para el mismo directorio:
un registro en `<state_dir>/sessions.json` guarda, por archivo fuente, el `offset` de bytes ya
leídos, así que `refresh()` solo procesa lo nuevo desde la última corrida — medido, 0.09 segundos.
La diferencia de dos órdenes de magnitud no es casualidad: es la MISMA idea (bookmark de bytes) que
`usage.py` nunca adoptó porque se escribió antes, en la Fase original del proyecto. Este plan lleva
esa misma idea a `usage.py`, sin heredar sus tests ni su alcance — son problemas hermanos, no el
mismo problema.

## Decisión de diseño

Tres formas de cerrar esto, de la más simple (y descartada) a la recomendada:

- **Opción B — derivar `usage` de `sessions.json` en vez de releer las transcripciones.**
  `sessions.py` ya extrae, por sesión, cuántas veces se invocó cada agente/skill
  (`state["agents"]`/`state["skills"]`, Tarea 12) con el proyecto ya atribuido. En teoría `usage`
  podría sumarse desde ahí sin abrir un solo `.jsonl` más. **Descartada** por tres razones
  concretas: (1) `sessions.py` solo recorre `<claude_home>/projects/<enc>/<sessionId>.jsonl` — a
  propósito NO entra a las carpetas `subagents/` (R3: "un subagente nunca es una sesión por sí
  sola"), pero el `grep` recursivo de `usage.py` HOY sí las escanea, así que invocaciones de
  agentes hechas dentro de un subagente se contarían hoy y se perderían con esta opción — una
  regresión silenciosa de alcance, no solo de rendimiento; (2) `sessions.json` se poda por
  `activity.retention_days` (default 365) porque para la pestaña Actividad "sesión vieja" no
  importa — pero `usage.py` tiene la garantía contraria, ACUMULAR fechas para siempre sin
  regresión (rule (a) de este encargo); derivar de un archivo que se poda exigiría un acumulador
  paralelo alimentado en cada `sessions.refresh()`, es decir, la MISMA cantidad de código nuevo que
  la Opción A pero con el acoplamiento añadido de depender de la forma interna de otro módulo; (3)
  hoy nada llama a `sessions.refresh()` desde `cabina agents`/`roster.py` — habría que añadir esa
  llamada igual, así que el ahorro de "una sola lectura" no es gratis, es una integración nueva.
- **Opción C — filtrar por `mtime` sin offset real (releer completo solo los archivos que
  cambiaron).** Más simple que A, pero insuficiente: un archivo de sesión activo crece durante
  horas y con esta opción se releería completo en cada refresh mientras esté "tocado" — exactamente
  el patrón que un usuario con una sesión larga golpea más. No resuelve el H2 raíz, solo lo
  atenúa.
- **Opción A (RECOMENDADA) — `usage.py` lleva su propio bookmark de bytes, igual que
  `sessions.py`, pero independiente.** Nuevo registro `<state_dir>/usage-history.json`, clave
  `source_path`, con `{offset, size, mtime, agents, skills}` — donde `agents`/`skills` son los
  conteos (`{name: {"n": int, "by_project": {...}}}`) que ESE archivo aportó hasta ahora. En cada
  refresh: leer solo los bytes nuevos desde `offset` (reutilizando la MISMA lógica de
  `_read_new_lines` que ya existe en `sessions.py`, línea por línea, nunca una línea a medias),
  recalcular los conteos de ese archivo, y sumar al acumulador global la DIFERENCIA entre los
  conteos nuevos y los que ya se habían guardado para ese archivo — no el conteo bruto. Por qué la
  resta y no la suma directa del delta de líneas: si un archivo se trunca o se reescribe (caso raro
  pero cubierto, mismo criterio que Tarea 17: `size < offset` ⇒ reparsear desde cero), sin la resta
  se contarían dos veces las invocaciones que ya estaban adentro antes del truncado. Con la resta,
  el archivo simplemente "corrige" su propio aporte al total, sin tocar el de los demás.
  Sencillo en la analogía: cada archivo tiene su propia notita de "yo ya aporté 7 usos de
  `code-reviewer`"; si se relee de cero y ahora aporta 5, el total baja en 2 — no se duplica nada.
  Es más código que la Opción B, pero cada pieza es acotada, no depende de la forma interna de
  `sessions.py`, y preserva EXACTO el alcance de hoy (incluye `subagents/`, needles idénticos).
  **Consecuencia necesaria:** `merge()` deja de ser "quedarse con el máximo" (`max(n_total, n)`,
  correcto solo cuando `fresh` es un recuento total de una relectura completa) y pasa a ser "sumar
  el delta" (correcto cuando `fresh` es incremental) — un cambio de contrato interno de `merge`,
  detallado en la Tarea 42. La garantía de fechas nunca-regresan (rule (a), break-test existente)
  no cambia: sigue siendo `max(last_previo, last_nuevo)`, ajena a este cambio.

Con offsets reales por archivo, el `grep` externo (y su fallback Windows) deja de aportar nada: ya
no se busca un texto en un directorio completo, se abren archivos puntuales y se leen bytes
puntuales. La Tarea 43 elimina `_lines()` y unifica todo en un solo camino Python, sin rama
POSIX/Windows — constraint (e) resuelta por diseño, no por decisión adicional.

**Enmienda tras revisión adversarial (2026-08-18):** el diseño original de la Tarea 43 tenía un bug
bloqueante: `usage.py` alimenta DOS salidas (`usage-agents.json` vía `kind="agents"`,
`usage-skills.json` vía `kind="skills"`) desde los MISMOS `.jsonl`, con una sola línea base
compartida por archivo en `usage-history.json`. Si el pase `agents` avanza esa línea base primero,
el pase `skills` que llega después sobre el mismo archivo ve un delta de cero bytes y pierde esas
invocaciones de skill para siempre — no hay una segunda oportunidad de leerlas. La corrección
(Tarea 43 reescrita abajo): cada llamada a `refresh()`, sin importar `kind`, hace UNA sola pasada
por los bytes nuevos de cada archivo, extrae agentes Y skills a la vez, y actualiza AMBOS registros
de salida en la misma llamada — la línea base compartida siempre refleja lo ya aplicado a los dos.
`kind` deja de decidir qué se procesa; solo decide cuál de los dos resultados devolver.

### Tarea 40: Fixtures — transcripciones sintéticas para probar offset, truncado y alcance de subagentes
**Archivos:** Modificar `tests/_env.py`

- [x] Paso 1: `tests/_env.py` no tiene hoy ningún helper para "hacer crecer" o "truncar" un archivo
      de historial de USO (el que existe, `touch_session`, solo cambia `mtime`, no contenido) — un
      test que llame a un método `env.grow_usage_history(...)` inexistente falla con
      `AttributeError`.
- [x] Paso 2: confirmar el `AttributeError` con
      `python3 -m unittest discover -s tests -p "test_usage.py" -v` (test nuevo de la Tarea 41
      referenciándolo).
- [x] Paso 3: agregar a `Env`: (a) `append_usage_line(text)` — escribe una línea `.jsonl` más al
      archivo de historial ya existente (`-x/s.jsonl`), simulando una sesión que sigue creciendo
      entre dos corridas de `refresh()`; (b) `truncate_usage_history(new_content)` — reemplaza el
      contenido completo del mismo archivo por algo más chico, simulando rotación/reescritura; (c)
      un archivo NUEVO bajo `<claude_home>/projects/-x/<sid>/subagents/sub.jsonl` con una línea que
      contiene `"subagent_type":"nested-from-subagent"` — preserva el caso "un subagente invoca
      otro agente", que hoy el grep recursivo de `usage.py` sí cuenta y la Fase 4 no debe perder;
      (d) exponer el atributo `self.usage_history_file` (el path del `.jsonl` principal, `-x/s.jsonl`)
      para que otras tareas (la 44, la 47) lo referencien directo en vez de reconstruir la ruta a
      mano — mismo criterio que `self.session_file` ya usa el resto de `Env`.
- [x] Paso 4: `python3 -m unittest discover -s tests -p "test_usage.py" -v` → verde una vez escrita
      la Tarea 41 (esta tarea sola no tiene aserciones propias, solo prepara el terreno).
- [x] Paso 5: `git add tests/_env.py && git commit -m "test: _env.py — fixtures de usage incremental (crecimiento, truncado, invocación anidada en subagents/)"`

### Tarea 41: `usage._read_new_lines` + `_scan_file`: extracción de agentes y skills en una sola pasada por archivo
**Archivos:** Modificar `src/cabina/usage.py`, `tests/test_usage.py`

Duplicar (no importar) el lector de bytes-por-offset de `sessions.py`: importar `sessions` desde
`usage` crearía un ciclo (`sessions.py` ya hace `from . import scan, usage`). Son ~10 líneas y solo
dos sitios de uso — por la regla propia de YAGNI/DRY ("extraer duplicación solo con 3+ repeticiones
reales"), duplicar acá es la decisión correcta, no un descuido. `_scan_file` es la pieza que hace
posible la línea base COMPARTIDA entre `agents` y `skills` (ver la enmienda arriba): siempre extrae
ambos needles de las mismas líneas nuevas, nunca solo uno.

- [x] Paso 1: test que falla:
  ```python
  def test_scan_file_extracts_both_needles_in_one_pass(self):
      with tempfile.TemporaryDirectory() as d:
          p = os.path.join(d, "f.jsonl")
          open(p, "w").write(
              '{"timestamp":"2026-08-01","cwd":"/x","subagent_type":"reviewer"}\n'
              '{"timestamp":"2026-08-01","cwd":"/x","name":"Skill","input":{"skill":"deploy"}}\n')
          agents, skills, new_offset = U._scan_file(p, 0, roots={})
          self.assertEqual(agents["reviewer"]["n"], 1)
          self.assertEqual(skills["deploy"]["n"], 1)
          self.assertGreater(new_offset, 0)
  ```
- [x] Paso 2: `python3 -m unittest discover -s tests -p "test_usage.py" -v` →
      `AttributeError: module 'cabina.usage' has no attribute '_scan_file'`.
- [x] Paso 3: en `usage.py`, agregar `_read_new_lines` (copia literal de la de `sessions.py`) y
      `_scan_file(path, offset, roots)`: lee las líneas nuevas, corre `_AGENT` Y `_SKILL` sobre
      CADA línea en la misma pasada (misma lógica que `extract()` hoy, sin el needle-prefiltro de
      `grep` porque ya no hace falta), devuelve `(agents_delta, skills_delta, new_offset)` con la
      MISMA forma de entrada que `extract()` devuelve hoy (`{name: {"n", "last", "by_project"}}`) —
      pero acá representa solo lo leído en ESTA pasada, no un total. Nunca se llama a `_scan_file`
      pidiendo solo un needle: siempre devuelve los dos.
- [x] Paso 4: `python3 -m unittest discover -s tests -p "test_usage.py" -v` → `OK`.
- [x] Paso 5: `git commit -am "feat: usage.py — _read_new_lines + _scan_file, extraccion de agentes y skills en una sola pasada"`

### Tarea 42: Registro por archivo (`usage-history.json`) y `merge()` pasa de máximo a suma de deltas
**Archivos:** Modificar `src/cabina/usage.py`, `tests/test_usage.py`, `tests/test_breaks.py`

El corazón del diseño: cada entrada de `usage-history.json` guarda, además de `offset/size/mtime`,
los conteos que ESE archivo aportó la última vez (`"agents"`, `"skills"` — los DOS siempre, nunca
uno solo, porque `_scan_file` de la Tarea 41 los extrae juntos). En cada refresh se recalculan los
conteos de ese archivo (desde `offset` si creció, desde cero si se truncó) y se suma al acumulador
global la diferencia contra lo guardado — nunca el conteo bruto de la pasada.

**Limitación conocida (`by_project` y cambio de `roots`):** el delta se suma al proyecto que
`_project_of(cwd, roots)` resuelve EN EL MOMENTO del refresh. Si los `roots` de la config cambian
después (un proyecto se renombra, se mueve, o dos proyectos se fusionan) y el mismo `cwd` empieza a
resolver a otro nombre de proyecto, el aporte YA SUMADO bajo el proyecto anterior no se reasigna
retroactivamente — queda "pegado" al nombre viejo dentro de `by_project`, aunque los refresh futuros
sí acumulen correctamente bajo el nombre nuevo. El remedio es manual y exacto, no automático:
`rm <state_dir>/usage-history.json` (y opcionalmente `usage-agents.json`/`usage-skills.json` si se
quiere también limpiar el acumulado histórico) fuerza un recuento completo desde cero con los
`roots` vigentes. No se automatiza porque detectar "cuándo cambiaron los roots de forma relevante"
es justamente el tipo de heurística frágil que este proyecto evita (ver "Guards" en CLAUDE.md: mide
y avisa, no repara solo).

- [x] Paso 1: tests que fallan:
  ```python
  def test_accumulates_across_two_incremental_refreshes(self):
      # dos refresh() sucesivos con una línea nueva en medio deben SUMAR, no promediar ni pisar
      env = Env(); items1, _ = U.refresh(P, HIST, "agents", ROOTS)
      env.append_usage_line('{"timestamp":"2026-08-05","cwd":"...", "subagent_type":"reviewer"}')
      items2, _ = U.refresh(P, HIST, "agents", ROOTS)
      self.assertEqual(items2["reviewer"]["n_total"], items1["reviewer"]["n_total"] + 1)

  def test_truncated_file_does_not_double_count(self):
      env = Env(); U.refresh(P, HIST, "agents", ROOTS)
      env.truncate_usage_history(SHORTER_CONTENT_WITH_ONE_HIT)
      items, _ = U.refresh(P, HIST, "agents", ROOTS)
      self.assertEqual(items["reviewer"]["n_total"], 1)     # no se suma lo viejo + lo nuevo
  ```
  Break-test en `tests/test_breaks.py` (junto a `test_usage_never_regresses`, que sigue intacto):
  ```python
  def test_usage_history_diff_guard(self):
      # si el registro por archivo se ignorara (se sumara el conteo bruto en vez del delta),
      # una relectura completa del mismo archivo duplicaría el conteo
      with mock.patch.object(U, "_file_delta", lambda new, old: new):   # guard disabled: delta = new, ignora old
          out = U._accumulate({"reviewer": {"n_total": 7}}, {"reviewer": {"n": 7}})   # ya se había contado
          self.assertEqual(out["reviewer"]["n_total"], 14)                             # duplicado -> canary red
      out2 = U._accumulate({"reviewer": {"n_total": 7}}, {"reviewer": {"n": 7}})       # guard presente
      self.assertEqual(out2["reviewer"]["n_total"], 7)                                 # sin cambio: ya estaba contado
  ```
- [x] Paso 2: `AttributeError: module 'cabina.usage' has no attribute '_accumulate'` /
      `'_file_delta'`.
- [x] Paso 3: agregar `_file_delta(new_counts, old_counts)` (resta por clave, nunca negativo hacia
      fechas) y `_accumulate(registry_items, delta)` (aplica el delta al acumulador global,
      preservando el `max()` SOLO para `last`, y suma para `n_total`/`by_project`); reescribir
      `merge()` para usarlos por dentro sin romper su firma pública. Nombres FIJOS para leer/escribir
      `usage-history.json` (los usan las Tareas 43/44 tal cual, sin inventar variantes):
      `_load_history(path)` (tolera archivo ausente/corrupto, devuelve `{}`) y
      `_save_history(path, registry)` (mismo patrón `tmp` + `os.replace` que `save()`).
- [x] Paso 4: `python3 -m unittest discover -s tests -p "test_usage.py" -v` y
      `-p "test_breaks.py"` → ambos verdes.
- [x] Paso 5: `git commit -am "feat: usage.py — registro por archivo con diff, merge() acumula deltas en vez de tomar el maximo (evita doble conteo en truncado)"`

### Tarea 43: `refresh()` unificado — una sola pasada alimenta `usage-agents.json` Y `usage-skills.json`; elimina `_lines()` (grep + fallback)
**Archivos:** Modificar `src/cabina/usage.py`, `tests/test_usage.py`, `tests/test_breaks.py`

Esta es la tarea que corrige el bug bloqueante de la enmienda: hoy `roster.py` llama
`usage.refresh(usage_agents_path, history, "agents", roots)` y `server.py` llama por separado
`usage.refresh(usage_skills_path, history, "skills", roots)` — dos llamadas independientes sobre los
MISMOS archivos. La firma pública `refresh(path, history_dir, kind, roots)` no cambia (ningún
caller se toca), pero por dentro pasa a ser un envoltorio delgado sobre un helper privado
`_refresh_both(state_dir, history_dir, roots)` que: (1) deriva `state_dir` de
`os.path.dirname(path)` — válido porque ambos callers ya pasan una ruta dentro del mismo
`cfg["state_dir"]`; (2) para cada archivo de `history_dir` (mismo `os.walk` recursivo de hoy, incluye
`subagents/`), llama a `_scan_file` UNA vez, con el offset de `usage-history.json`, obteniendo agentes
Y skills a la vez; (3) actualiza y guarda `usage-agents.json` Y `usage-skills.json` en la MISMA
llamada, sin importar qué `kind` la disparó; (4) `refresh()` público solo elige cuál de los dos
resultados devolver. Así, si `roster.py` llama con `kind="agents"` y momentos después `server.py`
llama con `kind="skills"` sobre el mismo archivo recién leído, la segunda llamada ve delta cero
**porque el trabajo ya se hizo en la primera** — no porque se haya perdido.

- [x] Paso 1: tests que fallan:
  ```python
  def test_agents_then_skills_refresh_does_not_lose_the_skill_invocation(self):
      # el escenario exacto del bug: dos llamadas con distinto kind sobre el mismo archivo,
      # que contiene AMBOS needles en líneas nuevas.
      env = Env()
      env.append_usage_line('{"timestamp":"2026-08-05","cwd":"...", "name":"Skill","input":{"skill":"deploy"}}')
      U.refresh(AGENTS_PATH, HIST, "agents", ROOTS)                 # dispara la unica pasada
      skill_items, _ = U.refresh(SKILLS_PATH, HIST, "skills", ROOTS)  # llega DESPUES, mismo archivo
      self.assertGreaterEqual(skill_items["deploy"]["n_total"], 1)     # antes de la enmienda: 0 (perdido)
  ```
  Test estructural: `self.assertFalse(hasattr(U, "_lines"))` — confirma que el camino grep+fallback
  desapareció, no solo que dejó de llamarse.
  Break-test en `tests/test_breaks.py`:
  ```python
  def test_usage_dual_output_single_pass_guard(self):
      # si refresh() solo actualizara la salida de SU kind (el bug original), el otro kind
      # perdería las invocaciones que aparecieron en la misma pasada.
      env = Env()
      env.append_usage_line('{"timestamp":"2026-08-05","cwd":"...", "name":"Skill","input":{"skill":"deploy"}}')
      with mock.patch.object(U, "_save_sibling_output", lambda *a, **k: None):  # guard disabled: solo guarda el kind pedido
          U.refresh(AGENTS_PATH, HIST, "agents", ROOTS)
          skill_items = U.load(SKILLS_PATH)
          self.assertNotIn("deploy", skill_items)                    # se perdio -> canary red
      U.refresh(AGENTS_PATH, HIST, "agents", ROOTS)                  # guard presente
      self.assertIn("deploy", U.load(SKILLS_PATH))                   # no se perdio
  ```
- [x] Paso 2: `AttributeError: module 'cabina.usage' has no attribute '_refresh_both'` (o el
      escenario de pérdida se reproduce con el código viejo de dos `refresh()` independientes).
- [x] Paso 3: implementar `_refresh_both` como se describe arriba; `refresh()` público queda como
      envoltorio de una línea. Nombre FIJO para el guardado del resultado que NO fue el `kind`
      pedido (lo usa el break-test de esta tarea tal cual): `_save_sibling_output(state_dir, kind,
      items, meta)` — guarda `usage-agents.json`/`usage-skills.json` según corresponda; `_refresh_both`
      llama a `_save_sibling_output` para AMBOS resultados, no solo el del `kind` que disparó la
      llamada. Borrar `_lines()` y los imports `subprocess`/`shutil` que ya no se usan.
- [x] Paso 4: `python3 -m unittest discover -s tests -p "test_usage.py" -v` y
      `-p "test_breaks.py"` → ambos `OK`.
- [x] Paso 5: `git commit -am "fix: usage.py — refresh() unificado, una pasada alimenta agents y skills a la vez (evita perder invocaciones por desync entre kinds); elimina grep y el fallback Windows"`

### Tarea 44: `threading.Lock` a nivel de módulo — serializar `refresh()` completo
**Archivos:** Modificar `src/cabina/usage.py`, `tests/test_usage.py`

`server.py` corre sobre `ThreadingHTTPServer`: dos requests concurrentes pueden llamar
`usage.refresh()` en hilos distintos (además de que CLI/MCP/`check.py` también lo invocan, aunque
sin concurrencia entre procesos). Sin serializar, dos hilos pueden leer `usage-history.json`, leer
los mismos bytes nuevos, y escribir de vuelta cada uno con su propia cuenta — el que escribe último
"pisa" al otro y ese delta se pierde para siempre (no hay resta que lo corrija, porque el registro
en disco nunca refleja lo que el otro hilo ya había sumado en memoria). El guard es un
`threading.Lock` módulo-nivel que envuelve TODO `_refresh_both` (leer registro → leer bytes → 
escribir registro), no solo el `save()` final — el `save()` con `tmp+os.replace` (ya existente)
sigue siendo atómico a nivel de archivo, pero eso no evita la carrera de lectura-modificación-escritura
si dos hilos calculan su delta contra el mismo estado leído antes de que ninguno escriba.

- [x] Paso 1: test que falla — dos hilos llaman `refresh()` CADA UNO sobre un archivo DISTINTO con
      un delta DISTINTO (el `.jsonl` principal de la fixture y el `subagents/sub.jsonl` que la
      Tarea 40 agrega, cada uno con una invocación de un agente distinto) — no el mismo archivo con
      el mismo delta: si ambos hilos leyeran y sumaran lo mismo, una pérdida real (uno pisa al otro)
      daría el mismo resultado que "sin pérdida" por coincidencia, y el test nunca se pondría rojo
      sin el lock. Con archivos y deltas distintos, perder uno de los dos hace que el total NO
      cuadre, así que el test sí distingue "con lock" de "sin lock". Se fuerza la intercalación con
      un `mock.patch.object` que inserta una pausa entre "leer registro" y "guardar registro", igual
      que un test de carrera clásico.
  ```python
  def test_concurrent_refresh_does_not_lose_a_delta(self):
      env = Env()
      orig_save = U._save_history
      def slow_save(*a, **k):
          time.sleep(0.05)          # ventana para que el otro hilo lea el registro viejo
          return orig_save(*a, **k)
      env.append_usage_line('...subagent_type":"reviewer"...')   # hilo A: va al .jsonl principal (-x/s.jsonl)
      # hilo B cuenta la invocacion de "nested-from-subagent" que la fixture de la Tarea 40 ya deja
      # en subagents/sub.jsonl — es un archivo DISTINTO, no hace falta agregarle nada mas.
      with mock.patch.object(U, "_save_history", side_effect=slow_save):
          t1 = threading.Thread(target=U.refresh, args=(AGENTS_PATH, HIST, "agents", ROOTS))
          t2 = threading.Thread(target=U.refresh, args=(AGENTS_PATH, HIST, "agents", ROOTS))
          t1.start(); t2.start(); t1.join(); t2.join()
      items = U.load(AGENTS_PATH)
      self.assertEqual(items["reviewer"]["n_total"], 1)              # delta del archivo principal
      self.assertEqual(items["nested-from-subagent"]["n_total"], 1)  # delta de subagents/sub.jsonl — sin lock, uno de los dos se pierde
  ```
- [x] Paso 2: corrido varias veces sin el lock, el test es intermitente/falla (carrera real,
      dependiente del scheduler) — documentar que por eso el Paso 1 fuerza la intercalación con el
      mock en vez de confiar en la suerte del scheduler del sistema.
- [x] Paso 3: agregar `_LOCK = threading.Lock()` a nivel de módulo en `usage.py`; `_refresh_both`
      completo (o el `refresh()` público, según quede más simple de envolver tras la Tarea 43) corre
      dentro de `with _LOCK:`.
- [x] Paso 4: `python3 -m unittest discover -s tests -p "test_usage.py" -v` → `OK`, corrido 10 veces
      seguidas sin intermitencia (`for i in {1..10}; do python3 -m unittest ...; done`).
- [x] Paso 5: `git commit -am "fix: usage.py — lock de modulo serializa refresh(), evita perder deltas por lectura-modificacion-escritura concurrente"`

### Tarea 45: Compatibilidad — cargar un `usage-agents.json`/`usage-skills.json` viejo (formato max-based, con `n_window`) sin perder nada
**Archivos:** Modificar `src/cabina/usage.py`, `tests/test_usage.py`

El esquema de salida pierde el campo `n_window` en esta fase (decisión, no pregunta abierta: cero
consumidores fuera de `usage.py` mismo, verificado por grep en `src/` y `static/` — representaba
"conteo de la última relectura completa", un concepto que no sobrevive a la lectura incremental sin
perder utilidad). `load()` debe tolerar un archivo viejo que todavía lo traiga (ignorarlo, no
fallar); `save()` deja de escribirlo. Aparte de eso, el esquema (`{last, n_total, by_project}`) no
cambia — solo la aritmética interna con la que se actualiza. Un archivo escrito por la versión vieja
(con un `n_total` que venía de tomar el máximo entre corridas) sigue sirviendo de punto de partida
correcto: el primer `refresh()` con el código nuevo debe SUMAR sobre ese `n_total` existente, nunca
resetearlo a cero ni recontar desde el inicio de la historia.

- [x] Paso 1: tests que fallan: (a) sembrar `usage-agents.json` a mano con `{"reviewer": {"n_total":
      40, "last": "2026-07-01", "by_project": {"alpha": 40}, "n_window": 3}}` (formato viejo, sin
      ninguna entrada en `usage-history.json`), correr `refresh()` con un historial que tiene 2 usos
      nuevos, y confirmar `n_total == 42` (no `2`, no `40`); (b) confirmar que el `save()` posterior
      ya NO escribe `"n_window"` en el archivo resultante.
- [x] Paso 2: (a) falla porque hoy `refresh()` recontaría desde cero y el `max()` viejo lo dejaría en
      el mayor de los dos, no en la suma; (b) falla porque `save()` todavía escribe `n_window`.
- [x] Paso 3: (a) sin cambios de código nuevos — este sub-test valida que las Tareas 42/43 ya lo
      resuelven; (b) en `usage.py`, quitar `e["n_window"] = v.get("n", 0)` de `merge()` y el
      `e.setdefault("n_window", 0)` correspondiente; `load()` no necesita cambio (ya devuelve el dict
      tal cual, con o sin la clave vieja).
- [x] Paso 4: `python3 -m unittest discover -s tests -p "test_usage.py" -v` → `OK` (si (a) falla,
      revisar la Tarea 42: probablemente `_accumulate` está pisando en vez de sumar sobre el registro
      previo).
- [x] Paso 5: `git commit -am "feat: usage.py — elimina n_window del esquema de salida (0 consumidores); compatibilidad con archivos viejos que aun lo traigan"`

### Tarea 46: Break-test — primer arranque sin `usage-history.json` procesa el historial completo una sola vez
**Archivos:** Modificar `tests/test_breaks.py`

Constraint (g): `agents --unused` (el detector de `check.py`, que lee `usage.load()` del caché) no
puede dar falsos positivos porque el registro nuevo esté vacío. Con el diseño de offsets, un
archivo sin entrada en `usage-history.json` se lee desde `offset=0` — es decir, completo — así que
esto debería cumplirse "gratis" por construcción; el break-test existe para que quede demostrado,
no asumido.

- [x] Paso 1: test que falla: con un `Env` fresco (sin ningún `usage-history.json` ni
      `usage-agents.json` previos), llamar `usage.refresh(...)` UNA vez y confirmar que el agente
      `reviewer` (invocado en la fixture del historial sintético) aparece con `n_total >= 1` — es
      decir, el primer refresh ya lo encontró, no hizo falta una segunda corrida.
- [x] Paso 2: correr contra el código de la Tarea 41 sin la 42/43 (registro roto a propósito con
      `mock.patch.object(U, "_scan_file", lambda *a, **k: ({}, {}, 0))`) → el agente NO aparece,
      confirmando que el test detecta la falla si el "primer scan completo" se rompe.
- [x] Paso 3: sin código nuevo — el comportamiento correcto ya lo dan las Tareas 41-43; este paso
      es la prueba formal.
- [x] Paso 4: `python3 -m unittest discover -s tests -p "test_breaks.py" -v` → `OK`, y con el mock
      del Paso 2 reinsertado manualmente se confirma el rojo (canary).
- [x] Paso 5: `git commit -am "test: test_breaks.py — primer arranque sin registro de usage lee el historial completo, agents --unused no da falsos positivos"`

### Tarea 47: Break-test — un archivo truncado/rotado no duplica conteos, y un archivo BORRADO no baja el total
**Archivos:** Modificar `tests/test_breaks.py`

Formaliza como break-test lo que la Tarea 42 ya prueba en `test_usage.py`, pero apuntando
específicamente a que alguien podría "simplificar" `_accumulate` de vuelta a una suma ingenua del
conteo bruto (no del delta) sin que ningún test de comportamiento normal lo note — solo se ve con
un archivo que se encoge. Además cubre el caso hermano, con la garantía CONTRARIA: un archivo que
Claude Code borra por rotación normal (no se trunca, desaparece por completo del disco) NO debe
bajar el total global — su última contribución conocida se queda en el acumulador para siempre
(mismo espíritu que `sessions.py` con `ended`: la ausencia del archivo fuente no es una señal de
"restar", solo de "no hay nada nuevo que leer de acá").

- [x] Paso 1: tests que fallan:
  ```python
  def test_truncated_file_guard(self):
      # con env.truncate_usage_history(...) (Tarea 40), desactivar la resta por delta y
      # confirmar que el total DUPLICA lo esperado tras dos refresh.
      with mock.patch.object(U, "_file_delta", lambda new, old: new):
          ...  # el total duplica -> canary red

  def test_deleted_file_does_not_regress_the_total(self):
      env = Env(); U.refresh(AGENTS_PATH, HIST, "agents", ROOTS)
      before = U.load(AGENTS_PATH)["reviewer"]["n_total"]
      os.remove(env.usage_history_file)             # rotacion normal: el archivo ya no existe
      U.refresh(AGENTS_PATH, HIST, "agents", ROOTS)
      after = U.load(AGENTS_PATH)["reviewer"]["n_total"]
      self.assertEqual(after, before)                # nunca baja por desaparicion del archivo
  ```
- [x] Paso 2: el primer test falla si se desactiva el guard (confirma que hoy funciona); el segundo
      falla si `_refresh_both` (Tarea 43) tratara "archivo ya no listado por `os.walk`" como
      "restar su última contribución" en vez de simplemente no volver a visitarlo.
- [x] Paso 3: sin código nuevo para el primer test (usa `_file_delta` de la Tarea 42 tal cual); para
      el segundo, confirmar que `_refresh_both` solo itera archivos que `os.walk` encuentra HOY —
      nunca recorre las claves de `usage-history.json` para "dar de baja" las que ya no aparecen en
      disco.
- [x] Paso 4: `python3 -m unittest discover -s tests -p "test_breaks.py" -v` → `OK` con los guards
      activos; con los mocks de cada Paso 1 aplicados, ambos canarios dan rojo como se espera.
- [x] Paso 5: `git commit -am "test: test_breaks.py — archivo truncado no duplica conteos; archivo borrado por rotacion no los resta"`

### Tarea 48: Medición final antes/después (frío y estable) + nota en CLAUDE.md si el comportamiento observable cambia
**Archivos:** ninguno de código; posible edición de `CLAUDE.md` (sección "Usage is best-effort...")

- [x] Paso 1: sobre el disco real de Danny (1.4 GB / 2 044 archivos), medir el ANTES: `git stash`
      (o checkout a un commit previo a la Tarea 41) + `time PYTHONPATH=src python3 -m cabina agents
      --json > /dev/null`, tres corridas, promedio.
- [x] Paso 2: `git stash pop` (o vuelta al HEAD de esta fase). Medir DOS números, no solo uno: (a) el
      primer refresh EN FRÍO, sin `usage-history.json` (el "primer arranque lento" es esperado, no
      es un defecto — pero hay que dejar el número escrito, no asumirlo); (b) el ESTADO ESTABLE, tres
      corridas más después de poblado el registro — debería acercarse al orden de magnitud de
      `sessions.py` (~0.1 s).
- [x] Paso 3: si el número en frío del Paso 2(a) supera ~15 s en el disco real, la única acción de
      esta tarea es confirmar que el aviso ya existente en `cli.py::_agents` ("scanning usage
      history…" en stderr) se sigue mostrando durante esa espera — eso se considera SUFICIENTE para
      esta fase; no se agrega ninguna otra optimización (barra de progreso, paralelismo, cache
      parcial) sin que el usuario lo pida.
- [x] Paso 4: si el número de `"invocations"`/`"here"` que muestra `cabina agents` para algún agente
      real cambia respecto al ANTES (posible por el paso de `max()` a suma — ver Tarea 45), anotarlo
      explícitamente en el resultado de esta tarea, no en silencio.
- [x] Paso 5: si `CLAUDE.md` (sección "Usage is best-effort and attributed by cwd") sigue siendo
      precisa tras el cambio, no tocarla; si el mecanismo que describe (grep + fallback) ya no
      existe, actualizarla para reflejar el registro por offset, y `git commit -am "docs: CLAUDE.md
      — usage.py ahora incremental por offset, ya no relee history_dir completo"` (solo si se tocó).

## Enmiendas aplicadas durante la ejecución (Fase 4)

1. **Tarea 43, Paso 3 — RESUELTO en la ronda D-F2 (commit `e4c74bd`).** El intento inicial dejó
   `_lines()`/`extract()`/`extract_agents()`/`extract_skills()`/`subprocess`/`shutil` sin borrar
   porque `tests/test_platform.py::TestNoGrep.test_usage_extract_without_grep` dependía de ese
   camino y ese archivo estaba fuera del scope original del lote. El coordinador autorizó
   tocar `test_platform.py`; se verificó por grep que `extract_agents`/`extract_skills`/`_lines`
   no tenían más consumidores que ese test + 4 tests de `test_usage.py`, se adaptaron esos 4
   para usar `_scan_file` directamente (mismo comportamiento), y se eliminó
   `test_usage_extract_without_grep` con justificación en el docstring de `TestNoGrep`: no queda
   ninguna rama "con grep" vs "sin grep" que distinguir en `usage.py` (los otros dos tests de esa
   clase, sobre `roster.py`/`scan.py`, son subsistemas distintos y no se tocaron). `_lines()` y
   compañía, junto con los imports `subprocess`/`shutil`, quedaron eliminados de `usage.py`.
2. **Tarea 45, Paso 3(a) — el plan asumía "sin cambios de código nuevos"; eso resultó falso.** El
   texto decía que las Tareas 42/43 ya resolvían la migración desde un `usage-agents.json` viejo
   (formato `max()`, con `n_window`) sin código adicional. Verificado empíricamente que NO es
   así: comparar el agregado fresco de la primera corrida (sin ninguna entrada en
   `usage-history.json`) contra el `n_total` heredado vía `_file_delta` resta el total viejo en
   vez de sumarle lo nuevo — con 40 invocaciones históricas + 2 nuevas el resultado daba `2`, no
   `42`. Se agregó `_add_onto_registry(registry, delta)`: cuando `usage-history.json` no tiene
   NINGUNA entrada antes de la llamada (el estado_dir nunca corrió `refresh()` con el código
   incremental), se suma el agregado fresco sobre el registro existente en lugar de
   reconciliarlo por resta — no hay nada contra qué reconciliar todavía. Detalle en el commit
   `664a311`.
3. **Tarea 48 — el número en frío empeoró primero (11.3s → 51.1s), corregido en la ronda D-F1
   (commit `9d47a00`).** Causa raíz confirmada (no solo sospechada): `_scan_file` corría
   `_TS.search`/`_CWD.search`/`_project_of` (y las dos regex `_AGENT`/`_SKILL`) sobre TODAS las
   líneas, tuvieran o no el needle — a diferencia del `grep -F`/fallback Python viejo, que
   pre-filtraba por substring antes de tocar una regex. Fix (TDD, test rojo con
   `mock.patch.object(U, "_project_of", wraps=U._project_of)` contando invocaciones — 20 líneas,
   solo 2 con needle, `spy.call_count` daba 20 en vez de ≤2): un chequeo de substring en C
   (`'"subagent_type"' not in line and '"name":"Skill"' not in line: continue`) al tope del loop,
   antes de cualquier regex. Resultado: frío 51.06s → **4.65s** (mejor que el 11.34s original,
   sin hacer falta `cProfile`). Ver la tabla actualizada más abajo en el reporte de cierre del
   ejecutor. El estado ESTABLE se mantuvo en el objetivo (~0.08s).

# Concerns (Fase 4)

1. **`usage-history.json` es un archivo más para retener/podar.** A diferencia de
   `usage-agents.json`/`usage-skills.json` (que acumulan para siempre a propósito), el registro por
   archivo (`offset`/conteos-por-archivo) podría crecer indefinidamente si Claude Code nunca borra
   transcripciones viejas en algún entorno atípico. `sessions.py` no tiene este problema porque poda
   por `retention_days`; esta fase no propone poda equivalente para `usage-history.json` — queda
   como pregunta abierta, no como tarea, porque podar mal ahí SÍ arriesga perder el punto de partida
   de la resta por delta (Tarea 42) y duplicar conteos.
2. **`n_window` se elimina, decisión ya tomada (Tarea 45).** Se documenta acá solo porque el campo
   existió en el esquema hasta esta fase: representaba "cuántas veces apareció en la última
   relectura completa", un concepto sin equivalente útil bajo lectura incremental (la "última
   pasada" pasa a ser un delta pequeño, no una foto del total). Verificado por grep que ningún
   consumidor (CLI/servidor/UI) lo leía fuera de `usage.py` mismo — el retiro no repara nada visible.
3. **El escenario de truncado real nunca se observó en producción.** El diseño (Tarea 42) asume que
   un archivo `.jsonl` de Claude Code puede encogerse bajo el mismo `source_path` (mismo criterio
   defensivo que ya usa `sessions.py`, Tarea 17) — pero no hay evidencia de que esto ocurra alguna
   vez en la práctica; es una guardia defensiva, no una reparación de un bug observado.
4. **Cambiar `merge()` de máximo a suma es una diferencia de comportamiento observable, no solo
   interna.** Si `usage-agents.json` tenía guardado un `n_total` que ya estaba "inflado" por algún
   historial de relecturas completas anteriores a esta fase (posible bajo el esquema viejo si el
   mismo archivo de historial se contó completo en dos corridas distintas sin que nada lo evitara),
   el primer `refresh()` con el código nuevo parte de esa base sin corregirla — la Tarea 45 prueba
   que no se pierde nada, no que el número viejo fuera exacto.
5. **`by_project` no se reasigna si los `roots` de la config cambian.** Detallado en la Tarea 42: el
   delta se atribuye al proyecto que resuelve `_project_of` EN EL MOMENTO del refresh; un cambio
   posterior de `roots` (renombrar/mover/fusionar un proyecto) deja el aporte histórico "pegado" al
   nombre viejo dentro de `by_project`. El remedio es el comando exacto `rm
   <state_dir>/usage-history.json` para forzar un recuento completo — deliberadamente manual, no
   automático (mismo criterio del proyecto: medir y avisar, no adivinar cuándo repararlo solo).

# Preguntas abiertas (Fase 4)

- ¿`usage-history.json` necesita su propia poda (por ejemplo, olvidar archivos cuyo `source_path`
  ya no existe en disco Y superó cierta antigüedad), o el riesgo de perder la base de la resta por
  delta (Concern 1) pesa más que el archivo crezca sin límite? `sessions.py` no es un buen espejo
  acá porque ahí la poda es de RESÚMENES (reemplazables), no de bases de conteo acumulativo.
- ¿Vale la pena, en una fase posterior, resolver el Concern 4 recalculando `usage-agents.json` desde
  cero UNA vez al adoptar el esquema nuevo (con el costo de una relectura completa, pagada una sola
  vez y documentada) en vez de partir de un `n_total` potencialmente inflado?
- La Opción B (derivar de `sessions.json`) fue descartada para esta fase por el hueco de alcance en
  `subagents/` — ¿ese hueco importa en la práctica (cuántas invocaciones reales pasan por ahí), o es
  aceptable cerrarlo más adelante y sí converger `usage.py` sobre `sessions.py` para eliminar la
  lectura duplicada de los mismos archivos por dos módulos distintos?

---

# Concerns

1. **El costo de `TranscriptProvider.active_projects()` en entornos grandes.** Cada llamada a
   `App.working()` (que ahora la incluye, Tarea 21) recorre TODOS los subdirectorios de
   `~/.claude/projects/`, y por cada uno sin actividad reciente en el archivo principal, también
   recorre sus subcarpetas buscando `subagents/`. `working()` se llama en cada `GET /api/docs` — no
   es "una vez por segundo" como la pestaña Live con herdr, pero si alguien abre la pestaña Docs
   seguido en un entorno con cientos de proyectos, vale medir antes de dar esto por cerrado.
2. **`subagent_tokens` no es incremental por offset (Tarea 14).** A diferencia del archivo de
   sesión principal (que sí trackea `offset`), los archivos de subagentes se leen COMPLETOS en cada
   `refresh()`. Es una simplificación deliberada (son archivos chicos, y R2 solo pide offset
   explícitamente para el archivo de sesión) — pero si un subagente llega a producir transcripciones
   grandes, esto se vuelve el costo dominante de cada refresh.
3. **La definición de "turno" (`turns`) sigue siendo mía, no del brief.** Un turno es una línea
   `type:"user"` con `role:"user"` que contiene al menos un bloque `text` — es decir, un mensaje
   real de la persona, excluyendo tanto los rebotes `tool_result` como (ahora, R6) las líneas
   sidechain. El brief nunca lo define con esa precisión.
4. **El desempate de "mayoría de cwd" (R5) no está especificado.** Si dos valores de `cwd`
   aparecen la misma cantidad de veces, `max(counts, key=counts.get)` de Python elige el primero
   que apareció en orden de inserción del diccionario — en la práctica, el primer `cwd` visto en la
   sesión. Es un comportamiento razonable pero implícito de la implementación, no una regla que
   R5 dicte explícitamente.
5. **El test de XSS de `hub` (Fase 2, R10) es estructural, no de ejecución real de JS.** Verifica
   con una expresión regular que el código fuente envuelve `x.title` en `esc(...)`, no que un
   navegador real efectivamente neutralice el payload. Es la prueba más fuerte que se puede hacer
   sin agregar un runner de navegador (Playwright/Selenium) al proyecto — que hoy es "zero
   dependencies" y sin infraestructura de tests de UI. Ver "Preguntas abiertas".
6. **`brief()` queda con una sola línea i18n'zada en medio de líneas fijas en inglés.** El resto de
   la función no pasa por `i18n.py`; se tradujo solo la línea nueva porque el brief pide
   explícitamente que las superficies de esta fase estén en `i18n.py` en+es — no se tocó el resto
   de `brief()` porque no era parte del pedido.
7. **El guard de privacidad (`SUMMARY_FIELDS`, Tarea 15) exige mantenimiento manual.** Cada campo
   legítimo nuevo que se agregue después a `sessions.py` necesita sumarse también a
   `SUMMARY_FIELDS`, o se cae en silencio. Es el trade-off correcto de una lista blanca (fallar
   cerrado, no abierto) — pero vale dejarlo anotado.

# Preguntas abiertas

- ¿El test estructural de XSS de `hub` (Concern 5) alcanza, o el equipo quiere agregar un runner de
  navegador real (Playwright) para probar la neutralización de punta a punta? Eso sería la primera
  dependencia de test-only del proyecto (`dependencies = []` sigue intacto en runtime, pero el
  entorno de desarrollo ganaría una pieza nueva) — decisión de alcance, no de código.
- ¿El desempate de mayoría de cwd (Concern 4) debería ser explícito en vez de depender del orden de
  inserción del diccionario — por ejemplo, "el cwd de la ÚLTIMA línea entre los empatados"?
- ¿"Tablero de proyectos" (R13) va dentro de la pestaña Projects existente (como se diseñó arriba,
  tiles sobre la lista actual) o como pestaña nueva? R13 solo define el CONTENIDO (tiles read-only),
  no la ubicación.
- `cabina hub`: ¿necesita el mismo header `X-Cabina-Token` que el servidor normal en sus rutas GET,
  o al no tener NINGUNA ruta POST (R10) alcanza con bindear `127.0.0.1`? El servidor normal hoy
  tampoco exige el token en GET, así que mantener esa misma asimetría en `hub` es lo consistente —
  pero como `hub` puede correr sobre una carpeta compartida entre varias personas del equipo, vale
  confirmarlo antes de publicar la Fase 2.
- ¿El umbral de retención `cfg.activity.retention_days = 365` (Tarea 17, R4) es el valor correcto
  para el tamaño real de `sessions.json` en el uso diario de Danny, o conviene medirlo después de
  unas semanas de uso real antes de fijarlo en piedra?
