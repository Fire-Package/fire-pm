import { loadConfig, saveConfig, isSetupComplete } from "../config";
import { hashPassword, verifyPassword, generateJwtToken, generateCsrfToken } from "../auth";

export class AuthService {
  static isConfigured(): boolean {
    return isSetupComplete();
  }

  static async setup(password: string): Promise<{ token: string; csrfToken: string }> {
    if (this.isConfigured()) {
      throw new Error("Setup is already complete. Please log in.");
    }

    if (!password || password.length < 6) {
      throw new Error("Password must be at least 6 characters long.");
    }

    const passwordHash = await hashPassword(password);
    const config = loadConfig();
    config.auth.passwordHash = passwordHash;
    saveConfig(config);

    const token = generateJwtToken("admin");
    const csrfToken = generateCsrfToken();
    return { token, csrfToken };
  }

  static async login(password: string): Promise<{ token: string; csrfToken: string }> {
    if (!this.isConfigured()) {
      throw new Error("Initial setup required.");
    }

    const config = loadConfig();
    const isValid = await verifyPassword(password, config.auth.passwordHash);
    if (!isValid) {
      throw new Error("Invalid password.");
    }

    const token = generateJwtToken("admin");
    const csrfToken = generateCsrfToken();
    return { token, csrfToken };
  }

  static async changePassword(currentPass: string, newPass: string): Promise<{ success: boolean }> {
    if (!newPass || newPass.length < 6) {
      throw new Error("New password must be at least 6 characters long.");
    }

    const config = loadConfig();
    const isValid = await verifyPassword(currentPass, config.auth.passwordHash);
    if (!isValid) {
      throw new Error("Current password is incorrect.");
    }

    config.auth.passwordHash = await hashPassword(newPass);
    saveConfig(config);
    return { success: true };
  }
}
