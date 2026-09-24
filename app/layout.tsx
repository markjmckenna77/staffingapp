import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Cleartelligence Staffing",
  description: "Weekly resource management: utilization, outlook, open roles.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
