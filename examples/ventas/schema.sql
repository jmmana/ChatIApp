-- ============================================================================
-- ChatIApp · Base de datos de ejemplo «Ventas»  (dialecto: PostgreSQL)
--
-- Cadena de tiendas de tecnología con 6 sucursales. Es el esquema que usan la
-- demo, las pruebas del motor y el set de evaluación.
--
-- Se puede importar tal cual en el Estudio del modelo: el importador DDL lee
-- tablas, tipos, llaves primarias, llaves foráneas y los COMMENT ON como
-- descripciones. Ver docs/MODELO_SEMANTICO.md#importar-la-estructura
-- ============================================================================

CREATE TABLE sucursales (
    id             INTEGER PRIMARY KEY,
    nombre         VARCHAR(80)  NOT NULL,
    ciudad         VARCHAR(60)  NOT NULL,
    region         VARCHAR(30)  NOT NULL,
    abierta_desde  DATE         NOT NULL
);

CREATE TABLE productos (
    id            INTEGER PRIMARY KEY,
    sku           VARCHAR(20)   NOT NULL UNIQUE,
    nombre        VARCHAR(120)  NOT NULL,
    categoria     VARCHAR(40)   NOT NULL,
    marca         VARCHAR(40)   NOT NULL,
    precio_lista  NUMERIC(14,2) NOT NULL
);

CREATE TABLE clientes (
    id         INTEGER PRIMARY KEY,
    nombre     VARCHAR(120) NOT NULL,
    documento  VARCHAR(20)  NOT NULL,
    email      VARCHAR(160),
    segmento   VARCHAR(20)  NOT NULL,
    ciudad     VARCHAR(60)  NOT NULL,
    creado_en  DATE         NOT NULL
);

CREATE TABLE facturas (
    id           INTEGER PRIMARY KEY,
    numero       VARCHAR(20)   NOT NULL UNIQUE,
    fecha        DATE          NOT NULL,
    cliente_id   INTEGER       NOT NULL REFERENCES clientes (id),
    sucursal_id  INTEGER       NOT NULL REFERENCES sucursales (id),
    canal        VARCHAR(12)   NOT NULL,
    subtotal     NUMERIC(14,2) NOT NULL,
    descuento    NUMERIC(14,2) NOT NULL DEFAULT 0,
    impuesto     NUMERIC(14,2) NOT NULL,
    total        NUMERIC(14,2) NOT NULL,
    estado       VARCHAR(12)   NOT NULL
);

CREATE TABLE factura_detalle (
    id               INTEGER PRIMARY KEY,
    factura_id       INTEGER       NOT NULL REFERENCES facturas (id),
    producto_id      INTEGER       NOT NULL REFERENCES productos (id),
    cantidad         INTEGER       NOT NULL,
    precio_unitario  NUMERIC(14,2) NOT NULL,
    total_linea      NUMERIC(14,2) NOT NULL
);

-- Tablas resumidas: las alimenta un proceso nocturno a partir de facturas PAGADAS.
CREATE TABLE ventas_diarias (
    fecha         DATE          NOT NULL,
    sucursal_id   INTEGER       NOT NULL REFERENCES sucursales (id),
    canal         VARCHAR(12)   NOT NULL,
    total_ventas  NUMERIC(16,2) NOT NULL,
    num_facturas  INTEGER       NOT NULL,
    unidades      INTEGER       NOT NULL,
    PRIMARY KEY (fecha, sucursal_id, canal)
);

CREATE TABLE ventas_mensuales (
    mes           DATE          NOT NULL,
    sucursal_id   INTEGER       NOT NULL REFERENCES sucursales (id),
    total_ventas  NUMERIC(16,2) NOT NULL,
    num_facturas  INTEGER       NOT NULL,
    unidades      INTEGER       NOT NULL,
    PRIMARY KEY (mes, sucursal_id)
);

COMMENT ON TABLE facturas IS 'Encabezado de cada factura de venta. Una fila por factura.';
COMMENT ON COLUMN facturas.fecha IS 'Fecha de emisión, en hora de Colombia.';
COMMENT ON COLUMN facturas.subtotal IS 'Valor antes de IVA, ya con descuentos aplicados.';
COMMENT ON COLUMN facturas.total IS 'Valor final cobrado: subtotal + impuesto.';
COMMENT ON COLUMN facturas.estado IS 'PAGADA, PENDIENTE o ANULADA. Solo PAGADA cuenta como venta.';
COMMENT ON COLUMN facturas.canal IS 'TIENDA, ONLINE o MAYORISTA.';
COMMENT ON TABLE factura_detalle IS 'Líneas de cada factura: un producto por fila.';
COMMENT ON TABLE ventas_diarias IS 'Resumen diario de facturas PAGADAS por sucursal y canal. Se actualiza cada hora.';
COMMENT ON TABLE ventas_mensuales IS 'Resumen mensual de facturas PAGADAS por sucursal. Se carga al cerrar cada mes.';
COMMENT ON COLUMN clientes.documento IS 'Cédula o NIT. Dato personal: no exponer.';
COMMENT ON COLUMN clientes.email IS 'Correo del cliente. Dato personal: no exponer.';
