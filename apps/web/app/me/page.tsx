"use client";

/**
 * 三个自我管理面的路由壳。屏本身在 components/my-record-screen，
 * 好让它脱离路由被测。
 *
 * 路由是 `/me` 而不是 `/people/[id]`——**不存在可供他人浏览的个人主页**。
 * 一旦有了带 id 的个人页，产品就退回「看人卡决定要不要连接」。
 */

import { MyRecordScreen } from "@/components/my-record-screen";

export default function Page() {
  return <MyRecordScreen />;
}
