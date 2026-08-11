import type { Metadata } from "next";
import "./globals.css";

import { SiteNav } from "@/components/site-nav";

export const metadata: Metadata = {
  // 对外名与副标题还在待测（见 docs/07 §9），界面先留占位。
  title: "共域 · 找到人，把事做成",
  description: "说一句想做的事，找到能一起做成它的人。",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body className="min-h-dvh">
        {/* 常驻导航。在有它之前每一屏都做好了，但没有任何东西把它们连起来——
            一个刚打开这个网页的人只能停在首页。 */}
        <SiteNav />
        {children}
      </body>
    </html>
  );
}
