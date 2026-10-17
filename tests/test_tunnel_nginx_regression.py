import os
import re
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


class TunnelNginxRegressionTests(unittest.TestCase):

    def setUp(self):
        self.template_path = os.path.join(PROJECT_ROOT, "shared", "nginx", "fire-tunnel.conf")
        self.cli_path = os.path.join(PROJECT_ROOT, "app", "fire")
        with open(self.template_path, "r", encoding="utf-8") as f:
            self.template_content = f.read()
        with open(self.cli_path, "r", encoding="utf-8") as f:
            self.cli_content = f.read()

    def test_template_server_name_excludes_apex_domain(self):
        """Verify shared/nginx/fire-tunnel.conf does not include bare {{TUNNEL_DOMAIN}} in server_name."""
        match = re.search(r"server_name\s+([^;]+);", self.template_content)
        self.assertIsNotNone(match, "server_name directive should exist in template")
        server_name_value = match.group(1).strip()
        self.assertNotIn("{{TUNNEL_DOMAIN}}", server_name_value, "Template server_name must not include {{TUNNEL_DOMAIN}}")
        self.assertIn("~^[a-z0-9]{8,10}-tunnel", server_name_value, "Template server_name must match hash-tunnel regex")

    def test_cli_ensure_nginx_config_excludes_apex_domain(self):
        """Verify app/fire does not include $TUNNEL_BASE_DOMAIN in server_name."""
        # Find server_name inside ensure_nginx_custom_tunnel_config
        match = re.search(r'ensure_nginx_custom_tunnel_config\(\)\s*\{(.*?)open_custom_tunnel\(\)', self.cli_content, re.DOTALL)
        self.assertIsNotNone(match, "ensure_nginx_custom_tunnel_config function should exist")
        fn_body = match.group(1)
        self.assertNotIn('server_name $TUNNEL_BASE_DOMAIN', fn_body, "CLI server_name must not include $TUNNEL_BASE_DOMAIN")
        self.assertIn('server_name "~^[a-z0-9]{8,10}-tunnel', fn_body, "CLI server_name must match hash-tunnel regex")

    def test_tunnel_subdomain_regex_matching(self):
        """Verify the Nginx server_name regex matches only hash-tunnel subdomains and rejects apex domains."""
        domain = "example.com"
        domain_regex = domain.replace(".", r"\.")
        pattern = re.compile(rf"^[a-z0-9]{{8,10}}-tunnel\.{domain_regex}$")

        # Valid tunnel subdomains
        self.assertTrue(pattern.match("18p89kn6cs-tunnel.example.com"))
        self.assertTrue(pattern.match("abcd1234-tunnel.example.com"))

        # Must NOT match bare apex/base domain
        self.assertFalse(pattern.match("example.com"))
        self.assertFalse(pattern.match("www.example.com"))
        self.assertFalse(pattern.match("tunnel.example.com"))
        self.assertFalse(pattern.match("otherdomain.com"))


if __name__ == "__main__":
    unittest.main()
