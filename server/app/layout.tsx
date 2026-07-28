import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "Vancouver Real Estate MCP",
  description:
    "35 years of Metro Vancouver and Fraser Valley benchmark prices, as an MCP server any AI agent can connect to.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
