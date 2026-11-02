"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/lib/auth";

const links = [
  { href: "/capture", label: "Capture" },
  { href: "/audit", label: "Audit" },
  { href: "/recaptures", label: "Compare recaptures" },
  { href: "/history", label: "History" },
  { href: "/methods", label: "Methods" },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { email, token, signOut } = useAuth();
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 border-b border-line bg-white/95 backdrop-blur">
        <div className="mx-auto flex max-w-6xl flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center sm:gap-6">
          <div className="flex items-center justify-between gap-3">
            <Link href="/capture" className="text-lg font-semibold tracking-tight text-pink">
              Shade of Doubt
            </Link>
            {token ? (
              <button className="rounded-full border border-line px-3 py-1.5 text-sm sm:hidden" onClick={() => signOut()} type="button">
                Sign out
              </button>
            ) : (
              <span className="text-sm text-mute sm:hidden">Not signed in</span>
            )}
          </div>
          <nav className="flex flex-1 gap-1 overflow-x-auto text-sm" aria-label="Primary">
            {links.map((link) => {
              const active = pathname === link.href || pathname.startsWith(link.href + "/");
              return (
                <Link
                  key={link.href}
                  href={link.href}
                  aria-current={active ? "page" : undefined}
                  className={`shrink-0 whitespace-nowrap rounded-full px-3 py-1.5 ${active ? "bg-blush font-semibold text-pink" : "text-ink hover:bg-wash"}`}
                >
                  {link.label}
                </Link>
              );
            })}
          </nav>
          {token ? (
            <button className="hidden rounded-full border border-line px-3 py-1.5 text-sm sm:inline" onClick={() => signOut()} type="button">
              {email || "Signed in"} · Sign out
            </button>
          ) : (
            <span className="hidden text-sm text-mute sm:inline">Not signed in</span>
          )}
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-5 py-8">{children}</main>
      <footer className="mx-auto max-w-6xl px-5 pb-10 text-xs leading-5 text-mute">
        Appearance scores are model outputs, not physiological measurements. Shopping suggestions are not safety or efficacy advice. This tool does not diagnose conditions or prescribe treatment.
      </footer>
    </div>
  );
}
