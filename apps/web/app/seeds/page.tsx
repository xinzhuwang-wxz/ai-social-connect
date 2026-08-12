"use client";

/** 「信箱」的路由壳。屏本身在 components/seed-inbox，好让它脱离路由被测。 */

import { SeedInbox } from "@/components/seed-inbox";

export default function Page() {
  return <SeedInbox />;
}
