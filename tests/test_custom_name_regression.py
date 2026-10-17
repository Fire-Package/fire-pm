import os
import re
import subprocess
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


class CustomNameRegressionTests(unittest.TestCase):

    def setUp(self):
        self.fire_ssh_path = os.path.join(PROJECT_ROOT, "app", "fire_ssh.py")
        self.fire_cli_path = os.path.join(PROJECT_ROOT, "app", "fire")
        with open(self.fire_ssh_path, "r", encoding="utf-8") as f:
            self.ssh_content = f.read()
        with open(self.fire_cli_path, "r", encoding="utf-8") as f:
            self.cli_content = f.read()

    def test_fire_ssh_py_argparse_supports_name_flag(self):
        """Verify fire_ssh.py argparse accepts --name and -n for start subcommand."""
        self.assertIn('p_start.add_argument("--name", "-n"', self.ssh_content)
        self.assertIn("session_title = args.title or getattr(args, \"name\", None) or None", self.ssh_content)

    def test_fire_ssh_py_cli_help_includes_name(self):
        """Verify running fire_ssh.py start --help shows --name."""
        proc = subprocess.run(
            ["python3", self.fire_ssh_path, "start", "--help"],
            capture_output=True,
            text=True,
            check=False
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("--name", proc.stdout)
        self.assertIn("-n", proc.stdout)

    def test_cli_parse_args_handles_name_variants(self):
        """Verify app/fire parse_args correctly sets NAME_OPT for --name, --name=, -n, and -n=."""
        match = re.search(r'(NAME_OPT=""[\s\S]*?\nparse_args\(\)\s*\{[\s\S]*?\n\})', self.cli_content)
        self.assertIsNotNone(match, "parse_args block should exist in app/fire")
        fn_code = match.group(1)

        bash_script = f"""
        {fn_code}
        
        # Test 1: --name val
        NAME_OPT=""
        parse_args --name "test-name-1"
        [[ "$NAME_OPT" == "test-name-1" ]] || exit 1

        # Test 2: --name=val
        NAME_OPT=""
        parse_args --name="test-name-2"
        [[ "$NAME_OPT" == "test-name-2" ]] || exit 2

        # Test 3: -n val
        NAME_OPT=""
        parse_args -n "test-name-3"
        [[ "$NAME_OPT" == "test-name-3" ]] || exit 3

        # Test 4: -n=val
        NAME_OPT=""
        parse_args -n="test-name-4"
        [[ "$NAME_OPT" == "test-name-4" ]] || exit 4

        echo "PARSE_ARGS_PASSED"
        """
        proc = subprocess.run(["bash", "-c", bash_script], capture_output=True, text=True, check=False)
        self.assertEqual(proc.returncode, 0, f"parse_args test failed: {proc.stderr}")
        self.assertIn("PARSE_ARGS_PASSED", proc.stdout)

    def test_cli_tunnel_open_extracts_name_and_validates(self):
        """Verify action_tunnel_open and open_custom_tunnel handle custom names and validate formatting."""
        # Check that action_tunnel_open parses --name and -n
        self.assertIn('custom_name="${arg#*=}"', self.cli_content)
        self.assertIn('"$a" == "--name" || "$a" == "-n"', self.cli_content)

        # Check that open_custom_tunnel sanitizes and validates
        self.assertIn("local custom_name=\"${3:-}\"", self.cli_content)
        self.assertIn("hash=$(echo \"$custom_name\" | tr '[:upper:]' '[:lower:]'", self.cli_content)
        self.assertIn("write_tunnel_state \"$port\" \"0\" \"$url\" \"\" \"$start_ts\" \"custom\" \"$hash\"", self.cli_content)

    def test_cli_tunnel_close_by_name_logic(self):
        """Verify action_tunnel_close contains logic to resolve target by name if non-numeric."""
        self.assertIn("if ! [[ \"$target\" =~ ^[0-9]+$ ]]; then", self.cli_content)
        self.assertIn('"$TUNNEL_STATE_NAME" == "$target"', self.cli_content)

    def test_cli_ssh_close_by_name_logic(self):
        """Verify action_ssh_close matches both numeric port and session name/title."""
        self.assertIn('name=$(grep -o \'"name": *"[^"]*"\'', self.cli_content)
        self.assertIn('"$target_port" != "$title" && "$target_port" != "$name"', self.cli_content)

    def test_cli_ssh_start_forwards_name_to_tunnel(self):
        """Verify action_ssh_start passes session_title/name to open_custom_tunnel and open_quick_tunnel."""
        self.assertIn('open_custom_tunnel "$port" "$start_ts" "$session_title"', self.cli_content)
        self.assertIn('open_quick_tunnel "$port" "$start_ts" "$session_title"', self.cli_content)


if __name__ == "__main__":
    unittest.main()
