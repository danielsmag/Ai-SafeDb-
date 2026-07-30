-- Seed table with synthetic PII for local development / AI-safety experiments.
-- All values are fake; do not treat as real personal data.

CREATE TABLE IF NOT EXISTS customers (
    id              SERIAL PRIMARY KEY,
    first_name      VARCHAR(100)  NOT NULL,
    last_name       VARCHAR(100)  NOT NULL,
    email           VARCHAR(255)  NOT NULL UNIQUE,
    phone           VARCHAR(30)   NOT NULL,
    date_of_birth   DATE          NOT NULL,
    ssn             CHAR(11)      NOT NULL UNIQUE,
    address_line1   VARCHAR(255)  NOT NULL,
    address_line2   VARCHAR(255),
    city            VARCHAR(100)  NOT NULL,
    state           CHAR(2)       NOT NULL,
    zip_code        VARCHAR(10)   NOT NULL,
    country         VARCHAR(50)   NOT NULL DEFAULT 'US',
    credit_card     VARCHAR(19)   NOT NULL,
    ip_address      INET          NOT NULL,
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE customers IS 'Synthetic customer records with PII columns for local testing';
COMMENT ON COLUMN customers.ssn IS 'PII: Social Security Number (fake)';
COMMENT ON COLUMN customers.email IS 'PII: Email address (fake)';
COMMENT ON COLUMN customers.phone IS 'PII: Phone number (fake)';
COMMENT ON COLUMN customers.date_of_birth IS 'PII: Date of birth (fake)';
COMMENT ON COLUMN customers.credit_card IS 'PII: Credit card number (fake, Luhn-valid style)';
COMMENT ON COLUMN customers.ip_address IS 'PII-adjacent: IP address (fake)';
COMMENT ON COLUMN customers.address_line1 IS 'PII: Street address (fake)';

INSERT INTO customers (
    first_name, last_name, email, phone, date_of_birth, ssn,
    address_line1, address_line2, city, state, zip_code, country,
    credit_card, ip_address
) VALUES
    ('Ava',      'Nguyen',    'ava.nguyen@example.com',      '+1-415-555-0142', '1991-03-14', '521-84-3012',
     '482 Market St',        'Apt 12B',  'San Francisco', 'CA', '94105', 'US', '4532-1488-9012-3341', '203.0.113.14'),
    ('Marcus',   'Okafor',    'marcus.okafor@example.com',   '+1-312-555-0198', '1985-11-02', '478-22-6591',
     '220 N Michigan Ave',   NULL,       'Chicago',       'IL', '60601', 'US', '5412-7531-8890-2210', '198.51.100.42'),
    ('Sofia',    'Ramirez',   'sofia.ramirez@example.com',   '+1-718-555-0163', '1994-07-28', '612-39-8840',
     '91 Bedford Ave',       'Floor 3',  'Brooklyn',      'NY', '11211', 'US', '3714-496353-98427',   '192.0.2.77'),
    ('James',    'Whitfield', 'j.whitfield@example.com',     '+1-617-555-0111', '1979-01-19', '339-05-2176',
     '15 Beacon St',         NULL,       'Boston',        'MA', '02108', 'US', '6011-0009-9013-9424', '203.0.113.201'),
    ('Priya',    'Sharma',    'priya.sharma@example.com',    '+1-206-555-0177', '1988-09-05', '554-71-4403',
     '1600 Pike Pl',         'Suite 4',  'Seattle',       'WA', '98101', 'US', '4000-1234-5678-9010', '198.51.100.9'),
    ('Liam',     'Chen',      'liam.chen@example.com',       '+1-650-555-0133', '1996-12-21', '487-16-9925',
     '3500 Deer Creek Rd',   NULL,       'Palo Alto',     'CA', '94304', 'US', '5105-1051-0510-5100', '192.0.2.19'),
    ('Elena',    'Petrov',    'elena.petrov@example.com',    '+1-303-555-0184', '1990-05-30', '601-44-3388',
     '1700 Broadway',        'Unit 8C',  'Denver',        'CO', '80202', 'US', '3782-822463-10005',   '203.0.113.88'),
    ('Noah',     'Brooks',    'noah.brooks@example.com',     '+1-512-555-0155', '1983-08-11', '449-28-7701',
     '401 Congress Ave',     NULL,       'Austin',        'TX', '78701', 'US', '5555-5555-5555-4444', '198.51.100.130'),
    ('Amara',    'Diallo',    'amara.diallo@example.com',    '+1-404-555-0120', '1992-02-17', '528-63-1104',
     '75 Piedmont Ave NE',   'Apt 6',    'Atlanta',       'GA', '30308', 'US', '4111-1111-1111-1111', '192.0.2.250'),
    ('Oliver',   'Sato',      'oliver.sato@example.com',     '+1-503-555-0191', '1987-06-09', '536-90-2258',
     '1120 NW Couch St',     NULL,       'Portland',      'OR', '97209', 'US', '4242-4242-4242-4242', '203.0.113.55'),
    ('Isabella', 'Costa',     'isabella.costa@example.com',  '+1-305-555-0148', '1995-10-03', '590-17-6642',
     '200 S Biscayne Blvd',  'Ph 2',     'Miami',         'FL', '33131', 'US', '5200-8282-8282-8210', '198.51.100.201'),
    ('Ethan',    'Kowalski',  'ethan.kowalski@example.com',  '+1-313-555-0166', '1981-04-25', '372-48-9031',
     '1 Campus Martius',     NULL,       'Detroit',       'MI', '48226', 'US', '6011-1111-1111-1117', '192.0.2.33');
