# Fire PM Security Standards

This document defines the security standards and requirements for the Fire PM (Fire Process Manager) project. These standards are derived from the comprehensive security audit findings and provide a framework for secure development and deployment.

## Overview

Fire PM is a Linux-native process management platform that provides zero-daemon overhead operation directly against systemd with three main interfaces: CLI (Bash), TUI (Python Textual), and Web Dashboard (Next.js 15). Due to its direct system interaction and zero-configuration architecture, security is critical.

## Security Standards

### 1. Input Validation Standards

#### 1.1 Shell Parameter Validation
**File:** `app/fire_ssh.py` - `TerminalSession.start()`

**Standard:** All shell parameters must be validated through the `ShellValidator` class before use.

**Requirements:**
- Shell names must be limited to safe shells: `bash`, `sh`, `zsh`, `fish`, `dash`, `ash`
- Shell paths must be resolved and validated to prevent path traversal
- Shell must be located in allowed system paths: `/bin`, `/usr/bin`, `/usr/local/bin`, `/sbin`, `/usr/sbin`

**Implementation Example:**
```python
from SECURITY import ShellValidator

try:
    validated_shell = ShellValidator.validate_shell(shell_input)
    # Use validated_shell in execvpe()
except ValueError as e:
    security_manager.log_security_event('INVALID_SHELL', str(e), 'CRITICAL')
    raise
```

#### 1.2 File Path Validation
**Standard:** All file paths must be validated through `PathSanitizer` to prevent directory traversal.

**Requirements:**
- Paths must be normalized using `os.path.abspath()`
- Resulting paths must stay within the base directory
- Path components (`.`, `..`) must be rejected
- File operations must use sanitized paths

**Implementation Example:**
```python
from SECURITY import PathSanitizer

try:
    safe_path = PathSanitizer.sanitize_path(user_path, base_dir)
    # Use safe_path for file operations
except ValueError as e:
    security_manager.log_security_event('PATH_TRAVERSAL', str(e), 'HIGH')
    raise
```

#### 1.3 Service Name Validation
**Standard:** All service names must be validated to prevent injection.

**Requirements:**
- Service names must match pattern: `^[a-zA-Z0-9_-]+$`
- Service names cannot start or end with dots
- Special systemd service names must be blocked

**Implementation Example:**
```python
from SECURITY import InputSanitizer

try:
    safe_name = InputSanitizer.sanitize_service_name(service_name)
    # Use safe_name for service operations
except ValueError as e:
    security_manager.log_security_event('INVALID_SERVICE', str(e), 'MEDIUM')
    raise
```

### 2. Authentication and Session Management

#### 2.1 Password Storage
**Standard:** Passwords must use PBKDF2 with SHA256, minimum 600,000 iterations.

**Requirements:**
- Use `hashlib.pbkdf2_hmac('sha256', password, salt, iterations=600000)`
- Store salt and hash separately
- Use `secrets.token_bytes(32)` for salt generation
- Use `os.chmod(0o600)` for credential files

**Implementation Example:**
```python
class SecurePasswordManager:
    ITERATIONS = 600000
    SALT_SIZE = 32
    
    @staticmethod
    def hash_password(plain_text: str) -> tuple:
        salt = secrets.token_bytes(SecurePasswordManager.SALT_SIZE)
        hash_value = hashlib.pbkdf2_hmac(
            'sha256',
            plain_text.encode('utf-8'),
            salt,
            iterations=SecurePasswordManager.ITERATIONS
        )
        return salt.hex(), hash_value.hex()
    
    @staticmethod
    def verify_password(plain_text: str, salt_hex: str, hash_hex: str) -> bool:
        salt = bytes.fromhex(salt_hex)
        computed_hash = hashlib.pbkdf2_hmac(
            'sha256',
            plain_text.encode('utf-8'),
            salt,
            iterations=SecurePasswordManager.ITERATIONS
        )
        return hmac.compare_digest(computed_hash.hex(), hash_hex)
```

#### 2.2 Session Management
**Standard:** Sessions must use cryptographically secure tokens and IP binding.

**Requirements:**
- Session tokens must be `secrets.token_urlsafe(32)`
- Sessions must validate client IP addresses
- Sessions must expire after 24 hours
- Sessions must be cleaned up properly

**Implementation Example:**
```python
from SECURITY import SecureSessionManager

# Create session bound to specific IP
session_token = SecureSessionManager.create_session(client_ip, user_data)

# Validate session with IP binding
is_valid, message = SecureSessionManager.validate_session(session_token, client_ip)
if not is_valid:
    # Handle invalid session
    pass
```

### 3. Web Interface Security

#### 3.1 Content Security Policy (CSP)
**Standard:** Web dashboard must implement strict CSP headers.

**Required Headers:**
```nginx
add_header X-Content-Type-Options nosniff;
add_header X-Frame-Options DENY;
add_header X-XSS-Protection "1; mode=block";
add_header Referrer-Policy "strict-origin-when-cross-origin";
add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self';";
add_header Permissions-Policy "geolocation=(), microphone=(), camera=();";
```

#### 3.2 CSRF Protection
**Standard:** All mutating operations must include CSRF tokens.

**Requirements:**
- CSRF tokens must be stored in secure, HTTP-only cookies
- CSRF tokens must be validated on all POST/PUT/DELETE requests
- CSRF tokens must be regenerated after successful authentication

**Implementation Example:**
```python
# In web dashboard
import secrets
import hashlib
import hmac

def generate_csrf_token(session_id: str) -> str:
    secret = get_csrf_secret()  # From environment variable
    timestamp = str(int(time.time()))
    data = f"{session_id}:{timestamp}"
    signature = hmac.new(
        secret.encode('utf-8'),
        data.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return f"{data}:{signature}"

def validate_csrf_token(token: str, session_id: str) -> bool:
    try:
        data, signature = token.rsplit(':', 1)
        expected_session, timestamp = data.split(':', 1)
        
        # Check timestamp is recent (e.g., within 1 hour)
        if int(time.time()) - int(timestamp) > 3600:
            return False
        
        # Verify signature
        secret = get_csrf_secret()
        expected_signature = hmac.new(
            secret.encode('utf-8'),
            data.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(signature, expected_signature) and expected_session == session_id
    except Exception:
        return False
```

### 4. Network Security

#### 4.1 HTTPS Enforcement
**Standard:** All web traffic must use HTTPS with TLS 1.2 or higher.

**Requirements:**
- Use Let's Encrypt for automatic certificate management
- Configure HSTS headers
- Disable HTTP entirely
- Use HTTP/2 protocol

#### 4.2 Rate Limiting
**Standard:** Implement comprehensive rate limiting.

**Requirements:**
- Rate limit authentication attempts to 5 per 5 minutes per IP
- Rate limit API endpoints appropriately
- Implement exponential backoff for retries
- Log rate limit violations

### 5. Logging and Monitoring

#### 5.1 Security Logging
**Standard:** All security-relevant events must be logged.

**Required Log Events:**
- Command injection attempts
- Path traversal attempts
- Invalid shell parameters
- Failed authentication attempts
- Rate limit violations
- File access attempts

**Implementation Example:**
```python
from SECURITY import security_manager

# Example logging for various events
security_manager.log_security_event(
    'COMMAND_INJECTION_ATTEMPT',
    f"Invalid shell parameter: {shell_input}",
    'CRITICAL'
)

security_manager.log_security_event(
    'PATH_TRAVERSAL_ATTEMPT',
    f"Path traversal attempt: {user_path}",
    'HIGH'
)

security_manager.log_security_event(
    'RATE_LIMIT_EXCEEDED',
    f"IP {ip_address} exceeded rate limit",
    'MEDIUM'
)
```

#### 5.2 Security Monitoring
**Standard:** Implement real-time security monitoring.

**Requirements:**
- Monitor for abnormal authentication patterns
- Alert on multiple failed login attempts
- Track resource usage for DoS detection
- Monitor for unusual file access patterns

### 6. File and Directory Security

#### 6.1 File Permissions
**Standard:** All sensitive files must have secure permissions.

**Required Permissions:**
- Configuration files: `0o600` (owner read/write only)
- Log files: `0o640` (owner read/write, group read)
- Password files: `0o600` (owner read/write only)
- Temporary files: `0o600` (owner read/write only, deleted on exit)

#### 6.2 Directory Structure
**Standard:** Secure directory structure with proper permissions.

**Required Directories:**
```bash
/etc/fire-pm/          # 0o700, owner root only
  config.json         # 0o600
  ssh-auth.json       # 0o600
/var/log/fire-pm/     # 0o750
  security.log       # 0o640
/tmp/fire-pm/         # 0o700, cleaned on reboot
~/.fire/             # 0o700, user-specific
  ssh-auth.json       # 0o600
```

## Compliance Checklist

### Mandatory Security Controls
- [ ] Shell validation implemented in `fire_ssh.py`
- [ ] Path traversal protection for all file operations
- [ ] Session IP binding implemented
- [ ] CSRF tokens for all mutating operations
- [ ] HTTPS enforced with valid certificates
- [ ] Rate limiting configured and tested
- [ ] Security logging implemented
- [ ] Input validation for all user inputs
- [ ] Password hashing with PBKDF2 (600k+ iterations)
- [ ] Secure file permissions configured
- [ ] CSP headers implemented
- [ ] Session expiration configured

### Security Testing
- [ ] Unit tests for input validation
- [ ] Integration tests for security controls
- [ ] Penetration testing
- [ ] Security audit trails
- [ ] Load testing for rate limiting
- [ ] Manual security review

## Implementation Timeline

### Phase 1: Critical Fixes (Immediate)
1. Implement shell validation in `fire_ssh.py`
2. Add path validation to all file operations
3. Fix session management vulnerabilities
4. Deploy security logging infrastructure

### Phase 2: Security Enhancements (30-60 days)
1. Implement CSRF protection
2. Configure HTTPS with Let's Encrypt
3. Deploy rate limiting
4. Implement security monitoring

### Phase 3: Advanced Security (60-90 days)
1. Implement CSP headers
2. Add security testing suite
3. Deploy Web Application Firewall
4. Conduct security audit

## Conclusion

The security of Fire PM is critical for production deployment. This document provides the standards and requirements for implementing secure development practices throughout the Fire PM project. All development teams must follow these security standards and undergo regular security reviews and testing.

The zero-daemon architecture of Fire PM makes input validation absolutely critical - there are no intermediate layers to sanitize or validate user input. Every user input must be validated before use.
