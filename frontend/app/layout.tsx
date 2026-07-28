import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Plum Claims Processing",
  description: "AI-powered health insurance claims adjudication",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
