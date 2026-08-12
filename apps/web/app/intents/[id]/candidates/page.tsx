"use client";

/** 「谁说了愿意」的路由壳。屏本身在 components/candidates-screen。 */

import { use } from "react";

import { CandidatesScreen } from "@/components/candidates-screen";

export default function Page({ params }: { params: Promise<{ id: string }> }) {
  return <CandidatesScreen intentId={use(params).id} />;
}
