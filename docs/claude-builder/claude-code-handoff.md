# Claude Code 执行交接

请在下面这个项目目录内工作：

```text
C:\Users\杨玉璋\Desktop\card-battle-mvp
```

先完整阅读以下文件，再开始实现：

1. `README.md`
2. `docs/mvp.md`
3. `docs/interaction-design.md`
4. `docs/superpowers/plans/2026-09-18-card-battle-mvp.md`
5. `docs/acceptance.md`

你的任务是实现计划中的全部 Task 1 到 Task 7，完成一个可在本机运行的 Flask 卡牌对战 MVP。

执行要求：

- 先写测试，再写最小实现；
- 每完成一个 Task，运行该 Task 写明的 pytest 命令；
- 不修改已经确认的角色、卡牌、伤害、回合、AI 优先级和页面流程；
- 不增加多人对战、登录、抽卡、排行榜、外部 AI API 或复杂动画；
- 所有 `POST` 路由采用 Post/Redirect/Get，刷新页面不能重复执行上一条战斗操作；
- 不覆盖或删除已有的需求文档；
- 每完成一个 Task 创建一次 Git 提交，提交信息使用计划给出的内容；
- 完成后必须通过 `docs/acceptance.md` 的全部硬门槛：`python -m compileall app.py game`、`ruff check .`、`ruff format --check .`、`pytest -v`，并手动启动 Flask 走通一次：开始页 → 角色选择 → 战斗 → 结束回合 → 结果页 → 再来一局。

完成后请在最终回复中列出：

1. 实际修改和新增的文件；
2. 语法检查、Ruff 和 `pytest -v` 的结果；
3. 本地启动命令；
4. 是否有未完成项或需要人工确认的地方。
