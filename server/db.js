const { Pool } = require("pg");

const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
  ssl: process.env.DATABASE_URL && process.env.DATABASE_URL.includes("localhost")
    ? false
    : { rejectUnauthorized: false },
});

const SCHEMA = `
CREATE TABLE IF NOT EXISTS branches (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  username TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('master','staff')),
  branch TEXT
);
CREATE TABLE IF NOT EXISTS items (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  unit TEXT,
  min_stock NUMERIC DEFAULT 0,
  max_stock NUMERIC,
  pieces_per_pack NUMERIC,
  cost_price NUMERIC
);
CREATE TABLE IF NOT EXISTS stock (
  branch TEXT NOT NULL,
  item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  qty NUMERIC DEFAULT 0,
  PRIMARY KEY (branch, item_id)
);
CREATE TABLE IF NOT EXISTS menu_items (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  price NUMERIC DEFAULT 0,
  recipe JSONB DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS sales (
  id SERIAL PRIMARY KEY,
  branch TEXT NOT NULL,
  cashier TEXT,
  items JSONB NOT NULL,
  total NUMERIC NOT NULL,
  ts TIMESTAMPTZ NOT NULL DEFAULT now(),
  mode TEXT,
  payments JSONB,
  paid_total NUMERIC,
  change NUMERIC,
  voided BOOLEAN DEFAULT false,
  voided_by TEXT,
  voided_at TIMESTAMPTZ,
  void_reason TEXT,
  consumption JSONB
);
CREATE TABLE IF NOT EXISTS suppliers (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS purchases (
  id SERIAL PRIMARY KEY,
  branch TEXT NOT NULL,
  supplier_id TEXT,
  supplier_name TEXT,
  items JSONB NOT NULL,
  total NUMERIC NOT NULL,
  ts TIMESTAMPTZ NOT NULL DEFAULT now(),
  recorded_by TEXT
);
CREATE TABLE IF NOT EXISTS transfers (
  id SERIAL PRIMARY KEY,
  src_branch TEXT NOT NULL,
  dst_branch TEXT NOT NULL,
  item_id TEXT NOT NULL,
  item_name TEXT,
  qty NUMERIC NOT NULL,
  status TEXT DEFAULT 'pending',
  requested_by TEXT,
  requested_at TIMESTAMPTZ DEFAULT now(),
  decided_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS payment_methods (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  ord INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS stock_ledger (
  id TEXT PRIMARY KEY,
  branch TEXT NOT NULL,
  date DATE NOT NULL,
  rows JSONB NOT NULL,
  recorded_by TEXT,
  updated_at TIMESTAMPTZ DEFAULT now()
);
`;

async function initSchema() {
  await pool.query(SCHEMA);
}

module.exports = { pool, initSchema };
