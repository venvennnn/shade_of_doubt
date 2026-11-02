"use client";

import { useEffect, useState } from "react";
import { apiBlob } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export function Photo({ assetId, alt }: { assetId: string | null | undefined; alt: string }) {
  const { token } = useAuth();
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!assetId || !token) {
      setUrl(null);
      return;
    }
    let cancelled = false;
    let current: string | null = null;
    apiBlob(`/v1/assets/${assetId}/content`, token)
      .then((blob) => {
        if (cancelled) return;
        current = URL.createObjectURL(blob);
        setUrl(current);
        setError(null);
      })
      .catch((reason: Error) => {
        if (!cancelled) setError(reason.message);
      });
    return () => {
      cancelled = true;
      if (current) URL.revokeObjectURL(current);
    };
  }, [assetId, token]);

  if (!assetId) {
    return <div className="flex h-full min-h-48 items-center justify-center bg-wash text-sm text-mute">No image stored</div>;
  }
  if (error) {
    return <div className="flex h-full min-h-48 items-center justify-center bg-wash p-4 text-sm text-mute">{error}</div>;
  }
  if (!url) {
    return <div className="flex h-full min-h-48 items-center justify-center bg-wash text-sm text-mute">Loading photograph</div>;
  }
  return <img src={url} alt={alt} className="h-full w-full object-cover" />;
}
