import { ArrowDown, ArrowUp, ChevronsUpDown } from "lucide-react";
import { useMemo, useState } from "react";
import type { ResultData } from "../types";
import { formatCell } from "./format";
import type { FormatOptions } from "./format";
import { isNumericColumn } from "./shape";
import { sortRows } from "./sort";

interface Sort {
  index: number;
  dir: "asc" | "desc";
}

export function ResultTable({ result, locale }: { result: ResultData } & FormatOptions) {
  const [sort, setSort] = useState<Sort | null>(null);
  const numeric = useMemo(() => result.columns.map((_, i) => isNumericColumn(result, i)), [result]);
  const rows = useMemo(
    () => (sort ? sortRows(result.rows, sort.index, sort.dir) : result.rows),
    [result.rows, sort],
  );

  function toggle(index: number) {
    setSort((current) =>
      current?.index !== index
        ? { index, dir: "asc" }
        : current.dir === "asc"
          ? { index, dir: "desc" }
          : null,
    );
  }

  return (
    <div className="max-h-96 overflow-auto rounded-md border">
      <table className="w-full text-sm">
        <thead className="sticky top-0 bg-muted">
          <tr>
            {result.columns.map((name, i) => {
              const active = sort?.index === i ? sort.dir : null;
              const Icon =
                active === "asc" ? ArrowUp : active === "desc" ? ArrowDown : ChevronsUpDown;
              return (
                <th
                  key={i}
                  scope="col"
                  aria-sort={
                    active === "asc" ? "ascending" : active === "desc" ? "descending" : "none"
                  }
                  className={`px-3 py-2 font-medium ${numeric[i] ? "text-right" : "text-left"}`}
                >
                  <button
                    type="button"
                    onClick={() => toggle(i)}
                    className={`inline-flex items-center gap-1 ${numeric[i] ? "flex-row-reverse" : ""}`}
                  >
                    {name}
                    <Icon aria-hidden className="size-3.5" />
                  </button>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, r) => (
            <tr key={r} className="border-t">
              {result.columns.map((_, c) => (
                <td
                  key={c}
                  className={`px-3 py-1.5 ${numeric[c] ? "text-right tabular-nums" : "text-left"}`}
                >
                  {formatCell(row[c], { locale })}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
