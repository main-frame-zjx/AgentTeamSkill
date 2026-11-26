"""Regression checks for rebuilding from the current skill documents."""

import json
from pathlib import Path
import runpy
from tempfile import TemporaryDirectory
import unittest


REPO = Path(__file__).resolve().parents[2]
BUILDER = REPO / ".agents/skills/update-skills-relation/scripts/build_index.py"
publish = runpy.run_path(str(BUILDER))["publish"]


class IndexTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.repo = Path(temp.name)
        self.skills = self.repo / "skills"
        self.output = self.repo / "dev-visual" / "skill-relation.json"
        self.output.parent.mkdir()
        self.review = {"categories": ["测试"], "skills": []}

    def add_skill(self, name, body=""):
        directory = self.skills / name
        directory.mkdir(parents=True)
        path = directory / "SKILL.md"
        path.write_text(f"---\nname: {name}\ndescription: 测试简介\n---\n{body}", encoding="utf-8")
        self.review["skills"].append({"name": name, "category": "测试", "next": []})
        return path

    def rebuild(self):
        before = {p: p.read_bytes() for p in self.skills.rglob("*.md")}
        index = publish(self.repo, self.review)
        self.assertEqual(json.loads(self.output.read_text(encoding="utf-8")), index)
        self.assertEqual(before, {p: p.read_bytes() for p in self.skills.rglob("*.md")})
        return index["skills"]

    def test_add_rename_remove(self):
        self.add_skill("at-start")
        self.assertEqual([s["name"] for s in self.rebuild()], ["at-start"])
        path = self.add_skill("at-step")
        self.assertEqual(len(self.rebuild()), 2)
        renamed = self.skills / "at-revised" / "SKILL.md"
        renamed.parent.mkdir()
        renamed.write_text(path.read_text(encoding="utf-8").replace("at-step", "at-revised"), encoding="utf-8")
        path.unlink()
        with self.assertRaisesRegex(ValueError, "清单与目录不符"):
            self.rebuild()
        self.review["skills"][1]["name"] = "at-revised"
        self.assertEqual(self.rebuild()[1]["document"], "at-revised/SKILL.md")
        renamed.unlink()
        self.review["skills"].pop()
        self.assertEqual([s["name"] for s in self.rebuild()], ["at-start"])

    def test_evidence_and_target_must_match_before_replacing_index(self):
        quote = "完成后调用 `$at-end`。"
        self.add_skill("at-start", quote)
        self.add_skill("at-end")
        item = {"source": "at-start/SKILL.md", "quote": quote, "condition": "完成后"}
        edge = {"target": "at-end", "evidence": [item]}
        self.review["skills"][0]["next"] = [edge]
        self.rebuild()
        original = self.output.read_bytes()
        for key, value in [("quote", "必要时调用 `$at-end`。"), ("source", "at-end/SKILL.md"),
                           ("source", "../README.md")]:
            with self.subTest(key=key, value=value):
                previous = item[key]
                item[key] = value
                with self.assertRaises(ValueError):
                    self.rebuild()
                item[key] = previous
                self.assertEqual(self.output.read_bytes(), original)
        edge["target"] = "at-missing"
        with self.assertRaisesRegex(ValueError, "目标不存在"):
            self.rebuild()
        self.assertEqual(self.output.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
