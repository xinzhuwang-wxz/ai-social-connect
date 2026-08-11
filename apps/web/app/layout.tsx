import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  // 对外名与副标题还在待测（见 docs/07 §9），界面先留占位。
  title: "共域 · 找到人，把事做成",
  description: "说一句想做的事，找到能一起做成它的人。",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body className="min-h-dvh">{children}</body>
    </html>
  );
}
