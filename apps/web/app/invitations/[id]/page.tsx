"use client";

/** 「这次你会得到什么」的路由壳。从通知点进来落在这里。 */

import { use } from "react";

import { InvitationScreen } from "@/components/invitation-screen";

export default function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return <InvitationScreen proposalId={id} />;
}
