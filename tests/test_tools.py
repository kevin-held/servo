import unittest
import os
from tools import web_search, fetch_url, shell_exec, filesystem

class TestToolsE2E(unittest.TestCase):
    """
    End-to-End integration tests for all available backend tools.
    These tests hit live endpoints to verify structural parsers are healthy.
    """

    def test_web_search_live(self):
        output = web_search.execute("Python programming site:python.org", max_results=3)
        self.assertIsInstance(output, str)
        self.assertNotIn("Error", output)
        self.assertIn("Title:", output)
        self.assertIn("URL:", output)
        self.assertIn("python.org", output.lower())

    def test_fetch_url_live(self):
        # Hitting a stable wikipedia endpoint to test structural peeling
        output = fetch_url.execute("https://en.wikipedia.org/wiki/Main_Page")
        self.assertIsInstance(output, str)
        self.assertNotIn("Error", output)
        self.assertTrue(len(output) > 500, "Should have downloaded a decent chunk of text")
        self.assertIn("Wikipedia", output)

    def test_shell_exec(self):
        output = shell_exec.execute("echo test_run_success")
        self.assertIn("test_run_success", output)

    def test_filesystem_rw(self):
        test_file = "tests/e2e_rw_test.txt"
        
        # 1. Write
        w_out = filesystem.execute("write", test_file, "E2E OK")
        self.assertIn("Wrote", w_out)
        self.assertTrue(os.path.exists(test_file))
        
        # 2. Read
        r_out = filesystem.execute("read", test_file)
        self.assertEqual("E2E OK", r_out.strip())
        
        # 3. List
        l_out = filesystem.execute("list", "tests")
        self.assertIn("e2e_rw_test.txt", l_out)
        
        # Cleanup
        if os.path.exists(test_file):
            os.remove(test_file)

if __name__ == '__main__':
    unittest.main()
