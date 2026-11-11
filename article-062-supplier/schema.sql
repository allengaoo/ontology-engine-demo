-- @db purchase
CREATE TABLE supplier (
    id integer PRIMARY KEY,
    name text NOT NULL
);

CREATE TABLE purchase_order (
    id integer PRIMARY KEY,
    factory_id integer NOT NULL,
    supplier_id integer NOT NULL REFERENCES supplier (id),
    annual_amount bigint NOT NULL,
    write_count integer NOT NULL DEFAULT 0
);

CREATE TABLE change_order (
    id integer PRIMARY KEY,
    po_id integer NOT NULL UNIQUE REFERENCES purchase_order (id),
    new_supplier_id integer NOT NULL REFERENCES supplier (id),
    annual_amount bigint NOT NULL,
    status text NOT NULL
);

CREATE TABLE audit_log (
    id bigserial PRIMARY KEY,
    change_id integer NOT NULL,
    actor text NOT NULL,
    result text NOT NULL,
    detail text NOT NULL
);

CREATE TABLE consumed_event (
    event_id text PRIMARY KEY
);

CREATE TABLE probe (
    id integer PRIMARY KEY,
    n integer NOT NULL
);

-- @db contract
CREATE TABLE contract (
    id integer PRIMARY KEY,
    po_id integer NOT NULL UNIQUE,
    supplier_id integer NOT NULL,
    write_count integer NOT NULL DEFAULT 0
);

CREATE TABLE probe (
    id integer PRIMARY KEY,
    n integer NOT NULL
);
