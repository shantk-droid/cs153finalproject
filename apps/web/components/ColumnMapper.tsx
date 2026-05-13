"use client";

import { useMemo, useState } from "react";
import {
  CANONICAL_FIELDS,
  type ColumnDetection,
  type ColumnMapping,
  type CanonicalField,
  FIELD_LABEL,
  REQUIRED_FIELDS,
  type SuggestedMappingItem,
} from "@/lib/types";
import { cn } from "@/lib/utils";

interface Props {
  detectedColumns: ColumnDetection[];
  suggestedMapping: SuggestedMappingItem[];
  sampleRows: Record<string, unknown>[];
  onConfirm: (mapping: ColumnMapping) => void;
  pending?: boolean;
}

const REQUIRED = new Set<CanonicalField>(REQUIRED_FIELDS);

export function ColumnMapper({
  detectedColumns,
  suggestedMapping,
  sampleRows,
  onConfirm,
  pending,
}: Props) {
  const initial = useMemo(() => {
    const m: Partial<Record<CanonicalField, string>> = {};
    for (const s of suggestedMapping) if (s.file_column) m[s.canonical] = s.file_column;
    return m;
  }, [suggestedMapping]);

  const [mapping, setMapping] = useState<Partial<Record<CanonicalField, string>>>(initial);

  const fileColumns = detectedColumns.map((c) => c.name);
  const errors: Partial<Record<CanonicalField, string>> = {};
  for (const req of REQUIRED) if (!mapping[req]) errors[req] = "Required";
  const usedColumns = new Set(Object.values(mapping).filter(Boolean) as string[]);
  const isValid = Object.keys(errors).length === 0;

  const handleSubmit = () => {
    if (!isValid) return;
    onConfirm(mapping as ColumnMapping);
  };

  return (
    <div className="space-y-6">
      <section>
        <h2 className="text-lg font-semibold">Map your columns</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          We auto-detected the most likely match for each canonical field. Override any that look wrong.
        </p>
      </section>

      <div className="grid gap-3 sm:grid-cols-2 md:grid-cols-3">
        {CANONICAL_FIELDS.map((canon) => {
          const value = mapping[canon] ?? "";
          const suggestion = suggestedMapping.find((s) => s.canonical === canon);
          return (
            <div key={canon} className="space-y-1.5">
              <label className="flex items-center gap-1.5 text-sm font-medium" htmlFor={`map-${canon}`}>
                {FIELD_LABEL[canon]}
                {REQUIRED.has(canon) && <span className="text-destructive">*</span>}
              </label>
              <select
                id={`map-${canon}`}
                value={value}
                onChange={(e) =>
                  setMapping((prev) => ({ ...prev, [canon]: e.target.value || undefined }))
                }
                className={cn(
                  "h-9 w-full rounded-md border border-input bg-background px-2 text-sm",
                  errors[canon] && "border-destructive",
                )}
              >
                <option value="">— not mapped —</option>
                {fileColumns.map((fc) => (
                  <option
                    key={fc}
                    value={fc}
                    disabled={usedColumns.has(fc) && mapping[canon] !== fc}
                  >
                    {fc}
                  </option>
                ))}
              </select>
              {errors[canon] && <p className="text-xs text-destructive">{errors[canon]}</p>}
              {suggestion?.file_column && (
                <p className="text-xs text-muted-foreground">
                  auto: {suggestion.file_column} ({Math.round((suggestion.confidence ?? 0) * 100)}%)
                </p>
              )}
            </div>
          );
        })}
      </div>

      <section className="space-y-2">
        <h3 className="text-sm font-medium">Preview (first 5 rows)</h3>
        <div className="overflow-auto rounded-md border">
          <table className="min-w-full text-xs">
            <thead className="bg-muted">
              <tr>
                {fileColumns.map((c) => (
                  <th key={c} className="whitespace-nowrap border-b px-2 py-1.5 text-left font-medium">
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sampleRows.slice(0, 5).map((row, i) => (
                <tr key={i} className="border-b last:border-b-0">
                  {fileColumns.map((c) => (
                    <td key={c} className="whitespace-nowrap px-2 py-1.5">
                      {row[c] === null || row[c] === undefined ? "—" : String(row[c])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={handleSubmit}
          disabled={!isValid || pending}
          className={cn(
            "inline-flex h-10 items-center justify-center rounded-md bg-primary px-5 text-sm font-medium text-primary-foreground transition",
            (!isValid || pending) && "opacity-50",
          )}
        >
          {pending ? "Confirming…" : "Continue"}
        </button>
        {!isValid && (
          <p className="text-xs text-destructive">
            Map all required fields ({Array.from(REQUIRED).map((f) => FIELD_LABEL[f]).join(", ")}) to continue.
          </p>
        )}
      </div>
    </div>
  );
}
