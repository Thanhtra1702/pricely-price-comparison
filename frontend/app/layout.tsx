import "./globals.css";
import type { Metadata } from "next";
export const metadata: Metadata = { title: "Pricebot", description: "So sánh giá và ưu đãi" };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) { return <html lang="vi"><body>{children}</body></html>; }
