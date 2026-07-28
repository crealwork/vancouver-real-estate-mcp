import crypto from "node:crypto";

/**
 * Stateless API keys: the key carries its own claims and a signature, so
 * verifying one needs no database round trip. Issuance is recorded by email,
 * which is all the free tier needs to know who is using it.
 *
 * Format: vanre_<base64url(payload)>.<base64url(hmac-sha256, 16 bytes)>
 */

const PREFIX = "vanre_";

export type KeyClaims = {
  /** SHA-256 of the lowercased email, truncated — enough to correlate, not to reverse. */
  e: string;
  /** Issued-at, seconds since epoch. */
  t: number;
  /** Tier; reserved for later. */
  p?: string;
};

function secret(): string {
  const s = process.env.API_KEY_SECRET;
  if (!s) throw new Error("API_KEY_SECRET is not set");
  return s;
}

function b64url(buf: Buffer): string {
  return buf.toString("base64url");
}

function sign(payload: string): string {
  return b64url(
    crypto.createHmac("sha256", secret()).update(payload).digest().subarray(0, 16),
  );
}

export function emailFingerprint(email: string): string {
  return crypto
    .createHash("sha256")
    .update(email.trim().toLowerCase())
    .digest("base64url")
    .slice(0, 12);
}

export function issueKey(email: string, tier = "free"): string {
  const claims: KeyClaims = { e: emailFingerprint(email), t: Math.floor(Date.now() / 1000) };
  if (tier !== "free") claims.p = tier;
  const payload = b64url(Buffer.from(JSON.stringify(claims)));
  return `${PREFIX}${payload}.${sign(payload)}`;
}

export function verifyKey(key: string | null | undefined): KeyClaims | null {
  if (!key || !key.startsWith(PREFIX)) return null;
  const body = key.slice(PREFIX.length);
  const dot = body.lastIndexOf(".");
  if (dot < 1) return null;

  const payload = body.slice(0, dot);
  const provided = body.slice(dot + 1);
  const expected = sign(payload);

  const a = Buffer.from(provided);
  const b = Buffer.from(expected);
  if (a.length !== b.length || !crypto.timingSafeEqual(a, b)) return null;

  try {
    const claims = JSON.parse(Buffer.from(payload, "base64url").toString()) as KeyClaims;
    if (typeof claims.e !== "string" || typeof claims.t !== "number") return null;
    return claims;
  } catch {
    return null;
  }
}

/** Pull the key out of an Authorization header or ?key= query parameter. */
export function keyFromRequest(req: Request): string | null {
  const auth = req.headers.get("authorization");
  if (auth) {
    const m = auth.match(/^Bearer\s+(.+)$/i);
    if (m) return m[1].trim();
  }
  const header = req.headers.get("x-api-key");
  if (header) return header.trim();
  try {
    return new URL(req.url).searchParams.get("key");
  } catch {
    return null;
  }
}
