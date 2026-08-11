/**
 * 演示期的身份。
 *
 * 真校园身份接入在后续里程碑；在那之前用一个本地生成的 id 让流程能走通。
 * 它只影响请求头，不影响任何领域边界——下游只看到一个 UUID。
 */
const KEY = "cofield.principal";

export function currentPrincipal(): string {
  if (typeof window === "undefined") return "";
  let id = window.localStorage.getItem(KEY);
  if (!id) {
    id = crypto.randomUUID();
    window.localStorage.setItem(KEY, id);
  }
  return id;
}
