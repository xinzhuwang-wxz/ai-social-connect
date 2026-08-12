"use client";

/** 欢迎屏的路由壳。屏本身在 components/welcome-screen，好让它脱离路由被测。 */

import { WelcomeScreen } from "@/components/welcome-screen";

export default function Page() {
  return <WelcomeScreen />;
}
