import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from threading import Thread
from unittest import TestCase
from unittest.mock import patch
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import serve


class LiveDocumentTests(TestCase):
    def test_requests_rescan_disk_without_restarting_or_writing_an_index(self):
        with TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            entry = root / "new-skill" / "SKILL.md"
            entry.parent.mkdir()
            with patch.object(serve, "SKILLS", root), serve.ThreadingHTTPServer(("127.0.0.1", 0), serve.Handbook) as server:
                thread = Thread(target=server.serve_forever)
                thread.start()
                try:
                    origin = f"http://127.0.0.1:{server.server_port}"

                    def catalog():
                        with urlopen(origin + "/api/skill-documents", timeout=5) as response:
                            self.assertEqual(response.headers["Cache-Control"], "no-store")
                            return json.load(response)

                    self.assertEqual(catalog(), [])
                    for revision in ("第一版", "修订版"):
                        body = f"---\nname: new-skill\ndescription: {revision}简介\n---\n{revision}正文"
                        entry.write_text(body, encoding="utf-8")
                        self.assertEqual(catalog(), [{"document": "new-skill/SKILL.md", "markdown": body}])
                        with urlopen(origin + "/docs/new-skill/SKILL.md", timeout=5) as response:
                            self.assertEqual(response.read().decode().splitlines(), body.splitlines())
                    entry.unlink()
                    self.assertEqual(catalog(), [])
                finally:
                    server.shutdown()
                    thread.join()
