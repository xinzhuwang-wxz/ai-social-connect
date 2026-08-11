/**
 * 有人在等你答复。
 *
 * ## 为什么需要它
 *
 * 「这次你会得到什么」那一屏做好了，`/invitations` 也打得开——但**没有任何
 * 东西告诉他有人在等他答复**。他只能自己想起来去翻那一页，而没人会。
 *
 * 这个产品的一半是"被邀请的那一侧"：他收到消息，看一眼，决定加不加入。
 * 不加入的原因很多，不需要细想——但**得先让他知道有这回事**。
 *
 * ## 为什么是拉不是推
 *
 * 推送要设备权限、要服务端订阅、要一套退订。而这里真正要解决的问题只是
 * "他不知道"——一个常驻的数字就够了。等真的有人说"看到得太晚"，
 * 再加推送不迟；反过来先上推送，是为一个还没被验证的问题付一整套代价。
 */

import { currentPrincipal } from "@/lib/session";

/** 还在等我答复的有几件。已经答过的不该再顶着一个红点。 */
export async function pendingInvitations(signal?: AbortSignal): Promise<number> {
  try {
    const response = await fetch("/api/me/proposals", {
      signal,
      headers: {
        "Content-Type": "application/json",
        "X-Principal-Id": currentPrincipal(),
      },
    });
    if (!response.ok) return 0;
    const invitations: Array<{ my_answer?: string }> = await response.json();
    return invitations.filter(
      (one) => (one.my_answer ?? "pending") === "pending",
    ).length;
  } catch {
    // 数不出来就当作没有。**顶着一个错的数字比不显示更糟**——
    // 用户会去点，然后发现什么都没有，下次就不信这个数了。
    return 0;
  }
}
