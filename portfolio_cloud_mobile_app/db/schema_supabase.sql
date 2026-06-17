create table if not exists holdings (
    id bigserial primary key,
    row_id text unique,
    sort_order integer,
    display_order integer,
    major_asset_class text,
    sub_asset_class text,
    asset_class text,
    market text,
    symbol text,
    name text,
    saebit_quantity numeric default 0,
    heeju_quantity numeric default 0,
    total_quantity numeric default 0,
    quantity numeric default 0,
    avg_price numeric default 0,
    currency text,
    memo text,
    created_at timestamptz default now(),
    updated_at timestamptz default now()
);

create table if not exists transactions (
    id bigserial primary key,
    trade_datetime text,
    trade_type text,
    account text,
    major_asset_class text,
    sub_asset_class text,
    asset_class text,
    market text,
    symbol text,
    name text,
    quantity numeric default 0,
    price numeric default 0,
    amount numeric default 0,
    currency text,
    memo text,
    after_saebit_quantity numeric default 0,
    after_heeju_quantity numeric default 0,
    after_total_quantity numeric default 0,
    after_quantity numeric default 0,
    after_avg_price numeric default 0,
    created_at timestamptz default now(),
    updated_at timestamptz default now(),
    constraint transactions_trade_type_check check (trade_type is null or trade_type in ('신규매수', '추가매수', '매수')),
    constraint transactions_account_check check (account is null or account in ('새빛', '희주'))
);

create table if not exists capital_flows (
    id bigserial primary key,
    flow_datetime text,
    flow_type text,
    amount numeric default 0,
    currency text,
    memo text,
    after_principal numeric default 0,
    created_at timestamptz default now(),
    updated_at timestamptz default now()
);

create table if not exists prices (
    id bigserial primary key,
    symbol text,
    current_price numeric,
    currency text,
    usd_krw numeric,
    last_price_updated_at text,
    status text,
    created_at timestamptz default now(),
    updated_at timestamptz default now()
);

create table if not exists portfolio_snapshots (
    id bigserial primary key,
    snapshot_datetime text,
    year integer,
    snapshot_type text,
    total_value numeric default 0,
    principal numeric default 0,
    profit_loss numeric default 0,
    cumulative_return numeric default 0,
    memo text,
    created_at timestamptz default now(),
    updated_at timestamptz default now()
);

create table if not exists disclosures (
    id bigserial primary key,
    saved_at text,
    market text,
    symbol text,
    name text,
    disclosure_date text,
    disclosure_type text,
    title text,
    source_url text,
    disclosure_id text,
    summary text,
    importance text,
    status text,
    created_at timestamptz default now(),
    updated_at timestamptz default now()
);

create table if not exists disclosure_watchlist (
    id bigserial primary key,
    market text,
    symbol text,
    name text,
    tracking_status text,
    add_method text,
    added_at text,
    memo text,
    created_at timestamptz default now(),
    updated_at timestamptz default now()
);

create table if not exists disclosure_logs (
    id bigserial primary key,
    run_datetime text,
    query_mode text,
    start_date text,
    end_date text,
    target_count integer,
    target_symbols text,
    success_count integer,
    failure_count integer,
    fetched_count integer,
    new_saved_count integer,
    duplicate_count integer,
    filtered_count integer,
    error_message text,
    detail_log text,
    created_at timestamptz default now(),
    updated_at timestamptz default now()
);

create table if not exists settings (
    id bigserial primary key,
    setting_key text unique,
    setting_value text,
    created_at timestamptz default now(),
    updated_at timestamptz default now()
);

alter table holdings add column if not exists row_id text;
alter table holdings add column if not exists sort_order integer;
alter table holdings add column if not exists display_order integer;
alter table holdings add column if not exists major_asset_class text;
alter table holdings add column if not exists sub_asset_class text;
alter table holdings add column if not exists asset_class text;
alter table holdings add column if not exists market text;
alter table holdings add column if not exists symbol text;
alter table holdings add column if not exists name text;
alter table holdings add column if not exists saebit_quantity numeric default 0;
alter table holdings add column if not exists heeju_quantity numeric default 0;
alter table holdings add column if not exists total_quantity numeric default 0;
alter table holdings add column if not exists quantity numeric default 0;
alter table holdings add column if not exists avg_price numeric default 0;
alter table holdings add column if not exists currency text;
alter table holdings add column if not exists memo text;
alter table holdings add column if not exists created_at timestamptz default now();
alter table holdings add column if not exists updated_at timestamptz default now();

alter table transactions add column if not exists trade_datetime text;
alter table transactions add column if not exists trade_type text;
alter table transactions add column if not exists account text;
alter table transactions add column if not exists major_asset_class text;
alter table transactions add column if not exists sub_asset_class text;
alter table transactions add column if not exists asset_class text;
alter table transactions add column if not exists market text;
alter table transactions add column if not exists symbol text;
alter table transactions add column if not exists name text;
alter table transactions add column if not exists quantity numeric default 0;
alter table transactions add column if not exists price numeric default 0;
alter table transactions add column if not exists amount numeric default 0;
alter table transactions add column if not exists currency text;
alter table transactions add column if not exists memo text;
alter table transactions add column if not exists after_saebit_quantity numeric default 0;
alter table transactions add column if not exists after_heeju_quantity numeric default 0;
alter table transactions add column if not exists after_total_quantity numeric default 0;
alter table transactions add column if not exists after_quantity numeric default 0;
alter table transactions add column if not exists after_avg_price numeric default 0;
alter table transactions add column if not exists created_at timestamptz default now();
alter table transactions add column if not exists updated_at timestamptz default now();

alter table capital_flows add column if not exists flow_datetime text;
alter table capital_flows add column if not exists flow_type text;
alter table capital_flows add column if not exists amount numeric default 0;
alter table capital_flows add column if not exists currency text;
alter table capital_flows add column if not exists memo text;
alter table capital_flows add column if not exists after_principal numeric default 0;
alter table capital_flows add column if not exists created_at timestamptz default now();
alter table capital_flows add column if not exists updated_at timestamptz default now();

alter table prices add column if not exists symbol text;
alter table prices add column if not exists current_price numeric;
alter table prices add column if not exists currency text;
alter table prices add column if not exists usd_krw numeric;
alter table prices add column if not exists last_price_updated_at text;
alter table prices add column if not exists status text;
alter table prices add column if not exists created_at timestamptz default now();
alter table prices add column if not exists updated_at timestamptz default now();

alter table settings add column if not exists setting_key text;
alter table settings add column if not exists setting_value text;
alter table settings add column if not exists created_at timestamptz default now();
alter table settings add column if not exists updated_at timestamptz default now();

alter table portfolio_snapshots add column if not exists snapshot_datetime text;
alter table portfolio_snapshots add column if not exists year integer;
alter table portfolio_snapshots add column if not exists snapshot_type text;
alter table portfolio_snapshots add column if not exists total_value numeric default 0;
alter table portfolio_snapshots add column if not exists principal numeric default 0;
alter table portfolio_snapshots add column if not exists profit_loss numeric default 0;
alter table portfolio_snapshots add column if not exists cumulative_return numeric default 0;
alter table portfolio_snapshots add column if not exists memo text;
alter table portfolio_snapshots add column if not exists created_at timestamptz default now();
alter table portfolio_snapshots add column if not exists updated_at timestamptz default now();

alter table disclosures add column if not exists saved_at text;
alter table disclosures add column if not exists market text;
alter table disclosures add column if not exists symbol text;
alter table disclosures add column if not exists name text;
alter table disclosures add column if not exists disclosure_date text;
alter table disclosures add column if not exists disclosure_type text;
alter table disclosures add column if not exists title text;
alter table disclosures add column if not exists source_url text;
alter table disclosures add column if not exists disclosure_id text;
alter table disclosures add column if not exists summary text;
alter table disclosures add column if not exists importance text;
alter table disclosures add column if not exists status text;
alter table disclosures add column if not exists created_at timestamptz default now();
alter table disclosures add column if not exists updated_at timestamptz default now();

alter table disclosure_watchlist add column if not exists market text;
alter table disclosure_watchlist add column if not exists symbol text;
alter table disclosure_watchlist add column if not exists name text;
alter table disclosure_watchlist add column if not exists tracking_status text;
alter table disclosure_watchlist add column if not exists add_method text;
alter table disclosure_watchlist add column if not exists added_at text;
alter table disclosure_watchlist add column if not exists memo text;
alter table disclosure_watchlist add column if not exists created_at timestamptz default now();
alter table disclosure_watchlist add column if not exists updated_at timestamptz default now();

alter table disclosure_logs add column if not exists run_datetime text;
alter table disclosure_logs add column if not exists query_mode text;
alter table disclosure_logs add column if not exists start_date text;
alter table disclosure_logs add column if not exists end_date text;
alter table disclosure_logs add column if not exists target_count integer;
alter table disclosure_logs add column if not exists target_symbols text;
alter table disclosure_logs add column if not exists success_count integer;
alter table disclosure_logs add column if not exists failure_count integer;
alter table disclosure_logs add column if not exists fetched_count integer;
alter table disclosure_logs add column if not exists new_saved_count integer;
alter table disclosure_logs add column if not exists duplicate_count integer;
alter table disclosure_logs add column if not exists filtered_count integer;
alter table disclosure_logs add column if not exists error_message text;
alter table disclosure_logs add column if not exists detail_log text;
alter table disclosure_logs add column if not exists created_at timestamptz default now();
alter table disclosure_logs add column if not exists updated_at timestamptz default now();

create index if not exists idx_holdings_symbol on holdings (symbol);
create index if not exists idx_holdings_market_symbol on holdings (market, symbol);
create index if not exists idx_transactions_account_symbol on transactions (account, symbol);
create index if not exists idx_transactions_symbol on transactions (symbol);
create index if not exists idx_transactions_account on transactions (account);
create index if not exists idx_disclosures_symbol on disclosures (market, symbol);

-- Protect tables exposed through the Supabase public API.
-- The Streamlit app uses the PostgreSQL connection string, so enabling RLS
-- and revoking API-role grants blocks anonymous REST access without changing
-- the app's data flow.
alter table holdings enable row level security;
alter table prices enable row level security;
alter table transactions enable row level security;
alter table capital_flows enable row level security;
alter table portfolio_snapshots enable row level security;
alter table disclosures enable row level security;
alter table disclosure_logs enable row level security;
alter table disclosure_watchlist enable row level security;
alter table settings enable row level security;

revoke all on table holdings from anon, authenticated, public;
revoke all on table prices from anon, authenticated, public;
revoke all on table transactions from anon, authenticated, public;
revoke all on table capital_flows from anon, authenticated, public;
revoke all on table portfolio_snapshots from anon, authenticated, public;
revoke all on table disclosures from anon, authenticated, public;
revoke all on table disclosure_logs from anon, authenticated, public;
revoke all on table disclosure_watchlist from anon, authenticated, public;
revoke all on table settings from anon, authenticated, public;

revoke all on all sequences in schema public from anon, authenticated, public;
alter default privileges in schema public revoke all on tables from anon, authenticated, public;
alter default privileges in schema public revoke all on sequences from anon, authenticated, public;
