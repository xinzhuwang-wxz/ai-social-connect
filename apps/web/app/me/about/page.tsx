"use client";

/** 「我这边」的路由壳。屏本身在 components/about-me-screen，好让它脱离路由被测。 */

import { AboutMeScreen } from "@/components/about-me-screen";

export default function Page() {
  return <AboutMeScreen />;
}
