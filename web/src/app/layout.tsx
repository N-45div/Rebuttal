import type { Metadata } from "next";
import { Fraunces, IBM_Plex_Sans, IBM_Plex_Mono } from "next/font/google";
import "./globals.css";
import Nav from "@/components/Nav";

const display = Fraunces({ subsets: ["latin"], weight: ["500", "700"], style: ["normal", "italic"], variable: "--font-display" });
const sans = IBM_Plex_Sans({ subsets: ["latin"], weight: ["400", "500", "600"], variable: "--font-sans" });
const mono = IBM_Plex_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-mono" });

export const metadata: Metadata = {
  title: "Rebuttal",
  description: "A GPT-6 Astra agent that assembles chargeback evidence across six apps, qualifies it under Visa CE 3.0, and refuses to file when it would lose.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${display.variable} ${sans.variable} ${mono.variable}`}>
      <body>
        <div className="shell">
          <Nav />
          {children}
          <footer>
            <a href="https://github.com/N-45div/Rebuttal">Repository</a>
            <a href="https://github.com/N-45div/Rebuttal/blob/main/ARCHITECTURE.md">Architecture</a>
            <a href="https://github.com/N-45div/Rebuttal/blob/main/TESTING.md">Testing</a>
            <a href="https://github.com/N-45div/Rebuttal/blob/main/SETUP.md">Setup</a>
            <span className="src">Multi-App AI Agent Hackathon · 13 Sep 2026 · GPT-6 Astra</span>
          </footer>
        </div>
      </body>
    </html>
  );
}
