"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Product } from "@/lib/types";

export default function CataloguePage() {
  const { token } = useAuth();
  const products = useQuery({
    queryKey: ["products", token],
    enabled: Boolean(token),
    queryFn: () => api<{ products: Product[] }>("/v1/products", token),
  });
  const [form, setForm] = useState({
    name: "",
    source_url: "",
    image_rights: "",
    price: "",
    currency: "USD",
    ingredient_label: "",
    source_observed_at: "",
    concern: "redness",
    support_note: "",
    confirmed: false,
  });
  const [message, setMessage] = useState("");
  const create = useMutation({
    mutationFn: () =>
      api("/v1/products", token, {
        method: "POST",
        body: JSON.stringify({
          ...form,
          source_observed_at: new Date(form.source_observed_at).toISOString(),
          confirmed: form.confirmed,
          mappings: form.concern
            ? [{ concern: form.concern, support_note: form.support_note, source_url: form.source_url, reviewer_confirmed: form.confirmed }]
            : [],
        }),
      }),
    onSuccess: () => {
      setMessage("Product saved. It is used only if you confirmed the entry and the mapping.");
      products.refetch();
    },
    onError: (reason) => setMessage(reason instanceof ApiError ? `${reason.message} ${reason.remediation}` : "Could not save."),
  });
  return (
    <div>
      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-pink">Catalogue</p>
      <h1 className="mt-2 text-4xl font-semibold tracking-tight">Products you can point to</h1>
      <p className="mt-2 max-w-2xl text-mute">Enter a real name, the page or pack you read, when you read it, and the rights you have in any image. The app does not invent products or guess ingredients.</p>
      {!token && <p className="mt-4">Preparing this browser.</p>}
      {token && (
        <form
          className="mt-6 grid gap-3 sm:max-w-xl"
          onSubmit={(event) => {
            event.preventDefault();
            create.mutate();
          }}
        >
          {(["name", "source_url", "image_rights", "price", "currency", "ingredient_label", "source_observed_at", "concern", "support_note"] as const).map((field) => (
            <label key={field} className="text-sm capitalize">
              {field.replaceAll("_", " ")}
              <input
                className="mt-1 w-full rounded-2xl border border-line px-3 py-2"
                type={field === "source_observed_at" ? "datetime-local" : "text"}
                value={form[field]}
                onChange={(event) => setForm({ ...form, [field]: event.target.value })}
                required={field === "name" || field === "source_url" || field === "image_rights" || field === "source_observed_at" || field === "support_note"}
              />
            </label>
          ))}
          <label className="text-sm">
            <input type="checkbox" className="mr-2" checked={form.confirmed} onChange={(event) => setForm({ ...form, confirmed: event.target.checked })} />
            I confirm this entry and mapping against the source.
          </label>
          <button className="rounded-full bg-pink px-4 py-2 text-sm font-semibold text-white" type="submit">Save product</button>
          {message && <p className="text-sm">{message}</p>}
        </form>
      )}
      <ul className="mt-8 space-y-3">
        {products.data?.products.map((product) => (
          <li key={product.id} className="rounded-[24px] border border-line p-4 text-sm">
            <p className="font-semibold">{product.name}</p>
            <p>{product.confirmed ? "Confirmed" : "Not confirmed"} · {product.price || "no price"} {product.currency || ""}</p>
            <a className="text-pink" href={product.source_url}>Source</a>
            <p className="text-mute">{product.ingredient_label || "No ingredient label recorded."}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}
