import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "Sony A7R III Studio & Photometric Camera System",
  description: "High-precision industrial optical studio and photometric stereo acquisition workbench",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className="bg-chassis text-gray-100 antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}

