"use client";

/** 「等配队」的路由壳。屏本身在 components/waiting-screen，好让它脱离路由被测。 */

import { WaitingScreen } from "@/components/waiting-screen";

export default function Page() {
  return <WaitingScreen />;
}
