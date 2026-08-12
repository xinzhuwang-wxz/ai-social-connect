import type { Metadata, Viewport } from "next";
import "./globals.css";

import { FirstRunGate } from "@/components/first-run-gate";
import { SiteNav } from "@/components/site-nav";

export const metadata: Metadata = {
  // 对外名与副标题还在待测（见 docs/07 §9），界面先留占位。
  title: {
    default: "共域 · 找到人，把事做成",
    // 每一屏自己说自己是什么。浏览器标签上一排都写着同一个名字时，
    // 开了三个标签的人分不出哪个是哪个。
    template: "%s · 共域",
  },
  description: "说一句想做的事，找到能一起做成它的人。",
  // 手机上"添加到主屏幕"之后的标题。长标题会被系统截成一串省略号。
  applicationName: "共域",
  appleWebApp: { capable: true, title: "共域", statusBarStyle: "default" },
  formatDetection: { telephone: false },
};

export const viewport: Viewport = {
  // viewport-fit=cover 让视口延伸到刘海和底部横条后面，
  // 这样 env(safe-area-inset-*) 才有意义——顶栏和底栏用它留出安全区。
  viewportFit: "cover",
  // 亮暗各给一个，让手机地址栏和状态栏染成品牌色而不是白边。
  // 应用本体只有亮色模式，但系统主题是暗色时浏览器 chrome 也该是暖色的。
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f7f0de" },
    { media: "(prefers-color-scheme: dark)", color: "#1a1d0e" },
  ],
  // 允许缩放。禁掉缩放对视力不好的人是实打实的排除，
  // 而它换来的只是"不会误触放大"。
  maximumScale: 5,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body className="min-h-dvh">
        {/* 第一次来的人先问名字。没有这道门，欢迎屏等于不存在——
            这个仓库已经在同一件事上栽过好几次。 */}
        <FirstRunGate />
        {/* 常驻导航。在有它之前每一屏都做好了，但没有任何东西把它们连起来——
            一个刚打开这个网页的人只能停在首页。 */}
        <SiteNav />
        {children}
      </body>
    </html>
  );
}
