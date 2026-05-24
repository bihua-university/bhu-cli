# Skill Marketplace

Kimi Code CLI supports installing skills from Claude Code-compatible marketplaces. This lets you use community-maintained skill collections without manually creating or copying `SKILL.md` files.

## What is a Marketplace

A **Marketplace** is a directory containing a `marketplace.json` file that lists available plugins. Each plugin can contain one or more **Skills** (directories with a `SKILL.md` file).

The marketplace itself is just an **index**—it tells you what plugins are available and where to download them. The actual installation into Kimi is done via the `install` command.

## Adding a Marketplace

Use `kimi marketplace add` to cache a marketplace locally:

```sh
# GitHub shorthand
kimi marketplace add owner/repo

# Full Git URL
kimi marketplace add https://github.com/owner/repo.git

# Local directory (useful for development)
kimi marketplace add /path/to/local-marketplace

# Custom name
kimi marketplace add owner/repo --name my-marketplace
```

After adding, the marketplace directory is cached to `~/.kimi/marketplaces/<name>/`, and the registry records the name and source URL.

## Listing Marketplaces

```sh
kimi marketplace list
```

Example output:

```
  engineering-skills (cached)  –  https://github.com/acme/engineering-skills.git
  my-marketplace (cached)      –  /path/to/local-marketplace
```

## Installing Plugin Skills

```sh
# Install from an added marketplace
kimi marketplace install <plugin-name>@<marketplace-name>

# Example
kimi marketplace install senior-backend@engineering-skills
```

During installation, Kimi Code CLI will:

1. Parse the plugin's `plugin.json`
2. Extract the `skills/` directory to `~/.kimi/skills/`
3. Rename each skill to `<plugin-name>--<skill-name>` to avoid conflicts between plugins

After installation, invoke skills via `/skill:<plugin-name>--<skill-name>`:

```sh
/skill:engineering-skills--senior-backend
```

### Skipping Confirmation

If a plugin contains components that Kimi does not support (e.g. commands, agents, hooks), a confirmation prompt is shown. Use `--yes` to skip it:

```sh
kimi marketplace install senior-backend@engineering-skills --yes
```

### Direct Install Without a Marketplace

If you know the plugin's Git URL or local path, you can install directly without adding the marketplace first:

```sh
kimi marketplace install https://github.com/acme/engineering-skills.git/senior-backend
kimi marketplace install /path/to/local-plugin
```

## Updating Marketplaces

Update a single marketplace to the latest version:

```sh
kimi marketplace update engineering-skills
```

Update all added marketplaces:

```sh
kimi marketplace update
```

## Removing a Marketplace

```sh
kimi marketplace remove engineering-skills
```

This removes the marketplace from the registry and clears the local cache. It **does not** delete any skills already installed to `~/.kimi/skills/`.

## Supported and Unsupported Components

Claude Code plugins can contain multiple component types. Kimi Code CLI currently supports **Skills** only; other components are detected and reported, but not installed:

| Component | Status | Notes |
|-----------|--------|-------|
| `skills` | ✅ Supported | Extracted to `~/.kimi/skills/` |
| `commands` | ❌ Ignored | Claude Code command system |
| `agents` | ❌ Ignored | Claude Code agent configs |
| `hooks` | ❌ Ignored | Claude Code hooks |
| `lspServers` | ❌ Ignored | LSP server configs |
| `outputStyles` | ❌ Ignored | Output styles |
| `monitors` | ❌ Ignored | Monitors |
| `mcpServers` | ⚠️ Detected only | Reported but not auto-merged |

During installation, a summary of the plugin's components is displayed. If unsupported components are present, you will be asked whether to continue.

## Installation Location

Skills installed via marketplace are stored at:

```
~/.kimi/skills/
└── <marketplace-name>-<plugin-name>/
    ├── skill-a/
    │   └── SKILL.md
    └── skill-b/
        └── SKILL.md
```

The skill's `name` field is automatically rewritten to `<plugin-name>--<skill-name>` to ensure skills from different plugins do not conflict.

::: tip
Skills installed via marketplace are treated as **user-level skills**, with the same priority as other skills in `~/.kimi/skills/`. See the scope documentation in [Agent Skills](./skills.md) for details.
:::

## Difference from `kimi plugin`

| Command | Purpose | Installs |
|---------|---------|----------|
| `kimi marketplace install` | Install **Skills** from Claude Code plugins | `SKILL.md` knowledge files |
| `kimi plugin install` | Install Kimi Code CLI **executable plugins** | `plugin.json` + tool scripts |

- **Marketplace** installs "knowledge"—the AI reads and follows the guidelines
- **Plugin** installs "tools"—the AI can directly invoke executable scripts

The two are complementary: you can use a marketplace to install code style skills, and plugins to install project-specific query tools.
