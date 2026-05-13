"use client";

import { useCallback, useRef, useState } from "react";
import { Upload } from "lucide-react";
import { cn } from "@/lib/utils";

const ACCEPT = ".csv,.tsv,.xlsx,.xlsm,.txt";
const MAX_BYTES = 50 * 1024 * 1024;

interface Props {
  onFile: (file: File) => void;
  disabled?: boolean;
}

export function UploadDropzone({ onFile, disabled }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [hovered, setHovered] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleFile = useCallback(
    (file: File) => {
      setError(null);
      const ext = file.name.toLowerCase().split(".").pop() ?? "";
      if (!["csv", "tsv", "xlsx", "xlsm", "txt"].includes(ext)) {
        setError(`Unsupported file type .${ext}. Use .csv, .tsv, or .xlsx.`);
        return;
      }
      if (file.size > MAX_BYTES) {
        setError(`File is ${(file.size / 1e6).toFixed(1)} MB. Max is ${MAX_BYTES / 1e6} MB.`);
        return;
      }
      onFile(file);
    },
    [onFile],
  );

  return (
    <div className="space-y-2">
      <div
        role="button"
        tabIndex={0}
        onClick={() => !disabled && inputRef.current?.click()}
        onKeyDown={(e) => {
          if ((e.key === "Enter" || e.key === " ") && !disabled) inputRef.current?.click();
        }}
        onDragEnter={(e) => {
          e.preventDefault();
          if (!disabled) setHovered(true);
        }}
        onDragLeave={(e) => {
          e.preventDefault();
          setHovered(false);
        }}
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          setHovered(false);
          if (disabled) return;
          const file = e.dataTransfer.files?.[0];
          if (file) handleFile(file);
        }}
        className={cn(
          "flex h-44 cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed border-input bg-card text-card-foreground transition",
          hovered && "border-primary bg-accent",
          disabled && "cursor-not-allowed opacity-50",
        )}
      >
        <Upload className="h-7 w-7 text-muted-foreground" aria-hidden />
        <p className="text-sm font-medium">Drop a CSV or Excel file, or click to browse</p>
        <p className="text-xs text-muted-foreground">.csv, .tsv, .xlsx — up to 50 MB</p>
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPT}
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) handleFile(file);
            e.target.value = "";
          }}
        />
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}
    </div>
  );
}
