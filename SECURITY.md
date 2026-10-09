import os
import re
import json
import threading
import time
import secrets
from pathlib import Path

# Security validation utilities for Fire PM

class ShellValidator:
    """Validate shell parameters to prevent command injection."""
    
    SAFE_SHELLS = ['bash', 'sh', 'zsh', 'fish', 'dash', 'ash']
    ALLOWED_PATHS = ['/bin', '/usr/bin', '/usr/local/bin', '/sbin', '/usr/sbin']
    
    @classmethod
    def validate_shell(cls, shell: str) -> str:
        """Validate and sanitize shell parameter.
        
        Args:
            shell: Shell name or path to validate
            
        Returns:
            Validated shell path
            
        Raises:
            ValueError: If shell is invalid or potentially malicious
        """
        if not shell or not isinstance(shell, str):
            raise ValueError("Shell must be a non-empty string")
        
        # Remove any path components to prevent path traversal
        shell_name = os.path.basename(shell)
        
        # Validate format - only alphanumeric, underscore, hyphen
        if not re.match(r'^[a-zA-Z0-9_-]+$', shell_name):
            raise ValueError(f"Invalid shell name: {shell_name}")
        
        # Check if shell is in safe list
        if shell_name not in cls.SAFE_SHELLS:
            raise ValueError(f"Shell not allowed: {shell_name}")
        
        # Resolve to absolute path and validate it's in allowed locations
        try:
            shell_path = shutil.which(shell_name)
            if not shell_path:
                raise ValueError(f"Shell not found: {shell_name}")
            
            # Check if path is in allowed locations
            is_allowed = False
            for allowed_path in cls.ALLOWED_PATHS:
                if shell_path.startswith(allowed_path):
                    is_allowed = True
                    break
            
            if not is_allowed:
                raise ValueError(f"Shell path not in allowed locations: {shell_path}")
                
        except Exception as e:
            raise ValueError(f"Shell validation failed: {e}")
        
        return shell_path

class PathSanitizer:
    """Sanitize file paths to prevent directory traversal attacks."""
    
    @classmethod
    def sanitize_path(cls, path: str, base_dir: str) -> str:
        """Sanitize file path to prevent directory traversal.
        
        Args:
            path: User-provided path
            base_dir: Base directory that path should be relative to
            
        Returns:
            Absolute, sanitized path
            
        Raises:
            ValueError: If path traversal attempt detected
        """
        if not path or not isinstance(path, str):
            raise ValueError("Path must be a non-empty string")
        
        # Normalize the path
        abs_path = os.path.abspath(os.path.join(base_dir, path))
        base_dir_abs = os.path.abspath(base_dir)
        
        # Check if the resulting path is still within base directory
        if not abs_path.startswith(base_dir_abs + os.sep) and abs_path != base_dir_abs:
            raise ValueError("Path traversal attempt detected")
        
        # Additional check: prevent path components like '..' and '.'
        path_parts = path.split(os.sep)
        for part in path_parts:
            if part in ('.', '..'):
                raise ValueError(f"Path component not allowed: {part}")
        
        return abs_path

class InputSanitizer:
    """Sanitize user inputs to prevent various injection attacks."""
    
    # Common shell metacharacters that could be used for injection
    SHELL_METACHARS = r';|&$`\><(){}[]*?~\n\r\t'
    
    @classmethod
    def sanitize_for_shell(cls, input_str: str) -> str:
        """Remove shell metacharacters from input.
        
        Args:
            input_str: User input to sanitize
            
        Returns:
            Sanitized string safe for shell usage
            
        Raises:
            ValueError: If input contains potentially dangerous characters
        """
        if not input_str or not isinstance(input_str, str):
            return ""
        
        # Check for shell metacharacters
        if re.search(r'[' + re.escape(cls.SHELL_METACHARS) + r']', input_str):
            raise ValueError("Input contains potentially dangerous characters")
        
        return input_str.strip()
    
    @classmethod
    def sanitize_service_name(cls, name: str) -> str:
        """Sanitize service name.
        
        Args:
            name: Service name to sanitize
            
        Returns:
            Sanitized service name
            
        Raises:
            ValueError: If name contains invalid characters
        """
        if not name or not isinstance(name, str):
            raise ValueError("Service name must be a non-empty string")
        
        # Service names should only contain alphanumeric, underscore, hyphen
        if not re.match(r'^[a-zA-Z0-9_-]+$', name):
            raise ValueError("Service name contains invalid characters")
        
        # Prevent special systemd service names
        if name.startswith('.') or name.endswith('.'):
            raise ValueError("Service name cannot start or end with a dot")
        
        return name
    
    @classmethod
    def sanitize_port(cls, port: str) -> int:
        """Sanitize port number.
        
        Args:
            port: Port number as string
            
        Returns:
            Validated port number as integer
            
        Raises:
            ValueError: If port is invalid
        """
        if not port or not isinstance(port, str):
            raise ValueError("Port must be a non-empty string")
        
        # Check if it's a valid number
        if not re.match(r'^[0-9]+$', port):
            raise ValueError("Port must be a number")
        
        port_num = int(port)
        
        # Check port range
        if port_num < 1 or port_num > 65535:
            raise ValueError("Port must be between 1 and 65535")
        
        return port_num
class SecurityLogger:
    """Centralized security logging for Fire PM."""
    
    def __init__(self):
        self.lock = threading.Lock()
        self.security_events = []
    
    def log_security_event(self, event_type: str, details: str, severity: str = "WARNING"):
        """Log a security event.
        
        Args:
            event_type: Type of security event (e.g., 'COMMAND_INJECTION', 'PATH_TRAVERSAL')
            details: Detailed description of the event
            severity: Severity level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        """
        event = {
            'timestamp': time.time(),
            'type': event_type,
            'details': details,
            'severity': severity
        }
        
        with self.lock:
            self.security_events.append(event)
            
            # Write to log file
            log_file = Path('/var/log/fire-pm/security.log')
            log_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(log_file, 'a') as f:
                f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {severity}: {event_type}: {details}\n")
    
    def get_security_events(self, hours: int = 24) -> list:
        """Get recent security events.
        
        Args:
            hours: Number of hours of events to retrieve
            
        Returns:
            List of recent security events
        """
        cutoff_time = time.time() - (hours * 3600)
        
        with self.lock:
            return [event for event in self.security_events 
                   if event['timestamp'] > cutoff_time]
class SecurityManager:
    """Main security manager for Fire PM."""
    
    def __init__(self):
        self.logger = SecurityLogger()
        self.rate_limiter = RateLimiter()
        self.session_manager = SecureSessionManager()
    
    def validate_shell_command(self, shell: str, **kwargs) -> tuple:
        """Validate shell command parameters.
        
        Args:
            shell: Shell parameter to validate
            **kwargs: Additional validation parameters
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            validated_shell = ShellValidator.validate_shell(shell)
            return True, validated_shell
        except ValueError as e:
            self.logger.log_security_event(
                'COMMAND_INJECTION_ATTEMPT', 
                f"Shell validation failed: {str(e)}",
                'CRITICAL'
            )
            return False, str(e)
    
    def validate_file_path(self, path: str, base_dir: str) -> tuple:
        """Validate file path for potential directory traversal.
        
        Args:
            path: File path to validate
            base_dir: Base directory
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            sanitized_path = PathSanitizer.sanitize_path(path, base_dir)
            return True, sanitized_path
        except ValueError as e:
            self.logger.log_security_event(
                'PATH_TRAVERSAL_ATTEMPT',
                f"Path validation failed: {str(e)}",
                'HIGH'
            )
            return False, str(e)
    
    def validate_service_name(self, name: str) -> tuple:
        """Validate service name.
        
        Args:
            name: Service name to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            sanitized_name = InputSanitizer.sanitize_service_name(name)
            return True, sanitized_name
        except ValueError as e:
            self.logger.log_security_event(
                'INVALID_SERVICE_NAME',
                f"Service name validation failed: {str(e)}",
                'MEDIUM'
            )
            return False, str(e)
    
    def check_rate_limit(self, ip: str) -> tuple:
        """Check if IP is rate limited.
        
        Args:
            ip: IP address to check
            
        Returns:
            Tuple of (is_allowed, remaining_time, remaining_attempts)
        """
        is_allowed, wait_time, remaining = self.rate_limiter.check_rate_limit(ip)
        
        if not is_allowed:
            self.logger.log_security_event(
                'RATE_LIMIT_EXCEEDED',
                f"IP {ip} exceeded rate limit",
                'MEDIUM'
            )
        
        return is_allowed, wait_time, remaining
# Global security manager instance
security_manager = SecurityManager()
