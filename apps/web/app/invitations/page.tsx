"use client";

/**
 * 「有人在等你」的路由壳。屏本身在 components/invitation-screen，
 * 好让它脱离路由被测。
 *
 * 它和 `/intents/[id]/teams` 是同一件事的两侧：那边是我发起、系统配给我的；
 * 这边是别人发起、我被拉进去的。没有这一侧，被拉进来的人根本不知道
 * 有人在等他答复。
 */

import { InvitationsScreen } from "@/components/invitation-screen";

export default function Page() {
  return <InvitationsScreen />;
}
