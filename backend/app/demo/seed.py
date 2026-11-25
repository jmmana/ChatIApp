"""Generador reproducible de la base de demostración «Ventas» en SQLite.

Uso (desde `backend/`):

    uv run python -m app.demo.seed --out demo/ventas.db --seed 42

El mismo `--seed` y la misma fecha final (`--hasta`) producen exactamente los mismos
datos. Todos los datos personales son ficticios (los correos usan el dominio reservado
`example.com`). Los montos son pesos colombianos enteros.
"""

from __future__ import annotations

import argparse
import random
import sqlite3
from collections import defaultdict
from collections.abc import Sequence
from datetime import date, timedelta
from pathlib import Path

FECHA_INICIO = date(2025, 1, 1)
NUM_FACTURAS = 50_000
NUM_CLIENTES = 2_000
IVA_PORCENTAJE = 19

# Esquema de examples/ventas/schema.sql adaptado a SQLite (sin COMMENT ON).
DDL = """
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
"""

# (nombre, ciudad, región, abierta_desde, peso de ventas)
SUCURSALES: list[tuple[str, str, str, date, float]] = [
    ("Bogotá Andino", "Bogotá", "Andina", date(2018, 3, 15), 1.6),
    ("Bogotá Unicentro", "Bogotá", "Andina", date(2019, 8, 1), 1.4),
    ("Bogotá Titán", "Bogotá", "Andina", date(2021, 11, 20), 1.0),
    ("Medellín El Tesoro", "Medellín", "Andina", date(2019, 5, 10), 1.3),
    ("Cali Chipichape", "Cali", "Pacífico", date(2020, 2, 7), 1.0),
    ("Barranquilla Buenavista", "Barranquilla", "Caribe", date(2022, 4, 29), 0.9),
]

CANALES = ["TIENDA", "ONLINE", "MAYORISTA"]
PESOS_CANAL = [62, 28, 10]
ESTADOS = ["PAGADA", "PENDIENTE", "ANULADA"]
PESOS_ESTADO = [90, 4, 6]

# categoría -> (prefijo de SKU, tipo, marcas, modelos, precio mínimo, precio máximo)
CATALOGO: dict[str, tuple[str, str, list[str], list[str], int, int]] = {
    "Celulares": (
        "CEL",
        "Celular",
        ["Samsung", "Xiaomi", "Motorola", "Apple"],
        ["A15", "A35", "Note 12", "Edge 40", "Pro 128GB", "Plus 256GB", "Ultra 512GB"],
        600_000,
        5_500_000,
    ),
    "Portátiles": (
        "POR",
        "Portátil",
        ["Lenovo", "HP", "Asus", "Acer"],
        ["IdeaBook 14", "Pavilion 15", "VivoBook 15", "Aspire 5", "Gamer 16", "Pro 14", "Air 13"],
        1_400_000,
        7_500_000,
    ),
    "Tablets": (
        "TAB",
        "Tablet",
        ["Samsung", "Lenovo", "Apple", "Huawei"],
        ["Lite 8", "Tab 10", "Tab 11", "Plus 12", "Pro 11", "Kids 7", "Max 13"],
        400_000,
        4_500_000,
    ),
    "Audio": (
        "AUD",
        "Audífonos",
        ["Sony", "JBL", "Logitech", "Anker"],
        [
            "Básicos",
            "Bluetooth",
            "Inalámbricos",
            "Cancelación de ruido",
            "Deportivos",
            "Estudio",
            "Gamer",
        ],
        50_000,
        1_200_000,
    ),
    "Televisores": (
        "TV",
        "Televisor",
        ["LG", "Samsung", "Hisense", "TCL"],
        ['32" HD', '43" Full HD', '50" 4K', '55" 4K', '65" 4K', '55" QLED', '75" QLED'],
        900_000,
        9_000_000,
    ),
    "Gaming": (
        "GAM",
        "Gaming",
        ["Sony", "Microsoft", "Nintendo", "Logitech"],
        [
            "Consola",
            "Control inalámbrico",
            "Volante",
            "Silla",
            "Teclado mecánico",
            "Mouse",
            "Auriculares",
        ],
        120_000,
        3_000_000,
    ),
    "Cámaras": (
        "CAM",
        "Cámara",
        ["Canon", "Nikon", "GoPro", "Sony"],
        [
            "Compacta",
            "Réflex",
            "Mirrorless",
            "Acción 4K",
            "Instantánea",
            "Seguridad WiFi",
            "Drone",
        ],
        200_000,
        6_500_000,
    ),
    "Accesorios": (
        "ACC",
        "Accesorio",
        ["Anker", "Logitech", "Belkin", "Kingston"],
        [
            "Cargador rápido",
            "Cable USB-C",
            "Funda",
            "Memoria 128GB",
            "Mouse inalámbrico",
            "Teclado",
            "Soporte",
        ],
        15_000,
        450_000,
    ),
}

NOMBRES = [
    "Camila", "Andrés", "Valentina", "Juan", "Laura", "Santiago", "Daniela", "Mateo",
    "Sofía", "Sebastián", "Isabella", "Felipe", "Natalia", "Nicolás", "Paula", "David",
    "María", "Carlos", "Luisa", "Jorge", "Carolina", "Diego", "Alejandra", "Julián",
    "Manuela", "Esteban", "Juliana", "Camilo", "Mariana", "Tomás",
]  # fmt: skip
APELLIDOS = [
    "Rodríguez", "Gómez", "López", "Martínez", "García", "Hernández", "Ramírez", "Torres",
    "Vargas", "Castro", "Rojas", "Moreno", "Jiménez", "Ortiz", "Silva", "Cardona",
    "Ospina", "Mejía", "Cárdenas", "Pardo", "Quintero", "Salazar", "Herrera", "Pineda",
    "Londoño", "Arango", "Montoya", "Restrepo", "Zapata", "Durán",
]  # fmt: skip
PALABRAS_EMPRESA = [
    "Andes", "Horizonte", "Delta", "Cumbre", "Nova", "Altiplano", "Quimbaya", "Aurora",
    "Pacífico", "Caribe", "Zafiro", "Orión", "Tecnova", "Solaris", "Meridiano",
]  # fmt: skip
SECTORES_EMPRESA = [
    "Soluciones",
    "Servicios",
    "Inversiones",
    "Comercializadora",
    "Distribuciones",
    "Consultores",
]
CIUDADES_CLIENTES = ["Bogotá", "Medellín", "Cali", "Barranquilla", "Bucaramanga", "Cartagena"]
PESOS_CIUDAD_CLIENTES = [40, 22, 15, 10, 7, 6]

ProductoFila = tuple[int, str, str, str, str, int]


def _productos(rng: random.Random) -> list[ProductoFila]:
    filas: list[ProductoFila] = []
    for categoria, (prefijo, tipo, marcas, modelos, minimo, maximo) in CATALOGO.items():
        for marca in marcas:
            for modelo in modelos:
                precio = rng.randint(minimo // 1000, maximo // 1000) * 1000
                id_ = len(filas) + 1
                nombre = f"{tipo} {marca} {modelo}"
                filas.append((id_, f"{prefijo}-{id_:04d}", nombre, categoria, marca, precio))
    return filas


def _clientes(rng: random.Random) -> list[tuple[str, str, str, str, str]]:
    """Devuelve (nombre, documento, email, segmento, ciudad) sin id ni fecha de creación."""
    filas: list[tuple[str, str, str, str, str]] = []
    for i in range(1, NUM_CLIENTES + 1):
        ciudad = rng.choices(CIUDADES_CLIENTES, PESOS_CIUDAD_CLIENTES)[0]
        if rng.random() < 0.12:
            nombre = (
                f"{rng.choice(SECTORES_EMPRESA)} {rng.choice(PALABRAS_EMPRESA)} "
                f"{rng.choice(PALABRAS_EMPRESA)} S.A.S."
            )
            documento = f"9{rng.randint(0, 99_999_999):08d}-{rng.randint(0, 9)}"
            segmento = "EMPRESA"
        else:
            nombre = f"{rng.choice(NOMBRES)} {rng.choice(APELLIDOS)} {rng.choice(APELLIDOS)}"
            documento = str(rng.randint(10_000_000, 1_999_999_999))
            segmento = "PERSONA"
        email = f"cliente{i:05d}@example.com" if rng.random() < 0.9 else ""
        filas.append((nombre, documento, email, segmento, ciudad))
    return filas


def _pesos_dias(dias: list[date]) -> list[float]:
    """Más ventas en fin de semana y en temporada alta (junio, noviembre, diciembre)."""
    temporada = {6: 1.1, 11: 1.3, 12: 1.6}
    return [(1.3 if d.weekday() >= 5 else 1.0) * temporada.get(d.month, 1.0) for d in dias]


def generar(out: Path, seed: int = 42, hasta: date | None = None) -> None:
    """Genera la base «Ventas» en `out` (la reemplaza si existe).

    `hasta` es la fecha de generación (por defecto hoy): las facturas llegan hasta ese día
    y `ventas_mensuales` no incluye su mes.
    """
    hasta = hasta or date.today()
    if hasta < FECHA_INICIO:
        raise ValueError(f"`hasta` debe ser posterior o igual a {FECHA_INICIO.isoformat()}")
    rng = random.Random(seed)

    productos = _productos(rng)
    clientes = _clientes(rng)
    pesos_sucursal = [s[4] for s in SUCURSALES]

    dias = [FECHA_INICIO + timedelta(days=i) for i in range((hasta - FECHA_INICIO).days + 1)]
    fechas = sorted(rng.choices(dias, _pesos_dias(dias), k=NUM_FACTURAS))
    # Cada cliente compra al menos una vez; el resto de las facturas se reparte al azar.
    cliente_ids = list(range(1, NUM_CLIENTES + 1))
    cliente_ids += rng.choices(range(1, NUM_CLIENTES + 1), k=NUM_FACTURAS - NUM_CLIENTES)
    rng.shuffle(cliente_ids)

    facturas: list[tuple[int, str, str, int, int, str, int, int, int, int, str]] = []
    detalle: list[tuple[int, int, int, int, int, int]] = []
    primera_compra: dict[int, date] = {}
    diarias: dict[tuple[str, int, str], list[int]] = defaultdict(lambda: [0, 0, 0])
    mensuales: dict[tuple[str, int], list[int]] = defaultdict(lambda: [0, 0, 0])
    mes_en_curso = hasta.replace(day=1).isoformat()

    for factura_id, (fecha, cliente_id) in enumerate(zip(fechas, cliente_ids, strict=True), 1):
        fecha_iso = fecha.isoformat()
        primera_compra.setdefault(cliente_id, fecha)
        sucursal_id = rng.choices(range(1, len(SUCURSALES) + 1), pesos_sucursal)[0]
        canal = rng.choices(CANALES, PESOS_CANAL)[0]
        estado = rng.choices(ESTADOS, PESOS_ESTADO)[0]

        num_lineas = rng.choices([1, 2, 3, 4, 5], [40, 30, 15, 10, 5])[0]
        suma_lineas = 0
        unidades = 0
        for producto in rng.sample(productos, num_lineas):
            if canal == "MAYORISTA":
                cantidad = rng.randint(5, 30)
            else:
                cantidad = rng.choices([1, 2, 3], [75, 18, 7])[0]
            precio = producto[5]
            total_linea = cantidad * precio
            detalle.append(
                (len(detalle) + 1, factura_id, producto[0], cantidad, precio, total_linea)
            )
            suma_lineas += total_linea
            unidades += cantidad

        porcentaje = rng.choices([0, 5, 10], [70, 20, 10])[0]
        if canal == "MAYORISTA":
            porcentaje += 5
        descuento = suma_lineas * porcentaje // 100
        subtotal = suma_lineas - descuento
        impuesto = subtotal * IVA_PORCENTAJE // 100
        total = subtotal + impuesto
        facturas.append(
            (
                factura_id,
                f"FV-{factura_id:07d}",
                fecha_iso,
                cliente_id,
                sucursal_id,
                canal,
                subtotal,
                descuento,
                impuesto,
                total,
                estado,
            )
        )

        if estado == "PAGADA":
            acum = diarias[(fecha_iso, sucursal_id, canal)]
            acum[0] += total
            acum[1] += 1
            acum[2] += unidades
            mes = fecha.replace(day=1).isoformat()
            if mes != mes_en_curso:
                acum = mensuales[(mes, sucursal_id)]
                acum[0] += total
                acum[1] += 1
                acum[2] += unidades

    # El cliente se crea antes de su primera compra, desde 2023.
    inicio_creacion = date(2023, 1, 1)
    filas_clientes = []
    for id_, (nombre, documento, email, segmento, ciudad) in enumerate(clientes, 1):
        rango = (primera_compra[id_] - inicio_creacion).days
        creado = inicio_creacion + timedelta(days=rng.randint(0, rango))
        filas_clientes.append(
            (id_, nombre, documento, email or None, segmento, ciudad, creado.isoformat())
        )

    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    conn = sqlite3.connect(out)
    try:
        conn.executescript(DDL)
        conn.executemany(
            "INSERT INTO sucursales VALUES (?, ?, ?, ?, ?)",
            [(i, s[0], s[1], s[2], s[3].isoformat()) for i, s in enumerate(SUCURSALES, 1)],
        )
        conn.executemany("INSERT INTO productos VALUES (?, ?, ?, ?, ?, ?)", productos)
        conn.executemany("INSERT INTO clientes VALUES (?, ?, ?, ?, ?, ?, ?)", filas_clientes)
        conn.executemany("INSERT INTO facturas VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", facturas)
        conn.executemany("INSERT INTO factura_detalle VALUES (?, ?, ?, ?, ?, ?)", detalle)
        conn.executemany(
            "INSERT INTO ventas_diarias VALUES (?, ?, ?, ?, ?, ?)",
            [(f, s, c, *v) for (f, s, c), v in sorted(diarias.items())],
        )
        conn.executemany(
            "INSERT INTO ventas_mensuales VALUES (?, ?, ?, ?, ?)",
            [(m, s, *v) for (m, s), v in sorted(mensuales.items())],
        )
        conn.commit()
    finally:
        conn.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Genera la base de demostración «Ventas».")
    parser.add_argument("--out", type=Path, required=True, help="Ruta del archivo SQLite")
    parser.add_argument("--seed", type=int, default=42, help="Semilla (por defecto 42)")
    parser.add_argument(
        "--hasta",
        type=date.fromisoformat,
        default=None,
        help="Fecha final AAAA-MM-DD (por defecto, hoy)",
    )
    args = parser.parse_args(argv)
    generar(args.out, args.seed, args.hasta)
    print(f"Base generada en {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
