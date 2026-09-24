import snowflake from "snowflake-sdk";
import { assertQuerySafe } from "./allowlist";

// Server-only module. Never import from a client component.
snowflake.configure({ logLevel: "WARN" });

type Row = Record<string, unknown>;

let connectionPromise: Promise<snowflake.Connection> | null = null;

function privateKey(): string {
  const raw = process.env.SNOWFLAKE_PRIVATE_KEY;
  if (!raw) throw new Error("SNOWFLAKE_PRIVATE_KEY is not set");
  // Vercel env vars are single-line; restore newlines.
  return raw.replace(/\\n/g, "\n");
}

function getConnection(): Promise<snowflake.Connection> {
  if (connectionPromise) return connectionPromise;
  connectionPromise = new Promise((resolve, reject) => {
    const conn = snowflake.createConnection({
      account: required("SNOWFLAKE_ACCOUNT"),
      username: required("SNOWFLAKE_USER"),
      role: required("SNOWFLAKE_ROLE"),
      warehouse: required("SNOWFLAKE_WAREHOUSE"),
      database: process.env.SNOWFLAKE_DATABASE ?? "PRD_BI_SUITE",
      schema: process.env.SNOWFLAKE_SCHEMA ?? "CONS_BI",
      authenticator: "SNOWFLAKE_JWT",
      privateKey: privateKey(),
      privateKeyPass: process.env.SNOWFLAKE_PRIVATE_KEY_PASSPHRASE || undefined,
      clientSessionKeepAlive: true,
    });
    conn.connect((err, c) => {
      if (err) {
        connectionPromise = null;
        reject(err);
      } else resolve(c);
    });
  });
  return connectionPromise;
}

function required(name: string): string {
  const v = process.env[name];
  if (!v) throw new Error(`${name} is not set`);
  return v;
}

/**
 * Run a read-only query. Refuses anything that matches a banned column pattern
 * or is not a SELECT/WITH statement.
 */
export async function query<T extends Row = Row>(sql: string, binds: snowflake.Binds = []): Promise<T[]> {
  const trimmed = sql.trim();
  if (!/^(select|with)\b/i.test(trimmed)) {
    throw new Error("Only SELECT queries are permitted");
  }
  assertQuerySafe(trimmed);

  const conn = await getConnection();
  return new Promise((resolve, reject) => {
    conn.execute({
      sqlText: trimmed,
      binds,
      complete: (err, _stmt, rows) => {
        if (err) reject(err);
        else resolve((rows ?? []) as T[]);
      },
    });
  });
}

export function snowflakeConfigured(): boolean {
  return !!(
    process.env.SNOWFLAKE_ACCOUNT &&
    process.env.SNOWFLAKE_USER &&
    process.env.SNOWFLAKE_PRIVATE_KEY
  );
}
