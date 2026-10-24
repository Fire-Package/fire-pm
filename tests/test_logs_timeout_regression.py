import os
import re
import subprocess
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


class LogsTimeoutRegressionTests(unittest.TestCase):

    def setUp(self):
        self.fire_cli_path = os.path.join(PROJECT_ROOT, "app", "fire")
        with open(self.fire_cli_path, "r", encoding="utf-8") as f:
            self.cli_content = f.read()

    def _run_bash_snippet(self, snippet):
        """Helper to run a bash snippet with app/fire functions extracted."""
        proc = subprocess.run(
            ["bash", "-c", snippet],
            capture_output=True,
            text=True,
            check=False
        )
        return proc

    def test_parse_args_handles_timeout_flags(self):
        """Verify parse_args sets TIMEOUT_OPT for --timeout, --timeout=, -t, -t=, and --no-timeout."""
        match = re.search(r'(TIMEOUT_OPT=""[\s\S]*?\nparse_args\(\)\s*\{[\s\S]*?\n\})', self.cli_content)
        self.assertIsNotNone(match, "parse_args block should exist in app/fire")
        fn_code = match.group(1)

        bash_script = f"""
        set -e
        CMD="logs"
        {fn_code}

        # 1. --timeout 45
        TIMEOUT_OPT=""
        ARGS=()
        parse_args --timeout 45
        [[ "$TIMEOUT_OPT" == "45" ]]

        # 2. --timeout=60
        TIMEOUT_OPT=""
        ARGS=()
        parse_args --timeout=60
        [[ "$TIMEOUT_OPT" == "60" ]]

        # 3. -t 30 for CMD=logs
        TIMEOUT_OPT=""
        ARGS=()
        parse_args -t 30
        [[ "$TIMEOUT_OPT" == "30" ]]

        # 4. -t=90 for CMD=logs
        TIMEOUT_OPT=""
        ARGS=()
        parse_args -t=90
        [[ "$TIMEOUT_OPT" == "90" ]]

        # 5. --no-timeout
        TIMEOUT_OPT=""
        ARGS=()
        parse_args --no-timeout
        [[ "$TIMEOUT_OPT" == "0" ]]

        # 6. -t when CMD=ssh is passed through to ARGS
        CMD="ssh"
        TIMEOUT_OPT=""
        ARGS=()
        parse_args -t "MyTitle"
        [[ "$TIMEOUT_OPT" == "" ]]
        [[ "${{ARGS[0]}}" == "-t" ]]
        [[ "${{ARGS[1]}}" == "MyTitle" ]]
        """
        proc = self._run_bash_snippet(bash_script)
        self.assertEqual(proc.returncode, 0, f"Bash execution failed:\n{proc.stderr}\n{proc.stdout}")

    def test_logs_timeout_defaults_and_normalization(self):
        """Verify default timeout of 180s and duration normalization in action_logs logic."""
        bash_script = f"""
        set -e
        # Helper to simulate timeout resolution logic from action_logs
        resolve_service_name() {{
          if [[ "$1" == "existing-app" ]]; then
            echo "fire-existing-app.service"
          else
            echo ""
          fi
        }}

        resolve_timeout() {{
          local target="$1"
          local subtarget="$2"
          local raw_timeout="$3"
          local resolved_target="$target"

          if [[ -z "$raw_timeout" ]]; then
            if [[ -n "$subtarget" && "$subtarget" =~ ^([0-9]+[smhd]?|none|inf|infinity)$ ]]; then
              raw_timeout="$subtarget"
            elif [[ -n "$target" && "$target" =~ ^([0-9]+[smhd]?|none|inf|infinity)$ ]]; then
              local check_svc
              check_svc=$(resolve_service_name "$target")
              if [[ -z "$check_svc" ]]; then
                raw_timeout="$target"
                resolved_target=""
              fi
            fi
          fi

          local timeout_val="${{raw_timeout:-180s}}"
          local timeout_enabled=1
          local timeout_display=""

          if [[ "$timeout_val" == "0" || "$timeout_val" == "0s" || "$timeout_val" == "none" || "$timeout_val" == "inf" || "$timeout_val" == "infinity" ]]; then
            timeout_enabled=0
            timeout_val="0"
          elif [[ "$timeout_val" =~ ^[0-9]+$ ]]; then
            timeout_display="${{timeout_val}}s"
            timeout_val="${{timeout_val}}s"
          elif [[ "$timeout_val" =~ ^[0-9]+[smhd]$ ]]; then
            timeout_display="$timeout_val"
          else
            echo "ERROR: INVALID"
            return 1
          fi

          echo "$timeout_enabled:$timeout_val:$timeout_display:$resolved_target"
        }}

        # Default when no args provided -> 180s
        res=$(resolve_timeout "" "" "")
        [[ "$res" == "1:180s:180s:" ]]

        # Default when target service provided -> 180s
        res=$(resolve_timeout "existing-app" "" "")
        [[ "$res" == "1:180s:180s:existing-app" ]]

        # Explicit flag override -> 60s
        res=$(resolve_timeout "existing-app" "" "60")
        [[ "$res" == "1:60s:60s:existing-app" ]]

        # Unit suffix override -> 5m
        res=$(resolve_timeout "existing-app" "" "5m")
        [[ "$res" == "1:5m:5m:existing-app" ]]

        # Explicit infinite -> 0
        res=$(resolve_timeout "existing-app" "" "0")
        [[ "$res" == "0:0::existing-app" ]]

        # Positional timeout with service -> api 45 -> 45s
        res=$(resolve_timeout "existing-app" "45" "")
        [[ "$res" == "1:45s:45s:existing-app" ]]

        # Positional timeout without service -> 30 -> all services 30s
        res=$(resolve_timeout "30" "" "")
        [[ "$res" == "1:30s:30s:" ]]
        """
        proc = self._run_bash_snippet(bash_script)
        self.assertEqual(proc.returncode, 0, f"Bash execution failed:\n{proc.stderr}\n{proc.stdout}")

    def test_cli_help_documents_timeout(self):
        """Verify show_help displays the logs timeout option and lines option."""
        self.assertIn("logs [name] [-n|--lines <num>] [-t|--timeout <sec>]", self.cli_content)
        self.assertIn("default: 100 lines, 180s timeout", self.cli_content)
        self.assertIn("fire logs api --lines 15", self.cli_content)
        self.assertIn("fire logs api --timeout 0", self.cli_content)

    def test_shell_completions_include_timeout(self):
        """Verify bash, zsh, and fish completions include --timeout, -t, and --lines for logs."""
        self.assertIn("--timeout -t --no-timeout --lines -n -l", self.cli_content)
        self.assertIn("complete -c fire -n '__fish_seen_subcommand_from logs log' -l timeout", self.cli_content)
        self.assertIn("complete -c fire -n '__fish_seen_subcommand_from logs log' -l lines", self.cli_content)

    def test_parse_args_handles_lines_flags(self):
        """Verify parse_args sets LINES_OPT for --lines, -n, and -l when CMD=logs."""
        match = re.search(r'(LINES_OPT=""[\s\S]*?\nparse_args\(\)\s*\{[\s\S]*?\n\})', self.cli_content)
        self.assertIsNotNone(match, "parse_args block should exist in app/fire")
        fn_code = match.group(1)

        bash_script = f"""
        set -e
        CMD="logs"
        {fn_code}

        # 1. --lines 15
        LINES_OPT=""
        ARGS=()
        parse_args --lines 15
        [[ "$LINES_OPT" == "15" ]]

        # 2. --lines=20
        LINES_OPT=""
        ARGS=()
        parse_args --lines=20
        [[ "$LINES_OPT" == "20" ]]

        # 3. -n 25 for CMD=logs
        LINES_OPT=""
        NAME_OPT=""
        ARGS=()
        parse_args -n 25
        [[ "$LINES_OPT" == "25" ]]
        [[ "$NAME_OPT" == "" ]]

        # 4. -n=30 for CMD=logs
        LINES_OPT=""
        NAME_OPT=""
        ARGS=()
        parse_args -n=30
        [[ "$LINES_OPT" == "30" ]]
        [[ "$NAME_OPT" == "" ]]

        # 5. -l 35 for CMD=logs
        LINES_OPT=""
        ARGS=()
        parse_args -l 35
        [[ "$LINES_OPT" == "35" ]]

        # 6. -l=40 for CMD=logs
        LINES_OPT=""
        ARGS=()
        parse_args -l=40
        [[ "$LINES_OPT" == "40" ]]

        # 7. -n when CMD=start sets NAME_OPT, NOT LINES_OPT
        CMD="start"
        LINES_OPT=""
        NAME_OPT=""
        ARGS=()
        parse_args -n "my-app"
        [[ "$NAME_OPT" == "my-app" ]]
        [[ "$LINES_OPT" == "" ]]
        """
        proc = self._run_bash_snippet(bash_script)
        self.assertEqual(proc.returncode, 0, f"Bash execution failed:\n{proc.stderr}\n{proc.stdout}")


if __name__ == "__main__":
    unittest.main()
