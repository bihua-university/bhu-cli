# Skill 市场

Kimi Code CLI 支持从 Claude Code 兼容的 Skill 市场（Marketplace）安装技能。这让你可以直接使用社区维护的技能集合，而不必手动创建或复制 `SKILL.md` 文件。

## 市场是什么

一个 **Marketplace** 就是一个包含 `marketplace.json` 的目录，里面列出了多个可用的插件（Plugin）。每个插件可以包含一个或多个 **Skills**（即包含 `SKILL.md` 的目录）。

Marketplace 本身只是**索引**——它告诉你有哪些插件可用、从哪里下载。真正把技能装到 Kimi 里用的是 `install` 命令。

## 添加市场

使用 `kimi marketplace add` 把一个市场添加到本地缓存：

```sh
# GitHub shorthand
kimi marketplace add owner/repo

# 完整 Git URL
kimi marketplace add https://github.com/owner/repo.git

# 本地目录（开发测试用）
kimi marketplace add /path/to/local-marketplace

# 指定自定义名称
kimi marketplace add owner/repo --name my-marketplace
```

添加后，市场目录会被缓存到 `~/.kimi/marketplaces/<name>/`，同时注册表会记录名称和源地址。

## 查看已添加的市场

```sh
kimi marketplace list
```

输出示例：

```
  engineering-skills (cached)  –  https://github.com/acme/engineering-skills.git
  my-marketplace (cached)      –  /path/to/local-marketplace
```

## 安装插件中的 Skills

```sh
# 从已添加的市场安装
kimi marketplace install <plugin-name>@<marketplace-name>

# 示例
kimi marketplace install senior-backend@engineering-skills
```

安装时，Kimi Code CLI 会：

1. 解析插件的 `plugin.json`
2. 提取 `skills/` 目录到 `~/.kimi/skills/`
3. 把 Skill 名称改写为 `<plugin-name>--<skill-name>` 格式，避免不同插件的 Skill 冲突

安装完成后，你可以通过 `/skill:<plugin-name>--<skill-name>` 调用：

```sh
/skill:engineering-skills--senior-backend
```

### 跳过确认提示

如果插件包含 Kimi 不支持的组件（如 commands、agents、hooks 等），安装前会提示确认。使用 `--yes` 跳过：

```sh
kimi marketplace install senior-backend@engineering-skills --yes
```

### 不通过市场，直接安装

如果你知道插件的 Git 地址或本地路径，可以直接安装，不需要先 `add` 市场：

```sh
kimi marketplace install https://github.com/acme/engineering-skills.git/senior-backend
kimi marketplace install /path/to/local-plugin
```

## 更新市场

更新单个市场到最新版本：

```sh
kimi marketplace update engineering-skills
```

更新所有已添加的市场：

```sh
kimi marketplace update
```

## 移除市场

```sh
kimi marketplace remove engineering-skills
```

这会从注册表中删除市场，并清除本地缓存。但**不会**删除已经安装到 `~/.kimi/skills/` 的 Skills。

## 支持与不支持的组件

Claude Code 插件可以包含多种组件。Kimi Code CLI 目前只支持 **Skills**，其他组件会被检测并提示，但不会安装：

| 组件 | 支持状态 | 说明 |
|------|----------|------|
| `skills` | ✅ 支持 | 提取到 `~/.kimi/skills/` |
| `commands` | ❌ 忽略 | Claude Code 的命令系统 |
| `agents` | ❌ 忽略 | Claude Code 的 Agent 配置 |
| `hooks` | ❌ 忽略 | Claude Code 的钩子 |
| `lspServers` | ❌ 忽略 | LSP 服务器配置 |
| `outputStyles` | ❌ 忽略 | 输出样式 |
| `monitors` | ❌ 忽略 | 监控器 |
| `mcpServers` | ⚠️ 仅检测 | 目前只报告存在，不自动合并 |

安装时会显示插件包含的组件列表，如果有不支持的组件会询问是否继续。

## 安装位置

通过 marketplace 安装的 Skills 存放在：

```
~/.kimi/skills/
└── <marketplace-name>-<plugin-name>/
    ├── skill-a/
    │   └── SKILL.md
    └── skill-b/
        └── SKILL.md
```

Skill 的 `name` 字段会被自动改写为 `<plugin-name>--<skill-name>`，确保不同插件的同名 Skill 不会冲突。

::: tip 提示
Marketplace 安装的 Skills 属于**用户级 Skills**，优先级与 `~/.kimi/skills/` 下的其他 Skills 相同。详见 [Agent Skills](./skills.md) 的作用域说明。
:::

## 与 `kimi plugin` 的区别

| 命令 | 用途 | 安装内容 |
|------|------|----------|
| `kimi marketplace install` | 安装 Claude Code 插件中的 **Skills** | `SKILL.md` 知识文件 |
| `kimi plugin install` | 安装 Kimi Code CLI 的 **可执行插件** | `plugin.json` + 工具脚本 |

- **Marketplace** 装的是「知识」——AI 读取后遵循其中的规范
- **Plugin** 装的是「工具」——AI 可以直接调用可执行脚本

两者互补：你可以同时用 marketplace 安装代码规范 Skill，用 plugin 安装项目特定的查询工具。
