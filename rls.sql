-- AMOS Watches: PostgreSQL RLS + GRANTs
-- Apply on Supabase/Postgres. SQLite in the app enforces the same rules in FastAPI.

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS admin_users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('owner', 'admin', 'staff')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS categories (
  id BIGSERIAL PRIMARY KEY,
  slug TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  sort_order INT NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS products (
  id BIGSERIAL PRIMARY KEY,
  category_id BIGINT NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  price INT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  image TEXT NOT NULL,
  featured BOOLEAN NOT NULL DEFAULT FALSE,
  sort_order INT NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS orders (
  id BIGSERIAL PRIMARY KEY,
  public_id TEXT UNIQUE NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('pending','awaiting_payment','paid','finalized','cancelled')),
  customer_name TEXT NOT NULL,
  phone TEXT NOT NULL,
  email TEXT NOT NULL,
  total INT NOT NULL,
  notes TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  paid_at TIMESTAMPTZ,
  finalized_at TIMESTAMPTZ,
  created_by UUID REFERENCES admin_users(id)
);

CREATE TABLE IF NOT EXISTS order_items (
  id BIGSERIAL PRIMARY KEY,
  order_id BIGINT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  product_id BIGINT REFERENCES products(id) ON DELETE SET NULL,
  title TEXT NOT NULL,
  price INT NOT NULL,
  qty INT NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS payments (
  id BIGSERIAL PRIMARY KEY,
  order_id BIGINT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  provider TEXT NOT NULL DEFAULT 'yaad',
  yaad_id TEXT,
  acode TEXT,
  ccode TEXT,
  amount INT,
  status TEXT NOT NULL,
  payload JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS security_events (
  id BIGSERIAL PRIMARY KEY,
  kind TEXT NOT NULL,
  message TEXT NOT NULL,
  ip TEXT,
  actor UUID REFERENCES admin_users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS google_reviews (
  id BIGSERIAL PRIMARY KEY,
  author TEXT NOT NULL,
  rating INT NOT NULL,
  body TEXT NOT NULL,
  relative_time TEXT,
  fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS presence (
  id TEXT PRIMARY KEY,
  last_seen TIMESTAMPTZ NOT NULL DEFAULT now(),
  page TEXT
);

CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

ALTER TABLE admin_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE categories ENABLE ROW LEVEL SECURITY;
ALTER TABLE products ENABLE ROW LEVEL SECURITY;
ALTER TABLE orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE order_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE payments ENABLE ROW LEVEL SECURITY;
ALTER TABLE security_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE google_reviews ENABLE ROW LEVEL SECURITY;
ALTER TABLE presence ENABLE ROW LEVEL SECURITY;
ALTER TABLE settings ENABLE ROW LEVEL SECURITY;

CREATE OR REPLACE FUNCTION public.amos_role()
RETURNS TEXT LANGUAGE sql STABLE AS $$
  SELECT COALESCE(auth.jwt() ->> 'role', 'anon')
$$;

-- Catalog is public read
CREATE POLICY categories_read ON categories FOR SELECT USING (true);
CREATE POLICY products_read ON products FOR SELECT USING (true);
CREATE POLICY reviews_read ON google_reviews FOR SELECT USING (true);
CREATE POLICY presence_read ON presence FOR SELECT USING (true);

CREATE POLICY categories_write ON categories FOR ALL
  USING (amos_role() IN ('owner','admin'))
  WITH CHECK (amos_role() IN ('owner','admin'));

CREATE POLICY products_write ON products FOR ALL
  USING (amos_role() IN ('owner','admin'))
  WITH CHECK (amos_role() IN ('owner','admin'));

CREATE POLICY orders_insert ON orders FOR INSERT
  WITH CHECK (true);

CREATE POLICY orders_select ON orders FOR SELECT
  USING (amos_role() IN ('owner','admin','staff') OR public_id = current_setting('request.headers', true)::json ->> 'x-order-id');

CREATE POLICY orders_update ON orders FOR UPDATE
  USING (amos_role() IN ('owner','admin','staff'));

CREATE POLICY order_items_insert ON order_items FOR INSERT WITH CHECK (true);
CREATE POLICY order_items_select ON order_items FOR SELECT
  USING (amos_role() IN ('owner','admin','staff'));

CREATE POLICY payments_insert ON payments FOR INSERT WITH CHECK (true);
CREATE POLICY payments_select ON payments FOR SELECT
  USING (amos_role() IN ('owner','admin','staff'));

CREATE POLICY security_staff ON security_events FOR SELECT
  USING (amos_role() IN ('owner','admin'));
CREATE POLICY security_insert ON security_events FOR INSERT
  WITH CHECK (amos_role() IN ('owner','admin','staff') OR amos_role() = 'anon');

CREATE POLICY users_owner ON admin_users FOR ALL
  USING (amos_role() = 'owner')
  WITH CHECK (amos_role() = 'owner');

CREATE POLICY users_self ON admin_users FOR SELECT
  USING (amos_role() IN ('owner','admin','staff'));

CREATE POLICY reviews_write ON google_reviews FOR ALL
  USING (amos_role() IN ('owner','admin'))
  WITH CHECK (amos_role() IN ('owner','admin'));

CREATE POLICY settings_admin ON settings FOR ALL
  USING (amos_role() IN ('owner','admin'))
  WITH CHECK (amos_role() IN ('owner','admin'));

CREATE POLICY presence_write ON presence FOR ALL
  USING (true) WITH CHECK (true);

GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;
GRANT SELECT ON categories, products, google_reviews, presence TO anon, authenticated;
GRANT INSERT ON orders, order_items, payments, security_events, presence TO anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO service_role;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO anon, authenticated, service_role;
