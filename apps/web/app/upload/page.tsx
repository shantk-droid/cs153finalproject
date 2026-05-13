"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { ColumnMapper } from "@/components/ColumnMapper";
import { ProfilePicker } from "@/components/ProfilePicker";
import { UploadDropzone } from "@/components/UploadDropzone";
import {
  confirmDataset,
  uploadDataset,
} from "@/lib/api-client";
import type { ColumnMapping, DatasetPreview } from "@/lib/types";

type Phase = "drop" | "mapping" | "confirming" | "error";

export default function UploadPage() {
  const router = useRouter();
  const [phase, setPhase] = useState<Phase>("drop");
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<DatasetPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [profileId, setProfileId] = useState<string>("auto");

  const handleFile = async (file: File) => {
    setBusy(true);
    setError(null);
    try {
      const p = await uploadDataset(file);
      setPreview(p);
      setPhase("mapping");
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
      setPhase("error");
    } finally {
      setBusy(false);
    }
  };

  const handleConfirm = async (mapping: ColumnMapping) => {
    if (!preview) return;
    setBusy(true);
    setError(null);
    setPhase("confirming");
    try {
      await confirmDataset(preview.dataset_id, mapping, profileId);
      router.push(`/upload/quality/${preview.dataset_id}`);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
      setPhase("error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="mx-auto flex min-h-screen max-w-4xl flex-col gap-8 px-6 py-12">
      <header>
        <p className="text-xs uppercase tracking-widest text-muted-foreground">Upload</p>
        <h1 className="mt-1 text-3xl font-semibold tracking-tight">Bring your SKU panel</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          CSV or Excel. Long format — one row per SKU per period. We'll auto-detect columns and run
          a data-quality report before saving.
        </p>
      </header>

      {phase === "drop" && (
        <UploadDropzone onFile={handleFile} disabled={busy} />
      )}

      {phase === "mapping" && preview && (
        <>
          <div className="rounded-md border bg-muted/30 px-4 py-3 text-sm">
            <span className="font-medium">{preview.filename}</span>{" "}
            <span className="text-muted-foreground">
              · {preview.n_total_rows.toLocaleString()} rows
              {preview.selected_sheet && ` · sheet "${preview.selected_sheet}"`}
            </span>
          </div>
          {preview.detected_connector === "shopify" && (
            <div className="rounded-md border border-emerald-500/40 bg-emerald-500/10 px-4 py-3 text-sm">
              <p className="font-medium text-emerald-700 dark:text-emerald-300">
                Detected: Shopify orders export
              </p>
              <p className="mt-1 text-emerald-700/80 dark:text-emerald-300/80">
                Line items rolled up to a daily SKU panel. Cancelled/refunded orders excluded;
                quantities and prices aggregated by SKU × date. The mapping below is pre-filled —
                review and confirm.
              </p>
            </div>
          )}
          <ProfilePicker value={profileId} onChange={setProfileId} />
          <ColumnMapper
            detectedColumns={preview.detected_columns}
            suggestedMapping={preview.suggested_mapping}
            sampleRows={preview.sample_rows}
            onConfirm={handleConfirm}
            pending={busy}
          />
        </>
      )}

      {phase === "confirming" && (
        <div className="text-sm text-muted-foreground">
          Validating, normalizing, and computing data-quality report…
        </div>
      )}

      {phase === "error" && (
        <div className="space-y-3">
          <div className="rounded-md border border-destructive/50 bg-destructive/10 p-4 text-sm text-destructive">
            <p className="font-medium">Upload failed</p>
            <p className="mt-1 whitespace-pre-wrap font-mono text-xs">{error}</p>
          </div>
          <button
            type="button"
            onClick={() => {
              setError(null);
              setPreview(null);
              setPhase("drop");
            }}
            className="inline-flex h-9 items-center justify-center rounded-md border border-input bg-background px-4 text-sm font-medium hover:bg-accent"
          >
            Try again
          </button>
        </div>
      )}
    </main>
  );
}
