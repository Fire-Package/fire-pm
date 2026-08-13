import jwt from "jsonwebtoken";
import bcrypt from "bcryptjs";
import crypto from "crypto";
import { loadConfig } from "./config";
import { AUTH_COOKIE_NAME, CSRF_COOKIE_NAME } from "./constants";

export { AUTH_COOKIE_NAME, CSRF_COOKIE_NAME };

export interface JwtPayload {
  sub: string;
  role: string;
  iat?: number;
  exp?: number;
}

export async function hashPassword(password: string): Promise<string> {
  const salt = await bcrypt.genSalt(12);
  return bcrypt.hash(password, salt);
}

export async function verifyPassword(password: string, hash: string): Promise<boolean> {
  if (!password || !hash) return false;
  return bcrypt.compare(password, hash);
}

export function generateJwtToken(subject: string = "admin"): string {
  const config = loadConfig();
  return jwt.sign(
    { sub: subject, role: "admin" },
    config.auth.jwtSecret,
    { expiresIn: "24h" }
  );
}

export function verifyJwtToken(token: string): JwtPayload | null {
  try {
    const config = loadConfig();
    const decoded = jwt.verify(token, config.auth.jwtSecret) as JwtPayload;
    return decoded;
  } catch {
    return null;
  }
}

export function generateCsrfToken(): string {
  return crypto.randomBytes(24).toString("hex");
}
