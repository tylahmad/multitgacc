-- ============================================================
-- AlSarab ShopBot - Complete Schema v3.0.1 (Professional - FIXED)
-- القاعدة الذهبية: كل ما يواجهه البوت لأول مرة يتعلمه
-- ============================================================
-- CHANGELOG v3.0.1:
--   [FIX] completed_tasks_history: فهرس فريد يتعامل مع parent_task_id = NULL
--         (COALESCE) - يمنع التكرار ويجعل insert→update يعمل بشكل صحيح
--   [FIX] tasks_queue: إضافة ALTER لعمود max_retries للقواعد القديمة
--   [FIX] فهرس جديد (status, retry_count) لسرعة مسح المهام العالقة
--   [FIX] حماية إنشاء الفهرس الفريد من الفشل عند وجود بيانات مكررة
-- ============================================================

-- Enable extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ==================== USERS ====================
CREATE TABLE IF NOT EXISTS users (
    user_id BIGINT PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    balance DECIMAL(10, 2) DEFAULT 0.00 CHECK (balance >= 0),
    points INTEGER DEFAULT 0 CHECK (points >= 0),
    referrer_id BIGINT REFERENCES users(user_id) ON DELETE SET NULL,
    total_referrals INTEGER DEFAULT 0,
    joined_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_active_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    is_banned BOOLEAN DEFAULT FALSE,
    language_code TEXT DEFAULT 'ar'
);
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_referrer_id ON users(referrer_id);

-- ==================== INVENTORY ====================
CREATE TABLE IF NOT EXISTS inventory (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    country TEXT NOT NULL,
    phone_number TEXT UNIQUE NOT NULL,
    price DECIMAL(10, 2) NOT NULL CHECK (price > 0),
    points_price INTEGER DEFAULT 0 CHECK (points_price >= 0),
    is_sold BOOLEAN DEFAULT FALSE,
    buyer_id BIGINT REFERENCES users(user_id) ON DELETE SET NULL,
    session_expires_at TIMESTAMP WITH TIME ZONE,
    activation_code TEXT,
    twofa_code TEXT,
    session_string TEXT,
    added_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    sold_at TIMESTAMP WITH TIME ZONE,
    status TEXT DEFAULT 'available' CHECK (status IN ('available', 'sold', 'expired', 'reserved'))
);
CREATE INDEX IF NOT EXISTS idx_inventory_country ON inventory(country);
CREATE INDEX IF NOT EXISTS idx_inventory_status ON inventory(status);
CREATE INDEX IF NOT EXISTS idx_inventory_is_sold ON inventory(is_sold);
CREATE INDEX IF NOT EXISTS idx_inventory_buyer_id ON inventory(buyer_id);

-- ==================== PROXY LIST ====================
CREATE TABLE IF NOT EXISTS proxy_list (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    proxy_type TEXT DEFAULT 'socks5' CHECK (proxy_type IN ('socks5', 'http', 'mtproto')),
    host TEXT NOT NULL,
    port INTEGER NOT NULL CHECK (port > 0 AND port < 65536),
    username TEXT,
    password TEXT,
    max_accounts INTEGER DEFAULT 5 CHECK (max_accounts > 0),
    used_count INTEGER DEFAULT 0 CHECK (used_count >= 0),
    is_active BOOLEAN DEFAULT TRUE,
    added_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_used_at TIMESTAMP WITH TIME ZONE
);
CREATE INDEX IF NOT EXISTS idx_proxy_list_is_active ON proxy_list(is_active);

-- ==================== CLIENT SESSIONS ====================
CREATE TABLE IF NOT EXISTS client_sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    phone TEXT UNIQUE NOT NULL,
    session_string TEXT NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    is_banned BOOLEAN DEFAULT FALSE,
    last_used_at TIMESTAMP WITH TIME ZONE,
    error_message TEXT,
    added_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    api_id INTEGER,
    api_hash TEXT,
    proxy_id UUID REFERENCES proxy_list(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_client_sessions_is_active ON client_sessions(is_active);

-- ==================== ACCOUNT GROUPS ====================
CREATE TABLE IF NOT EXISTS account_groups (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    group_name TEXT NOT NULL,
    group_type TEXT DEFAULT 'other' CHECK (group_type IN ('arabic', 'foreign', 'other')),
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ==================== TASKS QUEUE (v3.0 FIXED) ====================
CREATE TABLE IF NOT EXISTS tasks_queue (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    target_bot_link TEXT NOT NULL,
    task_type TEXT NOT NULL CHECK (task_type IN ('join', 'verify', 'click', 'forward', 'solve', 'composite', 'follow_channel', 'react_post', 'vote_poll', 'smart', 'manual', 'start', 'subscribe', 'check', 'math', 'phone', 'emoji', 'language', 'text', 'visit')),
    session_id UUID REFERENCES client_sessions(id) ON DELETE SET NULL,
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'completed', 'failed', 'waiting_fallback')),
    ref_id TEXT,
    target_message_link TEXT,
    solve_pattern TEXT,
    result_data JSONB,
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    speed TEXT DEFAULT 'medium' CHECK (speed IN ('slow', 'medium', 'fast')),
    composite_steps TEXT DEFAULT '[]',
    emoji_target TEXT DEFAULT '👍',
    vote_option TEXT DEFAULT '0',
    required_accounts INTEGER DEFAULT 1,
    -- v3.0 NEW COLUMNS
    parent_task_id UUID REFERENCES tasks_queue(id) ON DELETE SET NULL,
    multi_account BOOLEAN DEFAULT FALSE,
    channel_list TEXT DEFAULT '[]',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE
);
CREATE INDEX IF NOT EXISTS idx_tasks_queue_status ON tasks_queue(status);
CREATE INDEX IF NOT EXISTS idx_tasks_queue_session_id ON tasks_queue(session_id);
CREATE INDEX IF NOT EXISTS idx_tasks_queue_created_at ON tasks_queue(created_at);
CREATE INDEX IF NOT EXISTS idx_tasks_queue_parent ON tasks_queue(parent_task_id);
-- FIXED v3.0.1: فهرس لمسح المهام العالقة
CREATE INDEX IF NOT EXISTS idx_tasks_queue_status_retry ON tasks_queue(status, retry_count);

-- For existing DBs: add v2 + v3 columns
ALTER TABLE tasks_queue ADD COLUMN IF NOT EXISTS speed TEXT DEFAULT 'medium';
ALTER TABLE tasks_queue ADD COLUMN IF NOT EXISTS composite_steps TEXT DEFAULT '[]';
ALTER TABLE tasks_queue ADD COLUMN IF NOT EXISTS emoji_target TEXT DEFAULT '👍';
ALTER TABLE tasks_queue ADD COLUMN IF NOT EXISTS vote_option TEXT DEFAULT '0';
ALTER TABLE tasks_queue ADD COLUMN IF NOT EXISTS required_accounts INTEGER DEFAULT 1;
ALTER TABLE tasks_queue ADD COLUMN IF NOT EXISTS parent_task_id UUID REFERENCES tasks_queue(id) ON DELETE SET NULL;
ALTER TABLE tasks_queue ADD COLUMN IF NOT EXISTS multi_account BOOLEAN DEFAULT FALSE;
ALTER TABLE tasks_queue ADD COLUMN IF NOT EXISTS channel_list TEXT DEFAULT '[]';
-- FIXED v3.0.1: عمود max_retries للقواعد القديمة
ALTER TABLE tasks_queue ADD COLUMN IF NOT EXISTS max_retries INTEGER DEFAULT 3;

-- Fix check constraint for task_type
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'tasks_queue_task_type_check') THEN
        ALTER TABLE tasks_queue DROP CONSTRAINT tasks_queue_task_type_check;
    END IF;
END $$;
ALTER TABLE tasks_queue ADD CONSTRAINT tasks_queue_task_type_check CHECK (task_type IN ('join', 'verify', 'click', 'forward', 'solve', 'composite', 'follow_channel', 'react_post', 'vote_poll', 'smart', 'manual', 'start', 'subscribe', 'check', 'math', 'phone', 'emoji', 'language', 'text', 'visit'));

-- Fix status check
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'tasks_queue_status_check') THEN
        ALTER TABLE tasks_queue DROP CONSTRAINT tasks_queue_status_check;
    END IF;
END $$;
ALTER TABLE tasks_queue ADD CONSTRAINT tasks_queue_status_check CHECK (status IN ('pending', 'processing', 'completed', 'failed', 'waiting_fallback'));

-- ==================== BOT TEMPLATES ====================
CREATE TABLE IF NOT EXISTS bot_templates (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    bot_username TEXT NOT NULL UNIQUE,
    template_name TEXT,
    steps TEXT DEFAULT '[]',
    total_steps INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    fail_count INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_used_at TIMESTAMP WITH TIME ZONE
);
CREATE INDEX IF NOT EXISTS idx_bot_templates_username ON bot_templates(bot_username);

-- ==================== COMPLETED TASKS HISTORY (v3.0.1 FIXED) ====================
CREATE TABLE IF NOT EXISTS completed_tasks_history (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id UUID REFERENCES client_sessions(id) ON DELETE CASCADE,
    bot_username TEXT NOT NULL,
    task_type TEXT,
    parent_task_id UUID REFERENCES tasks_queue(id) ON DELETE SET NULL,
    completed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_completed_history_session ON completed_tasks_history(session_id);
CREATE INDEX IF NOT EXISTS idx_completed_history_bot ON completed_tasks_history(bot_username);
CREATE INDEX IF NOT EXISTS idx_completed_history_parent ON completed_tasks_history(parent_task_id);

-- v3.0: عمود parent_task_id للقواعد القديمة
ALTER TABLE completed_tasks_history ADD COLUMN IF NOT EXISTS parent_task_id UUID REFERENCES tasks_queue(id) ON DELETE SET NULL;
ALTER TABLE completed_tasks_history ADD COLUMN IF NOT EXISTS task_type TEXT;

-- إزالة القيود الفريدة القديمة (المحتمل وجودها من إصدارات سابقة)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'completed_tasks_history_session_id_bot_username_key') THEN
        ALTER TABLE completed_tasks_history DROP CONSTRAINT completed_tasks_history_session_id_bot_username_key;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'completed_tasks_history_session_id_bot_username_parent_task_id_key') THEN
        ALTER TABLE completed_tasks_history DROP CONSTRAINT completed_tasks_history_session_id_bot_username_parent_task_id_key;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'unique_session_bot_parent') THEN
        ALTER TABLE completed_tasks_history DROP CONSTRAINT unique_session_bot_parent;
    END IF;
END $$;

-- FIXED v3.0.1: فهرس فريد يعامل NULL بشكل صحيح (COALESCE)
-- يمنع تكرار السجلات حتى عندما يكون parent_task_id = NULL
DO $$
BEGIN
    DROP INDEX IF EXISTS unique_session_bot_parent;
    CREATE UNIQUE INDEX IF NOT EXISTS uq_completed_session_bot_parent
        ON completed_tasks_history (session_id, bot_username, COALESCE(parent_task_id::text, 'root'));
EXCEPTION
    WHEN unique_violation OR duplicate_table THEN
        -- يوجد بيانات مكررة قديمة: نحذف المكررات ثم نعيد الإنشاء
        DELETE FROM completed_tasks_history a
        USING completed_tasks_history b
        WHERE a.id > b.id
          AND a.session_id = b.session_id
          AND a.bot_username = b.bot_username
          AND COALESCE(a.parent_task_id::text, 'root') = COALESCE(b.parent_task_id::text, 'root');
        CREATE UNIQUE INDEX uq_completed_session_bot_parent
            ON completed_tasks_history (session_id, bot_username, COALESCE(parent_task_id::text, 'root'));
END $$;

-- ==================== TASK LOGS ====================
CREATE TABLE IF NOT EXISTS task_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id UUID REFERENCES client_sessions(id) ON DELETE SET NULL,
    bot_username TEXT,
    task_type TEXT,
    status TEXT,
    message TEXT,
    parent_task_id UUID REFERENCES tasks_queue(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_task_logs_session ON task_logs(session_id);
CREATE INDEX IF NOT EXISTS idx_task_logs_parent ON task_logs(parent_task_id);
ALTER TABLE task_logs ADD COLUMN IF NOT EXISTS parent_task_id UUID REFERENCES tasks_queue(id) ON DELETE SET NULL;

-- ==================== FALLBACK REQUESTS (NEW v3.0) ====================
CREATE TABLE IF NOT EXISTS fallback_requests (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    parent_task_id UUID REFERENCES tasks_queue(id) ON DELETE SET NULL,
    session_id UUID REFERENCES client_sessions(id) ON DELETE SET NULL,
    bot_username TEXT NOT NULL,
    message_text TEXT,
    buttons TEXT DEFAULT '[]',
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'answered', 'executed', 'expired')),
    admin_response TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    answered_at TIMESTAMP WITH TIME ZONE,
    executed_at TIMESTAMP WITH TIME ZONE
);
CREATE INDEX IF NOT EXISTS idx_fallback_status ON fallback_requests(status);
CREATE INDEX IF NOT EXISTS idx_fallback_parent ON fallback_requests(parent_task_id);

-- ==================== TRANSACTIONS ====================
CREATE TABLE IF NOT EXISTS transactions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    method TEXT NOT NULL CHECK (method IN ('binance', 'cham_cash')),
    amount DECIMAL(10, 2) NOT NULL CHECK (amount > 0),
    tx_id TEXT,
    sender_info TEXT,
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    admin_id BIGINT,
    admin_note TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    processed_at TIMESTAMP WITH TIME ZONE
);
CREATE INDEX IF NOT EXISTS idx_transactions_user_id ON transactions(user_id);
CREATE INDEX IF NOT EXISTS idx_transactions_status ON transactions(status);
CREATE INDEX IF NOT EXISTS idx_transactions_created_at ON transactions(created_at);

-- ==================== SETTINGS ====================
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT,
    is_enabled BOOLEAN DEFAULT FALSE,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

INSERT INTO settings (key, value, is_enabled) VALUES
    ('proxy_enabled', 'false', false),
    ('proxy_host', '', false),
    ('proxy_port', '', false),
    ('proxy_username', '', false),
    ('proxy_password', '', false),
    ('proxy_type', 'socks5', false),
    ('bot_maintenance_mode', 'false', false),
    ('min_deposit_amount', '0.50', true),
    ('session_duration_minutes', '15', true),
    ('referral_points_reward', '10', true),
    ('mandatory_channels', '[]', true),
    ('support_username', '@support', true),
    ('worker_last_heartbeat', '', false),
    -- v3.0 NEW SETTINGS
    ('ai_agent_enabled', 'true', true),
    ('ai_confidence_threshold', '70', true),
    ('ai_template_success_threshold', '80', true),
    ('ai_fallback_enabled', 'true', true),
    ('ai_default_language', 'english', true),
    ('ai_report_enabled', 'true', true),
    ('ai_delay_between_accounts_min', '30', true),
    ('ai_delay_between_accounts_max', '300', true)
ON CONFLICT (key) DO NOTHING;

-- ==================== FUNCTIONS & TRIGGERS ====================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

DROP TRIGGER IF EXISTS update_settings_updated_at ON settings;
CREATE TRIGGER update_settings_updated_at
    BEFORE UPDATE ON settings
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_templates_updated_at ON bot_templates;
CREATE TRIGGER update_templates_updated_at
    BEFORE UPDATE ON bot_templates
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE OR REPLACE FUNCTION update_user_last_active()
RETURNS TRIGGER AS $$
BEGIN
    NEW.last_active_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

DROP TRIGGER IF EXISTS update_user_last_active_trigger ON users;
CREATE TRIGGER update_user_last_active_trigger
    BEFORE UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION update_user_last_active();

-- ==================== VIEWS ====================
CREATE OR REPLACE VIEW available_inventory AS
SELECT
    i.id,
    i.country,
    i.phone_number,
    i.price,
    i.points_price,
    i.added_at,
    COUNT(*) OVER (PARTITION BY i.country) as available_count
FROM inventory i
WHERE i.is_sold = FALSE AND i.status = 'available';

CREATE OR REPLACE VIEW user_transactions_summary AS
SELECT
    u.user_id,
    u.username,
    u.balance,
    u.points,
    COUNT(CASE WHEN t.status = 'approved' THEN 1 END) as approved_deposits,
    COALESCE(SUM(CASE WHEN t.status = 'approved' THEN t.amount ELSE 0 END), 0) as total_deposited,
    COUNT(CASE WHEN t.status = 'pending' THEN 1 END) as pending_deposits
FROM users u
LEFT JOIN transactions t ON u.user_id = t.user_id
GROUP BY u.user_id, u.username, u.balance, u.points;

-- ==================== GRANTS (v3.0 FIXED) ====================
GRANT ALL ON ALL TABLES IN SCHEMA public TO postgres;
GRANT ALL ON ALL TABLES IN SCHEMA public TO service_role;
GRANT ALL ON ALL TABLES IN SCHEMA public TO authenticated;
GRANT ALL ON ALL TABLES IN SCHEMA public TO anon;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO postgres, service_role, authenticated, anon;
GRANT ALL ON ALL FUNCTIONS IN SCHEMA public TO postgres, service_role;

-- ==================== RLS POLICIES (v3.0 NEW) ====================
-- Enable RLS for new tables with permissive policies for service_role
ALTER TABLE fallback_requests ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Service role full access fallback" ON fallback_requests;
CREATE POLICY "Service role full access fallback" ON fallback_requests FOR ALL USING (true) WITH CHECK (true);

ALTER TABLE task_logs ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Service role full access logs" ON task_logs;
CREATE POLICY "Service role full access logs" ON task_logs FOR ALL USING (true) WITH CHECK (true);

ALTER TABLE proxy_list ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Service role full access proxy" ON proxy_list;
CREATE POLICY "Service role full access proxy" ON proxy_list FOR ALL USING (true) WITH CHECK (true);

ALTER TABLE bot_templates ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Service role full access templates" ON bot_templates;
CREATE POLICY "Service role full access templates" ON bot_templates FOR ALL USING (true) WITH CHECK (true);

ALTER TABLE account_groups ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Service role full access groups" ON account_groups;
CREATE POLICY "Service role full access groups" ON account_groups FOR ALL USING (true) WITH CHECK (true);
