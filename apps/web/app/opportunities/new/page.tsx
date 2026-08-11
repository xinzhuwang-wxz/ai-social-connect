"use client";

/** 「发一份招募」的路由壳。屏本身在 components/opportunity-form，好让它脱离路由被测。 */

import { OpportunityForm } from "@/components/opportunity-form";

export default function Page() {
  return <OpportunityForm />;
}
