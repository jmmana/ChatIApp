import { format } from "sql-formatter";
import type { SqlLanguage } from "sql-formatter";

const LANGUAGES: Record<string, SqlLanguage> = {
  sqlite: "sqlite",
  postgres: "postgresql",
  postgresql: "postgresql",
  mysql: "mysql",
  mariadb: "mariadb",
  mssql: "transactsql",
  sqlserver: "transactsql",
  tsql: "transactsql",
};

/** Da formato al SQL según el dialecto; si no se puede, devuelve el texto original. */
export function formatSql(sql: string, dialect: string): string {
  try {
    return format(sql, {
      language: LANGUAGES[dialect.toLowerCase()] ?? "sql",
      keywordCase: "upper",
    });
  } catch {
    return sql;
  }
}
