import type { Dialect, ErrorKind, Privacy } from "./api";

// Fuente: docs/BASES_DE_DATOS.md#motores-soportados
export const DIALECTS: { value: Dialect; label: string; driver: string; urlExample: string }[] = [
  {
    value: "postgres",
    label: "PostgreSQL",
    driver: "psycopg (extra postgres)",
    urlExample: "postgresql+psycopg://chatiapp_ro:***@host:5432/ventas",
  },
  {
    value: "tsql",
    label: "SQL Server / Azure SQL",
    driver: "pyodbc (extra sqlserver)",
    urlExample:
      "mssql+pyodbc://chatiapp_ro:***@host/ventas?driver=ODBC+Driver+18+for+SQL+Server",
  },
  {
    value: "mysql",
    label: "MySQL / MariaDB",
    driver: "pymysql (extra mysql)",
    urlExample: "mysql+pymysql://chatiapp_ro:***@host:3306/ventas",
  },
  {
    value: "oracle",
    label: "Oracle",
    driver: "oracledb (extra oracle)",
    urlExample: "oracle+oracledb://chatiapp_ro:***@host:1521/?service_name=VENTAS",
  },
  {
    value: "snowflake",
    label: "Snowflake",
    driver: "snowflake-sqlalchemy (extra snowflake)",
    urlExample: "snowflake://usuario:***@cuenta/BD/ESQUEMA?warehouse=WH",
  },
  {
    value: "bigquery",
    label: "Google BigQuery",
    driver: "sqlalchemy-bigquery (extra bigquery)",
    urlExample: "bigquery://proyecto/dataset",
  },
  {
    value: "sqlite",
    label: "SQLite",
    driver: "incluido",
    urlExample: "sqlite:///./demo/ventas.db",
  },
];

export function dialectLabel(dialect: string): string {
  return DIALECTS.find((d) => d.value === dialect)?.label ?? dialect;
}

// Fuente: docs/SEGURIDAD.md#qué-ve-el-modelo-de-ia
export const PRIVACY_LEVELS: { value: Privacy; label: string; help: string }[] = [
  {
    value: "schema",
    label: "Solo esquema",
    help: "El modelo de IA recibe la pregunta y el modelo semántico, nunca filas ni valores de ejemplo.",
  },
  {
    value: "aggregates",
    label: "Agregados",
    help: "Además recibe el resultado de la consulta si tiene 50 filas o menos.",
  },
  {
    value: "samples",
    label: "Con muestras",
    help: "Además recibe valores de ejemplo de las columnas. Las columnas ocultas nunca salen.",
  },
];

export function privacyLabel(privacy: string): string {
  return PRIVACY_LEVELS.find((p) => p.value === privacy)?.label ?? privacy;
}

export const ERROR_HELP: Record<ErrorKind, { title: string; action: string }> = {
  auth: {
    title: "Credenciales rechazadas",
    action:
      "Revisa el usuario y la contraseña de la URL y confirma que el usuario tenga permiso para conectarse.",
  },
  network: {
    title: "No se pudo alcanzar la base",
    action:
      "Revisa el host y el puerto, que la base esté encendida y que ningún firewall bloquee la conexión.",
  },
  driver_missing: {
    title: "Falta el driver",
    action: "Instala el extra indicado en el mensaje y reinicia ChatIApp.",
  },
  unknown: {
    title: "Error al conectar",
    action: "Revisa que la URL tenga el formato del dialecto elegido y consulta los registros del servidor.",
  },
};
