"use client";

/** 「这次留下了什么」的路由壳。屏本身在 components/echo-screen，好让它脱离路由被测。 */

import { use } from "react";

import { EchoScreen } from "@/components/echo-screen";

export default function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return <EchoScreen eventId={id} />;
}
