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

/**
 * 信箱里有几颗还没答的种子。已经答过的不该再顶着一个红点。
 *
 * 投递制之后（ADR 0010）数的是种子，不是提案：提案是"一支队等大家点头"，
 * 种子是"这件事到了你这里，你愿不愿意参与"。
 */
export async function unansweredSeeds(signal?: AbortSignal): Promise<number> {
  try {
    const response = await fetch("/api/me/seeds", {
      signal,
      headers: {
        "Content-Type": "application/json",
        "X-Principal-Id": currentPrincipal(),
      },
    });
    if (!response.ok) return 0;
    const seeds: Array<{ state?: string }> = await response.json();
    return seeds.filter((one) => (one.state ?? "delivered") === "delivered").length;
  } catch {
    // 数不出来就当作没有。**顶着一个错的数字比不显示更糟**——
    // 用户会去点，然后发现什么都没有，下次就不信这个数了。
    return 0;
  }
}

export type ComingUp = {
  event_id: string;
  space_id: string | null;
  title: string;
  starts_at: string;
  where: string | null;
  bring: string | null;
  change_note: string | null;
  my_state: string | null;
};

/**
 * 这两天要出发的事。
 *
 * **和「有 N 件事等你答复」同一条判断**：真正要解决的问题只是"他不知道"，
 * 一个常驻的入口就够了，不需要推送那一整套（设备权限、服务端订阅、退订）。
 *
 * 等真的有人说"看到得太晚"再上推送——反过来先上推送，是为一个还没被
 * 验证的问题付一整套代价。
 */
export async function comingUp(signal?: AbortSignal): Promise<ComingUp[]> {
  try {
    const response = await fetch("/api/me/coming-up", {
      signal,
      headers: {
        "Content-Type": "application/json",
        "X-Principal-Id": currentPrincipal(),
      },
    });
    if (!response.ok) return [];
    return (await response.json()) as ComingUp[];
  } catch {
    // 取不出来就当作没有。**顶着一个错的提醒比不显示更糟**：
    // 用户会照着它出门。
    return [];
  }
}
