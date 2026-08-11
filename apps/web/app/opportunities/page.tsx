"use client";

/** 「正在招人的事」的路由壳。屏本身在 components/opportunity-list，好让它脱离路由被测。 */

import { OpportunityList } from "@/components/opportunity-list";

export default function Page() {
  return <OpportunityList />;
}
