"use client";

import { useEffect, useState } from "react";
import { listProfiles } from "@/lib/api-client";
import type { ProfileListEntry } from "@/lib/types";

interface Props {
  value: string;
  onChange: (id: string) => void;
}

export function ProfilePicker({ value, onChange }: Props) {
  const [profiles, setProfiles] = useState<ProfileListEntry[]>([]);
  useEffect(() => {
    listProfiles()
      .then((r) => setProfiles(r.profiles))
      .catch(() => setProfiles([]));
  }, []);

  const options: Array<{ id: string; label: string; description: string }> = [
    {
      id: "auto",
      label: "Auto-detect (recommended)",
      description: "We'll match your data to the closest profile.",
    },
    ...profiles.map((p) => ({ id: p.id, label: p.label, description: p.description })),
  ];

  return (
    <fieldset className="space-y-3 rounded-lg border bg-card p-5">
      <legend className="text-sm font-semibold">What kind of data is this?</legend>
      <p className="text-xs text-muted-foreground">
        We use this to score your data quality against the right benchmark. You can change it later in Settings.
      </p>
      <div className="space-y-2">
        {options.map((opt) => {
          const selected = value === opt.id;
          return (
            <label
              key={opt.id}
              className={
                "flex cursor-pointer items-start gap-3 rounded-md border p-3 transition-colors " +
                (selected
                  ? "border-primary bg-primary/5"
                  : "border-border hover:bg-muted/40")
              }
            >
              <input
                type="radio"
                name="profile"
                value={opt.id}
                checked={selected}
                onChange={() => onChange(opt.id)}
                className="mt-0.5 h-4 w-4 cursor-pointer accent-primary"
              />
              <span>
                <span className="block text-sm font-medium">{opt.label}</span>
                <span className="block text-xs text-muted-foreground">{opt.description}</span>
              </span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}
