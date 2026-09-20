# Python 卡牌对战游戏

这是一个以 Python 为主的轻量级网页卡牌对战游戏项目。

当前阶段已经完成后端 MVP 和 JSON 接口。现有 HTML 页面只保留为 `/demo` 临时联调入口，正式前端后续由插件构建。完整需求见 [docs/mvp.md](docs/mvp.md)，玩法和交互规则见 [docs/interaction-design.md](docs/interaction-design.md)，接口约定见 [docs/api-contract.md](docs/api-contract.md)。代码实施步骤见 [实现计划](docs/superpowers/plans/2026-09-18-card-battle-mvp.md)，验收与质量门槛见 [验收文档](docs/claude-builder/acceptance.md)，外部 Claude Code 执行交接见 [Claude Code 交接](docs/claude-builder/claude-code-handoff.md)。

## 一句话玩法

玩家选择一个角色，与简单电脑对手进行一局 3–5 分钟的回合制战斗，在有限能量下决定攻击、防守和治疗的顺序，最终击败对手。

## MVP 范围

- 单人对战简单电脑 AI；
- 3 个角色：战士、法师、游侠；
- 5 种基础卡牌：斩击、重击、护盾、治疗、火球；
- 固定卡组，不做抽卡、卡牌收集和卡组编辑；
- 玩家回合、电脑回合、胜利、失败、平局等战斗状态；
- 后端 JSON 接口；HTML 开始页、角色选择页、战斗页、结果页仅作为 `/demo` 联调工具；
- 战斗日志、能量限制、生命值、护盾和胜负判断。

## 技术方向

- Python
- Flask
- SQLite
- HTML / CSS / JavaScript

## 当前不做

- 多人在线对战；
- 登录注册；
- 卡牌收集、稀有度和抽卡系统；
- 排位、商城和社交功能；
- 复杂 AI、外部 AI API、实时聊天；
- 复杂动画和音效。

## 四人分工建议

1. 战斗规则、伤害计算和状态机；
2. Flask 路由、数据结构和数据保存；
3. 战斗页面、卡牌展示和交互；
4. 电脑 AI、测试、平衡调整和项目文档。

## 开发原则

先把一局完整战斗跑通，再增加视觉效果或扩展玩法。所有卡牌效果、能量消耗和胜负判断都应能在代码和测试中明确验证。

## 本地启动

使用系统 Python 直接安装依赖并启动开发服务器：

```bash
pip install -r requirements.txt
flask --app app:create_app run --debug
```

启动后访问 `http://127.0.0.1:5000/` 查看服务信息，访问 `http://127.0.0.1:5000/demo` 打开临时联调页面。正式前端使用 `/api` 接口，具体见 [API 接口约定](docs/api-contract.md)。SQLite 数据库默认写入 `instance/card_battle.sqlite3`，首次启动时会自动建表。

如果希望隔离依赖，也可以走标准虚拟环境流程：

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
flask --app app:create_app run --debug
```

## 运行测试

```bash
pytest -v
```

测试覆盖角色、卡牌、战斗状态、电脑 AI、Session 序列化、SQLite 结果表和 Flask 路由。

## 演示流程（5 步）

1. 在开始页点击“开始游戏”，进入角色选择页，挑选一个角色后点击“确认角色”。
2. 在战斗页查看双方状态，使用一张手牌，确认电脑生命值下降、能量扣减、日志出现记录。
3. 试着点击一张能量不足的卡牌或本回合已用过的技能按钮，确认按钮被禁用或页面给出“能量不足”提示。
4. 点击“结束回合”，电脑执行一次行动，回到玩家回合或进入下一回合。
5. 当任一方生命值归零或达到 10 回合上限时进入结果页，点击“再来一局”回到角色选择页，重新开始新一局战斗。

刷新 `/demo/battle` 不会重复执行上一条战斗操作：临时联调页面的所有 `POST` 路由都遵循 Post/Redirect/Get 约定。
