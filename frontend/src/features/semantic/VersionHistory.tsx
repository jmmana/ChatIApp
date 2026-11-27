import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/features/auth/AuthProvider";
import { listVersions } from "./api";

const dateFormat = new Intl.DateTimeFormat("es", { dateStyle: "medium", timeStyle: "short" });

export function VersionHistory({ datasourceId }: { datasourceId: string }) {
  const { user } = useAuth();
  const versions = useQuery({
    queryKey: ["semantic-versions", datasourceId],
    queryFn: () => listVersions(datasourceId),
  });

  if (versions.isPending) return <p className="text-sm text-muted-foreground">Cargando…</p>;
  if (versions.isError) {
    return (
      <p role="alert" className="text-sm text-destructive">
        No se pudo cargar el historial.
      </p>
    );
  }
  if (versions.data.length === 0) {
    return <p className="text-sm text-muted-foreground">Todavía no hay versiones publicadas.</p>;
  }

  // La API solo devuelve el id del autor: el propio usuario se reconoce por su correo.
  function author(id: string | null): string {
    if (id === null) return "Sistema";
    return id === user?.id ? user.email : `Usuario ${id.slice(0, 8)}`;
  }

  return (
    <table className="w-full text-sm">
      <caption className="sr-only">Historial de versiones</caption>
      <thead>
        <tr className="border-b text-left text-muted-foreground">
          <th scope="col" className="py-2 pr-4 font-medium">
            Versión
          </th>
          <th scope="col" className="py-2 pr-4 font-medium">
            Fecha
          </th>
          <th scope="col" className="py-2 font-medium">
            Autor
          </th>
        </tr>
      </thead>
      <tbody>
        {versions.data.map((item) => (
          <tr key={item.version} className="border-b">
            <td className="py-2 pr-4 font-medium">v{item.version}</td>
            <td className="py-2 pr-4">{dateFormat.format(new Date(item.created_at))}</td>
            <td className="py-2">{author(item.created_by)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
