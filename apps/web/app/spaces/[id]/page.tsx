"use client";

/** 一起把这件事做完的地方。标题就是这个项目自己的名字，路由壳不替它起名。 */

import { use } from "react";

import { SpaceScreen } from "@/components/space-screen";

export default function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return <SpaceScreen spaceId={id} />;
}
