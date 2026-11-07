CREATE TABLE demo_snapshot (
 id smallint PRIMARY KEY CHECK(id=1),
 payload jsonb NOT NULL,
 updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE telegram_updates (
 update_id bigint PRIMARY KEY,
 chat_hash text NOT NULL,
 command text NOT NULL,
 status text NOT NULL,
 messages integer NOT NULL DEFAULT 0,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE telegram_cooldowns (
 chat_hash text PRIMARY KEY,
 requested_at timestamptz NOT NULL DEFAULT now()
);
