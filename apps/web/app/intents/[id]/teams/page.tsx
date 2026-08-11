"use client";

/** 「给你找的人」的路由壳。凑不出队时这一屏自己会变成「还差这几件事」。 */

import { use } from "react";

import { TeamsScreen } from "@/components/teams-screen";

export default function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return <TeamsScreen intentId={id} />;
}
