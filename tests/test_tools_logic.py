import unittest
import os
import shutil
import tempfile
import json
from pathlib import Path

# Since these tools often rely on paths or external libs, we might need to mock them,
# but we can test the pagination logic explicitly.
from tools import youtube_transcript
from tools import analyze_directory

class TestToolsLogic(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_youtube_transcript_pagination(self):
        # We can't hit the youtube transcript API directly because it requires network access,
        # so we will monkey-patch the module's fetcher inside the test
        from unittest.mock import patch

        class DummyTranscriptAPI:
            class DummySnippet:
                def __init__(self, text):
                    self.text = text
            def fetch(self, video_id, languages):
                return [self.DummySnippet("A" * 1000)] * 20

        with patch('youtube_transcript_api.YouTubeTranscriptApi', new=DummyTranscriptAPI):
            res0 = youtube_transcript.execute("dummy11char", block=0, max_chars=0)
            self.assertTrue("BLOCK 0 OF 1" in res0)
            self.assertTrue("Call again with block=1" in res0)
            self.assertTrue(len(res0) > 15000)

            res1 = youtube_transcript.execute("dummy11char", block=1, max_chars=0)
            self.assertTrue("BLOCK 1 OF 1" in res1)
            self.assertFalse("Call again with block" in res1)
            self.assertTrue(15000 > len(res1) >= 5000)

    def test_analyze_directory_safety(self):
        # We must use project-relative paths to bypass the tool's absolute path security restrictions
        tmp_path = tempfile.mkdtemp(dir="tests")
        rel_tmp = os.path.relpath(tmp_path).replace("\\", "/")
        os.makedirs(os.path.join(tmp_path, "logs"))
        with open(os.path.join(tmp_path, "logs", "test.log"), "w") as f:
            f.write("Line 1\nLine 2")
            
        res = analyze_directory.execute(rel_tmp, recursive=True)
        self.assertTrue("[STRUCTURE]" in res)
        self.assertTrue("logs\\test.log" in res or "logs/test.log" in res)
        self.assertTrue("[FILE CONTENTS]" in res)
        self.assertTrue("Line 1" in res)

if __name__ == "__main__":
    unittest.main()
