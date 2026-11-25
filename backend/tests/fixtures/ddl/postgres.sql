CREATE TABLE ventas.clientes (
    id     INTEGER PRIMARY KEY,
    nombre VARCHAR(120) NOT NULL,
    email  VARCHAR(160) UNIQUE
);

CREATE TABLE ventas.facturas (
    id         INTEGER NOT NULL,
    numero     VARCHAR(20) NOT NULL UNIQUE,
    cliente_id INTEGER NOT NULL REFERENCES ventas.clientes (id),
    total      NUMERIC(14,2) NOT NULL,
    CONSTRAINT pk_facturas PRIMARY KEY (id)
);

CREATE TABLE ventas.detalle (
    factura_id  INTEGER NOT NULL,
    linea       INTEGER NOT NULL,
    cantidad    INTEGER NOT NULL,
    PRIMARY KEY (factura_id, linea),
    FOREIGN KEY (factura_id) REFERENCES ventas.facturas (id),
    UNIQUE (factura_id, cantidad)
);

COMMENT ON TABLE ventas.facturas IS 'Encabezado de factura.';
COMMENT ON COLUMN ventas.facturas.total IS 'Valor final cobrado.';

CREATE INDEX ix_facturas_cliente ON ventas.facturas (cliente_id);
SELECT * FROM ventas.facturas;
INSERT INTO ventas.clientes (id, nombre) VALUES (1, 'Ana');
