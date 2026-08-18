import json, os, tempfile, threading, time, unittest
from unittest import mock
import _helpers  # noqa
from cabina import usage as U
from _env import Env

def hist(d, *lines):
    open(os.path.join(d, "s.jsonl"), "w").write("\n".join(lines) + "\n"); return d

class TestUsage(unittest.TestCase):
    def test_extract_count_and_last(self):
        with tempfile.TemporaryDirectory() as d:
            hist(d, '{"timestamp":"2026-08-01T10:00:00Z","x":{"subagent_type":"code-reviewer"}}',
                    '{"timestamp":"2026-08-05T10:00:00Z","x":{"subagent_type":"code-reviewer"}}',
                    '{"timestamp":"2026-08-03T10:00:00Z","x":{"subagent_type":"executor"}}')
            u = U.extract_agents(d)
            self.assertEqual((u["code-reviewer"]["n"], u["code-reviewer"]["last"], u["executor"]["n"]), (2, "2026-08-05", 1))

    def test_attribution_by_cwd(self):
        with tempfile.TemporaryDirectory() as d:
            hist(d, '{"timestamp":"2026-08-01T10:00:00Z","cwd":"/home/u/p/alpha/apps/api","x":{"subagent_type":"code-reviewer"}}',
                    '{"timestamp":"2026-08-02T10:00:00Z","cwd":"/home/u/p/beta","x":{"subagent_type":"code-reviewer"}}',
                    '{"timestamp":"2026-08-02T10:00:00Z","cwd":"/home/u/p/alpha-two","x":{"subagent_type":"code-reviewer"}}')
            u = U.extract_agents(d, roots={"alpha": "/home/u/p/alpha", "beta": "/home/u/p/beta"})
            self.assertEqual(u["code-reviewer"]["by_project"], {"alpha": 1, "beta": 1})   # alpha-two is NOT alpha

    def test_skill_invocations_not_mentions(self):
        with tempfile.TemporaryDirectory() as d:
            hist(d, '{"timestamp":"2026-08-01T10:00:00Z","x":{"name":"Skill","input":{"skill":"orchestrate"}}}',
                    '{"timestamp":"2026-08-02T10:00:00Z","x":"skill `mention-only`"}')
            u = U.extract_skills(d)
            self.assertEqual(u["orchestrate"]["n"], 1); self.assertNotIn("mention-only", u)

    def test_line_without_timestamp(self):
        with tempfile.TemporaryDirectory() as d:
            hist(d, '{"x":{"subagent_type":"odd"}}')
            self.assertEqual(U.extract_agents(d)["odd"], {"n": 1, "last": None, "by_project": {}})

    def test_merge_keeps_old_date_after_rotation(self):
        r = U.merge({"deploy": {"last": "2026-05-03", "n_total": 4}}, {})
        self.assertEqual((r["deploy"]["last"], r["deploy"]["n_total"]), ("2026-05-03", 4))

    def test_merge_advances_never_regresses(self):
        self.assertEqual(U.merge({"a": {"last": "2026-05-03", "n_total": 4}}, {"a": {"last": "2026-08-10", "n": 2}})["a"]["last"], "2026-08-10")
        self.assertEqual(U.merge({"a": {"last": "2026-08-10", "n_total": 9}}, {"a": {"last": "2026-08-01", "n": 1}})["a"]["last"], "2026-08-10")

    def test_merge_keeps_extra_fields_and_by_project(self):
        r = U.merge({"old": {"last": "2026-04-01", "n_total": 2, "archived": "2026-08-17", "by_project": {"p": 2}}}, {"old": {"n": 1, "last": None, "by_project": {"q": 1}}})
        self.assertEqual(r["old"]["archived"], "2026-08-17"); self.assertEqual(r["old"]["by_project"], {"p": 2, "q": 1})

    def test_save_load_roundtrip_and_missing(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "u.json"); U.save(p, {"a": {"last": "2026-08-01", "n_total": 1}})
            self.assertEqual(U.load(p)["a"]["last"], "2026-08-01")
        self.assertEqual(U.load("/no/x.json"), {})

    @unittest.skipIf(os.name == "nt", "symlinks need admin rights on Windows")
    def test_project_of_resolves_symlinks(self):
        with tempfile.TemporaryDirectory() as d:
            real = os.path.join(d, "real"); os.makedirs(real)
            link = os.path.join(d, "link"); os.symlink(real, link)
            self.assertEqual(U._project_of(os.path.join(link, "sub"), {"p": real}), "p")

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

    def test_for_agent_view(self):
        items = {"cr": {"n_total": 10, "last": "2026-08-01", "by_project": {"alpha": 7, "beta": 3}}}
        self.assertEqual(U.for_agent(items, "cr", "alpha"), {"total": 10, "last": "2026-08-01", "here": 7, "attributed": True})
        self.assertEqual(U.for_agent(items, "nope", "alpha")["total"], 0)


class TestUsageHistoryRegistry(unittest.TestCase):
    def setUp(self):
        self.env = Env()

    def tearDown(self):
        self.env.cleanup()

    def _paths(self):
        p = os.path.join(self.env.state, "usage-agents.json")
        history_dir = os.path.join(self.env.claude, "projects")
        roots = {"alpha": self.env.alpha}
        return p, history_dir, roots

    def test_accumulates_across_two_incremental_refreshes(self):
        # dos refresh() sucesivos con una línea nueva en medio deben SUMAR, no promediar ni pisar
        p, history_dir, roots = self._paths()
        items1, _ = U.refresh(p, history_dir, "agents", roots)
        self.env.append_usage_line(
            '{"timestamp":"2026-08-05T00:00:00Z","cwd":"%s","x":{"subagent_type":"reviewer"}}' % self.env.alpha)
        items2, _ = U.refresh(p, history_dir, "agents", roots)
        self.assertEqual(items2["reviewer"]["n_total"], items1["reviewer"]["n_total"] + 1)

    def test_truncated_file_does_not_double_count(self):
        p, history_dir, roots = self._paths()
        U.refresh(p, history_dir, "agents", roots)
        self.env.truncate_usage_history(
            '{"timestamp":"2026-08-01T00:00:00Z","cwd":"%s","x":{"subagent_type":"reviewer"}}\n' % self.env.alpha)
        items, _ = U.refresh(p, history_dir, "agents", roots)
        self.assertEqual(items["reviewer"]["n_total"], 1)     # no se suma lo viejo + lo nuevo

    def test_agents_then_skills_refresh_does_not_lose_the_skill_invocation(self):
        # el escenario exacto del bug: dos llamadas con distinto kind sobre el mismo archivo,
        # que contiene AMBOS needles en líneas nuevas.
        p, history_dir, roots = self._paths()
        skills_path = os.path.join(self.env.state, "usage-skills.json")
        self.env.append_usage_line(
            '{"timestamp":"2026-08-05T00:00:00Z","cwd":"%s","x":{"name":"Skill","input":{"skill":"deploy"}}}' % self.env.alpha)
        U.refresh(p, history_dir, "agents", roots)                          # dispara la unica pasada
        skill_items, _ = U.refresh(skills_path, history_dir, "skills", roots)  # llega DESPUES, mismo archivo
        self.assertGreaterEqual(skill_items["deploy"]["n_total"], 1)        # antes de la enmienda: 0 (perdido)
        self.assertIn("deploy", U.load(skills_path))                        # y quedo PERSISTIDO en disco

    def test_concurrent_refresh_does_not_lose_a_delta(self):
        # Sin lock, dos refresh() concurrentes escriben al MISMO ".tmp" de usage-history.json:
        # uno de los dos os.replace() puede fallar con FileNotFoundError porque el otro hilo ya
        # lo consumio (o lo piso a mitad de escritura) — una carrera real de
        # lectura-modificacion-escritura, no solo de rendimiento. Se fuerza la intercalacion con
        # un mock que inserta una pausa entre "leer/escanear" y "guardar", igual que un test de
        # carrera clasico (confiar en el scheduler del sistema es intermitente, ver Paso 2).
        p, history_dir, roots = self._paths()
        orig_save = U._save_history
        def slow_save(*a, **k):
            time.sleep(0.05)          # ventana para que el otro hilo lea el registro viejo
            return orig_save(*a, **k)
        self.env.append_usage_line(
            '{"timestamp":"2026-08-05T00:00:00Z","cwd":"%s","x":{"subagent_type":"reviewer"}}' % self.env.alpha)
        # hilo B cuenta la invocacion de "nested-from-subagent" que la fixture de la Tarea 40 ya
        # deja en projects/-x/usage-sid/subagents/sub.jsonl — es un archivo DISTINTO.
        errors = []
        def run():
            try:
                U.refresh(p, history_dir, "agents", roots)
            except Exception as e:
                errors.append(e)
        with mock.patch.object(U, "_save_history", side_effect=slow_save):
            t1 = threading.Thread(target=run)
            t2 = threading.Thread(target=run)
            t1.start(); t2.start(); t1.join(); t2.join()
        self.assertEqual(errors, [])                                   # sin el lock: FileNotFoundError intermitente
        items = U.load(p)
        self.assertEqual(items["reviewer"]["n_total"], 4)              # 3 originales + 1 agregada
        self.assertEqual(items["nested-from-subagent"]["n_total"], 1)  # del subagents/sub.jsonl fijo

    def test_loads_old_max_based_registry_and_sums_on_top(self):
        # un usage-agents.json escrito por la version vieja (n_total via max(), con n_window)
        # y SIN ninguna entrada en usage-history.json: el primer refresh() con el codigo nuevo
        # debe SUMAR sobre ese n_total existente, nunca resetearlo ni recontar desde el inicio.
        with tempfile.TemporaryDirectory() as d:
            state = os.path.join(d, "state"); os.makedirs(state)
            p = os.path.join(state, "usage-agents.json")
            json.dump({"meta": {}, "items": {"reviewer": {
                "n_total": 40, "last": "2026-07-01", "by_project": {"alpha": 40}, "n_window": 3}}},
                open(p, "w"))
            history_dir = os.path.join(d, "hist"); os.makedirs(history_dir)
            open(os.path.join(history_dir, "s.jsonl"), "w").write(
                '{"timestamp":"2026-08-01T00:00:00Z","cwd":"/x","x":{"subagent_type":"reviewer"}}\n'
                '{"timestamp":"2026-08-02T00:00:00Z","cwd":"/x","x":{"subagent_type":"reviewer"}}\n')
            items, _ = U.refresh(p, history_dir, "agents", {})
            self.assertEqual(items["reviewer"]["n_total"], 42)     # 40 + 2, no 2, no 40
            self.assertNotIn("n_window", items["reviewer"])        # save() ya no lo escribe

    def test_scan_file_skips_regex_on_lines_without_the_needle(self):
        # D-F1: _scan_file no debe correr _CWD.search (y por tanto _project_of) sobre lineas
        # que ni siquiera contienen "subagent_type" o el patron de Skill — un pre-filtro de
        # substring (barato) debe descartarlas ANTES de llegar a las regex/_project_of.
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "f.jsonl")
            lines = ['{"timestamp":"2026-08-01","cwd":"/x","noise":"line %d"}' % i for i in range(20)]
            lines[3] = '{"timestamp":"2026-08-01","cwd":"/x","subagent_type":"reviewer"}'
            lines[11] = '{"timestamp":"2026-08-01","cwd":"/x","name":"Skill","input":{"skill":"deploy"}}'
            open(p, "w").write("\n".join(lines) + "\n")
            with mock.patch.object(U, "_project_of", wraps=U._project_of) as spy:
                agents, skills, _ = U._scan_file(p, 0, roots={})
            self.assertEqual(agents["reviewer"]["n"], 1)
            self.assertEqual(skills["deploy"]["n"], 1)
            self.assertLessEqual(spy.call_count, 2)   # hoy: 20 (una por linea, sin pre-filtro)

if __name__ == "__main__":
    unittest.main()
