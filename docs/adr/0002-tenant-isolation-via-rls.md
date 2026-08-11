# ADR 0002 · 租户隔离用行级安全 + SET LOCAL ROLE

- 状态：已采纳
- 日期：2026-08-12
- 相关：issue #1，[`04-治理与安全`](../04-治理与安全.md)

## 背景

每所校园是策略与数据边界，仿真人口跑在独立 campus 上。隔离有两种做法：
每个查询记得加 `WHERE campus_id = ?`，或者交给数据库。

## 决定

**用 Postgres 行级安全（RLS），并且业务查询以一个非属主、非超级用户、
`NOBYPASSRLS` 的角色 `cofield_app` 执行，通过事务内 `SET LOCAL ROLE` 切入。**

租户变量是会话级的 `app.current_campus`，用 `set_config(..., true)` 设置，
作用域限于事务。

## 理由

**为什么不靠 WHERE**：忘记加 WHERE 是一次代码审查疏漏；忘记开 RLS 是一次
迁移评审疏漏。后者次数少得多，也更容易被测试逮住。

**为什么必须切角色**：这是实现过程中真实踩到的坑——第一版启用了
`ENABLE` + `FORCE ROW LEVEL SECURITY`，隔离测试却全部失败，一个租户能读到
另一个租户的全部行。原因是容器里的 `cofield` 是超级用户，而**超级用户绕过
RLS，`FORCE` 也拦不住**（`FORCE` 只解决表属主绕过）。不切角色的话，隔离
测试会变成一场表演。

**为什么角色是 NOLOGIN**：不给它密码就没有密码要管。`SET LOCAL ROLE` 在
事务结束自动复原，连接归还池子时不会把上一个租户或角色带给下一个请求。

## 后果

- 迁移、种子装载、测试清理必须显式走 `owner_connection`，它绕过 RLS。
  业务代码用它就是绕过隔离，这条靠代码审查把关——没有静态检查能替代。
- 新增带租户的表时必须同时加策略并把表名登记进 `schema.RLS_TABLES`。
- 没设租户变量时策略求值为 NULL，读不到任何行——默认拒绝而不是默认放行。
  `app_connection` 存在的唯一理由就是让这条能被断言。

## 附带记录：PostgreSQL 18 的挂载点变了

从 18 起，卷要挂 `/var/lib/postgresql` 而不是 `/var/lib/postgresql/data`——
镜像把数据放进按主版本号命名的子目录，好让 `pg_upgrade --link` 不跨挂载点。
挂错的表现是容器启动即退出。见 docker-compose.yml 里的注释。
