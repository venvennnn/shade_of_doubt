import type { Metadata } from "next";
import { Outfit } from "next/font/google";
import { Providers } from "./providers";
import { Shell } from "@/components/shell";
import "./globals.css";

const sans = Outfit({ subsets: ["latin"], variable: "--font-sans" });

export const metadata: Metadata = {
  title: "Shade of Doubt",
  description: "Audit whether small, explicit photograph changes move YouCam appearance scores and shopping suggestions.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className={`${sans.variable} font-sans antialiased`}>
        <Providers>
          <Shell>{children}</Shell>
        </Providers>
      </body>
    </html>
  );
}
