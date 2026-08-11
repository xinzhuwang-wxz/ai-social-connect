"use client";

/** 第二屏的路由壳。屏本身在 components/sharing-screen，好让它脱离路由被测。 */

import { use } from "react";

import { SharingScreen } from "@/components/sharing-screen";

export default function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return <SharingScreen intentId={id} />;
}
