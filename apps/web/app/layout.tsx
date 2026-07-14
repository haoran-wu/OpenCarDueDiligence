import type { Metadata, Viewport } from "next";
import { Noto_Sans_SC, Source_Sans_3 } from "next/font/google";
import "./globals.css";

const sans = Source_Sans_3({ subsets: ["latin"], variable: "--font-sans" });
const cjk = Noto_Sans_SC({ subsets: ["latin"], variable: "--font-cjk" });

export const metadata: Metadata = {
  title: "OpenCarDueDiligence — Evidence before purchase",
  description:
    "Bilingual, evidence-led used-car due diligence, valuation, negotiation, inspection, and transaction planning.",
  applicationName: "OpenCarDueDiligence",
  manifest: "/manifest.webmanifest",
};

export const viewport: Viewport = {
  themeColor: "#176b5b",
  colorScheme: "light",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body className={`${sans.variable} ${cjk.variable}`}>{children}</body>
    </html>
  );
}
