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

// In-memory rate limiting for sensitive endpoints (e.g. login)
interface RateLimitEntry {
  count: number;
  resetAt: number;
}

const rateLimitMap = new Map<string, RateLimitEntry>();

export function checkRateLimit(key: string, maxAttempts: number = 5, windowMs: number = 60000): boolean {
  const now = Date.now();
  const entry = rateLimitMap.get(key);

  if (!entry || now > entry.resetAt) {
    rateLimitMap.set(key, { count: 1, resetAt: now + windowMs });
    return true;
  }

  if (entry.count >= maxAttempts) {
    return false;
  }

  entry.count += 1;
  return true;
}

// Ensure secret is securely resolved or randomly generated in memory
let fallbackJwtSecret: string | null = null;
function getJwtSecret(): string {
  const config = loadConfig();
  if (config.auth?.jwtSecret && config.auth.jwtSecret !== "default-secret") {
    return config.auth.jwtSecret;
  }
  if (!fallbackJwtSecret) {
    fallbackJwtSecret = crypto.randomBytes(32).toString("hex");
  }
  return fallbackJwtSecret;
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
  const secret = getJwtSecret();
  return jwt.sign(
    { sub: subject, role: "admin" },
    secret,
    { expiresIn: "24h" }
  );
}

export function verifyJwtToken(token: string): JwtPayload | null {
  try {
    const secret = getJwtSecret();
    const decoded = jwt.verify(token, secret) as JwtPayload;
    return decoded;
  } catch {
    return null;
  }
}

export function generateCsrfToken(): string {
  return crypto.randomBytes(24).toString("hex");
}
